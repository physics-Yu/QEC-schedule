"""Lower already admitted independent or shared AOD waves transactionally.

This module checks a declaration against emitted actions. It never discovers
parallelism by trying expansions or establishes a noise model. Local correction
families retain their original pulse times and may finish before their peers.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from copy import copy
from dataclasses import asdict, dataclass, replace
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    CZPulse,
    GlobalRY,
    Load,
    LocalU,
    Measure,
    Move,
    Reset,
    Rotation,
    Store,
    Wait,
)
from nadit_physical_compiler.compiler import CompiledOperation
from nadit_physical_compiler.coverage import RegionSet
from nadit_physical_compiler.device import Position, Region
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.serialization import (
    encode_device,
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.state import AtomLayout, validate_layout

from modules.codes.contracts.component import ComponentExpansion, MeasurementOutput
from modules.codes.contracts.parallel import ComponentExecutionSpec
from modules.logical_compiler.src.scheduling import Admission
from modules.logical_compiler.src.scheduling.compatibility import compatible_specs

from .assembly import (
    PhysicalBatch,
    _append_part,
    _flattened_operation_records,
    _part_record,
    _validate_unobserved,
)
from .local_batch import align_local_lanes
from .shared_grid import (
    SharedGridMapping,
    check_device_claim,
    fuse_step,
    make_mappings,
    project_member,
)

if TYPE_CHECKING:
    from .physical import PhysicalContext


@dataclass(frozen=True)
class PhysicalBatchRequest:
    """One already-admitted call and its exact preallocated measurement count."""

    invocation_id: str
    bound: Any
    result_count: int


def _check_admission(
    context: PhysicalContext,
    admission: Admission,
    requests: tuple[PhysicalBatchRequest, ...],
    not_before_us: float,
) -> tuple[float, tuple[frozenset[int], ...], tuple[frozenset[str], ...]]:
    if not isinstance(admission, Admission):
        raise TypeError("INVALID_BATCH_ADMISSION: immutable Admission required")
    if (
        not requests
        or not isinstance(requests, tuple)
        or any(not isinstance(r, PhysicalBatchRequest) for r in requests)
    ):
        raise ValueError("INVALID_BATCH_REQUESTS: a nonempty tuple is required")
    if admission.snapshot_id != context.snapshot_id:
        raise ValueError("STALE_BATCH_ADMISSION: physical snapshot changed")
    if not isinstance(admission.batch_id, str) or not admission.batch_id.strip():
        raise ValueError("INVALID_BATCH_ID")
    if admission.batch_id in context._identities:
        raise ValueError("DUPLICATE_BATCH_ID")
    if tuple(node.id for node in admission.nodes) != tuple(
        r.invocation_id for r in requests
    ):
        raise ValueError("BATCH_ADMISSION_MEMBERS_DIFFER")
    if len({r.invocation_id for r in requests}) != len(requests):
        raise ValueError("DUPLICATE_BATCH_MEMBER")
    if admission.batch_id in {r.invocation_id for r in requests}:
        raise ValueError("BATCH_ID_COLLIDES_WITH_MEMBER")
    start = admission.start_us
    if (
        type(start) not in (float, int)
        or not isfinite(start)
        or start < context.clock_us
        or start < not_before_us
    ):
        raise ValueError("INVALID_BATCH_START: admission must fix the actual start")
    shapes: set[tuple[str, str, str]] = set()
    owned_atoms: list[frozenset[int]] = []
    owned_aods: list[frozenset[str]] = []
    all_atoms: set[int] = set()
    all_resources: set[str] = set()
    all_spaces: list[Region] = []
    for node, request in zip(admission.nodes, requests, strict=True):
        spec = node.spec
        if (
            spec.parallel_mode
            not in (
                "independent_aods_lockstep",
                "shared_aod_lockstep",
                "local_parallel",
            )
            or not isinstance(spec.waveform_key, str)
            or not spec.waveform_key.strip()
        ):
            raise ValueError("UNDECLARED_LOCKSTEP_SHAPE")
        shapes.add(
            (
                spec.code_id,
                "local_parallel"
                if spec.parallel_mode == "local_parallel"
                else spec.component_id,
                spec.waveform_key,
            )
        )
        if (
            type(request.result_count) is not int
            or request.result_count < 0
            or request.result_count != spec.result_count
        ):
            raise ValueError("INVALID_BATCH_RESULT_COUNT")
        bindings = [context.bindings[block] for block in spec.participant_blocks]
        atoms = frozenset(atom for binding in bindings for atom in binding.atom_ids)
        resources = set(spec.exclusive_resources)
        aods = frozenset(
            resource.removeprefix("aod:")
            for resource in resources
            if resource.startswith("aod:")
        )
        if spec.shared_aod is not None:
            check_device_claim(spec.shared_aod, context._device, context.world)
            aods = aods | {spec.shared_aod.aod_id}
        if not aods <= {binding.aod_id for binding in bindings}:
            raise ValueError("INVALID_BATCH_AOD_BINDING")
        if atoms & all_atoms or resources & all_resources:
            raise ValueError("CONFLICTING_BATCH_CLAIMS")
        if not spec.spaces or any(
            not (
                claim.region.x_max < old.x_min
                or old.x_max < claim.region.x_min
                or claim.region.y_max < old.y_min
                or old.y_max < claim.region.y_min
            )
            for claim in spec.spaces
            for old in all_spaces
        ):
            raise ValueError("CONFLICTING_OR_UNDECLARED_BATCH_SPACE")
        all_spaces.extend(claim.region for claim in spec.spaces)
        _check_envelope(AtomStep(()), context.world, atoms, spec.spaces)
        all_atoms.update(atoms)
        all_resources.update(resources)
        owned_atoms.append(atoms)
        owned_aods.append(aods)
    if len(shapes) != 1:
        raise ValueError("INCOMPATIBLE_LOCKSTEP_DECLARATIONS")
    if not compatible_specs(tuple(node.spec for node in admission.nodes)):
        raise ValueError("INCOMPATIBLE_LOCKSTEP_DECLARATIONS")
    return float(start), tuple(owned_atoms), tuple(owned_aods)


def _check_participants(
    parts: tuple[ComponentExpansion, ...], spec: ComponentExecutionSpec
) -> None:
    """Require joint calls to expose every ordered entry and exit participant."""
    expected = spec.participant_blocks
    for part in parts:
        entries = tuple(binding.block_id for binding in part.participant_bindings)
        exits = (
            (part.exit_binding.block_id,)
            if part.exit_binding is not None
            else tuple(binding.block_id for binding in part.exit_participant_bindings)
        )
        if not set(entries) <= set(expected) or not set(exits) <= set(expected):
            raise ValueError("BATCH_PARTICIPANT_OWNERSHIP_MISMATCH: undeclared binding")
        if len(expected) > 1 and (entries != expected or exits != expected):
            raise ValueError("BATCH_JOINT_PARTICIPANT_BINDINGS_INCOMPLETE")


def _signature(step: AtomStep) -> tuple[Any, ...]:
    result = []
    for action in step.actions:
        common = (type(action).__name__, action.duration_us)
        value: tuple[Any, ...]
        if isinstance(action, Load | Store):
            value = (
                len(action.grid.rows),
                len(action.grid.columns),
                len(action.bindings),
            )
        elif isinstance(action, Move):
            value = (
                len(action.grid.rows),
                len(action.grid.columns),
                len(action.targets),
            )
        elif isinstance(action, Rotation):
            value = (action.channel, action.axis, action.angle, len(action.atoms))
        elif isinstance(action, LocalU):
            value = (
                action.channel,
                action.theta,
                action.phi,
                action.lam,
                len(action.atoms),
            )
        elif isinstance(action, Reset):
            value = (action.channel, len(action.atoms))
        elif isinstance(action, Measure):
            value = (action.channel, action.retain_atoms, len(action.results))
        elif isinstance(action, CZPulse):
            value = (action.channel, type(action.coverage).__name__)
        elif isinstance(action, GlobalRY):
            raise NotImplementedError(
                "GLOBAL_PULSE_BATCH_UNSUPPORTED: explicit footprint required"
            )
        elif isinstance(action, Wait):
            value = ()
        else:
            raise NotImplementedError("UNSUPPORTED_BATCH_ACTION")
        result.append(common + value)
    return tuple(result)


def _projection(
    layout: AtomLayout, atoms: frozenset[int], aods: frozenset[str]
) -> dict[str, Any]:
    return {
        "atoms": [asdict(layout.atom(atom)) for atom in sorted(atoms)],
        "aod_grids": [asdict(layout.grid(aod)) for aod in sorted(aods)],
    }


def _check_ownership(
    step: AtomStep, atoms: frozenset[int], aods: frozenset[str]
) -> None:
    for action in step.actions:
        if isinstance(action, Load | Move | Store):
            if action.grid.aod_id not in aods:
                raise ValueError("BATCH_ACTION_EXCEEDS_AOD_CLAIM")
            touched = {
                a
                for a, *_ in (
                    action.targets if isinstance(action, Move) else action.bindings
                )
            }
        elif isinstance(action, Measure):
            touched = {a for a, _ in action.results}
        elif isinstance(action, Rotation | LocalU | Reset):
            touched = set(action.atoms)
        elif isinstance(action, CZPulse):
            touched = (
                set(action.coverage) if isinstance(action.coverage, tuple) else set()
            )
        else:
            touched = set()
        if not touched <= atoms:
            raise ValueError("BATCH_ACTION_EXCEEDS_PARTICIPANT_CLAIM")


def _inside(region: Region, point: Position) -> bool:
    return (
        region.x_min <= point.x <= region.x_max
        and region.y_min <= point.y <= region.y_max
    )


def _check_envelope(
    step: AtomStep, entry: AtomLayout, atoms: frozenset[int], spaces: Any
) -> None:
    regions = tuple(space.region for space in spaces)
    if not regions:
        raise ValueError("UNDECLARED_BATCH_SPACE")
    if any(
        not any(_inside(region, entry.atom(atom).position) for region in regions)
        for atom in atoms
    ):
        raise ValueError("BATCH_PARTICIPANT_OUTSIDE_DECLARED_SPACE")
    footprints = []
    for action in step.actions:
        if (
            isinstance(action, Load | Move | Store)
            and action.grid.rows
            and action.grid.columns
        ):
            footprints.append(
                (
                    Position(
                        min(c.coordinate for c in action.grid.columns),
                        min(r.coordinate for r in action.grid.rows),
                    ),
                    Position(
                        max(c.coordinate for c in action.grid.columns),
                        max(r.coordinate for r in action.grid.rows),
                    ),
                )
            )
        if isinstance(action, Move):
            footprints.extend(
                (entry.atom(atom).position, target) for atom, target in action.targets
            )
        if isinstance(action, CZPulse) and isinstance(
            action.coverage, Region | RegionSet
        ):
            coverage = (
                (action.coverage,)
                if isinstance(action.coverage, Region)
                else action.coverage.regions
            )
            footprints.extend(
                (Position(r.x_min, r.y_min), Position(r.x_max, r.y_max))
                for r in coverage
            )
    if any(
        not any(_inside(region, left) and _inside(region, right) for region in regions)
        for left, right in footprints
    ):
        raise ValueError("BATCH_ACTION_OUTSIDE_DECLARED_SPACE")


_MemberStep = tuple[int, AtomStep, tuple[int, ...]]


def _compose_steps(
    lanes: tuple[tuple[AtomStep, ...], ...],
    mappings: tuple[SharedGridMapping, ...],
    *,
    local: bool,
    shared: bool,
    start_us: float,
) -> Iterator[tuple[AtomStep, tuple[tuple[_MemberStep, ...], ...]]]:
    """Yield real merged steps and every original member step/action mapping."""
    if local:
        alignment = align_local_lanes(lanes, start_us=start_us)
        grouped: list[list[list[_MemberStep]]] = [
            [[] for _ in lanes] for _ in alignment.steps
        ]
        for member, lane in enumerate(lanes):
            for source, step in enumerate(lane):
                slot = alignment.member_step_indices[member][source]
                grouped[slot][member].append(
                    (source, step, alignment.member_action_indices[member][source])
                )
        for step, groups in zip(alignment.steps, grouped, strict=True):
            yield step, tuple(tuple(group) for group in groups)
        return
    for source, lane_steps in enumerate(zip(*lanes, strict=True)):
        if shared:
            merged, indices = fuse_step(lane_steps, mappings)
        else:
            actions = tuple(action for step in lane_steps for action in step.actions)
            merged = AtomStep(actions)
            offsets = []
            action_base = 0
            for step in lane_steps:
                offsets.append(
                    tuple(range(action_base, action_base + len(step.actions)))
                )
                action_base += len(step.actions)
            indices = tuple(offsets)
        if any(step.duration_us != merged.duration_us for step in lane_steps):
            raise ValueError("LOCKSTEP_DURATION_MISMATCH")
        yield (
            merged,
            tuple(
                ((source, step, index),)
                for step, index in zip(lane_steps, indices, strict=True)
            ),
        )


def build_batch(
    context: PhysicalContext,
    admission: Admission,
    requests: tuple[PhysicalBatchRequest, ...],
    *,
    not_before_us: float,
) -> PhysicalBatch:
    """Check an admitted wave, expand its members and prove the actual embedding.

    Only private context copies are mutated. Admission is checked before invoking
    an expander. Failure never selects a different batch or falls back to serial.
    """
    start, atom_sets, aod_sets = _check_admission(
        context, admission, requests, not_before_us
    )
    members: list[tuple[str, tuple[ComponentExpansion, ...]]] = []
    sources: dict[str, Any] = {}
    records = []
    bindings = dict(context.bindings)
    reserved = context.next_result_id
    identities = {request.invocation_id: request.invocation_id for request in requests}
    for node, request, atoms, aods in zip(
        admission.nodes, requests, atom_sets, aod_sets, strict=True
    ):
        trial = copy(context)
        trial._sources = dict(context._sources)
        trial._next_result_id = reserved
        parts = trial.invoke(
            request.bound,
            request.invocation_id,
            request.result_count,
            not_before_us=start,
        )
        _check_participants(parts, node.spec)
        for part in parts:
            owner = identities.get(part.invocation_id)
            if (
                owner is not None
                and owner != request.invocation_id
                or part.invocation_id == admission.batch_id
                or not set(part.wire_atoms) <= atoms
            ):
                raise ValueError("INVALID_BATCH_PART_IDENTITY_OR_OWNERSHIP")
            identities[part.invocation_id] = request.invocation_id
            for step in part.program.steps:
                _check_ownership(step, atoms, aods)
        members.append((request.invocation_id, parts))
        sources[request.invocation_id] = trial.source(request.invocation_id)
        records.append(trial.invocations[-1])
        for block in admission.nodes[len(members) - 1].spec.participant_blocks:
            bindings[block] = trial.bindings[block]
        reserved += request.result_count
    local = admission.nodes[0].spec.parallel_mode == "local_parallel"
    reference = members[0][1]
    phase_signature = tuple(
        tuple(_signature(step) for step in part.program.steps) for part in reference
    )
    for _, parts in members:
        phase_clock = start
        for part in parts:
            if part.start_us != phase_clock:
                raise ValueError("LOCKSTEP_PHASE_TIME_MISMATCH")
            for step in part.program.steps:
                phase_clock += step.duration_us
            if part.action_end_us != phase_clock:
                raise ValueError("LOCKSTEP_PHASE_TIME_MISMATCH")
        signature = tuple(
            tuple(_signature(step) for step in part.program.steps) for part in parts
        )
        if not local and signature != phase_signature:
            raise ValueError(
                "LOCKSTEP_SHAPE_MISMATCH: no duration padding is permitted"
            )
        if not local and tuple((p.start_us, p.action_end_us) for p in parts) != tuple(
            (p.start_us, p.action_end_us) for p in reference
        ):
            raise ValueError("LOCKSTEP_PHASE_TIME_MISMATCH")

    wire_indices = {atom: wire for wire, atom in enumerate(context.world.qubit_to_atom)}
    nodes: list[PhysicalOperation] = []
    operations: list[CompiledOperation] = []
    edges: set[tuple[int, int]] = set()
    source_map: dict[str, Any] = {}
    part_records: list[dict[str, Any]] = []
    lanes: list[tuple[AtomStep, ...]] = []
    lane_origins: list[list[tuple[str, int]]] = []
    pending: list[MeasurementOutput] = []
    clbit_base, program_phase, dag_phase = 0, 0.0, 0.0
    for _identity, parts in members:
        lane: list[AtomStep] = []
        origins: list[tuple[str, int]] = []
        terminals: tuple[int, ...] = ()
        for part in parts:
            base = len(nodes)
            terminals = _append_part(
                part,
                wire_indices,
                lane,
                nodes,
                edges,
                operations,
                source_map,
                terminals,
                clbit_base,
            )
            origins.extend(
                (part.invocation_id, index) for index in range(len(part.program.steps))
            )
            part_records.append(_part_record(part, base))
            pending.extend(part.measurements)
            clbit_base += part.dag.num_clbits
            program_phase += part.program.global_phase
            dag_phase += part.dag.global_phase
        lanes.append(tuple(lane))
        lane_origins.append(origins)

    shared = admission.nodes[0].spec.parallel_mode == "shared_aod_lockstep"
    mappings = (
        make_mappings(
            tuple(lanes),
            tuple(
                node.spec.shared_aod
                for node in admission.nodes
                if node.spec.shared_aod is not None
            ),
            context.world,
        )
        if shared
        else ()
    )
    world, clock = context.world, start
    lane_worlds = [world for _ in lanes]
    steps: list[AtomStep] = []
    embeddings: list[list[dict[str, Any]]] = [[] for _ in lanes]
    composed = _compose_steps(
        tuple(lanes), mappings, local=local, shared=shared, start_us=start
    )
    for step_index, (merged, groups) in enumerate(composed):
        active_aods = [
            action.grid.aod_id
            for action in merged.actions
            if isinstance(action, Load | Move | Store)
        ]
        if len(set(active_aods)) != len(active_aods):
            raise ValueError("MULTIPLE_GRID_WRITES_IN_BATCH_STEP")
        next_world = apply_step(world, merged, context._device)
        validate_layout(context._device, next_world)
        for index, (group, atoms, aods) in enumerate(
            zip(groups, atom_sets, aod_sets, strict=True)
        ):
            for source_index, step, action_indices in group:
                _check_envelope(
                    step, lane_worlds[index], atoms, admission.nodes[index].spec.spaces
                )
                before = (
                    project_member(world, atoms, mappings[index])
                    if shared
                    else _projection(world, atoms, aods)
                )
                if before != _projection(lane_worlds[index], atoms, aods):
                    raise ValueError("BATCH_PARTICIPANT_ENTRY_PROJECTION_MISMATCH")
                lane_exit = apply_step(lane_worlds[index], step, context._device)
                after = (
                    project_member(next_world, atoms, mappings[index])
                    if shared
                    else _projection(next_world, atoms, aods)
                )
                if after != _projection(lane_exit, atoms, aods):
                    raise ValueError("BATCH_PARTICIPANT_EXIT_PROJECTION_MISMATCH")
                part_id, local_step = lane_origins[index][source_index]
                embeddings[index].append(
                    {
                        "batch_step_index": step_index,
                        "part_invocation_id": part_id,
                        "local_step_index": local_step,
                        "start_us": clock,
                        "end_us": clock + step.duration_us,
                        "batch_action_indices": sorted(set(action_indices)),
                        **(
                            {
                                "action_embeddings": [
                                    {
                                        "source_action_index": original_index,
                                        "batch_action_index": actual_index,
                                        "component_source_ids": list(action.source_ids),
                                        "component_action_sha256": canonical_hash(
                                            encode_program(
                                                AtomProgram((AtomStep((action,)),))
                                            )
                                        ),
                                    }
                                    for original_index, (
                                        action,
                                        actual_index,
                                    ) in enumerate(
                                        zip(step.actions, action_indices, strict=True)
                                    )
                                ]
                            }
                            if shared or local
                            else {}
                        ),
                        "participant_entry_sha256": canonical_hash(before),
                        "participant_exit_sha256": canonical_hash(after),
                    }
                )
                lane_worlds[index] = lane_exit
        steps.append(merged)
        clock += merged.duration_us
        world = next_world
    if clock != max(record.action_end_us for record in records):
        raise ValueError("LOCKSTEP_GLOBAL_CLOCK_MISMATCH")
    program = AtomProgram(tuple(steps), program_phase)
    dag = PhysicalDAG(
        len(wire_indices),
        clbit_base,
        tuple(nodes),
        tuple(sorted(edges)),
        global_phase=dag_phase,
    )
    local_operations = _flattened_operation_records(
        program,
        tuple(
            replace(op, start_us=op.start_us - start, end_us=op.end_us - start)
            for op in operations
        ),
    )
    validation = _validate_unobserved(
        program,
        context.world,
        world,
        context._device,
        dag,
        local_operations,
        tuple(pending),
        time_origin=start,
    )
    proof = {
        "schema": "nadit.physical_lockstep_batch/1",
        "batch_id": admission.batch_id,
        "admission_snapshot_id": admission.snapshot_id,
        "start_us": start,
        "action_end_us": clock,
        "waveform_key": admission.nodes[0].spec.waveform_key,
        "mode": admission.nodes[0].spec.parallel_mode,
        "time_basis": "ordered_global_atom_steps",
        "program_sha256": canonical_hash(encode_program(program)),
        "entry_world_sha256": canonical_hash(encode_layout(context.world)),
        "exit_world_sha256": canonical_hash(encode_layout(world)),
        "device_sha256": canonical_hash(encode_device(context._device)),
        "participant_trajectory_projection_verified": True,
        "declared_space_envelopes_verified": True,
        "cross_patch_interaction_check": "physical_pulse_and_addressing_validation",
        "noise_factorization_claimed": False,
        "global_noise_coverage_claimed": False,
        "validation": validation,
        "members": [
            {
                "invocation_id": request.invocation_id,
                "execution_spec": admission.nodes[index].spec.to_dict(),
                "participant_atoms": sorted(atoms),
                "aod_ids": sorted(aods),
                **({"shared_aod_mapping": mappings[index].to_dict()} if shared else {}),
                "result_id_base": record.result_id_base,
                "result_count": record.result_count,
                "steps": embedding,
                "source_parts": [
                    {
                        "invocation_id": part.invocation_id,
                        "template_content_sha256": part.template_content_sha256,
                        "program_sha256": canonical_hash(encode_program(part.program)),
                        "standalone_entry_world_sha256": canonical_hash(
                            encode_layout(part.entry_state)
                        ),
                        "standalone_exit_world_sha256": canonical_hash(
                            encode_layout(part.exit_state)
                        ),
                        "start_us": part.start_us,
                        "action_end_us": part.action_end_us,
                        "results_ready_us": part.results_ready_us,
                    }
                    for part in member[1]
                ],
                "pending_measurements": [
                    asdict(m) for part in member[1] for m in part.measurements
                ],
            }
            for index, (request, atoms, aods, record, embedding, member) in enumerate(
                zip(
                    requests,
                    atom_sets,
                    aod_sets,
                    records,
                    embeddings,
                    members,
                    strict=True,
                )
            )
        ],
    }
    return PhysicalBatch(
        admission.batch_id,
        start,
        clock,
        program,
        dag,
        local_operations,
        tuple(pending),
        context.world,
        world,
        tuple(bindings[key] for key in sorted(bindings)),
        tuple(records),
        tuple(members),
        source_map,
        tuple(part_records),
        json.dumps(proof, sort_keys=True, separators=(",", ":"), allow_nan=False),
        MappingProxyType(sources),
    )
