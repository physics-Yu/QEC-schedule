"""Export complete conditional raw-T preparation from validated saved segments."""

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Measure
from nadit_physical_compiler.compiler import CompiledOperation
from nadit_physical_compiler.cost import prepare
from nadit_physical_compiler.device import loads_device
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import decode_layout, decode_result
from nadit_physical_compiler.visualization import build_trace, write_html


def complete_trace(directory: Path, distance: int) -> dict[str, Any]:
    """Join time-ordered validated segments without using placeholder outcome bits.

    This is the conditional accepted path, not a sampled retry history. Every
    source segment is semantically revalidated and the concatenated program is
    replayed in the full world. No atoms, actions or transport steps are omitted.
    """
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    case = next(c for c in summary["cases"] if c["distance"] == distance)
    names = [f"d{distance}.injection.result.json"]
    if distance > 3:
        names.append(f"d{distance}.growth.result.json")
    documents = [
        json.loads((directory / name).read_text(encoding="utf-8")) for name in names
    ]
    device = loads_device(json.dumps(documents[0]["device"]))
    if (device.timing.load_us, device.timing.store_us) != (10, 10):
        raise ValueError("This animation requires the requested 10 us transfers.")
    entry = decode_layout(documents[0]["entry_state"])
    entry = replace(entry, qubit_to_atom=tuple(a.id for a in entry.atoms))
    steps: list[AtomStep] = []
    operations: list[CompiledOperation] = []
    stages: list[dict[str, Any]] = []
    cursor, phase, node_base = 0.0, 0.0, 0
    result_ids: set[int] = set()
    for name, document in zip(names, documents, strict=True):
        prepare(document)
        if document["device"] != documents[0]["device"]:
            raise ValueError("Cannot join segments from different devices.")
        for endpoint in ("entry_state", "exit_state"):
            state = decode_layout(document[endpoint])
            if replace(state, qubit_to_atom=entry.qubit_to_atom) != entry:
                raise ValueError("Stage boundary does not preserve the complete world.")
        result = decode_result(document)
        start = cursor
        for step in result.program.steps:
            for action in step.actions:
                if isinstance(action, Measure):
                    ids = {ref.measurement_id for _, ref in action.results}
                    if result_ids & ids:
                        raise ValueError(
                            "Measurement identities overlap across stages."
                        )
                    result_ids.update(ids)
            steps.append(
                AtomStep(
                    tuple(
                        replace(
                            a, source_ids=tuple(i + node_base for i in a.source_ids)
                        )
                        for a in step.actions
                    )
                )
            )
            cursor += step.duration_us
        operations.extend(
            replace(
                op,
                operation_id=op.operation_id + node_base,
                start_us=op.start_us + start,
                end_us=op.end_us + start,
            )
            for op in result.operations
        )
        phase += result.program.global_phase
        stages.append(
            {
                "name": name,
                "start_us": start,
                "end_us": cursor,
                "source_sha256": canonical_hash(document),
            }
        )
        node_base += len(document["dag"]["nodes"])
    program = AtomProgram(tuple(steps), phase)
    if replay(program, entry, device) != entry:
        raise ValueError("Complete animation fails final replay equality.")
    expected = case["injection_metrics"]["execution_duration_us"] + (
        0
        if case["growth_metrics"] is None
        else case["growth_metrics"]["execution_duration_us"]
    )
    if abs(program.duration_us - expected) > 1e-8:
        raise ValueError("Animation duration differs from the actual branch schedule.")
    injection_rounds = case["protocol"]["injection_rounds"]
    growth_rounds = case["protocol"]["growth_rounds"]
    trace = build_trace(
        program,
        entry,
        device,
        title=f"d3 injection -> d{distance}: {injection_rounds}+{growth_rounds} SE rounds",
        description=f"LOAD/STORE 10 us; readout 100 us. Full conditional accepted path, {program.duration_us / 1000:.3f} ms; no sampled rejection/retry or measurement values. Injection ends at {stages[0]['end_us']:.3f} us. All {len(entry.atoms)} atoms retained. Gates and movement replay only; not a quantum-state animation.",
        operations=operations,
    )
    trace["compilation"] = {
        "validation": {
            "ok": True,
            "scope": "all_source_segments_semantically_revalidated_and_complete_replay",
            "measurement_values_verified": False,
        },
        "stages": stages,
        "physical_execution": False,
        "measurement_evidence": "unobserved",
        "source_tree_sha256": summary["source_tree_sha256"],
    }
    trace["stage_boundaries"] = stages
    return trace


def main() -> None:
    """Write a self-contained viewer, defaulting to the discussed d5 example."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    traces = [complete_trace(args.directory, d) for d in (5, 7, 3)]
    path = write_html(
        traces, args.output, title="MSD: 10 us transfer, complete injection and growth"
    )
    # Choose direct endpoint interpolation for this export; the shared viewer
    # and all compiled coordinates/timing remain unchanged.
    html = path.read_text(encoding="utf-8")
    html = html.replace(
        '<option value="direct">Direct</option>',
        '<option value="direct" selected>Direct</option>',
    )
    html = html.replace(
        '<option value="proportional">', '<option value="proportional" selected>'
    )
    path.write_text(html, encoding="utf-8", newline="\n")
    path.with_suffix(".traces.json").write_text(
        json.dumps({"traces": traces}, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "viewer": str(path),
                "cases": [
                    {
                        "title": t["title"],
                        "steps": len(t["steps"]),
                        "duration_us": t["duration_us"],
                    }
                    for t in traces
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
