"""Assemble selected component actions without creating measurement evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from math import isclose, isfinite
from typing import Any

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Measure, Wait
from nadit_physical_compiler.compiler import (
    CompilationResult,
    CompiledOperation,
    MeasurementRecord,
)
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.physical_ir import (
    PhysicalDAG,
    PhysicalOperation,
    ResultRef,
)
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import (
    encode_dag,
    encode_device,
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.state import AtomLayout
from nadit_physical_compiler.validation import validate_result
from nadit_physical_compiler.validation_timing import TIME_TOLERANCE_US
from nadit_physical_compiler.visualization.trace import build_trace

from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentExpansion,
    MeasurementOutput,
)

_TIME_TOLERANCE_US = 1e-8


@dataclass(frozen=True)
class PhysicalWait:
    """An explicit idle interval retained in both Atom IR and provenance."""

    start_us: float
    end_us: float
    reason: str


type PhysicalEntry = ComponentExpansion | PhysicalWait | PhysicalBatch


@dataclass(frozen=True)
class PhysicalInvocation:
    """A committed adapter call with its reserved physical-result range."""

    invocation_id: str
    part_invocations: tuple[str, ...]
    start_us: float
    action_end_us: float
    result_id_base: int
    result_count: int


@dataclass(frozen=True)
class PhysicalBatch:
    """Committed synchronous actions plus their unchanged member source objects.

    The batch DAG uses the context's complete wire map and batch-local operation
    IDs. Result identities and all public times are already globally bound.
    Noise factorization requires a separate code-owned proof.
    """

    batch_id: str
    start_us: float
    action_end_us: float
    program: AtomProgram
    dag: PhysicalDAG
    operations: tuple[CompiledOperation, ...]
    measurements: tuple[MeasurementOutput, ...]
    entry_world: AtomLayout
    world: AtomLayout
    bindings: tuple[ComponentBinding, ...]
    invocations: tuple[PhysicalInvocation, ...]
    member_parts: tuple[tuple[str, tuple[ComponentExpansion, ...]], ...]
    source_map: dict[str, Any]
    part_records: tuple[dict[str, Any], ...]
    _proof_json: str
    _sources: Any

    @property
    def results_ready_us(self) -> float:
        """Return actual batch completion and unobserved-result availability."""
        return max(
            (self.action_end_us, *(m.available_at_us for m in self.measurements))
        )

    def source(self, invocation_id: str) -> Any:
        """Return an original runtime expansion; never serialize that object."""
        return self._sources[invocation_id]

    def to_dict(self) -> dict[str, Any]:
        """Return the actual embedding proof without runtime source objects."""
        result: dict[str, Any] = json.loads(self._proof_json)
        return result


@dataclass(frozen=True)
class PhysicalBundle:
    """Validated selected actions and pending results, never sampled bit records.

    The snapshot is separate from ``nadit.result`` because that physical format
    describes observed measurement records. This bundle records no observations.
    """

    program: AtomProgram
    entry_world: AtomLayout
    world: AtomLayout
    device: Device
    dag: PhysicalDAG
    operations: tuple[CompiledOperation, ...]
    pending_measurements: tuple[MeasurementOutput, ...]
    _snapshot_json: str

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-compatible snapshot, including validation scope."""
        document: dict[str, Any] = json.loads(self._snapshot_json)
        return document

    def to_json(self) -> str:
        """Return canonical JSON without recalculating or sampling anything."""
        return self._snapshot_json

    @property
    def validation(self) -> dict[str, Any]:
        """Return a copy of the whole-program validation report."""
        report: dict[str, Any] = self.to_dict()["validation"]
        return report

    def build_trace(self, *, title: str, description: str = "") -> dict[str, Any]:
        """Replay selected actions; keep pending values outside sampled records.

        The trace action timeline includes explicit waits only. ``results_ready_us``
        separately records any unobserved result availability beyond that timeline.
        """
        trace: dict[str, Any] = build_trace(
            self.program,
            self.entry_world,
            self.device,
            title=title,
            description=description,
            measurements=(),
            operations=self.operations,
        )
        snapshot = self.to_dict()
        trace.update(
            duration_us=snapshot["clock_us"],
            program_duration_us=snapshot["clock_us"],
            timing_source="ordered_atom_steps",
            pending_measurements=snapshot["pending_measurements"],
            results_ready_us=snapshot["results_ready_us"],
            measurement_evidence="unobserved",
            physical_execution=False,
            source_id_map=snapshot["source_id_map"],
            parts=snapshot["parts"],
            validation=snapshot["validation"],
        )
        if "parallel_batches" in snapshot:
            trace["parallel_batches"] = snapshot["parallel_batches"]
        return trace


