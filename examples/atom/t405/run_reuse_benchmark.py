"""Actual two-SE compiled-strategy reuse with independent observations and validation."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from na_pipeline.backend import PhysicalStrategyLibrary, place_patches
from na_pipeline.device import preinitialized_device
from na_pipeline.qec import build_physical_dag_bundle, materialize_physical_node
from na_pipeline.runtime import EventSession, LogicalListScheduler, bind_physical_plan, make_scenario
from na_pipeline.validation.dag_session import validate_session_run
from examples.atom.t405.reuse_workload import repeated_se_workload
from examples.atom.t405.observe_compiler import RawCompilerObserver, map_raw_calls_to_strategy


def save(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[3]
    files = [p for part in ("backend", "device", "qec", "runtime", "validation") for p in (root/"src/na_pipeline"/part).glob("*.py")]
    def hashes(): return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest() for p in files}
    before = hashes()
    logical = repeated_se_workload(patch_count=2); bundle = build_physical_dag_bundle(logical); device = preinitialized_device()
    placement = place_patches({p["patch_id"]: {"aod_group": "data", "basis": "Z", "value": 0} for p in logical["patches"]}, [], device)
    session = EventSession(device, placement["initial_state"], run_id="T405-compiled-strategy-two-SE")
    scheduler = LogicalListScheduler(logical, {}); library = PhysicalStrategyLibrary(device)
    records, metrics, strategy_ids = [], [], []
    for index in range(2):
        selected = scheduler.joint_candidates()["selected_node_ids"]
        dags = [materialize_physical_node(bundle, nid) for nid in selected]
        snapshot = session.snapshot(); context = session.compilation_context(dags)
        counts_before = library.stats; start = time.perf_counter()
        with RawCompilerObserver(root) as compile_observer:
            strategy = library.get_or_compile(dags, snapshot["world_state"])
            route_get = compile_observer.calls["src/na_pipeline/backend/enola_kernel.py:group_route"]
        get_seconds = time.perf_counter()-start; counts_get = library.stats
        start = time.perf_counter()
        with RawCompilerObserver(root) as bind_observer:
            plan = library.bind(strategy, dags, snapshot["world_state"], execution_context=context)
            route_bind = bind_observer.calls["src/na_pipeline/backend/enola_kernel.py:group_route"]
        bind_seconds = time.perf_counter()-start
        atom = bind_physical_plan(plan, context); scenario = make_scenario(atom, value=index)
        proposal = scheduler.propose_joint(plan); scheduler.reserve_joint(plan, proposal)
        session.submit(atom, scenario, expected_revision=context["revision"]); current = session.advance()
        scheduler.advance(current["time_us"]); trace = session.export_trace()
        for selection in proposal["selected"]:
            nid = selection["node_id"]; node = next(n for n in logical["nodes"] if n["id"] == nid)
            scheduler.complete(nid, {"node_id": nid, "completed_us": selection["end_us"], "physical_plan_ref": atom["artifact_id"],
                                     "event_trace_ref": trace["artifact_id"]}, {r: current["published_results"][r] for r in node["writes"]})
        records.append({"physical_plan": plan, "atom_program": atom, "scenario": scenario,
                        "compile_observation": compile_observer.evidence(), "bind_observation": bind_observer.evidence()})
        strategy_ids.append(strategy["strategy_id"])
        metrics.append({"instance": index, "get_wall_seconds_with_observer": get_seconds, "bind_wall_seconds_with_observer": bind_seconds,
                        "route_get_observed": route_get, "route_bind_observed": route_bind,
                        "before": counts_before, "after_get": counts_get, "after_bind": library.stats})
        if index == 0:
            save(args.out/"strategy.json.gz", strategy)
            save(args.out/"raw-plan-mapping.json", map_raw_calls_to_strategy(strategy, compile_observer.evidence()))
    data = {"scope": "two_rounds_of_two_independent_SE_compiled_strategy_reuse", "fixture": False, "full_shor": False,
            "logical_dag": logical, "physical_bundle": bundle, "device": device, "initial_state": placement["initial_state"],
            "windows": records, "event_trace": session.export_trace(), "logical_schedule": scheduler.snapshot()}
    report = validate_session_run(data)
    after = hashes(); values = [r["value"] for r in data["event_trace"]["results"].values()]
    summary = {"scope": data["scope"], "full_shor": False, "fixture": False, "source_stable": before == after,
               "source_before": before, "source_after": after, "strategies_identical": len(set(strategy_ids)) == 1,
               "library_stats": library.stats, "instances": metrics, "independent_report_passed": report["passed"],
               "result_values": values, "results_independent": values == [0]*16+[1]*16,
               "repeat_search_zero": metrics[1]["route_get_observed"] == 0 and metrics[1]["route_bind_observed"] == 0
                   and not records[1]["compile_observation"]["call_counts"] and not records[1]["bind_observation"]["call_counts"],
               "user_visual_acceptance": "pending"}
    save(args.out/"run.json.gz", data); save(args.out/"session-report.json", report); save(args.out/"summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("strategies_identical", "source_stable", "library_stats", "repeat_search_zero", "results_independent", "independent_report_passed")}, ensure_ascii=False))
    if not all(summary[k] for k in ("strategies_identical", "source_stable", "repeat_search_zero", "results_independent", "independent_report_passed")): raise SystemExit(2)


if __name__ == "__main__": main()
