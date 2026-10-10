"""Real R2 -> R3 -> R4 -> R5 small DAG integration, preserving each window."""
import argparse
import gzip
import json
from pathlib import Path
import time

from na_pipeline.device import preinitialized_device
from na_pipeline.frontend import build_patch_dag_example, validate_logical_dag
from na_pipeline.qec import build_physical_dag_bundle, materialize_physical_node
from na_pipeline.backend import place_logical_dag, compile_physical_dag
from na_pipeline.runtime import EventSession, LogicalListScheduler, bind_physical_plan, make_scenario
from na_pipeline.runtime.engine import digest


def save(path, data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", default="examples/scenarios/T505-dag-session-v1")
    args = parser.parse_args(); out = Path(args.output)
    device, dag = preinitialized_device(), build_patch_dag_example()
    assert not validate_logical_dag(dag)
    cached = Path("examples/atom/t405/placement-v1/patch-placement.json")
    placement = json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else None
    olddag = json.loads(cached.with_name("logical-dag.json").read_text(encoding="utf-8")) if cached.exists() else None
    if olddag is None or digest(olddag) != digest(dag) or placement["device_hash"] != digest(device):
        placement = place_logical_dag(dag, device, seed=7)
    session = EventSession(device, placement["initial_state"], run_id="T505-patch-example")
    scheduler = LogicalListScheduler(dag, {})
    bundle = build_physical_dag_bundle(dag)
    for name, value in (("logical-dag", dag), ("device", device), ("patch-placement", placement), ("physical-bundle", bundle)):
        save(out/(name+".json.gz"), value)
    started, iteration = time.perf_counter(), 0
    receipts = []
    try:
        while not scheduler.snapshot()["complete"]:
            candidate = scheduler.joint_candidates()
            if not candidate["selected_node_ids"]: raise RuntimeError("No physical ready batch; continuation needs explicit event/branch handling")
            graphs = [materialize_physical_node(bundle, nid) for nid in candidate["selected_node_ids"]]
            context = session.compilation_context(graphs)
            print(json.dumps({"window": iteration, "phase": "compile", "time_us": session.now_us, "nodes": candidate["selected_node_ids"]}), flush=True)
            plan = compile_physical_dag(graphs, device, session.snapshot()["world_state"],
                budget={"max_operations": 100000, "max_wall_seconds": 300}, execution_context=context)
            proposal = scheduler.propose_joint(plan)
            atom = bind_physical_plan(plan, context)
            scenario = make_scenario(atom, value=0)
            # Session checks first; reserve_joint was already deterministically checked.
            session.submit(atom, scenario, expected_revision=context["revision"])
            scheduler.reserve_joint(plan, proposal)
            session.advance()
            scheduler.advance(session.now_us)
            for graph in graphs:
                nid = graph["logical_binding"]["logical_node_id"]
                ids = plan["node_summaries"][graph["artifact_id"]]["action_ids"]
                end = max(session.completed[a] for a in ids)
                results = {r: session.results[r] for r in scheduler.nodes[nid]["writes"]}
                scheduler.complete(nid, {"node_id": nid, "completed_us": end, "physical_plan_ref": atom["artifact_id"],
                    "event_trace_ref": session.run_id+"/trace/"+str(session.revision)}, results)
            prefix = f"window-{iteration:03d}"
            save(out/(prefix+".json.gz"), {"candidates": candidate, "context": context, "physical_plan": plan,
                                         "logical_proposal": proposal, "atom_program": atom, "scenario": scenario})
            save(out/"checkpoint.json.gz", session.checkpoint())
            save(out/"logical-schedule.json.gz", scheduler.snapshot())
            receipt = {"window": iteration, "start_us": context["time_us"], "end_us": session.now_us,
                       "logical_nodes": candidate["selected_node_ids"], "actions": len(atom["actions"]),
                       "source_map_count": len(atom["source_map"]), "unique_shared_actions": len({a["id"] for a in atom["actions"]}),
                       "parallel_root_resets": len([a for a in atom["actions"] if a["kind"] == "reset" and a["t_start_us"] == context["time_us"]])}
            receipts.append(receipt); print(json.dumps(receipt), flush=True)
            iteration += 1
        save(out/"event-trace.json.gz", session.export_trace())
        save(out/"receipt.json", {"status": "author_integration_passed_R6_pending", "windows": receipts,
             "logical_complete": scheduler.snapshot()["complete"], "full_shor_complete": False,
             "wall_seconds": time.perf_counter()-started, "user_visual": "pending", "sampled": False})
    except Exception as exc:
        save(out/"failure.json", {"exception": type(exc).__name__, "message": str(exc), "details": getattr(exc, "details", None),
                                   "windows": receipts, "iteration": iteration, "time_us": session.now_us})
        save(out/"checkpoint.json.gz", session.checkpoint())
        save(out/"event-trace.json.gz", session.export_trace())
        raise


if __name__ == "__main__": main()