def _validate_unobserved(
    program: AtomProgram,
    entry: AtomLayout,
    exit_state: AtomLayout,
    device: Device,
    dag: PhysicalDAG,
    operations: tuple[CompiledOperation, ...],
    measurements: tuple[MeasurementOutput, ...],
    *,
    time_origin: float = 0,
) -> dict[str, Any]:
    if any(node.condition is not None for node in dag.nodes):
        raise ValueError(
            "UNSUPPORTED_PHYSICAL_CONDITION: select logical branches first"
        )
    if any(measurement.value is not None for measurement in measurements):
        raise ValueError("UNSUPPORTED_OBSERVED_MEASUREMENT: expected pending outputs")
    if replay(program, entry, device) != exit_state:
        raise ValueError(
            "PHYSICAL_REPLAY_MISMATCH: actions do not reach the exit world"
        )
    # validate_result requires bit records. These private structural stand-ins
    # cannot control branches (conditions were rejected), and leave this function
    # only as a validation report. They are never retained in a bundle or trace.
    checked = validate_result(
        CompilationResult(
            program,
            exit_state,
            operations,
            _validation_measurements(program, measurements, device, time_origin),
            (),
        ),
        entry_state=entry,
        device=device,
        dag=dag,
    )
    if not checked["ok"]:
        raise ValueError(f"PHYSICAL_VALIDATION_FAILED: {checked['failure']}")
    return dict(checked) | {
        "scope": "selected_actions_unobserved_measurements",
        "measurement_values_verified": False,
        "logical_branch_semantics_verified": False,
        "physical_execution": False,
    }


def _validation_measurements(
    program: AtomProgram,
    measurements: tuple[MeasurementOutput, ...],
    device: Device,
    time_origin: float,
) -> tuple[MeasurementRecord, ...]:
    """Convert only local validation records, retaining actual global evidence.

    Component-local and global step walks have different floating-point sums.
    An absolute ready time minus the component origin is therefore not its local
    equivalent. Preserve delivery delay relative to the same readout's end:
    local ready = local end + latency + (declared global ready - global minimum).

    Original outputs and event inputs are untouched. The global final validator
    (origin zero) receives their original ready times. A genuinely early global
    declaration is rejected using the physical validator's unchanged tolerance;
    neither the declaration nor its signed extra delay is clamped.
    """
    if time_origin == 0 or not measurements:
        return tuple(
            MeasurementRecord(output.result, 0, output.available_at_us)
            for output in measurements
        )
    if device.readout is None:
        raise ValueError("PHYSICAL_VALIDATION_FAILED: missing readout capability")
    ends: dict[ResultRef, tuple[float, float]] = {}
    local_start, global_start = 0.0, time_origin
    for step in program.steps:
        for action in step.actions:
            if isinstance(action, Measure):
                pair = (
                    local_start + action.duration_us,
                    global_start + action.duration_us,
                )
                for _, reference in action.results:
                    ends[reference] = pair
        local_start += step.duration_us
        global_start += step.duration_us
    records = []
    for output in measurements:
        if output.result not in ends:
            raise ValueError("PHYSICAL_VALIDATION_FAILED: result has no readout action")
        local_end, global_end = ends[output.result]
        global_minimum = global_end + device.readout.latency_us
        if (
            not isfinite(output.available_at_us)
            or output.available_at_us + TIME_TOLERANCE_US < global_minimum
        ):
            raise ValueError(
                "PHYSICAL_VALIDATION_FAILED: "
                f"measurement {output.result.measurement_id} declared at "
                f"{output.available_at_us} us before global readout readiness "
                f"{global_minimum} us"
            )
        extra_delay = output.available_at_us - global_minimum
        local_ready = local_end + device.readout.latency_us + extra_delay
        records.append(MeasurementRecord(output.result, 0, local_ready))
    return tuple(records)


