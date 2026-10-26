"""Two same-orientation odd-distance patches coupled by corresponding-data CNOTs.

Transversal neutral-atom logical gates: Bluvstein et al., Nature 626 (2024),
https://www.nature.com/articles/s41586-023-06927-3. The implementation below
claims ideal logical action and checked transport, not a noisy fault distance.
"""

import json
from dataclasses import dataclass, replace
from math import isclose

from nadit_physical_compiler.device import Device, Position

from modules.codes._support.atom_template import (
    AtomComponentTemplate,
    BindingRejected,
    BoundAtomComponent,
    compile_template,
)
from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentDescription,
    ComponentExpansion,
    InvocationContext,
)

from .definition import definition


def _equal_position(a: Position, b: Position) -> bool:
    return isclose(a.x, b.x, abs_tol=1e-9, rel_tol=0) and isclose(
        a.y, b.y, abs_tol=1e-9, rel_tol=0
    )


def _relative(a: Position, origin: Position) -> Position:
    return Position(a.x - origin.x, a.y - origin.y)


def _syndrome_relations(distance: int) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return local Heisenberg sign relations, without any stored frame."""
    result = []
    for participant in ("control", "target"):
        for basis in ("X", "Z"):
            for index in range(definition(distance).check_count // 2):
                port = f"{basis}{index}"
                output = f"{participant}.{port}"
                combines = (participant, basis) in (("control", "X"), ("target", "Z"))
                inputs = (
                    (f"input.control.{port}", f"input.target.{port}")
                    if combines
                    else (f"input.{output}",)
                )
                result.append((output, inputs))
    return tuple(result)


@dataclass(frozen=True)
class TransversalCNOTTemplate:
    """Joint actions cached for a specific relative displacement of two patches.

    Each participant retains its own origin, identity and atom mapping. Changing
    the relative displacement requires explicit compilation for the new homes.
    """

    atomic: AtomComponentTemplate
    relative_displacement: Position
    distance: int

    @property
    def description(self) -> ComponentDescription:
        """Return the shared operation description with participant-qualified roles."""
        return self.atomic.description

    @property
    def source_qasm(self) -> str:
        """Return the concrete two-patch source circuit."""
        return self.atomic.source_qasm

    def bind(
        self, control: ComponentBinding, target: ComponentBinding
    ) -> "BoundTransversalCNOT":
        """Bind two disjoint patches; reject changed geometry without recompiling."""
        for participant in (control, target):
            if (
                not participant.block_id
                or not participant.aod_id
                or len(participant.atom_ids) != definition(self.distance).atom_count
                or len(set(participant.atom_ids))
                != definition(self.distance).atom_count
                or any(
                    type(atom) is not int or atom < 0 for atom in participant.atom_ids
                )
            ):
                raise BindingRejected(
                    "Each CNOT participant requires "
                    f"{definition(self.distance).atom_count} distinct atoms."
                )
        if control.block_id == target.block_id or set(control.atom_ids) & set(
            target.atom_ids
        ):
            raise BindingRejected(
                "CNOT participants must have disjoint identities and atoms."
            )
        if control.aod_id != target.aod_id:
            raise BindingRejected(
                "This joint CNOT template requires one shared AOD resource."
            )
        if not _equal_position(
            _relative(target.origin, control.origin), self.relative_displacement
        ):
            raise BindingRejected(
                "Relative block displacement changed; "
                "explicitly compile for the new geometry."
            )
        sites: dict[str, str] = {}
        for participant in (control, target):
            if len(dict(participant.site_ids)) != len(participant.site_ids):
                raise BindingRejected("Repeated participant site-binding key.")
            for key, site in participant.site_ids:
                if key in sites and sites[key] != site:
                    raise BindingRejected("Conflicting joint reference-site bindings.")
                sites[key] = site
        # This collision-free internal label is not a substitute for the two
        # participant records exposed on the expansion and its exit.
        joint_id = "transversal_cnot:" + json.dumps(
            [control.block_id, target.block_id], separators=(",", ":")
        )
        joint = ComponentBinding(
            joint_id,
            control.origin,
            control.atom_ids + target.atom_ids,
            control.aod_id,
            tuple(sorted(sites.items())),
        )
        return BoundTransversalCNOT(self.atomic.bind(joint), control, target)


@dataclass(frozen=True)
class BoundTransversalCNOT:
    """Two explicit participants bound to one shared nonzoned action schedule."""

    atomic: BoundAtomComponent
    control: ComponentBinding
    target: ComponentBinding

    def expand(self, context: InvocationContext) -> ComponentExpansion:
        """Validate the complete world and return both unchanged participant exits."""
        return replace(
            self.atomic.expand(context),
            exit_binding=None,
            participant_bindings=(self.control, self.target),
            exit_participant_bindings=(self.control, self.target),
        )


@dataclass(frozen=True)
class TransversalCNOTComponent:
    """Approved corresponding-data logical CNOT, with no implicit SE or feedback."""

    distance: int
    name: str = "transversal_cnot"

    def __post_init__(self) -> None:
        definition(self.distance)
        if self.name != "transversal_cnot":
            raise ValueError(
                "Only the approved transversal_cnot protocol is supported."
            )

    @property
    def source_qasm(self) -> str:
        """Apply corresponding-data control-to-target CNOT; leave ancillas alone."""
        lines = [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            f"qubit[{2 * definition(self.distance).atom_count}] q;",
        ]
        lines.extend(
            f"cx q[{q}], q[{definition(self.distance).atom_count + q}];"
            for q in range(definition(self.distance).data_count)
        )
        return "\n".join(lines) + "\n"

    @property
    def description(self) -> ComponentDescription:
        """Declare two encoded participants and their precise reversible exit."""
        return ComponentDescription(
            f"rotated_surface_d{self.distance}",
            self.name,
            "1",
            tuple(
                f"{participant}.{role}"
                for participant in ("control", "target")
                for role in definition(self.distance).roles
            ),
            (),
            (
                f"Two disjoint same-orientation d{self.distance} blocks at SLM homes",
                "Both data blocks encoded; any known stabilizer-sign sectors allowed",
                "One shared inactive flexible AOD; complete world occupancy supplied",
                "Relative block displacement and resources match this template",
            ),
            (
                "Logical CNOT from control to target; all ancillas unchanged",
                "Each participant returns to its own entry homes and role mapping",
                "No reset, measurement, implicit SE, correction or frame update",
                "Local syndrome parity relations are metadata for the caller",
            ),
        )

    def compile(
        self,
        device: Device,
        *,
        control_home_sites: tuple[str, ...],
        target_home_sites: tuple[str, ...],
        control_origin: Position,
        target_origin: Position,
        aod_id: str,
    ) -> TransversalCNOTTemplate:
        """Compile a specific pair geometry; bind/expand never silently replan it."""
        size = definition(self.distance).atom_count
        if len(control_home_sites) != size or len(target_home_sites) != size:
            raise ValueError(
                f"Each reference participant requires exactly {size} homes."
            )
        homes = control_home_sites + target_home_sites
        if len(set(homes)) != 2 * size:
            raise ValueError(
                f"Reference CNOT participants need {2 * size} disjoint homes."
            )
        for control_site, target_site in zip(
            control_home_sites, target_home_sites, strict=True
        ):
            control_offset = _relative(
                device.site(control_site).position, control_origin
            )
            target_offset = _relative(device.site(target_site).position, target_origin)
            if not _equal_position(control_offset, target_offset):
                raise ValueError(
                    "Participants must have the same oriented local layout."
                )
        atomic = compile_template(
            self.description,
            self.source_qasm,
            device,
            home_sites=homes,
            origin=control_origin,
            aod_id=aod_id,
            expected_values=(),
            corrections=(),
        )
        atomic = replace(
            atomic, output_syndrome_parities=_syndrome_relations(self.distance)
        )
        return TransversalCNOTTemplate(
            atomic, _relative(target_origin, control_origin), self.distance
        )
