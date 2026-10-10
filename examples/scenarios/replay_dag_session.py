"""Re-execute immutable compiled windows using current runtime, no search replay."""
import gzip
import json
import argparse
from pathlib import Path
import time

from na_pipeline.runtime import EventSession, LogicalListScheduler, bind_physical_plan, make_scenario
from na_pipeline.runtime.session import source_identity
from run_dag_session import save


def read(path): return json.loads(gzip.decompress(path.read_bytes()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("examples/scenarios/T505-dag-session-v1"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-history", action="store_true")
    args = parser.parse_args(); source, out = args.source, args.output
    if out.exists(): raise ValueError("OUTPUT_ALREADY_EXISTS: preserve earlier runtime qualification")
    device, logical = read(source/"device.json.gz"), read(source/"logical-dag.json.gz")
    placement = read(source/"patch-placement.json.gz")
    session = EventSession(device, placement["initial_state"], run_id="T505-fixed-runtime")
    scheduler = LogicalListScheduler(logical, {})
    before, started = source_identity(), time.perf_counter()
    receipts = []
    for path in sorted(source.glob("window-*.json.gz")):
        old = read(path); plan = old["physical_plan"]; graphs = plan["physical_dags"]
        context = session.compilation_context(graphs)
        atom = bind_physical_plan(plan, context)
        proposal = scheduler.propose_joint(plan)
        session.submit(atom, make_scenario(atom), expected_revision=context["revision"])
        scheduler.reserve_joint(plan, proposal)
        # Restore at a genuine in-flight move, not just an idle checkpoint.
        move = next(a for a in atom["actions"] if a["kind"] == "move")
        session.advance((move["t_start_us"]+move["t_end_us"])/2)
        checkpoint = session.checkpoint()
        restored = EventSession.restore(device, checkpoint)
        assert restored.snapshot() == session.snapshot()
        session = restored; session.advance(); scheduler.advance(session.now_us)
        for graph in graphs:
            nid = graph["logical_binding"]["logical_node_id"]
            summary = plan["node_summaries"][graph["artifact_id"]]
            scheduler.complete(nid, {"node_id": nid, "completed_us": max(session.completed[a] for a in summary["action_ids"]),
                "physical_plan_ref": atom["artifact_id"], "event_trace_ref": session.run_id+"/trace/"+str(session.revision)},
                {r: session.results[r] for r in scheduler.nodes[nid]["writes"]})
        save(out/path.name, {"original_compiled_artifact": path.as_posix(), "atom_program": atom,
                            "scenario": make_scenario(atom), "logical_proposal": proposal})
        if args.archive_history:
            session.retire_committed(out/"history"/path.name, keep_result_ids=logical["result_types"])
        receipts.append({"source": path.as_posix(), "start_us": context["time_us"], "end_us": session.now_us,
                         "action_count": len(atom["actions"]), "mid_move_checkpoint_restored": True})
        print(json.dumps(receipts[-1]), flush=True)
    save(out/"event-trace.json.gz", session.export_trace())
    save(out/"logical-schedule.json.gz", scheduler.snapshot())
    save(out/"checkpoint.json.gz", session.checkpoint())
    save(out/"receipt.json", {"status": "author_current_runtime_reexecution_passed", "windows": receipts,
        "logical_complete": scheduler.snapshot()["complete"], "full_shor_complete": False,
        "runtime_source_before": before, "runtime_source_after": source_identity(), "source_stable": before == source_identity(),
        "stats": session.export_trace()["stats"], "wall_seconds": time.perf_counter()-started,
        "chunked_history": args.archive_history, "retained_action_count": len(session.actions),
        "independent_validation": "pending_R6", "user_visual": "pending", "sampled": False})


if __name__ == "__main__": main()