def validate_part(part: ComponentExpansion, device: Device) -> None:
    """Validate one candidate against the complete world before committing it.

    The component DAG uses local wire indices; spectators remain in both layouts.
    Raises ValueError on unsupported feedback, observed bits or failed checks.
    """
    _validate_unobserved(
        part.program,
        replace(part.entry_state, qubit_to_atom=part.wire_atoms),
        replace(part.exit_state, qubit_to_atom=part.wire_atoms),
        device,
        part.dag,
        part.operations,
        part.measurements,
        time_origin=part.start_us,
    )


def _append_part(
    part: ComponentExpansion,
    wire_indices: dict[int, int],
    steps: list[AtomStep],
    nodes: list[PhysicalOperation],
    edges: set[tuple[int, int]],
    operations: list[CompiledOperation],
    source_map: dict[str, Any],
    previous_terminals: tuple[int, ...],
    clbit_base: int,
) -> tuple[int, ...]:
    base = len(nodes)
    for step in part.program.steps:
        steps.append(
            replace(
                step,
                actions=tuple(
                    replace(
                        action, source_ids=tuple(base + i for i in action.source_ids)
                    )
                    for action in step.actions
                ),
            )
        )
    for node in part.dag.nodes:
        global_id = base + node.id
        nodes.append(
            replace(
                node,
                id=global_id,
                qubits=tuple(wire_indices[part.wire_atoms[q]] for q in node.qubits),
                clbits=tuple(clbit_base + bit for bit in node.clbits),
                source_id=node.source_id if node.result is not None else global_id,
            )
        )
        source_map[str(global_id)] = {
            "invocation_id": part.invocation_id,
            "native_operation_id": node.id,
            "source_operation_id": node.source_id,
            "template_content_sha256": part.template_content_sha256,
        }
    edges.update((base + source, base + target) for source, target in part.dag.edges)
    targets = {target for _, target in part.dag.edges}
    sources = {source for source, _ in part.dag.edges}
    roots = tuple(base + node.id for node in part.dag.nodes if node.id not in targets)
    terminals = tuple(
        base + node.id for node in part.dag.nodes if node.id not in sources
    )
    edges.update((source, target) for source in previous_terminals for target in roots)
    operations.extend(
        replace(
            operation,
            operation_id=base + operation.operation_id,
            start_us=part.start_us + operation.start_us,
            end_us=part.start_us + operation.end_us,
        )
        for operation in part.operations
    )
    return terminals or previous_terminals


def _flattened_operation_records(
    program: AtomProgram, operations: tuple[CompiledOperation, ...]
) -> tuple[CompiledOperation, ...]:
    """Read emitted intervals from the final action timeline's summation order.

    Component-local records have already been checked by validate_part. Adding a
    component origin to those local sums is not bitwise equivalent to walking
    the complete AtomProgram. Source IDs therefore bind each operation directly
    to the first and last contributing action on the exported physical timeline.
    Metadata decisions without an action retain their declared times; they are
    not invented gate intervals. Status and source coverage are still checked by
    the unchanged whole-program physical validator.
    """
    intervals: dict[int, tuple[float, float]] = {}
    for start, step in program.timeline():
        for action in step.actions:
            end = start + action.duration_us
            for source in action.source_ids:
                previous = intervals.get(source)
                intervals[source] = (
                    (start, end)
                    if previous is None
                    else (previous[0], max(previous[1], end))
                )
    return tuple(
        replace(
            operation,
            start_us=intervals[operation.operation_id][0],
            end_us=intervals[operation.operation_id][1],
        )
        if operation.operation_id in intervals
        else operation
        for operation in operations
    )


