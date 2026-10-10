"""R2 read-only consumer audit. No compiler, scheduler or EventSession is run."""
from collections import Counter
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
import re
import time

from na_pipeline.frontend import iter_logical_ops, postprocess_phase, validate_logical_dag
from na_pipeline.qec.hierarchical_binding import materialize_physical_node


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "knowledge/roles/R2/pipeline-consumption-evidence.json"
WORLD = "examples/atom/t405/resource-world-server-v1/world.json.gz"
BUNDLE = "examples/scenarios/T505-full-driver-preflight-v3/physical-bundle.json.gz"
JOB = "examples/scenarios/T505-full-shor-job.json"
SCENARIO = "examples/scenarios/T505-reject-then-accept.json"
REVIEWED = [
    "src/na_pipeline/runtime/pipeline.py",
    "src/na_pipeline/runtime/session.py",
    "src/na_pipeline/runtime/logical_scheduler.py",
    "src/na_pipeline/runtime/scenario.py",
    "src/na_pipeline/runtime/window_binding.py",
    "src/na_pipeline/qec/hierarchical_binding.py",
    "src/na_pipeline/qec/physical_dag.py",
    "src/na_pipeline/qec/surface17.py",
    "src/na_pipeline/backend/physical_window.py",
    "src/na_pipeline/backend/physical_dag.py",
    "src/na_pipeline/backend/physical_strategy.py",
    "src/na_pipeline/backend/strategy_compile.py",
    "src/na_pipeline/frontend/logical_dag.py",
    "src/na_pipeline/frontend/postprocess.py",
    "examples/scenarios/run_full_shor_session.py",
    JOB, SCENARIO,
    "knowledge/roles/R5/pipeline-interface.md",
    "knowledge/roles/R5/full-shor-continuation.md",
]
INPUTS = [
    WORLD, BUNDLE, "examples/logical/logical_dag/shor15_dag.json",
    "examples/scenarios/T505-full-driver-preflight-v3/preflight.json",
    "AGENTS.md", "knowledge/INDEX.md", "knowledge/registry.json",
    "knowledge/charter.md", "knowledge/governance.md", "knowledge/roles.md",
    "knowledge/tasks/T204.md", "knowledge/interfaces/hierarchical-dag-contract.md",
    "knowledge/roles/R2/logical-dag-interface.md",
]


def hashes(paths):
    return {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(paths)}


def read(path):
    data = (ROOT / path).read_bytes()
    return json.loads(gzip.decompress(data) if path.endswith(".gz") else data)


def check(condition, label):
    if not condition:
        raise ValueError("R2 consumer audit failed: " + label)


