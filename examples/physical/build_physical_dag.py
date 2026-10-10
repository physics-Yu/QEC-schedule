"""Publish T304 static sources and bounded component checks (no atom compile).

Run in the repository Python 3.12 environment with PYTHONPATH=src.
Full physical expansion/placement/routing/runtime qualification is a separate
server job owned by R0/R4/R5/R6/R7; this script never substitutes for that job.
"""

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

from na_pipeline.frontend import build_logical_dag, build_patch_dag_example
from na_pipeline.qec import (build_physical_dag_bundle, materialize_physical_node,
                             materialize_factory_protocol, build_factory_physical_dag,
                             build_patch_operation_spec, validate_physical_dag)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "examples/physical/physical_dag"
EVIDENCE = ROOT / "knowledge/roles/R3/evidence"


def main():
    start = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    sources = sorted((ROOT / "src/na_pipeline/qec").glob("*.py")) + sorted((ROOT / "tests/qec").glob("test_*.py"))
    sources.append(Path(__file__).resolve())
    before = {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest() for p in sources}
    files = []

    def write(name, value):
        path = OUT / name
        data = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        path.write_bytes(data)
        files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "byte_sha256": sha256(data).hexdigest(), "bytes": len(data)})

    logical = build_logical_dag()
    bundle = build_physical_dag_bundle(logical)
    write("shor15-bundle.json", bundle)
    write("shor15-resource-requirements.json", bundle["resource_requirements"])
    example = build_physical_dag_bundle(build_patch_dag_example())
    write("patch-example-bundle.json", example)
    instances = [materialize_physical_node(example, node) for node in example["instances"]]
    write("patch-example-instances.json", instances)
    # Export every distinct static library once, plus X/Z and both measurement bases.
    specs = {op: build_patch_operation_spec(op) for op in ("SE", "H", "X", "Z", "S", "SDG", "CX", "CZ", "RESET", "MEASURE")}
    specs["MEASURE_X"] = build_patch_operation_spec("MEASURE", params={"basis": "X"})
    write("static-specifications.json", specs)
    request_node = next(n for n in logical["nodes"] if n["operation"] == "TDG" and n["condition"])
    protocol = materialize_factory_protocol(bundle, request_node["id"], epoch=0)
    stages = {s: build_factory_physical_dag(protocol, s) for s in ("initialize", "rotate_04", "consume", "reject_cleanup")}
    write("factory-selected-stage-dags.json", stages)
    # Recipe index retains actual stages/bindings/input manifest; physical templates
    # are produced by the public builder, not duplicated for 817 potential requests.
    recipe_index = {k: v for k, v in protocol.items() if k not in {"templates", "schema_version"}}
    recipe_index.update(schema_version="FactoryRecipeIndex/0.1.0", protocol_schema_version=protocol["schema_version"],
                        templates_included=False, executable_protocol=False,
                        materializer={"function": "na_pipeline.qec.materialize_factory_protocol",
                                      "bundle": "shor15-bundle.json", "node_id": request_node["id"], "epoch": 0})
    write("factory-recipe-index.json", recipe_index)
    stage_audits = {s: validate_physical_dag(dag) for s, dag in stages.items()}
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests/qec"), pattern="test_*.py")
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    (EVIDENCE / "t304-tests.txt").write_bytes(log.getvalue().encode("utf-8"))
    after = {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest() for p in sources}
    report = {"schema_version": "r3-t304-source-qualification/0.1", "owner": "R3", "kb_revision": "kb-0006", "planning_revision": "plan-0008",
              "created_at": datetime.now(timezone.utc).isoformat(), "python": sys.version, "platform": platform.platform(),
              "scope": "source_contract_signed_Pauli_algebra_finite_pool_and_representative_stage_DAGs",
              "budget": {"processes": 1, "threads": 1, "work": "finite_static_library_and_component_tests",
                         "full_flat_Shor_expansion": False, "atom_compilation": False, "Enola_search": False,
                         "memory_cap_enforced": False, "wall_time_seconds": time.perf_counter() - start},
              "tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped), "passed": result.wasSuccessful()},
              "logical_nodes": len(logical["nodes"]), "logical_operation_counts": dict(Counter(n["operation"] for n in logical["nodes"])),
              "source_coverage_count": len(logical["source_coverage"]), "specification_count": len(bundle["specifications"]),
              "coverage": {k: v for k, v in bundle["coverage"].items() if k != "static_source_coverage"},
              "physical_counts": {key: value["summary"]["physical_operation_count"] for key, value in specs.items()},
              "stage_audits": stage_audits, "resource_counts": bundle["resource_requirements"]["counts"], "physical_qubits": 205,
              "input_refs": {"logical_dag_sha256": bundle["logical_dag_sha256"], "bundle_hash": bundle["bundle_hash"]},
              "source_hashes_before": before, "source_hashes_after": after, "source_stable": before == after, "artifacts": files,
              "qualification": {"author_component": result.wasSuccessful(), "R6_independent": "pending", "physical_compile": "pending",
                                "factory_runtime": "pending", "full_Shor_execution": "pending", "user_visual": "pending"},
              "quantum_state_simulated": False, "sampled": False, "hardware_executed": False}
    (EVIDENCE / "t304-source-qualification.json").write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"tests": report["tests"], "logical_nodes": report["logical_nodes"], "physical_qubits": 205,
                      "specifications": report["specification_count"], "source_stable": report["source_stable"],
                      "seconds": report["budget"]["wall_time_seconds"]}, ensure_ascii=False))
    if not result.wasSuccessful() or before != after:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