def _part_record(part: ComponentExpansion, base: int) -> dict[str, Any]:
    return {
        "invocation_id": part.invocation_id,
        "block_id": part.block_id,
        "description": asdict(part.description),
        "start_us": part.start_us,
        "action_end_us": part.action_end_us,
        "results_ready_us": part.results_ready_us,
        "wire_atoms": part.wire_atoms,
        "native_operation_base": base,
        "native_operation_count": len(part.dag.nodes),
        "template_content_sha256": part.template_content_sha256,
        "exit_binding": asdict(part.exit_binding) if part.exit_binding else None,
        "participant_bindings": [
            asdict(binding) for binding in part.participant_bindings
        ],
        "exit_participant_bindings": [
            asdict(binding) for binding in part.exit_participant_bindings
        ],
        "correction_relations": [
            asdict(relation) for relation in part.correction_relations
        ],
        "acceptance_conditions": [
            (asdict(reference), value)
            for reference, value in part.acceptance_conditions
        ],
        "output_syndrome_parities": part.output_syndrome_parities,
    }


def _append_batch(
    batch: PhysicalBatch,
    steps: list[AtomStep],
    nodes: list[PhysicalOperation],
    edges: set[tuple[int, int]],
    operations: list[CompiledOperation],
    source_map: dict[str, Any],
    previous_terminals: tuple[int, ...],
    clbit_base: int,
) -> tuple[int, ...]:
    base = len(nodes)
    for step in batch.program.steps:
        steps.append(
            replace(
                step,
                actions=tuple(
                    replace(
                        action, source_ids=tuple(base + i for i in action.source_ids)
                    )
                    for action in step.actions
                ),
            )
        )
    for node in batch.dag.nodes:
        nodes.append(
            replace(
                node,
                id=base + node.id,
                clbits=tuple(clbit_base + bit for bit in node.clbits),
                source_id=node.source_id if node.result is not None else base + node.id,
            )
        )
    source_map.update(
        {str(base + int(key)): value for key, value in batch.source_map.items()}
    )
    edges.update((base + source, base + target) for source, target in batch.dag.edges)
    targets = {target for _, target in batch.dag.edges}
    sources = {source for source, _ in batch.dag.edges}
    roots = tuple(base + node.id for node in batch.dag.nodes if node.id not in targets)
    edges.update((source, target) for source in previous_terminals for target in roots)
    operations.extend(
        replace(
            operation,
            operation_id=base + operation.operation_id,
            start_us=batch.start_us + operation.start_us,
            end_us=batch.start_us + operation.end_us,
        )
        for operation in batch.operations
    )
    return (
        tuple(base + node.id for node in batch.dag.nodes if node.id not in sources)
        or previous_terminals
    )


