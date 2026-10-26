"""Export required raw-T usage without changing either original component."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep
from nadit_physical_compiler.compiler import CompiledOperation
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import (
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.visualization.trace import build_trace

from modules.codes._support.atom_template import AtomComponentTemplate
from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselectionExpansion,
    RawTPostselectionTemplate,
)


def _joined_actions(
    sequence: RawTPostselectionExpansion,
) -> tuple[AtomProgram, tuple[CompiledOperation, ...], dict[str, Any]]:
    """Concatenate real actions, qualifying native operation IDs for the viewer.

    Only provenance IDs change. Physical action parameters and result IDs remain
    exactly those of the validated parts. The sidecar preserves the inverse map.
    """
    steps: list[AtomStep] = []
    operations: list[CompiledOperation] = []
    source_map: dict[str, Any] = {}
    base, start = 0, sequence.parts[0].start_us
    for part in sequence.parts:
        steps.extend(
            replace(
                step,
                actions=tuple(
                    replace(
                        action, source_ids=tuple(i + base for i in action.source_ids)
                    )
                    for action in step.actions
                ),
            )
            for step in part.program.steps
        )
        operations.extend(
            replace(
                operation,
                operation_id=operation.operation_id + base,
                start_us=operation.start_us + part.start_us - start,
                end_us=operation.end_us + part.start_us - start,
            )
            for operation in part.operations
        )
        source_map.update(
            {
                str(node.id + base): {
                    "invocation_id": part.invocation_id,
                    "native_operation_id": node.id,
                }
                for node in part.dag.nodes
            }
        )
        base += len(part.dag.nodes)
    return (
        AtomProgram(tuple(steps), sum(p.program.global_phase for p in sequence.parts)),
        tuple(operations),
        source_map,
    )


def export_raw_t_postselection(
    output: Path,
    device: Device,
    binding: ComponentBinding,
    raw_template: AtomComponentTemplate,
    context: InvocationContext,
    *,
    extra_rounds: int,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Export a complete postselection sequence and return its trace and summary."""
    se = get_component("se_round").compile(
        device,
        home_sites=raw_template.home_sites,
        origin=binding.origin,
        aod_id=binding.aod_id,
    )
    template = RawTPostselectionTemplate(raw_template, se, extra_rounds)
    sequence = template.bind(binding).expand(context)
    program, operations, source_map = _joined_actions(sequence)
    if replay(program, sequence.parts[0].entry_state, device) != sequence.exit_state:
        raise ValueError("Combined raw-T animation disagrees with the sequence exit.")
    name = "raw_t_postselection"
    trace = build_trace(
        program,
        sequence.parts[0].entry_state,
        device,
        title=name,
        description=(
            f"Required raw-T use: unchanged raw_t + {extra_rounds} ordinary SE. "
            f"{len(sequence.measurements)} results, {len(sequence.detectors)} detectors. "
            f"Acceptance PENDING; results ready at {sequence.results_ready_us:.3f} us. "
            "Final temporal boundary remains open."
        ),
        operations=operations,
    )
    report = {
        "protocol_id": sequence.protocol_id,
        "protocol_version": sequence.version,
        "postselection_scope": sequence.postselection_scope,
        "terminal_boundary": sequence.terminal_boundary,
        "followup_rounds": extra_rounds,
        "template_content_sha256": template.content_sha256,
        "start_us": context.start_us,
        "action_end_us": sequence.action_end_us,
        "results_ready_us": sequence.results_ready_us,
        "acceptance_status": sequence.acceptance_status,
        "ready_for_use": sequence.ready_for_use(sequence.results_ready_us),
        "measurements": len(sequence.measurements),
        "detectors": len(sequence.detectors),
        "correction_relations": len(sequence.correction_relations),
        "source_cx": 24 * (1 + extra_rounds),
        "source_cz": 0,
        "validated": True,
        "quantitative_error_rate": None,
    }
    payload = report | {
        "entry_state": encode_layout(sequence.parts[0].entry_state),
        "exit_state": encode_layout(sequence.exit_state),
        "exit_binding": asdict(sequence.exit_binding)
        if sequence.exit_binding
        else None,
        "program": encode_program(program),
        "viewer_source_id_map": source_map,
        "measurements": [asdict(m) for m in sequence.measurements],
        "correction_relations": [asdict(c) for c in sequence.correction_relations],
        "detectors": [
            {
                "name": detector.name,
                "expected": 0,
                "value": detector.value,
                "available_at_us": detector.available_at_us,
                "inputs": [
                    {
                        "invocation_id": m.invocation_id,
                        "port": m.port,
                        "result": asdict(m.result),
                    }
                    for m in detector.measurements
                ],
            }
            for detector in sequence.detectors
        ],
        "parts": [
            {
                "invocation_id": part.invocation_id,
                "component_id": part.description.component_id,
                "template_content_sha256": part.template_content_sha256,
                "start_us": part.start_us,
                "action_end_us": part.action_end_us,
                "results_ready_us": part.results_ready_us,
                "program": encode_program(part.program),
                "measurements": [asdict(m) for m in part.measurements],
                "local_acceptance_status": part.acceptance_status,
            }
            for part in sequence.parts
        ],
    }
    (output / f"{name}.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / f"{name}.atom.txt").write_text(program.to_text(), encoding="utf-8")
    (output / f"{name}.se.qasm3").write_text(se.source_qasm, encoding="utf-8")
    (output / f"{name}.se.relative.json").write_text(
        json.dumps(
            {
                "template_content_sha256": se.content_sha256,
                "relative_program": encode_program(se.relative_program),
                "description": asdict(se.description),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return trace, report, len(sequence.measurements)
