"""Explicit same-atom block translation through the existing transport planner.

This is a native component adapter, not a state swap or a code-conversion protocol.
It must not enter a source-QASM-only lowering path: its identity DAG deliberately
contains no quantum gates, while its native Load/Move/Store program is essential.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from math import isclose, isfinite
from typing import Any

from nadit_physical_compiler.atom_ir import AtomProgram, Load, Move, Store
from nadit_physical_compiler.compiler import CompilationResult
from nadit_physical_compiler.contracts import TransportGoal
from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import (
    encode_device,
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.state import AtomLayout, SLMHolder, validate_layout
from nadit_physical_compiler.transport import StrictTransport
from nadit_physical_compiler.transport.occupancy import Occupancy
from nadit_physical_compiler.validation import validate_result

from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentDescription,
    ComponentExpansion,
    InvocationContext,
)

from .definition import definition
from .geometry import SITE_PITCH_UM


def _same(first: Position, second: Position) -> bool:
    return isclose(first.x, second.x, abs_tol=1e-9, rel_tol=0) and isclose(
        first.y, second.y, abs_tol=1e-9, rel_tol=0
    )


@dataclass(frozen=True)
class CompiledBlockTranslation:
    """Validated native actions tied to an exact Device and complete entry world."""

    description: ComponentDescription
    device: Device
    entry_world: AtomLayout
    exit_world: AtomLayout
    entry_binding: ComponentBinding
    exit_binding: ComponentBinding
    program: AtomProgram
    validation_json: str

    @property
    def result_count(self) -> int:
        """Transport does not measure or allocate results."""
        return 0

    @property
    def device_sha256(self) -> str:
        """Identify the exact device, including all timing and occupancy capabilities."""
        return canonical_hash(encode_device(self.device))

    @property
    def entry_world_sha256(self) -> str:
        """Identify the complete saved entry including spectator atoms and wire map."""
        return canonical_hash(encode_layout(self.entry_world))

    @property
    def exit_world_sha256(self) -> str:
        """Identify the actual moved exit without modifying atom or wire identities."""
        return canonical_hash(encode_layout(self.exit_world))

    def _document(self) -> dict[str, Any]:
        return {
            "schema": "nadit.block_translation/1",
            "description": asdict(self.description),
            "device": encode_device(self.device),
            "entry_state": encode_layout(self.entry_world),
            "exit_state": encode_layout(self.exit_world),
            "entry_binding": asdict(self.entry_binding),
            "exit_binding": asdict(self.exit_binding),
            "program": encode_program(self.program),
            "validation": json.loads(self.validation_json),
            "ideal_quantum_operation": "identity_on_unchanged_atom_ids",
            "physical_execution": False,
            "logical_quality": None,
        }

    @property
    def content_sha256(self) -> str:
        """Identify all actions, interpretation and exact state-transition boundaries."""
        return canonical_hash(self._document())

    def to_dict(self) -> dict[str, Any]:
        """Export exact native action and entry/exit metadata without quantum samples."""
        document = self._document()
        document["content_sha256"] = canonical_hash(document)
        return document

    def expand(self, context: InvocationContext) -> ComponentExpansion:
        """Bind invocation time only; reject changed Device/world without replanning."""
        if context.device != self.device:
            raise ValueError(
                "TRANSLATION_DEVICE_CHANGED: explicitly compile new transport"
            )
        if context.world_state != self.entry_world:
            raise ValueError(
                "TRANSLATION_WORLD_CHANGED: explicitly compile current occupancy"
            )
        return ComponentExpansion(
            description=self.description,
            invocation_id=context.invocation_id,
            block_id=self.entry_binding.block_id,
            start_us=context.start_us,
            entry_state=context.world_state,
            exit_state=self.exit_world,
            wire_atoms=self.entry_binding.atom_ids,
            program=self.program,
            dag=PhysicalDAG(len(self.entry_binding.atom_ids), 0, (), ()),
            operations=(),
            measurements=(),
            correction_relations=(),
            validation_checks=tuple(json.loads(self.validation_json)["checks"]),
            exit_binding=self.exit_binding,
            participant_bindings=(self.entry_binding,),
            template_content_sha256=self.content_sha256,
        )


@dataclass(frozen=True)
class BlockTranslationComponent:
    """Translate an entire standard-orientation patch into explicitly empty SLM sites.

    Data and syndrome roles keep their atom identities and ordering. This uses
    no gates, resets, measurements, SWAPs, code conversion or implicit SE. Native
    transport may split the requested rigid endpoint translation into batches.
    """

    distance: int

    def __post_init__(self) -> None:
        definition(self.distance)

    @property
    def result_count(self) -> int:
        """Declare the static zero-measurement interface without routing."""
        return 0

    @property
    def description(self) -> ComponentDescription:
        """Describe same-code, same-atom translation, with transport noise unassessed."""
        return ComponentDescription(
            f"rotated_surface_d{self.distance}",
            "block_translation",
            "1",
            definition(self.distance).roles,
            (),
            (
                "Complete current world; every atom at SLM homes and AODs inactive",
                "Standard code role geometry; explicit vacant receiving SLM sites",
                "Caller retains resource ownership and state/frame metadata",
            ),
            (
                "Same block, atom IDs, role ordering, code and distance",
                "Translated origin and explicit destination home sites",
                "Every spectator unchanged; no gate/reset/readout/implicit SE",
                "Transport noise and delivered logical quality are separate assessments",
            ),
        )

    def _target(
        self,
        device: Device,
        world: AtomLayout,
        binding: ComponentBinding,
        target_origin: Position,
        target_home_sites: tuple[str, ...],
    ) -> tuple[AtomLayout, ComponentBinding]:
        code = definition(self.distance)
        if not isinstance(binding, ComponentBinding) or not isinstance(
            target_origin, Position
        ):
            raise TypeError("TRANSLATION_INVALID_BINDING_OR_DESTINATION")
        if (
            len(binding.atom_ids) != code.atom_count
            or len(set(binding.atom_ids)) != code.atom_count
            or any(type(atom) is not int or atom < 0 for atom in binding.atom_ids)
            or not binding.block_id
            or not binding.aod_id
            or len(target_home_sites) != code.atom_count
            or len(set(target_home_sites)) != code.atom_count
            or any(
                type(v) not in (int, float) or not isfinite(v)
                for v in (target_origin.x, target_origin.y)
            )
        ):
            raise ValueError("TRANSLATION_INVALID_BINDING_OR_DESTINATION")
        if _same(binding.origin, target_origin):
            raise ValueError("TRANSLATION_REQUIRES_NONZERO_DISPLACEMENT")
        if world.aod_grids or any(
            not isinstance(atom.holder, SLMHolder) for atom in world.atoms
        ):
            raise ValueError("TRANSLATION_REQUIRES_IDLE_SLM_WORLD")
        try:
            validate_layout(device, world)
            device.aod(binding.aod_id)
            atoms = {atom.id: atom for atom in world.atoms}
            occupancy = Occupancy({atom.id: atom.position for atom in world.atoms})
            source_homes = []
            destinations = {}
            for atom_id, (x, y), site_id in zip(
                binding.atom_ids,
                code.reference_coordinates,
                target_home_sites,
                strict=True,
            ):
                atom = atoms[atom_id]
                assert isinstance(atom.holder, SLMHolder)
                source = Position(
                    binding.origin.x + x * SITE_PITCH_UM,
                    binding.origin.y + y * SITE_PITCH_UM,
                )
                target = device.site(site_id).position
                expected = Position(
                    target_origin.x + x * SITE_PITCH_UM,
                    target_origin.y + y * SITE_PITCH_UM,
                )
                if not _same(atom.position, source) or not _same(target, expected):
                    raise ValueError("TRANSLATION_CODE_GEOMETRY_MISMATCH")
                if occupancy.at(target):
                    raise ValueError("TRANSLATION_DESTINATION_OCCUPIED")
                source_homes.append(atom.holder.site_id)
                destinations[atom_id] = (site_id, target)
            aliases = dict(binding.site_ids)
            if len(aliases) != len(binding.site_ids) or any(
                site not in source_homes for site in aliases.values()
            ):
                raise ValueError("TRANSLATION_UNSUPPORTED_SITE_ALIASES")
            target_world = replace(
                world,
                atoms=tuple(
                    replace(
                        atom,
                        position=destinations[atom.id][1],
                        holder=SLMHolder(destinations[atom.id][0]),
                    )
                    if atom.id in destinations
                    else atom
                    for atom in world.atoms
                ),
            )
            validate_layout(device, target_world)
        except KeyError as error:
            raise ValueError(
                f"TRANSLATION_MISSING_ATOM_DEVICE_OR_SITE: {error}"
            ) from error
        except ValueError as error:
            if str(error).startswith("TRANSLATION_"):
                raise
            raise ValueError(f"TRANSLATION_INVALID_WORLD: {error}") from error
        renamed = dict(zip(source_homes, target_home_sites, strict=True))
        exit_binding = replace(
            binding,
            origin=target_origin,
            site_ids=tuple((key, renamed[site]) for key, site in binding.site_ids),
        )
        return target_world, exit_binding

    def native_goal(
        self,
        device: Device,
        *,
        world: AtomLayout,
        binding: ComponentBinding,
        target_origin: Position,
        target_home_sites: tuple[str, ...],
        operation_id: int,
    ) -> tuple[PhysicalOperation, TransportGoal, ComponentBinding]:
        """Declare this code-owned translation in the current native wire domain.

        Reuses the rigid geometry and vacant-site checks without routing or
        assigning costs. The caller inserts the returned node into its joint
        dependency graph and supplies the goal to the existing physical strategy.
        The exit binding is a requested endpoint, not an executed state update.
        Missing wires raise ValueError; atom identities and code distance remain
        unchanged even when the native wire map is permuted or contains gaps.
        """
        _target_world, exit_binding = self._target(
            device, world, binding, target_origin, target_home_sites
        )
        wires = {atom_id: wire for wire, atom_id in enumerate(world.qubit_to_atom)}
        try:
            selected = tuple(wires[atom_id] for atom_id in binding.atom_ids)
        except KeyError as error:
            raise ValueError(f"TRANSLATION_SOURCE_WIRE_MISSING: {error}") from error
        goal = TransportGoal(
            operation_id, tuple(zip(selected, target_home_sites, strict=True))
        )
        return (
            PhysicalOperation(operation_id, "relocate", selected, (), ()),
            goal,
            exit_binding,
        )

    def compile(
        self,
        device: Device,
        *,
        world: AtomLayout,
        binding: ComponentBinding,
        target_origin: Position,
        target_home_sites: tuple[str, ...],
    ) -> CompiledBlockTranslation:
        """Explicitly route/validate one same-atom translation in the complete world.

        Destination sites must already exist and be vacant. Changed worlds,
        obstructed routes or spectator transport fail rather than inventing a
        buffer, moving another block, changing Device parameters or replanning
        later during expansion. The returned adapter works with PhysicalContext.
        """
        target, exit_binding = self._target(
            device, world, binding, target_origin, target_home_sites
        )
        local_entry = replace(world, qubit_to_atom=binding.atom_ids)
        local_target = replace(target, qubit_to_atom=binding.atom_ids)
        fragment = StrictTransport(binding.aod_id).construct(
            local_entry, local_target, device
        )
        if fragment.exit_layout != local_target:
            raise ValueError("TRANSLATION_EXIT_MISMATCH")
        program = AtomProgram(fragment.steps)
        participants = set(binding.atom_ids)
        for step in program.steps:
            for action in step.actions:
                if isinstance(action, Load | Store):
                    touched = {item[0] for item in action.bindings}
                elif isinstance(action, Move):
                    touched = {item[0] for item in action.targets}
                else:
                    raise TypeError("TRANSLATION_UNEXPECTED_NONTRANSPORT_ACTION")
                if not touched <= participants:
                    raise ValueError("TRANSLATION_TRANSPORTED_SPECTATOR")
        validation = validate_result(
            CompilationResult(program, local_target, (), (), ()),
            entry_state=local_entry,
            device=device,
            dag=PhysicalDAG(len(binding.atom_ids), 0, (), ()),
        )
        if not validation["ok"]:
            raise ValueError(f"TRANSLATION_VALIDATION_FAILED: {validation}")
        return CompiledBlockTranslation(
            self.description,
            device,
            world,
            target,
            binding,
            exit_binding,
            program,
            json.dumps(validation, sort_keys=True),
        )
