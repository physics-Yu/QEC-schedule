"""Generate, compile and independently check three d3 operation examples."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any

from circuits import CHECKS, COORDINATES, job, operations, qasm, se_layers


def write_json(path: Path, value: Any) -> None:
    """Save a deterministic, inspectable JSON artifact."""
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def freeze_compiler(output: Path, requested_revision: str) -> dict[str, Any]:
    """Extract committed compiler sources without altering the shared checkout."""
    root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).parent,
            text=True,
        ).strip()
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", f"{requested_revision}^{{commit}}"], cwd=root, text=True
    ).strip()
    prefix = "modules/physical_compiler/src/"
    archive = subprocess.check_output(
        ["git", "archive", "--format=zip", revision, prefix], cwd=root
    )
    snapshot = output / "compiler_snapshot"
    hashes = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        for member in zipped.infolist():
            if member.is_dir() or not member.filename.startswith(prefix):
                continue
            relative = member.filename.removeprefix(prefix)
            path = snapshot / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = zipped.read(member)
            path.write_bytes(data)
            hashes[relative] = hashlib.sha256(data).hexdigest()
    sys.path.insert(0, str(snapshot))
    script_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(__file__).parent.glob("*.py")
    }
    provenance = {
        "compiler_revision": revision,
        "python_version": sys.version,
        "installed_versions": {
            name: version(name)
            for name in ("stim", "numpy", "qiskit", "qiskit-qasm3-import")
        },
        "compiler_snapshot_sha256": hashes,
        "study_scripts_sha256": script_hashes,
        "working_tree_changes_excluded_from_compiler_snapshot": True,
        "working_tree_status_at_start": subprocess.check_output(
            ["git", "status", "--short"], cwd=root, text=True, encoding="utf-8"
        ),
    }
    write_json(output / "provenance.json", provenance)
    return provenance


def normalize_coordinates(
    value: Any, origin: tuple[float, float], path: tuple[str, ...] = ()
) -> Any:
    """Remove a common resource-tile translation from serialized Atom IR."""
    if isinstance(value, list):
        return [normalize_coordinates(v, origin, path) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, v in value.items():
        if key in ("x", "x_min", "x_max"):
            result[key] = v - origin[0]
        elif key in ("y", "y_min", "y_max"):
            result[key] = v - origin[1]
        elif key == "coordinate":
            assert "rows" in path or "columns" in path
            result[key] = v - origin[1 if "rows" in path else 0]
        else:
            result[key] = normalize_coordinates(v, origin, (*path, key))
    return result


def compile_one(
    output: Path, name: str, provenance: dict[str, Any]
) -> tuple[dict[str, Any], Any]:
    """Compile a base case plus a translated tile and write their evidence."""
    from nadit_physical_compiler.job import compile_job, load_job
    from nadit_physical_compiler.serialization import encode_program, encode_result
    from nadit_physical_compiler.validation import validate_result
    from nadit_physical_compiler.visualization.trace import build_trace
    from verify import check_operation, source_circuit

    source = qasm(name)
    (output / f"{name}.qasm3").write_text(source, encoding="utf-8")
    reference, _ = source_circuit(source)
    (output / f"{name}.source.stim").write_text(str(reference), encoding="utf-8")
    (output / f"{name}.circuit.svg").write_text(
        str(reference.diagram("timeline-svg")), encoding="utf-8"
    )
    write_json(output / f"{name}.job.json", job(name))
    resolved = load_job(output / f"{name}.job.json")
    result = compile_job(resolved)
    validation = validate_result(
        result,
        entry_state=resolved.entry_state,
        device=resolved.device,
        dag=resolved.dag,
    )
    write_json(output / f"{name}.validation.json", validation)
    assert validation["ok"], validation
    quantum, actual = check_operation(name, source, result, resolved)
    (output / f"{name}.atom_ideal.stim").write_text(str(actual), encoding="utf-8")
    (output / f"{name}.atom.txt").write_text(result.program.to_text(), encoding="utf-8")
    document = encode_result(
        result,
        entry_state=resolved.entry_state,
        job=resolved.document,
        dag=resolved.dag,
        device=resolved.device,
        inputs=resolved.inputs,
        validation=validation,
    )
    document["provenance"]["compiler_source_revision"] = provenance["compiler_revision"]
    document["provenance"]["study_provenance_file"] = "provenance.json"
    write_json(output / f"{name}.result.json", document)
    # This recompilation verifies equivariance; it is not a reusable binding API.
    origin = (120.0, 80.0)
    write_json(output / f"{name}.translated.job.json", job(name, origin))
    translated_job = load_job(output / f"{name}.translated.job.json")
    translated = compile_job(translated_job)
    translated_validation = validate_result(
        translated,
        entry_state=translated_job.entry_state,
        device=translated_job.device,
        dag=translated_job.dag,
    )
    assert translated_validation["ok"], translated_validation
    assert translated.exit_state == translated_job.entry_state
    assert normalize_coordinates(
        encode_program(translated.program), origin
    ) == encode_program(result.program)
    write_json(
        output / f"{name}.translated.result.json",
        encode_result(
            translated,
            entry_state=translated_job.entry_state,
            job=translated_job.document,
            dag=translated_job.dag,
            device=translated_job.device,
            inputs=translated_job.inputs,
            validation=translated_validation,
        ),
    )
    counts = Counter(g for g, _ in operations(name) if g != "TICK")
    report = {
        "source_gate_counts": dict(counts),
        "metrics": document["metrics"],
        "physical_validation": validation,
        "quantum_checks": quantum,
        "exit_equals_entry": True,
        "translation_check": {
            "offset_um": origin,
            "entire_resource_tile_translated": True,
            "normalized_actions_identical": True,
            "validation": translated_validation,
        },
        "measurement_available_at_us": [r.available_at_us for r in result.measurements],
        "measurement_records": document["measurements"],
    }
    write_json(output / f"{name}.checks.json", report)
    trace = build_trace(
        result.program,
        resolved.entry_state,
        resolved.device,
        title=name,
        description="Fixed nonzoned compilation; fake case bits, separate ideal quantum checks. No noise or FT claim.",
        measurements=result.measurements,
        operations=result.operations,
    )
    print(
        f"{name}: verified; actions={result.program.duration_us:.6f} us; results={result.duration_us:.6f} us",
        flush=True,
    )
    return report, trace


def main() -> None:
    """Run the bounded study into a fresh output directory."""
    if not __debug__:
        raise RuntimeError("Evidence checks require Python assertions; do not use -O.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler-revision", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    provenance = freeze_compiler(output, args.compiler_revision)
    from nadit_physical_compiler.visualization.export import write_html
    from verify import code_checks

    report = {
        "scope": "Three d3 operation examples, not a production component interface",
        "compiler_revision": provenance["compiler_revision"],
        "code_checks": code_checks(),
        "operations": {},
        "limitations": [
            "Illustrative device timings, no optimization search",
            "No circuit-level distance or noisy logical-failure claim",
            "No runtime frame or component-result continuity API",
            "Translation check moves the full resource tile, including readout",
        ],
    }
    write_json(
        output / "relative_layout.json",
        {
            "origin_um": [0, 0],
            "unit_um": 10,
            "roles": [
                {
                    "role": f"data[{q}]" if q < 9 else f"check[{q - 9}]",
                    "qubit": q,
                    "atom_id": q,
                    "home_offset_um": [10 * x, 10 * y],
                }
                for q, (x, y) in COORDINATES.items()
            ],
            "checks": [
                {"basis": b, "support": qs, "ancilla": 9 + i}
                for i, (b, qs, _) in enumerate(CHECKS)
            ],
            "se_nz_layers": se_layers(),
        },
    )
    traces = []
    for name in ("initialize_0", "initialize_plus", "se_round"):
        checked, trace = compile_one(output, name, provenance)
        report["operations"][name] = checked
        traces.append(trace)
    write_json(output / "report.json", report)
    write_html(
        traces,
        output / "index.html",
        title="NADiT d3 initialization and single-round SE",
    )
    rows = [
        "# d3 three-operation compilation report",
        "",
        "All three source circuits and six physical compilations passed the recorded checks.",
        "",
        "| Operation | CX | Measurements | Action time (us) | Result-ready time (us) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, checked in report["operations"].items():
        c, m = checked["source_gate_counts"], checked["metrics"]
        rows.append(
            f"| {name} | {c['CX']} | {c.get('M', 0)} | {m['program_duration_us']:.6f} | {m['duration_us']:.6f} |"
        )
    rows += [
        "",
        "See report.json for exact checks, provenance.json for source hashes,",
        "and index.html for the action viewer. Source SVGs and QASM, Atom IR text,",
        "self-contained results, and independent ideal Stim reconstructions are retained.",
        "",
        "## Limits",
        "",
        *[f"- {s}." for s in report["limitations"]],
        "",
    ]
    (output / "report.md").write_text("\n".join(rows), encoding="utf-8")
    print(f"Report: {output / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
