"""Reproduce R2 artifacts using PYTHONPATH=src and Python >=3.12.

Only writes into this script's examples/logical directory. --check compares
bytes without writing. --verify also writes the role-owned self-test evidence.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
import tracemalloc
import unittest

from na_pipeline.frontend import (
    SynthesisRequiredError, build_shor15, iter_logical_ops, postprocess_phase,
    require_clifford_t, to_openqasm3, validate_logical, t_demand_for_phase,
)

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise SystemExit("Python >=3.12 required; do not use C:/Anaconda/python.exe")
    tracemalloc.start()
    started = time.perf_counter()
    program = build_shor15()
    source_program = build_shor15(synthesize=False)
    assert not validate_logical(program)
    require_clifford_t(program)
    rejected = deepcopy(program)
    rejected["artifact_id"] += "-rejected-feedback-dependency"
    rejected["provenance"].update(fixture=True, purpose="negative_contract_test")
    feedback = next(n["op"] for n in rejected["body"] if n["kind"] == "op" and n["op"]["condition"])
    feedback["after"] = []
    rejection_errors = validate_logical(rejected)
    assert any(e["code"] == "READ_BEFORE_READY_DEPENDENCY" for e in rejection_errors)
    try:
        require_clifford_t(source_program)
    except SynthesisRequiredError as exc:
        refusal = {"status": "rejected_for_executable_handoff", "code": "SYNTHESIS_REQUIRED",
                   "operation_ids": [op["id"] for op in exc.operations],
                   "unresolved_count": len(exc.operations), "reason": "explicit_unsynthesized_source_negative_fixture",
                   "fixture": True, "does_not_describe_default_build": True}
    else:
        raise AssertionError("Expected unresolved synthesis to block executable handoff")
    examples = []
    for label, value in (("explicit_fake_quarter", 64), ("explicit_fake_zero", 0), ("explicit_fake_half", 128)):
        bits = [int(bit) for bit in f"{value:08b}"]
        examples.append({"label": label, "fixture": True,
                         "scope": "postprocessing_unit_input_not_runtime_trace",
                         "result": postprocess_phase(bits)})
    outputs = {
        "shor15.logical.json": json_bytes(program),
        "shor15.qasm": to_openqasm3(program).encode("utf-8"),
        "shor15.symbolic.json": json_bytes(source_program),
        "shor15.symbolic.qasm": to_openqasm3(source_program).encode("utf-8"),
        "rejected_missing_feedback_dependency.json": json_bytes(rejected),
        "postprocess_examples.json": json_bytes(examples),
        "handoff_refusal.json": json_bytes(refusal),
        "synthesis_certificates.json": json_bytes({
            "schema_version": "R2SynthesisCertificates/0.1.0", "artifact_id": program["artifact_id"] + "-certificates",
            "provenance": {"owner": "R2", "task_id": "T202", "logical_artifact_id": program["artifact_id"]},
            "execution_kind": "compile_plan", "quantum_state_simulated": False,
            "hardware_executed": False, "loss_enabled": False,
            "synthesis": program["synthesis"], "certificates": program["synthesis_certificates"],
            "branch_global_phases": program["branch_global_phases"],
            "resource_summary": program["resource_summary"]}),
        "t_demand_examples.json": json_bytes([t_demand_for_phase(program, bits)
                                               for bits in ([0]*8, [1]*8, [0,1,0,0,0,0,0,0])]),
    }
    manifest = {"schema_version": "R2ArtifactManifest/0.1.0", "artifact_id": program["artifact_id"] + "-manifest",
                "provenance": {"owner": "R2", "task_id": "T202", "generator": "examples/logical/build_artifacts.py"},
                "execution_kind": "compile_plan", "quantum_state_simulated": False,
                "hardware_executed": False, "loss_enabled": False,
                "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                          for name, data in outputs.items()}}
    outputs["manifest.json"] = json_bytes(manifest)
    for name, data in outputs.items():
        path = DIRECTORY / name
        if args.check:
            if not path.is_file() or path.read_bytes() != data:
                raise SystemExit(f"artifact mismatch: {path}")
        else:
            path.write_bytes(data)
    build_seconds = time.perf_counter() - started
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if args.verify:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests/frontend"))
        stream = io.StringIO()
        test_started = time.perf_counter()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        test_seconds = time.perf_counter() - test_started
        code_paths = sorted((ROOT / "src/na_pipeline/frontend").glob("*.py"))
        code_paths += sorted((ROOT / "tests/frontend").glob("*.py")) + sorted(DIRECTORY.glob("*.py"))
        evidence = {
            "schema_version": "R2SelfTestEvidence/0.1.0", "artifact_id": "R2-T202-selftest",
            "provenance": {"owner": "R2", "knowledge_revision": "kb-0004",
                           "interface_ref": "IF-MVP-001/0.2.1-draft", "date": "2026-10-06",
                           "test_kind": "author_self_test", "independent_validation": False},
            "execution_kind": "compile_plan", "quantum_state_simulated": False,
            "hardware_executed": False, "loss_enabled": False,
            "host": platform.node(), "platform": platform.platform(), "python": sys.version,
            "python_executable": sys.executable,
            "budget": {"scope": "lightweight_local_frontend_only", "parallelism": 1,
                       "search": "none", "admission_time_seconds": 60,
                       "admission_memory_mib": 256,
                       "enforcement": "diagnostic_admission_limits_not_os_hard_caps"},
            "build_check_seconds": build_seconds, "python_tracemalloc_peak_bytes": peak_memory,
            "peak_scope": "Python allocations during artifact generation; not full process RSS",
            "test_seconds": test_seconds, "tests_run": result.testsRun,
            "self_tests_passed": result.wasSuccessful(), "test_log": stream.getvalue(),
            "expanded_logical_operations": sum(1 for _ in iter_logical_ops(program)),
            "logical_validation_errors": validate_logical(program),
            "negative_example_errors": rejection_errors, "synthesis_handoff": refusal,
            "default_build_clifford_t_handoff": "passed_static_interval_and_dependency_checks",
            "synthesis_summary": program["synthesis"], "resource_summary": program["resource_summary"],
            "code_sha256": {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in code_paths},
            "artifact_manifest_sha256": hashlib.sha256(outputs["manifest.json"]).hexdigest(),
            "checks": {"controlled_inputs": 64, "fredkin_boolean_inputs": 8,
                       "toffoli_phase_inputs_per_instance": 8, "toffoli_instances": 5,
                       "feedback_phase_words": 256, "postprocess_soundness_cases": 1024,
                       "synthesized_angles": 5, "synthesized_instances": 15, "path_inventory_cases": 256},
            "unverified": ["R3_logical_lowering", "R6_independent_validation",
                           "external_QASM_parser", "full_physical_pipeline", "user_visual_acceptance"],
        }
        evidence_path = ROOT / "knowledge/roles/R2/evidence.json"
        evidence_path.write_bytes(json_bytes(evidence))
        print(stream.getvalue())
        if not result.wasSuccessful():
            raise SystemExit(1)
    print(json.dumps({"artifact_mode": "checked" if args.check else "written",
                      "files": list(outputs), "build_seconds": build_seconds,
                      "logical_operations": sum(1 for _ in iter_logical_ops(program)), "synthesis_ready": True}))


if __name__ == "__main__":
    main()
