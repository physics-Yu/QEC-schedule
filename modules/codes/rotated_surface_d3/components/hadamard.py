"""Logical H with a real single-AOD six-stroke data permutation.

arXiv:2607.28149v1, Sec. 2.4, Remark 2 gives the six-stroke d3 bound.
The batches here were independently reconstructed in this code convention.
Timing comes from the Device, not the paper's constant-jerk model.
"""

from dataclasses import dataclass, replace
from math import isclose

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Load, Move, Store
from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.state import AODGrid, AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.transport.rules import MoveRequest, rules_for

from ..._support.atom_binding import rebind_program
from ..._support.atom_template import AtomComponentTemplate, compile_template
from ...contracts.component import (
    ComponentBinding,
    ComponentDescription,
    InvocationContext,
)
from ..definition import REFERENCE_COORDINATES, ROLES

H_REFERENCE_HOMES = tuple(f"home_r{y + 2}_c{x + 2}" for x, y in REFERENCE_COORDINATES)
DATA_DESTINATIONS = (2, 5, 8, 1, 4, 7, 0, 3, 6)
OUTPUT_ROLE_PERMUTATION = (6, 3, 0, 7, 4, 1, 8, 5, 2, *range(9, 17))
OUTPUT_SYNDROME_PARITIES = (
    *((f"X{i}", (f"input.Z{i}",)) for i in range(4)),
    *((f"Z{i}", (f"input.X{3 - i}",)) for i in range(4)),
)
# (horizontal, displacement in data-grid spacings, original data-atom roles).
ROTATION_STROKES = (
    (True, 1, (0, 1, 2)),
    (False, 1, (0, 2, 4, 7)),
    (False, -2, (0, 3, 4, 6, 7)),
    (True, -2, (2, 5, 7, 8)),
    (True, 1, (0, 2, 3, 5, 7)),
    (False, 1, (0, 1, 2, 3, 4, 5)),
)


def _site_at(device: Device, point: Position) -> str:
    matches = [
        s.id
        for s in device.slm_sites
        if isclose(s.position.x, point.x, abs_tol=1e-9, rel_tol=0)
        and isclose(s.position.y, point.y, abs_tol=1e-9, rel_tol=0)
    ]
    if len(matches) != 1:
        raise ValueError(f"H rotation requires one unambiguous SLM buffer at {point}.")
    return matches[0]


