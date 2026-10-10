"""Export T303 formal primitives and exact group references, without atom plans."""

from collections import Counter
from hashlib import sha256
import json
import io
from pathlib import Path
import platform
import sys
import time
import unittest

from na_pipeline.qec import build_logical_primitive, iter_physical_ops, validate_primitive_contract

ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": len(data), "sha256": sha256(data).hexdigest()}


def main():
    start = time.perf_counter()
    entries = []
    for name, operation, params in (("prepare_zero", "prepare", {"state": "0"}),
                                    ("prepare_plus", "prepare", {"state": "+"}),
                                    ("syndrome_round", "syndrome_round", {}), ("logical_cx", "logical_cx", {})):
        program = build_logical_primitive(operation, params=params)
        errors = validate_primitive_contract(program)
        if errors:
            raise ValueError(errors)
        ops = list(iter_physical_ops(program))
        entries.append({"name": name, "artifact": write_json(ROOT / "examples/physical/logical_primitives" / (name + ".json"), program),
                        "physical_operations": len(ops), "counts": dict(Counter(op["kind"] for op in ops)),
                        "physical_input_hash": program["strategy_contract"]["physical_input_hash"],
                        "strategy_contract_hash": program["strategy_contract"]["contract_hash"],
                        "groups": [{"id": g["group_id"], "purpose": g["purpose"], "members": len(g["members"])} for g in program["strategy_contract"]["groups"]]})
    invalid = build_logical_primitive("syndrome_round")
    invalid["provenance"]["fixture"] = True
    invalid["strategy_contract"]["groups"][0]["members"][0]["basis_change_op_id"] = None
    rejected = validate_primitive_contract(invalid)
    negative = write_json(ROOT / "examples/physical/logical_primitives/rejected_missing_x_basis.json", invalid)
    log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests/qec"))
    tests = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    log_path = ROOT / "knowledge/roles/R3/evidence/logical-primitives-tests.txt"
    log_path.write_bytes(log.getvalue().encode("utf-8"))
    from na_pipeline.device import grouped_device
    from na_pipeline.frontend import encoded_operation_catalog, build_t000_program
    def digest(value):
        return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    report = {"schema_version": "R3LogicalPrimitiveEvidence/0.1", "task_id": "T303", "kb_revision": "kb-0005", "planning_revision": "plan-0007",
              "environment": {"python": sys.version, "executable": sys.executable, "host": platform.node(), "dependencies": "standard_library"},
              "artifacts": entries, "negative": {"artifact": negative, "errors": rejected},
              "qec_source_sha256": program["strategy_contract"]["qec_source_sha256"],
              "producer_input_hashes": {"r1_grouped_device": digest(grouped_device()),
                                        "r2_operation_catalog": digest(encoded_operation_catalog()),
                                        "r2_t000_rounds3": digest(build_t000_program(3))},
              "tests": {"count": tests.testsRun, "failures": len(tests.failures), "errors": len(tests.errors),
                        "passed": tests.wasSuccessful(), "log": "knowledge/roles/R3/evidence/logical-primitives-tests.txt"},
              "budget": {"workers": 1, "scope": "bounded_primitives_and_static_checks", "placement_routing_search": "not_run"},
              "wall_seconds": time.perf_counter() - start, "scope": "formal_physical_source_and_group_contract",
              "compiled_strategy": False, "enola_executed": False, "quantum_state_simulated": False,
              "independent_validation": "pending", "user_visual_acceptance": "pending"}
    write_json(ROOT / "knowledge/roles/R3/evidence/logical-primitives.json", report)
    print(json.dumps({"artifacts": [{"name": e["name"], "operations": e["physical_operations"], "groups": e["groups"]} for e in entries],
                      "negative_rejected": bool(rejected), "tests": report["tests"], "wall_seconds": report["wall_seconds"]}, ensure_ascii=False, indent=2))
    if not tests.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
