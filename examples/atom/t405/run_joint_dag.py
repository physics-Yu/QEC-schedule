"""Real R2/R3/R4/R5 ready batches, coupling and SE continuation in one session."""
import argparse
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from na_pipeline.backend import place_logical_dag, compile_physical_dag
from na_pipeline.device import preinitialized_device
from na_pipeline.frontend import build_patch_dag_example
from na_pipeline.qec import build_physical_dag_bundle, materialize_physical_node
from na_pipeline.runtime import EventSession, LogicalListScheduler, bind_physical_plan, make_scenario
from na_pipeline.validation.dag_observer import EnolaStageObserver


def save(path, data):
    raw = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[3]
    files = [p for part in ("backend", "device", "frontend", "qec", "runtime", "validation") for p in (root/"src/na_pipeline"/part).glob("*.py")]
    def hashes(): return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest() for p in files}
    before = hashes(); started = time.perf_counter()
    logical = build_patch_dag_example(); physical = build_physical_dag_bundle(logical); device = preinitialized_device()
    placement = place_logical_dag(logical, device, seed=7, budget={"max_iterations": 1000})
    session = EventSession(device, placement["initial_state"], run_id="T405-joint-real")
    scheduler = LogicalListScheduler(logical, {})
    records = []
    while not scheduler.snapshot()["complete"]:
        candidates = scheduler.joint_candidates()
        ids = candidates["selected_node_ids"]
        if not ids: raise ValueError("NO_EXECUTABLE_READY_BATCH")
        dags = [materialize_physical_node(physical, nid) for nid in ids]
        context = session.compilation_context(dags); snapshot = session.snapshot()
        with EnolaStageObserver(root/"third_party/enola/upstream") as observer:
            plan = compile_physical_dag(dags, device, snapshot["world_state"], execution_context=context,
                                        budget={"max_operations": 100000, "max_wall_seconds": 600.})
        proposal = scheduler.propose_joint(plan)
        atom = bind_physical_plan(plan, context); scenario = make_scenario(atom, value=1)
        session.submit(atom, scenario, expected_revision=context["revision"])
        scheduler.reserve_joint(plan, proposal)
        ends = sorted({s["end_us"] for s in proposal["selected"]})
        for end in ends:
            current = session.advance(end); scheduler.advance(end)
            trace = session.export_trace()
            for selection in proposal["selected"]:
                if selection["end_us"] != end: continue
                nid = selection["node_id"]
                source = next(n for n in logical["nodes"] if n["id"] == nid)
                results = {r: deepcopy(current["published_results"][r]) for r in source["writes"]}
                scheduler.complete(nid, {"node_id": nid, "completed_us": end, "physical_plan_ref": atom["artifact_id"],
                                         "event_trace_ref": trace["artifact_id"]}, results)
        records.append({"candidates": candidates, "physical_dags": dags, "execution_context": context,
                        "physical_plan": plan, "atom_program": atom, "scenario": scenario, "proposal": proposal,
                        "enola_observation": observer.evidence()})
        save(args.out/(f"batch-{len(records):02d}.json.gz"), records[-1])
        save(args.out/"checkpoint.json.gz", session.checkpoint())
        save(args.out/"status.json", {"complete": False, "completed_batches": len(records), "model_time_us": session.snapshot()["time_us"],
                                     "wall_seconds": time.perf_counter()-started, "selected": ids})
        print(json.dumps({"batch": len(records), "selected": ids, "compile_seconds": plan["atom_program"]["stats"]["compile_wall_seconds"]}), flush=True)
    trace = session.export_trace(); after = hashes()
    save(args.out/"inputs.json.gz", {"logical_dag": logical, "physical_bundle": physical, "device": device, "patch_placement": placement})
    save(args.out/"trace.json.gz", trace); save(args.out/"logical-schedule.json", scheduler.snapshot())
    summary = {"scope": "real_four_patch_two_DAG_SE_coupling_SE_component", "full_shor": False, "fixture": False,
               "complete": True, "logical_nodes": len(logical["nodes"]), "batches": len(records), "trace_stats": trace["stats"],
               "source_before": before, "source_after": after, "source_stable": before == after,
               "wall_seconds": time.perf_counter()-started, "independent_validation": "pending_R6", "user_visual_acceptance": "pending"}
    save(args.out/"summary.json", summary); save(args.out/"status.json", {k: v for k, v in summary.items() if not k.startswith("source_")})
    print(json.dumps({k: v for k, v in summary.items() if not k.startswith("source_")}), flush=True)
    if before != after: raise SystemExit(2)


if __name__ == "__main__": main()