def _rotation(
    device: Device, home_sites: tuple[str, ...], aod_id: str
) -> tuple[AtomProgram, set[str]]:
    positions = {i: device.site(home_sites[i]).position for i in range(9)}
    center = positions[4]
    spacing = positions[1].x - positions[0].x
    if spacing <= 0 or any(
        not isclose(p.x, center.x + (q % 3 - 1) * spacing, abs_tol=1e-9)
        or not isclose(p.y, center.y + (q // 3 - 1) * spacing, abs_tol=1e-9)
        for q, p in positions.items()
    ):
        raise ValueError("H reference data homes must form the standard square grid.")
    rules = rules_for(device.aod(aod_id), device.timing)
    steps: list[AtomStep] = []
    sites: set[str] = set()
    for horizontal, displacement, atoms in ROTATION_STROKES:
        delta = displacement * spacing
        moves = tuple(
            MoveRequest(
                atom,
                positions[atom],
                Position(
                    positions[atom].x + (delta if horizontal else 0),
                    positions[atom].y + (0 if horizontal else delta),
                ),
            )
            for atom in atoms
        )
        if not rules.can_fit(moves) or any(
            not rules.compatible(a, b) for a in moves for b in moves
        ):
            raise ValueError("H rotation exceeds AOD motion or resource limits.")
        before, after, bindings = rules.frames(moves)
        destinations = tuple((m.atom_id, _site_at(device, m.target)) for m in moves)
        sites.update(site for _, site in destinations)
        steps.extend(
            (
                AtomStep((Load(before, bindings, duration_us=device.timing.load_us),)),
                AtomStep(
                    (
                        Move(
                            after,
                            tuple((m.atom_id, m.target) for m in moves),
                            duration_us=device.timing.move_duration(abs(delta)),
                        ),
                    )
                ),
                AtomStep(
                    (
                        Store(
                            AODGrid(aod_id),
                            destinations,
                            duration_us=device.timing.store_us,
                        ),
                    )
                ),
            )
        )
        positions.update((m.atom_id, m.target) for m in moves)
    for old, new in enumerate(DATA_DESTINATIONS):
        if positions[old] != device.site(home_sites[new]).position:
            raise ValueError("H rotation did not reach the declared data permutation.")
    return AtomProgram(tuple(steps)), sites


@dataclass(frozen=True)
class HadamardComponent:
    """Compile H9 and explicit physical rotation, returning a new role binding."""

    name: str = "logical_h"

    def __post_init__(self) -> None:
        if self.name != "logical_h":
            raise ValueError("Only the approved physical logical_h is supported.")

    @property
    def source_qasm(self) -> str:
        """Return gates on stable atom wires; output roles additionally permute."""
        return 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[17] q;\n' + "".join(
            f"h q[{q}];\n" for q in range(9)
        )

    @property
    def description(self) -> ComponentDescription:
        """Declare buffer occupancy, fixed atoms, and canonical output roles."""
        return ComponentDescription(
            "rotated_surface_d3",
            self.name,
            "1",
            ROLES,
            (),
            (
                "17 atoms at standard square reference homes; inactive flexible AODs",
                "All declared rotation buffer traps available; complete world supplied",
                "Encoded data; preserve data and leave auxiliary states untouched",
            ),
            (
                "H on nine data atoms, then six physical LOAD/MOVE/STORE strokes",
                "Data homes occupied by permuted atoms; auxiliary atoms unchanged",
                "Use exit_binding for subsequent components at canonical orientation",
                "Output signs X_i=input.Z_i; Z_i=input.X_(3-i)",
                "Conjugation X_L -> Z_L; Z_L -> X_L times all four output X checks",
                "Logical H on the +1 code sector; retain signs for other sectors",
                "No measurements, implicit SE, SWAP gates or frame updates",
            ),
        )

    def compile(
        self,
        device: Device,
        *,
        home_sites: tuple[str, ...],
        origin: Position,
        aod_id: str,
    ) -> AtomComponentTemplate:
        """Compile local gates, append legal transport, validate the declared exit."""
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
        transport, used = _rotation(device, home_sites, aod_id)
        relative_transport = rebind_program(
            transport,
            shift=Position(-origin.x, -origin.y),
            atoms={i: i for i in range(17)},
            sites={s: s for s in used},
            channels={},
            aod_id="component_aod",
            results={},
        )
        sites = dict(template.relative_sites)
        sites.update(
            (
                s,
                Position(
                    device.site(s).position.x - origin.x,
                    device.site(s).position.y - origin.y,
                ),
            )
            for s in used
        )
        template = replace(
            template,
            relative_program=replace(
                template.relative_program,
                steps=template.relative_program.steps + relative_transport.steps,
            ),
            relative_sites=tuple(sorted(sites.items())),
            exit_home_sites=tuple(
                home_sites[i] for i in (*DATA_DESTINATIONS, *range(9, 17))
            ),
            exit_role_permutation=OUTPUT_ROLE_PERMUTATION,
            output_syndrome_parities=OUTPUT_SYNDROME_PARITIES,
        )
        atoms = tuple(range(17))
        world = AtomLayout(
            tuple(
                AtomState(i, device.site(s).position, SLMHolder(s))
                for i, s in enumerate(home_sites)
            ),
            qubit_to_atom=atoms,
        )
        checked = template.bind(
            ComponentBinding("reference", origin, atoms, aod_id)
        ).expand(InvocationContext("reference-h", 0, 0, device, world))
        return replace(template, reference_validation_checks=checked.validation_checks)
