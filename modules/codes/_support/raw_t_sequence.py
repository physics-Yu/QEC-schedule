"""Revalidate actual raw-preparation parts as one occupied-world timeline.

The caller supplies code-owned approved source circuits. This helper preserves
inter-round gaps, result-delivery tails, atom identities, and all spectators.
"""

import re
from dataclasses import replace
from hashlib import sha256
from math import isfinite
from typing import Any, Protocol

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Measure, Wait
from nadit_physical_compiler.compiler import (
    CompilationResult,
    CompiledOperation,
    MeasurementRecord,
)
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_device, encode_result
from nadit_physical_compiler.state import AtomLayout
from nadit_physical_compiler.validation import validate_result

from modules.codes.contracts.component import ComponentExpansion, MeasurementOutput


class ComponentTimeline(Protocol):
    """Read-only equal-width sequence used for validated timeline serialization."""

    @property
    def parts(self) -> tuple[ComponentExpansion, ...]: ...

    @property
    def measurements(self) -> tuple[MeasurementOutput, ...]: ...

    @property
    def exit_state(self) -> AtomLayout: ...


def _shift_measurements(body: str, offset: int) -> str:
    """Give each concatenated round distinct classical source wires."""
    return re.sub(r"m\[(\d+)\]", lambda match: f"m[{int(match[1]) + offset}]", body)


def joint_raw_t_document(
    sequence: ComponentTimeline,
    device: Device,
    *,
    sources: tuple[str, ...],
    participant_count: int,
    measurements_per_round: int,
) -> dict[str, Any]:
    """Join original physical parts and revalidate one complete v2 timeline.

    Value-zero records are structural validation placeholders, never sampled or
    used to construct probabilities. Only the unobserved detector identities are
    consumed. One activity derivation prevents duplicate per-part idle tails.
    The complete occupied world is retained for semantic validation and cost;
    the participant DAG wires refer only to this raw preparation's participants.
    The segment is rebased to its first action, excluding earlier world history.
    """
    if any(record.value is not None for record in sequence.measurements):
        raise ValueError(
            "Offline model construction requires unobserved measurement ports."
        )
    if len(sequence.parts[0].wire_atoms) != participant_count:
        raise ValueError("Raw-T estimation participant count disagrees with its code.")
    if len(sources) != len(sequence.parts):
        raise ValueError("Raw-T source count disagrees with the round count.")
    bodies: list[str] = []
    steps: list[AtomStep] = []
    operations: list[CompiledOperation] = []
    measurements: list[MeasurementRecord] = []
    node_base = 0
    previous_end = sequence.parts[0].start_us
    cursor = 0.0
    latency = device.readout.latency_us if device.readout is not None else 0.0
    for index, (part, source) in enumerate(zip(sequence.parts, sources, strict=True)):
        expected = loads_qasm(source)
        local_ids = {
            i: m.result.measurement_id for i, m in enumerate(part.measurements)
        }
        expected = replace(
            expected,
            nodes=tuple(
                replace(node, source_id=local_ids[node.clbits[0]])
                if node.result is not None
                else node
                for node in expected.nodes
            ),
        )
        if expected != part.dag:
            raise ValueError("Unapproved raw-T/SE source profile in estimator input.")
        lines = source.splitlines()
        if lines[:4] != [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            f"qubit[{participant_count}] q;",
            f"bit[{measurements_per_round}] m;",
        ]:
            raise ValueError("Unrecognized source register profile.")
        bodies.append(
            _shift_measurements("\n".join(lines[4:]), measurements_per_round * index)
        )
        gap = part.start_us - previous_end
        if gap < -1e-9:
            raise ValueError("Raw-T component action timelines overlap.")
        if gap > 1e-9:
            steps.append(AtomStep((Wait(duration_us=gap),)))
            cursor += gap
        # Rebase private records using the same ordered additions as this joined
        # program. Subtracting a large absolute clock can exceed the validator's
        # tolerance even when the original source records are exactly correct.
        offset = cursor
        time_map = {0.0: cursor}
        absolute_cursor = part.start_us
        absolute_ready: dict[int, float] = {}
        local_ready: dict[int, float] = {}
        for local_start, step in part.program.timeline():
            time_map[local_start] = cursor
            for action in step.actions:
                time_map[local_start + action.duration_us] = cursor + action.duration_us
                if isinstance(action, Measure):
                    for _, reference in action.results:
                        absolute_ready[reference.measurement_id] = (
                            absolute_cursor + action.duration_us + latency
                        )
                        local_ready[reference.measurement_id] = (
                            cursor + action.duration_us + latency
                        )
            steps.append(
                replace(
                    step,
                    actions=tuple(
                        replace(
                            action,
                            source_ids=tuple(n + node_base for n in action.source_ids),
                        )
                        for action in step.actions
                    ),
                )
            )
            cursor += step.duration_us
            absolute_cursor += step.duration_us
            time_map[local_start + step.duration_us] = cursor
        operations.extend(
            replace(
                operation,
                operation_id=operation.operation_id + node_base,
                start_us=time_map.get(operation.start_us, offset + operation.start_us),
                end_us=time_map.get(operation.end_us, offset + operation.end_us),
            )
            for operation in part.operations
        )
        for measurement in part.measurements:
            identity = measurement.result.measurement_id
            delay = measurement.available_at_us - absolute_ready[identity]
            if not isfinite(delay):
                raise ValueError("Source measurement availability must be finite.")
            if delay < -1e-9:
                raise ValueError(
                    "Source measurement precedes actual result availability."
                )
            # Preserve an explicit delivery delay, but never rewrite the public
            # measurement/event time or infer extra delay from clock rebasing.
            measurements.append(
                MeasurementRecord(
                    measurement.result, 0, local_ready[identity] + max(0.0, delay)
                )
            )
        node_base += len(part.dag.nodes)
        previous_end = part.action_end_us
    joined_source = "\n".join(
        [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            f"qubit[{participant_count}] q;",
            f"bit[{len(sequence.measurements)}] m;",
            *bodies,
            "",
        ]
    )
    dag = loads_qasm(joined_source)
    ids = {i: m.result.measurement_id for i, m in enumerate(sequence.measurements)}
    dag = replace(
        dag,
        nodes=tuple(
            replace(n, source_id=ids[n.clbits[0]]) if n.result is not None else n
            for n in dag.nodes
        ),
    )
    entry = replace(
        sequence.parts[0].entry_state, qubit_to_atom=sequence.parts[0].wire_atoms
    )
    exit_state = replace(
        sequence.exit_state, qubit_to_atom=sequence.parts[0].wire_atoms
    )
    program = AtomProgram(
        tuple(steps), sum(part.program.global_phase for part in sequence.parts)
    )
    result = CompilationResult(
        program,
        exit_state,
        tuple(operations),
        tuple(measurements),
        (),
    )
    validation = validate_result(result, entry_state=entry, device=device, dag=dag)
    if not validation["ok"]:
        raise ValueError(f"Combined raw-T semantic admission failed: {validation}")
    return encode_result(
        result,
        entry_state=entry,
        job={"strategy": {"kind": "nonzoned"}},
        provenance={"purpose": "offline_raw_t_detector_probability"},
        validation=validation,
        dag=dag,
        device=device,
        inputs={
            "qasm_sha256": sha256(joined_source.encode()).hexdigest(),
            "device_sha256": canonical_hash(encode_device(device)),
        },
    )
