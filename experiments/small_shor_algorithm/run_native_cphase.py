"""Compile every distinct supplied circuit and export rigid-AOD replay cases.

Run with the repository's physical_compiler Python 3.12 environment.
Forced feedback cases exercise scheduling, not quantum measurement likelihood.
"""

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from copy import deepcopy
from html import escape
from pathlib import Path

from build_lab_viewer import main as build_lab_viewer
from build_loss_time_viewer import main as build_loss_time_viewer
from nadit_physical_compiler.job import compile_job, loads_job
from nadit_physical_compiler.serialization import encode_result
from nadit_physical_compiler.validation import validate_result
from nadit_physical_compiler.visualization.export import write_html
from nadit_physical_compiler.visualization.result import build_result_trace
from quantum_checks import (
    check_atom_trajectory,
    check_raw_static_source,
    source_trajectory,
)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
OUT = ROOT / "native_cphase"
BASIS = ["h", "cz", "t", "tdg", "p", "cp"]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def collect_inputs():
    """Extract only flat QASM files, preserving archive identities and hashes."""
    manifest = []
    tar = shutil.which("bsdtar") or "tar"
    for name in ("n15(1).rar", "n15.rar", "n21(1).rar", "n21.rar"):
        archive = ROOT / name
        members = subprocess.check_output(
            [tar, "-tf", str(archive)], text=True
        ).splitlines()
        for member in members:
            if Path(member).name != member or not member.endswith(".qasm3"):
                raise ValueError(f"Unexpected archive member: {member}")
            raw = subprocess.check_output([tar, "-xOf", str(archive), member])
            path = OUT / "inputs" / archive.stem / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            manifest.append(
                {
                    "archive": archive.name,
                    "member": member,
                    "path": path.relative_to(OUT).as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    write_json(OUT / "inputs.json", manifest)
    return manifest


def job_spec(path):
    """Use the existing single-row rigid device, with explicit CP permission."""
    architecture = json.loads(
        (
            REPO
            / "modules/physical_compiler/examples/architectures/zoned_rigid_16.json"
        ).read_text()
    )
    architecture["params"]["cphase"] = deepcopy(architecture["params"]["cz"])
    architecture["params"]["gate_zones"][0]["operations"] = [
        "load",
        "store",
        "cz",
        "cp",
        "rotate",
        "reset",
    ]
    return {
        "schema": "nadit.job/1",
        "circuit": {"qasm": str(path), "gate_set": BASIS},
        "device": {"architecture": architecture},
        "aod": "transport",
        "strategy": {
            "kind": "search_smarter",
            "scheduler": {"kind": "ready", "max_cz_gates": "catalog"},
            "placement": {"kind": "ids", "max_nodes": 20000},
            "transport": {"kind": "strict"},
            "emitter": {"kind": "whole_layer"},
            "reuse": {"kind": "matching"},
        },
        "case": {"seed": 17},
    }


def main():
    """Generate distinct source variants and four cases for each feedback input."""
    manifest = collect_inputs()
    unique = {item["sha256"]: item for item in reversed(manifest)}
    summary, traces = [], []
    for item in unique.values():
        path = OUT / item["path"]
        label = item["archive"].split("(")[0].split(".")[0] + "-" + path.stem
        spec = job_spec("../" + item["path"])
        job_dir = OUT / "jobs"
        initial = loads_job(json.dumps(spec), base_dir=job_dir)
        trajectory = source_trajectory(initial.dag)
        measurements = [node for node in initial.dag.nodes if node.name == "measure"]
        feedback = any(node.condition for node in initial.dag.nodes)
        raw_fidelity = None if feedback else check_raw_static_source(path, trajectory)
        cases = {"ideal-sample": trajectory[0]}
        if feedback:
            for name, bits in (
                ("forced-zero", [0] * len(measurements)),
                ("forced-one", [1] * len(measurements)),
                ("forced-alternating", [i % 2 for i in range(len(measurements))]),
            ):
                cases[name] = {
                    node.source_id: bit
                    for node, bit in zip(measurements, bits, strict=True)
                }
        for case, outcomes in cases.items():
            title = label + "-" + case
            print("Compiling " + title, flush=True)
            current = deepcopy(spec)
            current["case"]["overrides"] = {str(k): v for k, v in outcomes.items()}
            write_json(job_dir / (title + ".json"), current)
            job = loads_job(json.dumps(current), base_dir=job_dir)
            result = compile_job(job)
            report = validate_result(
                result, entry_state=job.entry_state, device=job.device, dag=job.dag
            )
            if not report["ok"]:
                raise RuntimeError(report)
            quantum = (
                check_atom_trajectory(job, result, trajectory)
                if case == "ideal-sample"
                else {
                    "scope": "forced branch: geometry, gate semantics and feedback timing only"
                }
            )
            if raw_fidelity is not None:
                quantum["raw_qasm_to_native_state_fidelity"] = raw_fidelity
            document = encode_result(
                result,
                entry_state=job.entry_state,
                job=job.document,
                dag=job.dag,
                device=job.device,
                inputs=job.inputs,
                validation=report,
            )
            write_json(OUT / "results" / (title + ".json"), document)
            (OUT / "results" / (title + ".atom_ir.txt")).write_text(
                result.program.to_text(), encoding="utf-8"
            )
            description = (
                "Rigid AOD; one entanglement row; native CPhase; CP duration 0.5 us is a study assumption. "
                + (
                    "Ideal-state sampled measurement case; "
                    if case == "ideal-sample"
                    else "Forced measurement case, not a quantum sample; "
                )
                + "outcomes in source order: "
                + "".join(str(outcomes[n.source_id]) for n in measurements)
            )
            trace = build_result_trace(document, title=title, description=description)
            write_html([trace], OUT / "viewers" / (title + ".html"), title=title)
            traces.append(trace)
            summary.append(
                {
                    "name": title,
                    "source": item,
                    "feedback": feedback,
                    "qubits": job.dag.num_qubits,
                    "gates": dict(Counter(n.name for n in job.dag.nodes)),
                    "conditioned_gates": sum(
                        n.condition is not None for n in job.dag.nodes
                    ),
                    "decisions": dict(Counter(n.status for n in result.operations)),
                    "measurement_bits": [outcomes[n.source_id] for n in measurements],
                    "metrics": document["metrics"],
                    "validation": report,
                    "quantum_evidence": quantum,
                }
            )
            write_json(OUT / "summary.json", summary)
            print("Validated " + title, flush=True)
    write_html(
        traces,
        OUT / "all-animations.html",
        title="Small Shor: rigid AOD, native CPhase",
    )
    build_loss_time_viewer()
    build_lab_viewer()
    rows = []
    for row in summary:
        name = escape(row["name"])
        rows.append(
            f'<tr><td><a href="viewers/{name}.html">{name}</a></td><td>{row["qubits"]}</td>'
            f"<td>{row['gates'].get('cz', 0)}</td><td>{row['gates'].get('cp', 0)}</td>"
            f"<td>{row['metrics']['duration_us']:.3f}</td><td>{row['decisions'].get('skipped', 0)}</td></tr>"
        )
    (OUT / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Small Shor animations</title>'
        "<style>body{font:16px system-ui;max-width:1200px;margin:40px auto;color:#243748}td,th{padding:12px;text-align:left;border-bottom:1px solid #ddd}a{color:#176b83}</style>"
        "<h1>Small Shor: rigid AOD, single entanglement row</h1>"
        "<p>Native H, CZ, T, T dagger, Phase and CPhase. CP duration: assumed 0.5 us. "
        "Forced branches test scheduling only; ideal-sample cases use quantum-state sampling.</p>"
        '<p><a href="all-animations.html">Open all animations with case selector</a></p>'
        '<p><a href="loss_time/SmallShor-Loss-Time-Offline/all-animations.html">Time and atom-loss sensitivity (14 cases)</a></p>'
        '<p><a href="lab_cn/SmallShor-Lab-CN/all-animations.html">半经典反馈电路：固定分支时间、物理损失与相干预算</a></p>'
        "<table><tr><th>Animation</th><th>Qubits</th><th>CZ</th><th>CP</th><th>Model duration (us)</th><th>Skipped</th></tr>"
        + "".join(rows)
        + "</table>",
        encoding="utf-8",
    )
    print(
        f"Completed {len(summary)} validated animations from {len(unique)} distinct inputs."
    )


if __name__ == "__main__":
    main()