def main():
    started = time.perf_counter()
    sources = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src/na_pipeline").rglob("*.py")]
    files = set(REVIEWED + INPUTS + sources + [Path(__file__).relative_to(ROOT).as_posix()])
    before = hashes(files)
    world, bundle, job, scenario = (read(p) for p in (WORLD, BUNDLE, JOB, SCENARIO))
    dag = world["logical_dag"]
    check(not validate_logical_dag(dag), "current R2 LogicalDAG validator")
    check(dag == bundle["logical_dag"], "saved preflight bundle keeps exact world DAG")
    nodes = {n["id"]: n for n in dag["nodes"]}
    check(len(nodes) == len(dag["nodes"]) == 2102, "complete original DAG")
    check(set(bundle["instances"]) == set(nodes), "all bundle instances")
    check(bundle["edges"] == dag["edges"], "all typed edges preserved")
    check(all(i["logical_node"] == nodes[nid] for nid, i in bundle["instances"].items()),
          "every bundle instance retains its full logical source")
    check(len(world["initial_state"]["atoms"]) == 205, "whole-world inventory")
    program = dag["source_program"]
    ops = {o["id"]: o for o in iter_logical_ops(program)}
    check(len(ops) == len(dag["source_coverage"]) == 2069, "all expanded source operations")
    for sid, coverage in dag["source_coverage"].items():
        if coverage["kind"] == "node":
            n = nodes[coverage["node_id"]]
            check(n["source_operation"] == ops[sid], "source operation " + sid)
            check(n["source_parameters"] == ops[sid]["params"], "source parameters " + sid)
            check(set(ops[sid]["source_ids"]) <= set(n["source_ids"]), "source IDs " + sid)
    entry = dag["entry"]["source_preconditions"]
    entry_ids = [x["source_operation"]["id"] for x in entry]
    check(set(entry_ids) == {"init/reset_w0", "init/reset_w1", "init/reset_w2", "init/reset_w3", "round7/reset"},
          "exactly the five first-use resets at entry")
    check(all(x["source_operation"] == ops[x["source_operation"]["id"]] and x["declared_logical_state"] == "0_L" for x in entry),
          "entry reset provenance and encoded logical zero")
    check(sum(n["operation"] == "RESET" for n in nodes.values()) == 8, "eight remaining runtime resets")

    feedback = []
    for body in program["body"]:
        original = body.get("logical_source_op") if body["kind"] == "call" else body.get("op")
        if not original or not re.fullmatch(r"round[0-7]/feedback_from_[1-7]", original["id"]):
            continue
        j, k = map(int, re.fullmatch(r"round([0-7])/feedback_from_([1-7])", original["id"]).groups())
        angle = {"numerator": -1, "denominator": 2 ** (k-j)}
        condition = {"bit": f"phase[{k}]", "equals": 1}
        check(k > j and original["params"]["angle_pi"] == angle, "feedback angle")
        check(original["condition"] == condition, "original feedback guard")
        members = [n for n in nodes.values() if n.get("source_operation", {}).get("synthesis_instance_id", n.get("source_operation", {}).get("id")) == original["id"]]
        check(bool(members), "feedback retains expanded nodes")
        check(all(n["condition"] == condition and n["reads"] == [condition["bit"]] for n in members), "all expanded feedback guards and reads")
        check(all(original["id"] in n["source_ids"] for n in members), "original feedback source ID")
        feedback.append({"source_id": original["id"], "angle_pi": angle, "condition": condition,
                         "expanded_node_count": len(members), "synthesized": body["kind"] == "call"})
    check(len(feedback) == 28 and sum(f["synthesized"] for f in feedback) == 15, "28 sites / 15 finite synthesized words")
    expected_sites = {f"round{j}/feedback_from_{k}" for j in range(8) for k in range(j+1, 8)}
    check({f["source_id"] for f in feedback} == expected_sites, "all feedback pairs")
    check(len(dag["branch_global_phases"]) == 15, "phase ledger count")
    for phase in dag["branch_global_phases"]:
        original = next(p for p in program["branch_global_phases"] if p["source_operation_id"] == phase["source_operation_id"])
        check(all(phase[k] == original[k] for k in ("condition", "global_phase_pi", "scope")), "phase ledger contents")

    phase_ids = [f"phase[{i}]" for i in range(8)]
    measurements = [n for n in dag["nodes"] if n["operation"] == "MEASURE"]
    check([n["writes"][0] for n in measurements] == phase_ids[::-1], "measurement chronology")
    maps = []
    for node in measurements:
        # Materialize only the saved ten-operation readout specification. No routing.
        graph = materialize_physical_node(bundle, node["id"])
        byid = {n["id"]: n for n in graph["nodes"]}
        rid = node["writes"][0]
        writer = byid[graph["result_producers"][rid]]
        check(writer["kind"] == "classical" and writer["params"]["operation"] == "xor", "derived public phase")
        measured = [byid[graph["result_producers"][r]] for r in writer["reads"]]
        check([m["qubits"] for m in measured] == [["ctrl/d0"], ["ctrl/d1"], ["ctrl/d2"]], "logical Z support")
        check(all(m["kind"] == "measure" for m in measured), "XOR reads actual measurement producers")
        check(graph["logical_binding"]["logical_source"] == node, "readout instance source binding")
        maps.append({"logical_node": node["id"], "public_result": rid,
                     "xor_writer": writer["id"], "physical_reads": writer["reads"],
                     "configured_physical_read": writer["reads"][0]})
    post = nodes["classical/postprocess"]
    check(post["reads"] == phase_ids and post["params"]["bits_msb_first"] == phase_ids, "postprocess MSB order")
    check(post["params"]["N"] == 15 and post["params"]["a"] == 2, "postprocess modular input")
    graph = materialize_physical_node(bundle, post["id"])
    writer = next(n for n in graph["nodes"] if n["id"] == graph["result_producers"]["postprocess/result"])
    check(writer["reads"] == phase_ids and writer["params"]["bits_msb_first"] == phase_ids, "physical postprocess order")
    check(writer["params"]["failure_policy"] == "return_explicit_classical_failure", "failure policy")
    post_checks = [postprocess_phase([(v >> (7-i)) & 1 for i in range(8)], N=15, a=2, origin="fake") for v in (64, 0, 128)]
    check(post_checks[0]["factors"] == [3, 5] and post_checks[0]["period"] == 4, "phase64 classical calculation")
    check(all(r["status"] == "failed" and r["factors"] == [] for r in post_checks[1:]), "phase0 / phase128 explicit failure")

    bits = [0, 1, 0, 0, 0, 0, 0, 0]
    values = dict(zip(phase_ids, bits))
    projection = [n for n in nodes.values() if n["condition"] is None or values[n["condition"]["bit"]] == n["condition"]["equals"]]
    counts = dict(Counter(n["operation"] for n in projection))
    check(len(projection) == 157 and len(nodes)-len(projection) == 1945 and sum(counts.get(k, 0) for k in ("T", "TDG")) == 35, "budget-only phase64 projection")
    request = "logical/round1/multiply/swap0/g03"
    check(nodes[request]["operation"] == "TDG" and nodes[request]["condition"] is None, "retry request identity")
    check([a["terminal_x_parities"] for a in scenario["requests"][request]] == [[1, 0, 0, 0], [0, 0, 0, 0]], "bounded retry fixture")
    check(job["argv"][job["argv"].index("--phase-value")+1] == "64", "job scenario value")
    check(job["argv"][job["argv"].index("--world")+1] == WORLD, "job world")
    check(job["argv"][job["argv"].index("--factory-scenarios")+1] == SCENARIO, "job factory scenario")
    saved_spec_drift = []
    for spec in bundle["specifications"].values():
        for basename, expected in spec.get("source_sha256", {}).items():
            path = "src/na_pipeline/qec/" + basename
            if before.get(path) != expected:
                saved_spec_drift.append({"path": path, "saved": expected, "current": before.get(path)})
    after = hashes(files)
    check(before == after, "inputs and code stable during lightweight audit")
    receipt = {
        "schema_version": "R2PipelineConsumerReview/0.1.0", "owner": "R2", "task_id": "T204",
        "created_utc": datetime.now(timezone.utc).isoformat(), "kb_revision": "kb-0006", "planning_revision": "plan-0008",
        "classification": "source_review_and_finite_static_binding_checks",
        "full_program_passed": False, "physical_execution_started": False, "quantum_state_simulated": False,
        "independent_validation": "pending_R6", "user_visual": "pending",
        "reviewed_paths": REVIEWED, "byte_sha256": before, "unchanged_during_check": True,
        "source_manifest_note": "Additional Python files are hashed for identity only; not all were reviewed.",
        "interfaces": {"R2-LOGICAL-DAG-001": "0.2.0", "LogicalDAG": "0.1.0", "R5-PIPELINE-001": "0.2.0-draft", "GOV-001": "0.4.1"},
        "source": {"logical_nodes": len(nodes), "edges": len(dag["edges"]), "expanded_operations": len(ops),
                   "entry_reset_ids": entry_ids, "remaining_resets": 8, "phase_ledger_instances": 15,
                   "bundle_instances_exact": True, "physical_inventory": len(world["initial_state"]["atoms"])},
        "feedback": feedback, "measurement_xor_bindings": maps,
        "postprocess_source": post, "pure_classical_postprocess_checks": post_checks,
        "phase64_budget_projection": {"execution_evidence": False, "bits_msb_first": bits, "execute_candidates": len(projection),
                                      "conditional_skip_candidates": len(nodes)-len(projection), "operation_counts": counts,
                                      "logical_T_requests": 35, "configured_extra_rejected_attempts": 1},
        "saved_preflight_spec_source_drift": saved_spec_drift,
        "runtime_checks": "Manual source review documented separately; no pipeline constructor, EventSession, scheduler execution, full bundle rebuild or compiler invoked.",
        "python": platform.python_version(), "wall_seconds": time.perf_counter()-started,
        "local_budget": {"wall_seconds": 180, "memory_mib": 512, "parallelism": 1, "search_expansions": 0, "kind": "diagnostic_ceiling_not_OS_enforced"},
    }
    OUT.write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2)+"\n").encode("utf-8"))
    print(json.dumps({"receipt": str(OUT), "logical_nodes": len(nodes), "feedback_sites": len(feedback),
                      "finite_readout_bindings": len(maps), "phase64_execute_candidates": len(projection),
                      "saved_spec_drift_count": len(saved_spec_drift), "wall_seconds": receipt["wall_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
