"""Export code-owned atom components with independent saved-result admission."""

import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Measure
from nadit_physical_compiler.compiler import (
    CompilationResult,
    CompiledOperation,
    MeasurementRecord,
)
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import (
    encode_dag,
    encode_device,
    encode_layout,
    encode_program,
    encode_result,
)
from nadit_physical_compiler.validation import validate_result
from nadit_physical_compiler.visualization import build_trace, write_html

from modules.codes._support.atom_template import AtomComponentTemplate
from modules.codes.contracts.component import ComponentExpansion, validate_sequence

from .calibrate import summarize


def write_json(path: Path, data: Any) -> None:
    """Create a JSON artifact without silently replacing an existing result."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def export_component(
    template: AtomComponentTemplate,
    expansion: ComponentExpansion,
    device: Device,
    output: Path,
) -> dict[str, Any]:
    """Save source, complete relative template, pending expansion and validated IR.

    Result zeros are structural validator placeholders, explicitly marked in
    provenance. Public expansion outcomes and viewer measurement values remain
    unobserved. H retains its changed physical exit and canonical exit binding.
    """
    output.mkdir(parents=True, exist_ok=False)
    if any(m.value is not None for m in expansion.measurements):
        raise ValueError("Component export requires unobserved measurements.")
    offsets = {}
    for start, step in expansion.program.timeline():
        for action in step.actions:
            if isinstance(action, Measure):
                assert device.readout is not None
                for _, ref in action.results:
                    offsets[ref] = (
                        start + action.duration_us + device.readout.latency_us
                    )
    result = CompilationResult(
        expansion.program,
        replace(expansion.exit_state, qubit_to_atom=expansion.wire_atoms),
        expansion.operations,
        tuple(
            MeasurementRecord(m.result, 0, offsets[m.result])
            for m in expansion.measurements
        ),
        (),
    )
    entry = replace(expansion.entry_state, qubit_to_atom=expansion.wire_atoms)
    validation = validate_result(
        result, entry_state=entry, device=device, dag=expansion.dag
    )
    if not validation["ok"]:
        raise ValueError(
            f"Export validation failed for {expansion.invocation_id}: {validation}"
        )
    document = encode_result(
        result,
        entry_state=entry,
        job={"strategy": {"kind": "nonzoned"}},
        provenance={
            "purpose": "unobserved_component_export",
            "measurement_values_are_observations": False,
        },
        validation=validation,
        dag=expansion.dag,
        device=device,
        inputs={
            "qasm_sha256": sha256(template.source_qasm.encode()).hexdigest(),
            "device_sha256": canonical_hash(encode_device(device)),
        },
    )
    (output / "source.qasm3").write_text(template.source_qasm, encoding="utf-8")
    (output / "actions.atom.txt").write_text(
        expansion.program.to_text(), encoding="utf-8"
    )
    write_json(
        output / "template.json",
        asdict(template)
        | {
            "relative_program": encode_program(template.relative_program),
            "dag": encode_dag(template.dag),
            "content_sha256": template.content_sha256,
        },
    )
    write_json(
        output / "expansion.json",
        asdict(expansion)
        | {
            "program": encode_program(expansion.program),
            "dag": encode_dag(expansion.dag),
            "entry_state": encode_layout(expansion.entry_state),
            "exit_state": encode_layout(expansion.exit_state),
        },
    )
    write_json(output / "result.json", document)
    trace = build_trace(
        expansion.program,
        expansion.entry_state,
        device,
        title=expansion.invocation_id,
        description="Actual compiled actions in the complete world. Measurement outcomes remain unobserved; frame corrections are explicit metadata.",
        operations=expansion.operations,
    )
    write_html([trace], output / "index.html", title=expansion.invocation_id)
    return {
        "description": asdict(expansion.description),
        "template_sha256": template.content_sha256,
        "source_sha256": template.source_sha256,
        "measurement_count": len(expansion.measurements),
        "correction_relation_count": len(expansion.correction_relations),
        "participant_atoms": len(expansion.wire_atoms),
        "exit_binding": asdict(expansion.exit_binding)
        if expansion.exit_binding
        else None,
        "exit_participant_bindings": [
            asdict(b) for b in expansion.exit_participant_bindings
        ],
        "metrics": summarize(document),
        "validation": validation,
        "artifacts": {
            "source": "source.qasm3",
            "relative_template": "template.json",
            "pending_expansion": "expansion.json",
            "validated_result": "result.json",
            "actions": "actions.atom.txt",
            "viewer": "index.html",
        },
    }


def export_sequence_viewer(
    parts: tuple[ComponentExpansion, ...], device: Device, output: Path, *, title: str
) -> None:
    """Show all stages of an unobserved conditional branch without choosing it."""
    validate_sequence(parts)
    steps: list[AtomStep] = []
    operations: list[CompiledOperation] = []
    node_base = 0
    for part in parts:
        steps.extend(
            replace(
                step,
                actions=tuple(
                    replace(a, source_ids=tuple(n + node_base for n in a.source_ids))
                    for a in step.actions
                ),
            )
            for step in part.program.steps
        )
        operations.extend(
            replace(
                op,
                operation_id=op.operation_id + node_base,
                start_us=op.start_us + part.start_us,
                end_us=op.end_us + part.start_us,
            )
            for op in part.operations
        )
        node_base += len(part.dag.nodes)
    program = AtomProgram(tuple(steps), sum(p.program.global_phase for p in parts))
    if abs(program.duration_us - (parts[-1].action_end_us - parts[0].start_us)) > 1e-8:
        raise ValueError("Sequence viewer must not drop an inter-stage wait.")
    trace = build_trace(
        program,
        parts[0].entry_state,
        device,
        title=title,
        description="Conditional accepted injection/growth path; no sampled outcomes, retries or physical correction frame application. Each source stage is validated separately.",
        operations=operations,
    )
    write_html([trace], output, title=title)
