"""Emit the full structured R3 protocol, without preselecting a fake path."""

from collections import Counter
from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

from na_pipeline.qec import build_factory15to1_protocol, factory_stage_program, iter_physical_ops

ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    data = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(data).hexdigest(), "bytes": len(data)}


def main():
    started = time.perf_counter()
    protocol = build_factory15to1_protocol(data_block_id="live_data", request_id="single_T_0", epoch=1)
    artifact = write_json(ROOT / "examples/physical/factory15to1_protocol.json", protocol)
    stage_counts = {}
    for sid, stage in protocol["stages"].items():
        if stage["kind"] != "physical":
            continue
        counts = Counter()
        for op in iter_physical_ops(factory_stage_program(protocol, sid)):
            counts[op["kind"]] += 1
            if op["kind"] == "gate":
                counts[op["params"]["name"]] += 1
        stage_counts[sid] = dict(counts)
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests/qec"))
    tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    evidence_dir = ROOT / "knowledge/roles/R3/evidence"
    (evidence_dir / "factory-unittest.txt").write_bytes(stream.getvalue().encode("utf-8"))
    files = sorted((ROOT / "src/na_pipeline/qec").glob("*.py")) + sorted((ROOT / "tests/qec").glob("*.py")) + [Path(__file__).resolve()]
    report = {"schema_version": "R3FactoryQualification/0.1.0", "task_id": "T302", "kb_revision": "kb-0004",
              "date": "2026-10-06", "timezone": "Asia/Shanghai", "scope": "author_operator_and_physical_template_checks",
              "quantum_state_simulated": False, "sampled": False, "hardware_executed": False,
              "protocol_executed": False, "independent_validation": "pending", "user_visual_acceptance": "pending",
              "environment": {"python": sys.version, "executable": sys.executable, "host": platform.node(),
                              "dependencies": "standard_library_only"},
              "budget": {"workers": 1, "routing_search": "not_run", "atom_runtime": "not_run",
                         "stored_form": "versioned_templates_plus_adaptive_stage_graph"},
              "artifact": artifact, "qubits": len(protocol["qubits"]), "raw_inputs": len(protocol["raw_inputs"]),
              "templates": len(protocol["templates"]), "stages": len(protocol["stages"]), "stage_operation_counts": stage_counts,
              "tests": {"count": tests.testsRun, "failures": len(tests.failures), "errors": len(tests.errors),
                        "passed": tests.wasSuccessful(), "log": "knowledge/roles/R3/evidence/factory-unittest.txt"},
              "source_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest() for path in files},
              "wall_seconds": time.perf_counter() - started,
              "unverified": protocol["unverified"] + ["R4_classical_lowering", "continuous_atom_geometry", "production_accept_reject_retry_run"]}
    write_json(evidence_dir / "factory-qualification.json", report)
    summary = {"artifact": artifact, "qubits": report["qubits"], "raw_inputs": report["raw_inputs"],
               "templates": report["templates"], "stages": report["stages"], "tests": report["tests"],
               "wall_seconds": report["wall_seconds"], "protocol_executed": False}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if tests.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
