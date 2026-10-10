"""Produce complete T204 logical artifacts; no physical compilation or sampling."""

import argparse
from collections import Counter
from copy import deepcopy
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

from na_pipeline.frontend import (build_logical_dag, build_patch_dag_example, patch_placement_inputs,
                                  logical_dag_requirements, ready_logical_nodes, validate_logical_dag)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "examples/logical/logical_dag"


def encode(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def peak_working_set():
    if sys.platform != "win32":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
              "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    pmc = Counters()
    pmc.cb = ctypes.sizeof(pmc)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not get_memory(kernel.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None
    return pmc.PeakWorkingSetSize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    start = time.perf_counter()
    shor = build_logical_dag()
    example = build_patch_dag_example()
    shor_errors, example_errors = validate_logical_dag(shor), validate_logical_dag(example)
    if shor_errors or example_errors:
        raise RuntimeError(str(shor_errors + example_errors))
    negative = deepcopy(example)
    negative["provenance"]["fixture"] = True
    negative["edges"].append({"source": "example/couple0", "target": "maintenance/entry/P0", "kind": "protocol"})
    cycle_errors = validate_logical_dag(negative)
    missing = deepcopy(example)
    missing["provenance"]["fixture"] = True
    missing["nodes"][0]["reads"] = ["missing/result"]
    missing_errors = validate_logical_dag(missing)
    assert any(e["code"] == "LOGICAL_DAG_CYCLE" for e in cycle_errors)
    assert any(e["code"] == "MISSING_RESULT_PRODUCER" for e in missing_errors)
    roots = ready_logical_nodes(example, [])
    audit_counts = dict(Counter(r["disposition"] for r in shor["source_dependency_audit"]))
    report = {"schema_version": "R2DAGAuthorChecks/0.1.0", "artifact_id": "T204-author-checks",
              "provenance": {"owner": "R2", "task_id": "T204", "kb_revision": "kb-0006", "plan_revision": "plan-0008"},
              "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
              "source_operations": len(shor["source_coverage"]), "entry_precondition_operations": len(shor["entry"]["source_preconditions"]),
              "logical_nodes": len(shor["nodes"]), "logical_edges": len(shor["edges"]), "operation_counts": shor["operation_counts"],
              "source_dependency_audit_counts": audit_counts, "source_errors": shor_errors,
              "example_errors": example_errors, "cycle_negative_errors": cycle_errors, "producer_negative_errors": missing_errors,
              "four_patch_roots": roots, "four_patch_next_ready": ready_logical_nodes(example, [r["node_id"] for r in roots]),
              "readiness_examples_scope": "logical_completion_fixtures_no_runtime_or_physical_parallel_claim",
              "semantic_author_checks_passed": True, "independent_validation_passed": False,
              "full_physical_pipeline_completed": False,
              "unverified": ["actual_R4_patch_placement_for_full_world", "R3_all_operation_specs_and_factory_binding",
                             "R5_resource_schedule_and_continuous_fake_run", "R6_independent_graph_and_physical_checks",
                             "user_visual_acceptance"]}
    outputs = {"shor15_dag.json": encode(shor), "shor15_interactions.json": encode(shor["patch_interaction_graph"]),
               "shor15_placement_input.json": encode(patch_placement_inputs(shor)),
               "shor15_requirements.json": encode(logical_dag_requirements(shor)),
               "four_patch_dag.json": encode(example), "four_patch_interactions.json": encode(example["patch_interaction_graph"]),
               "four_patch_placement_input.json": encode(patch_placement_inputs(example)),
               "rejected_cycle.json": encode(negative), "rejected_missing_producer.json": encode(missing),
               "author_checks.json": encode(report)}
    manifest = {"schema_version": "R2LogicalDAGManifest/0.1.0", "artifact_id": "T204-dag-manifest",
                "provenance": report["provenance"], "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                                                           for name, data in outputs.items()},
                "scope": "complete_logical_source_and_semantic_graph_only"}
    outputs["manifest.json"] = encode(manifest)
    for name, data in outputs.items():
        if args.check:
            if not (OUT / name).is_file() or (OUT / name).read_bytes() != data:
                raise SystemExit("artifact mismatch: " + name)
        else:
            (OUT / name).write_bytes(data)
    generation_time = time.perf_counter() - start
    if args.verify:
        test_start = time.perf_counter()
        stream = io.StringIO()
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests/frontend"))
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        paths = sorted((ROOT / "src/na_pipeline/frontend").glob("*.py")) + sorted((ROOT / "tests/frontend").glob("*.py")) + [Path(__file__).resolve()]
        evidence = {**report, "tests_run": result.testsRun, "author_tests_passed": result.wasSuccessful(),
                    "test_log": stream.getvalue(), "test_seconds": time.perf_counter() - test_start,
                    "generation_seconds": generation_time, "peak_process_working_set_bytes": peak_working_set(),
                    "peak_scope": "Windows process working-set peak, all imports/generation/tests included; unavailable is null",
                    "python": sys.version, "python_executable": sys.executable, "host": platform.node(),
                    "budget": {"scope": "lightweight_local_logical_graph_only_no_physical_expansion_or_routing",
                               "parallelism": 1, "search": "none", "diagnostic_wall_seconds": 180, "diagnostic_memory_mib": 512},
                    "source_sha256": {str(p.relative_to(ROOT)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                    "manifest_sha256": hashlib.sha256(outputs["manifest.json"]).hexdigest()}
        (ROOT / "knowledge/roles/R2/logical-dag-evidence.json").write_bytes(encode(evidence))
        print(stream.getvalue())
        if not result.wasSuccessful():
            raise SystemExit(1)
    print(json.dumps({"mode": "checked" if args.check else "written", "logical_nodes": len(shor["nodes"]),
                      "source_operations": len(shor["source_coverage"]), "edge_audit": audit_counts,
                      "files": len(outputs), "generation_seconds": generation_time}))


if __name__ == "__main__":
    main()
