"""Logical H with explicit data rotation using a conservative one-buffer route."""

from dataclasses import dataclass, replace
from math import hypot, isclose

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Load, Move, Store
from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.state import AODGrid, AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.transport.rules import MoveRequest, rules_for

from modules.codes._support.atom_binding import rebind_program
from modules.codes._support.atom_template import AtomComponentTemplate, compile_template
from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentDescription,
    InvocationContext,
)

from .definition import definition


@dataclass(frozen=True)
class HadamardComponent:
    """Apply H to data and rotate carriers into canonical code orientation.

    One external empty SLM trap breaks each four-site permutation cycle. The
    sequential one-atom route is explicit and legal, but not transport-optimal.
    """

    distance: int
    name: str = "logical_h"

    def __post_init__(self) -> None:
        definition(self.distance)
        if self.name != "logical_h":
            raise ValueError("HadamardComponent only implements logical_h.")

    @property
    def data_destinations(self) -> tuple[int, ...]:
        """Map each input atom to its clockwise-rotated canonical data role."""
        d = self.distance
        return tuple((q % d) * d + d - 1 - q // d for q in range(d * d))

    @property
    def source_qasm(self) -> str:
        """Return H on fixed data wires; carrier rotation is explicit atom IR."""
        code = definition(self.distance)
        return (
            f'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[{code.atom_count}] q;\n'
            + "".join(f"h q[{q}];\n" for q in range(code.data_count))
        )

    @property
    def output_syndrome_parities(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Track check signs through H plus the physical data permutation."""
        code = definition(self.distance)
        checks = {
            (b, tuple(qs)): role
            for role, (b, qs) in zip(code.check_roles, code.checks, strict=True)
        }
        incoming = {}
        for role, (basis, support) in zip(code.check_roles, code.checks, strict=True):
            target = (
                "Z" if basis == "X" else "X",
                tuple(sorted(self.data_destinations[q] for q in support)),
            )
            incoming[checks[target]] = (f"input.{role}",)
        return tuple((role, incoming[role]) for role in code.check_roles)

    @property
    def description(self) -> ComponentDescription:
        """Require one vacant buffer and expose the canonical exit binding."""
        code = definition(self.distance)
        return ComponentDescription(
            f"rotated_surface_d{self.distance}",
            self.name,
            "1",
            code.roles,
            (),
            (
                "Data homes form an axis-aligned square; complete world supplied",
                "One declared external SLM buffer must be empty; flexible AOD inactive",
                "Preserve encoded data; syndrome atoms are not operated on",
            ),
            (
                "Physical H on data followed by explicit LOAD/MOVE/STORE rotation",
                "Use exit_binding: canonical data roles now refer to permuted carriers",
                "Ancillas unchanged; no implicit SE, measurement, or frame update",
                "Logical H on positive code sector; preserve other-sector check signs",
                "One-buffer sequential routing is a valid baseline, not an optimum",
            ),
        )

    def _transport(
        self,
        device: Device,
        homes: tuple[str, ...],
        aod_id: str,
        buffer_site: str | None,
    ) -> tuple[AtomProgram, str]:
        code = definition(self.distance)
        n, d = code.data_count, code.distance
        positions = {q: device.site(homes[q]).position for q in range(n)}
        pitch = positions[1].x - positions[0].x
        origin = positions[0]
        if pitch <= 0 or any(
            not isclose(p.x, origin.x + (q % d) * pitch, abs_tol=1e-9)
            or not isclose(p.y, origin.y + (q // d) * pitch, abs_tol=1e-9)
            for q, p in positions.items()
        ):
            raise ValueError("H data homes must form the standard square grid.")
        if buffer_site is None:
            candidates = [
                s
                for s in device.slm_sites
                if s.id not in homes
                and device.aod(aod_id).workspace.contains(s.position)
            ]
            if not candidates:
                raise ValueError("H rotation needs one external empty SLM buffer.")
            buffer_site = min(
                candidates,
                key=lambda s: (
                    hypot(s.position.x - origin.x, s.position.y - origin.y),
                    s.id,
                ),
            ).id
        if buffer_site in homes:
            raise ValueError("H buffer must be outside the occupied patch homes.")
        rules = rules_for(device.aod(aod_id), device.timing)
        steps: list[AtomStep] = []

        def move(atom: int, target_site: str) -> None:
            request = MoveRequest(
                atom, positions[atom], device.site(target_site).position
            )
            if not rules.can_fit((request,)):
                raise ValueError("H rotation exceeds the selected AOD workspace.")
            before, after, bindings = rules.frames((request,))
            duration = device.timing.move_duration(
                hypot(
                    request.target.x - request.source.x,
                    request.target.y - request.source.y,
                )
            )
            steps.extend(
                (
                    AtomStep(
                        (Load(before, bindings, duration_us=device.timing.load_us),)
                    ),
                    AtomStep(
                        (Move(after, ((atom, request.target),), duration_us=duration),)
                    ),
                    AtomStep(
                        (
                            Store(
                                AODGrid(aod_id),
                                ((atom, target_site),),
                                duration_us=device.timing.store_us,
                            ),
                        )
                    ),
                )
            )
            positions[atom] = request.target

        visited = set()
        for first in range(n):
            if first in visited or self.data_destinations[first] == first:
                continue
            cycle, current = [], first
            while current not in visited:
                visited.add(current)
                cycle.append(current)
                current = self.data_destinations[current]
            move(cycle[-1], buffer_site)
            for atom in reversed(cycle[:-1]):
                move(atom, homes[self.data_destinations[atom]])
            move(cycle[-1], homes[first])
        if any(
            positions[q] != device.site(homes[target]).position
            for q, target in enumerate(self.data_destinations)
        ):
            raise ValueError(
                "H carrier rotation did not reach the declared permutation."
            )
        return AtomProgram(tuple(steps)), buffer_site

    def compile(
        self,
        device: Device,
        *,
        home_sites: tuple[str, ...],
        origin: Position,
        aod_id: str,
        buffer_site: str | None = None,
    ) -> AtomComponentTemplate:
        """Compile H and explicit routing; bind/expand checks full-world vacancy.

        Args:
            device: Device containing square data homes and an external buffer.
            home_sites: Ordered code-role homes.
            origin: Relative template origin.
            aod_id: Selected flexible transport AOD.
            buffer_site: Optional explicit empty SLM site; nearest candidate otherwise.
        Returns:
            A template carrying all movement costs and the output role permutation.
        Raises:
            ValueError: If geometry, buffer, transport, or replay is invalid.
        """
        code = definition(self.distance)
        template = compile_template(
            self.description,
            self.source_qasm,
            device,
            home_sites=home_sites,
            origin=origin,
            aod_id=aod_id,
            expected_values=(),
            corrections=(),
        )
        transport, buffer = self._transport(device, home_sites, aod_id, buffer_site)
        used = (*home_sites, buffer)
        relative = rebind_program(
            transport,
            shift=Position(-origin.x, -origin.y),
            atoms={i: i for i in range(code.atom_count)},
            sites={s: s for s in used},
            channels={},
            aod_id="component_aod",
            results={},
        )
        sites = dict(template.relative_sites)
        sites[buffer] = Position(
            device.site(buffer).position.x - origin.x,
            device.site(buffer).position.y - origin.y,
        )
        destinations = (
            *self.data_destinations,
            *range(code.data_count, code.atom_count),
        )
        inverse = tuple(destinations.index(q) for q in range(code.atom_count))
        template = replace(
            template,
            relative_program=replace(
                template.relative_program,
                steps=template.relative_program.steps + relative.steps,
            ),
            relative_sites=tuple(sorted(sites.items())),
            exit_home_sites=tuple(home_sites[q] for q in destinations),
            exit_role_permutation=inverse,
            output_syndrome_parities=self.output_syndrome_parities,
        )
        ids = tuple(range(code.atom_count))
        world = AtomLayout(
            tuple(
                AtomState(i, device.site(site).position, SLMHolder(site))
                for i, site in enumerate(home_sites)
            ),
            qubit_to_atom=ids,
        )
        checked = template.bind(
            ComponentBinding("reference", origin, ids, aod_id)
        ).expand(InvocationContext("reference-h", 0, 0, device, world))
        return replace(template, reference_validation_checks=checked.validation_checks)