def assemble(
    entries: tuple[PhysicalEntry, ...],
    *,
    device: Device,
    entry_world: AtomLayout,
    world: AtomLayout,
    bindings: tuple[ComponentBinding, ...],
    invocations: tuple[PhysicalInvocation, ...],
    input_entry_wire_map: tuple[int, ...],
) -> PhysicalBundle:
    """Flatten and validate committed serial calls and synchronous batches.

    Local operation IDs and wires are remapped; already-global ResultRefs are
    preserved. Invalid world, timing, source or result references raise ValueError.
    """
    wire_indices = {atom: wire for wire, atom in enumerate(entry_world.qubit_to_atom)}
    steps: list[AtomStep] = []
    nodes: list[PhysicalOperation] = []
    edges: set[tuple[int, int]] = set()
    operations: list[CompiledOperation] = []
    pending: list[MeasurementOutput] = []
    source_map: dict[str, Any] = {}
    part_records: list[dict[str, Any]] = []
    waits: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    terminals: tuple[int, ...] = ()
    clock, program_phase, dag_phase = 0.0, 0.0, 0.0
    clbit_count = 0
    for entry in entries:
        if not isclose(entry.start_us, clock, rel_tol=0, abs_tol=_TIME_TOLERANCE_US):
            raise ValueError("PHYSICAL_TIME_DISCONTINUITY: missing explicit Wait")
        if isinstance(entry, PhysicalWait):
            steps.append(AtomStep((Wait(duration_us=entry.end_us - entry.start_us),)))
            waits.append(asdict(entry))
            clock = entry.end_us
            continue
        base = len(nodes)
        if isinstance(entry, PhysicalBatch):
            terminals = _append_batch(
                entry,
                steps,
                nodes,
                edges,
                operations,
                source_map,
                terminals,
                clbit_count,
            )
            part_records.extend(
                record
                | {
                    "native_operation_base": record["native_operation_base"] + base,
                    "parallel_batch_id": entry.batch_id,
                }
                for record in entry.part_records
            )
            batches.append(entry.to_dict() | {"global_operation_base": base})
            pending.extend(entry.measurements)
            clbit_count += entry.dag.num_clbits
            program_phase += entry.program.global_phase
            dag_phase += entry.dag.global_phase
            clock = entry.action_end_us
            continue
        terminals = _append_part(
            entry,
            wire_indices,
            steps,
            nodes,
            edges,
            operations,
            source_map,
            terminals,
            clbit_count,
        )
        part_records.append(_part_record(entry, base))
        pending.extend(entry.measurements)
        clbit_count += entry.dag.num_clbits
        program_phase += entry.program.global_phase
        dag_phase += entry.dag.global_phase
        clock = entry.action_end_us
    program = AtomProgram(tuple(steps), program_phase)
    flattened_operations = _flattened_operation_records(program, tuple(operations))
    dag = PhysicalDAG(
        len(wire_indices),
        clbit_count,
        tuple(nodes),
        tuple(sorted(edges)),
        global_phase=dag_phase,
    )
    checked = _validate_unobserved(
        program, entry_world, world, device, dag, flattened_operations, tuple(pending)
    )
    document = {
        "schema": "nadit.logical_physical_program/1",
        "artifact_kind": "selected_atom_program",
        "physical_execution": False,
        "measurement_evidence": "unobserved",
        "frame_status": "unresolved",
        "program": encode_program(program),
        "dag": encode_dag(dag),
        "entry_state": encode_layout(entry_world),
        "exit_state": encode_layout(world),
        "device": encode_device(device),
        "input_entry_wire_map": input_entry_wire_map,
        "normalized_entry_wire_map": entry_world.qubit_to_atom,
        "operations": [asdict(operation) for operation in flattened_operations],
        "operation_timing_source": "flattened_atom_action_intervals",
        "pending_measurements": [asdict(measurement) for measurement in pending],
        "bindings": [asdict(binding) for binding in bindings],
        "invocations": [asdict(invocation) for invocation in invocations],
        "parts": part_records,
        "waits": waits,
        "source_id_map": source_map,
        **({"parallel_batches": batches} if batches else {}),
        "clock_us": clock,
        "timing_source": "ordered_atom_steps",
        "results_ready_us": max((clock, *(m.available_at_us for m in pending))),
        "validation": checked,
    }
    snapshot = json.dumps(
        document,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return PhysicalBundle(
        program,
        entry_world,
        world,
        device,
        dag,
        flattened_operations,
        tuple(pending),
        snapshot,
    )
