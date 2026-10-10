"""R3 source-only cleanup obligations for R5/R6; no execution receipt.

Consumes the frozen complete bundle and published builders. Leaves production
code and previously qualified artifacts untouched. Intended to bridge precise
terminal reset source IDs to R5's real completed-action cleanup evidence.
"""

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time

from na_pipeline.qec import (materialize_physical_node, materialize_factory_protocol,
                             build_factory_physical_dag, validate_physical_dag)

ROOT = Path(__file__).resolve().parents[2]


def derive_cleanup(dag, expected_qubits, protected_data):
    last, violations = {}, []
    for node in dag["nodes"]:
        if node["kind"] in {"measure", "reset"} and set(node["qubits"]) & set(protected_data):
            violations.append({"code": "LIVE_DATA_MEASURED_OR_RESET", "source_op_id": node["id"]})
        for q in node["qubits"]:
            last[q] = node
    resets = []
    for q in sorted(expected_qubits):
        op = last.get(q)
        if op is None or op["kind"] != "reset" or op["params"].get("basis") != "Z":
            violations.append({"code": "POOL_CARRIER_NOT_TERMINALLY_RESET", "qubit_id": q,
                               "last_source_op_id": op["id"] if op else None})
        else:
            resets.append({"physical_qubit_id": q, "terminal_reset_source_op_id": op["id"],
                           "source_ids": op["source_ids"]})
    return {"source_obligations_satisfied": not violations, "violations": violations,
            "pool_carrier_count": len(expected_qubits), "protected_live_data_ids": list(protected_data),
            "terminal_resets": resets, "required_leases": dag.get("required_leases", []),
            "execution_guard": dag.get("execution_guard"), "external_reads": dag.get("external_reads", []),
            "stage_id": dag.get("protocol_binding", {}).get("stage_id"),
            "logical_binding": dag.get("logical_binding"),
            "requires_whole_graph_commit": True, "requires_actual_completed_reset_actions": True,
            "requires_no_later_action_on_pool_carriers": True,
            "may_not_release_from_source_manifest_alone": True,
            "runtime_release_verified": False, "token_created": False}


def main():
    started = time.perf_counter()
    bundle_path = ROOT / "examples/physical/physical_dag/shor15-bundle.json"
    bundle = json.loads(bundle_path.read_bytes())
    production = sorted((ROOT / "src/na_pipeline/qec").glob("*.py"))
    before = {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest() for p in production}
    frozen_report_path = ROOT / "knowledge/roles/R3/evidence/t304-source-qualification.json"
    frozen = json.loads(frozen_report_path.read_bytes())
    frozen_matches = all(frozen["source_hashes_after"].get(path) == digest for path, digest in before.items())
    if not frozen_matches:
        raise AssertionError("production sources differ from the frozen T304 author evidence")
    pool = bundle["resource_requirements"]
    records, negatives = {}, []
    for operation in ("S", "SDG"):
        node_id = next(n for n, v in bundle["instances"].items() if v["logical_node"]["operation"] == operation)
        dag = materialize_physical_node(bundle, node_id)
        validate_physical_dag(dag)
        target = dag["logical_binding"]["patch_bindings"]["block"]
        expected = [f"{pool['factory_slots']['Y']}/{q}" for q in (f"d{i}" for i in range(9))]
        expected += [f"{pool['factory_slots']['Y']}/{b}{i}" for b in "xz" for i in range(4)]
        expected.append(pool["nonpatch_atoms"][0]["physical_qubit_id"])
        protected = [f"{target}/d{i}" for i in range(9)]
        record = derive_cleanup(dag, expected, protected)
        if not record["source_obligations_satisfied"]:
            raise AssertionError(record["violations"])
        record["dag_sha256"] = sha256(json.dumps(dag, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        records[operation] = record
        # A real post-reset use must invalidate release even if all reset IDs
        # are still present. This is a source fixture, not a submitted action.
        corrupt = deepcopy(dag)
        probe = expected[-1]
        corrupt["nodes"].append({"id": "fixture_after_cleanup", "kind": "gate", "qubits": [probe], "params": {"name": "X"}})
        rejected = derive_cleanup(corrupt, expected, protected)
        if rejected["source_obligations_satisfied"]:
            raise AssertionError("post-cleanup carrier reuse was accepted")
        negatives.append({"operation": operation, "fixture": True, "mutation": "append_probe_X_after_terminal_reset",
                          "rejected": True, "violations": rejected["violations"]})
    node_id = next(n for n, v in bundle["instances"].items() if v["logical_node"]["operation"] == "TDG" and v["logical_node"]["condition"])
    protocol = materialize_factory_protocol(bundle, node_id, epoch=0)
    for stage in ("consume_cleanup", "reject_cleanup"):
        dag = build_factory_physical_dag(protocol, stage)
        validate_physical_dag(dag)
        record = derive_cleanup(dag, protocol["factory_qubit_ids"], protocol["live_data_information_qubit_ids"])
        if not record["source_obligations_satisfied"]:
            raise AssertionError(record["violations"])
        record["dag_sha256"] = sha256(json.dumps(dag, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        records[stage] = record
    after = {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest() for p in production}
    if before != after:
        raise AssertionError("production source changed during audit")
    report = {"schema_version": "r3-cleanup-source-obligations/0.1", "owner": "R3", "task_id": "T304", "kb_revision": "kb-0006",
              "created_at": datetime.now(timezone.utc).isoformat(), "scope": "terminal_source_reset_mapping_only",
              "input": {"bundle_path": str(bundle_path.relative_to(ROOT)).replace("\\", "/"),
                        "bundle_byte_sha256": sha256(bundle_path.read_bytes()).hexdigest(), "bundle_hash": bundle["bundle_hash"]},
              "producer_source_hashes_before": before, "producer_source_hashes_after": after,
              "producer_source_unchanged": before == after,
              "matches_frozen_t304_production_sources": frozen_matches,
              "expected_whole_world_carriers": pool["physical_qubit_count"], "records": records, "negative_fixtures": negatives,
              "consumer_interfaces_read": {"R5-RESOURCE-POOL-001": "0.1.0-draft", "R5-SESSION-BIND-001": "0.1.1",
                                            "R4-HIERARCHICAL-IF-001": "0.1.0-draft"},
              "execution_rules": ["resolve_original_guard_with_actual_published_results_before_any_factory_production",
                                  "validate_signed_context_at_submit_after_D05_fix",
                                  "hold_factory_protocol_mutex_through_acceptance_conversion_consumption_or_reject_cleanup",
                                  "map_terminal_reset_source_ids_to_this_epoch_actual_completed_actions",
                                  "do_not_mint_token_or_release_lease_from_this_source_report"],
              "budget": {"processes": 1, "kind": "four_bounded_source_graphs_no_atom_compilation", "wall_seconds": time.perf_counter() - started},
              "quantum_state_simulated": False, "sampled": False, "runtime_executed": False, "independent_validation": "pending"}
    out = ROOT / "knowledge/roles/R3/evidence/t304-cleanup-source-obligations.json"
    out.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"counts": {name: r["pool_carrier_count"] for name, r in records.items()},
                      "source_unchanged": report["producer_source_unchanged"], "negative_fixtures_rejected": len(negatives),
                      "seconds": report["budget"]["wall_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
