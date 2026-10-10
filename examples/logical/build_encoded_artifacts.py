"""Reproducible T203 artifacts; default output stays within R2 ownership."""

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
    build_t000_program, encoded_operation_catalog, iter_encoded_calls, validate_encoded_program,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "examples/logical/t000"


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    tracemalloc.start()
    start = time.perf_counter()
    program = build_t000_program()
    calls = list(iter_encoded_calls(program))
    semantic_errors = validate_encoded_program(program, require_executable=False)
    unavailable = validate_encoded_program(program)
    assert not semantic_errors and unavailable
    negative = deepcopy(program)
    negative["artifact_id"] += "-negative-group"
    negative["provenance"].update(fixture=True, purpose="missing_readout_member_negative")
    negative["body"][1]["groups"][0]["members"].pop()
    negative_errors = validate_encoded_program(negative, require_executable=False)
    assert any(e["code"] == "GROUP_INTENT_MISMATCH" for e in negative_errors)
    report = {"schema_version": "R2EncodedAuthorChecks/0.1.0", "artifact_id": "T203-author-checks",
              "provenance": {"owner": "R2", "task_id": "T203", "kb_revision": "kb-0005", "plan_revision": "plan-0007"},
              "execution_kind": "compile_plan", "quantum_state_simulated": False,
              "hardware_executed": False, "loss_enabled": False,
              "semantic_errors": semantic_errors, "executable_errors": unavailable,
              "negative_group_errors": negative_errors, "semantic_check_passed": True,
              "executable_strategy_check_passed": False, "independent_validation_passed": False,
              "expanded_call_count": len(calls), "instance_result_slot_count": sum(len(c["writes"]) for c in calls),
              "unverified": ["R3_physical_primitive_mapping", "Enola_strategy_qualification", "runtime_binding_and_ready",
                             "complete_group_transport_and_timing", "R6_independent_validation", "user_visual_acceptance"]}
    artifacts = {"program.json": encode(program), "operation_catalog.json": encode(encoded_operation_catalog()),
                 "expanded_calls.json": encode({"schema_version": "ExpandedEncodedCalls/0.1.0", "artifact_id": program["artifact_id"] + "-calls",
                                                "provenance": program["provenance"], "execution_kind": "compile_plan",
                                                "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
                                                "calls": calls}),
                 "rejected_missing_readout_member.json": encode(negative), "author_checks.json": encode(report)}
    manifest = {"schema_version": "R2EncodedManifest/0.1.0", "artifact_id": "T203-manifest",
                "provenance": report["provenance"], "files": {n: {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in artifacts.items()},
                "scope": "semantic_artifacts_not_T000_qualification"}
    artifacts["manifest.json"] = encode(manifest)
    for name, data in artifacts.items():
        if args.check:
            if not (OUT / name).is_file() or (OUT / name).read_bytes() != data:
                raise SystemExit("artifact mismatch: " + name)
        else:
            (OUT / name).write_bytes(data)
    seconds = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if args.verify:
        stream = io.StringIO()
        started = time.perf_counter()
        tests = unittest.defaultTestLoader.discover(str(ROOT / "tests/frontend"))
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(tests)
        elapsed = time.perf_counter() - started
        paths = sorted((ROOT / "src/na_pipeline/frontend").glob("*.py")) + sorted((ROOT / "tests/frontend").glob("*.py")) + [Path(__file__).resolve(), ROOT / "examples/logical/probe_encoded_primitives.py"]
        evidence = {**report, "python": sys.version, "python_executable": sys.executable, "host": platform.node(),
                    "tests_run": result.testsRun, "author_self_tests_passed": result.wasSuccessful(),
                    "tests_seconds": elapsed, "test_log": stream.getvalue(), "build_seconds": seconds,
                    "tracemalloc_peak_bytes": peak, "memory_scope": "Python allocation peak during generation, not RSS",
                    "budget": {"parallelism": 1, "search": "none", "diagnostic_seconds": 60, "diagnostic_memory_mib": 128},
                    "code_sha256": {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                    "manifest_sha256": hashlib.sha256(artifacts["manifest.json"]).hexdigest(),
                    "test_fixture_note": "capability-positive tests use marked fictional assertions, no real Enola/qualification claim"}
        (ROOT / "knowledge/roles/R2/encoded-evidence.json").write_bytes(encode(evidence))
        print(stream.getvalue())
        if not result.wasSuccessful():
            raise SystemExit(1)
    print(json.dumps({"mode": "checked" if args.check else "written", "files": len(artifacts),
                      "expanded_calls": len(calls), "semantic_passed": True, "executable_passed": False}))


if __name__ == "__main__":
    main()
