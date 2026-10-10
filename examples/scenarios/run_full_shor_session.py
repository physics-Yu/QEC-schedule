"""Whole eight-round source driver; dispatch heavy execution through R7 only."""
import argparse
import gzip
import json
from pathlib import Path
import time

from na_pipeline.runtime import HierarchicalPipeline
from na_pipeline.runtime.pipeline import save_artifact


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--world", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--phase-value", type=int, default=64)
    p.add_argument("--stage-budget-seconds", type=float, default=3600)
    p.add_argument("--resume", type=Path)
    p.add_argument("--factory-scenarios", type=Path)
    p.add_argument("--preflight-only", action="store_true")
    args = p.parse_args()
    if not 0 <= args.phase_value <= 255: p.error("phase-value must be 0..255; it is an explicit fake scenario")
    world = read(args.world)
    if len(world["logical_dag"].get("rounds", [])) != 8: p.error("world must retain the complete eight-round source")
    budget = {"max_operations": 100000, "max_wall_seconds": args.stage_budget_seconds}
    if args.resume:
        checkpoint = read(args.resume)
        if args.factory_scenarios and read(args.factory_scenarios) != checkpoint["body"]["factory_scenarios"]:
            p.error("resume must preserve the committed bounded attempt policy")
        pipeline = HierarchicalPipeline.restore(world, args.out, checkpoint, compile_budget=budget)
    else:
        bits = [(args.phase_value >> (7-i)) & 1 for i in range(8)]
        pipeline = HierarchicalPipeline(world, args.out, phase_bits=bits, compile_budget=budget,
                                        factory_scenarios=read(args.factory_scenarios) if args.factory_scenarios else None)
    started = time.perf_counter()
    save_artifact(args.out/"checkpoint.json.gz", pipeline.checkpoint())
    if args.preflight_only:
        record = dict(pipeline.status(), preflight_only=True, physical_execution_started=False)
        save_artifact(args.out/"preflight.json", record)
        print(json.dumps({k: record[k] for k in ("preflight_only", "physical_execution_started", "logical_node_count", "complete_source_path")}))
        return
    try:
        while not pipeline.scheduler.snapshot()["complete"]:
            save_artifact(args.out/"current-phase.json", {"time_us": pipeline.session.now_us,
                "window": pipeline.window_count, "factory_stage": pipeline.factory.stage_id if pipeline.factory else None,
                "phase": "plan_and_execute_complete_next_window", "complete": False})
            print(json.dumps(pipeline.step(), ensure_ascii=False), flush=True)
        save_artifact(args.out/"event-trace.json.gz", pipeline.session.export_trace())
        save_artifact(args.out/"logical-schedule.json.gz", pipeline.scheduler.snapshot())
        report = dict(pipeline.status(), wall_seconds=time.perf_counter()-started)
        save_artifact(args.out/"manifest.json", report)
        print(json.dumps({"complete_source_path": report["complete_source_path"], "full_program_passed": False,
            "windows": report["windows"], "postprocess": report["postprocess"], "wall_seconds": report["wall_seconds"]}), flush=True)
    except Exception as exc:
        save_artifact(args.out/"failed-prefix.json.gz", pipeline.checkpoint())
        save_artifact(args.out/"incomplete.json", {"type": type(exc).__name__, "message": str(exc), "details": getattr(exc, "details", None),
            "time_us": pipeline.session.now_us, "window": pipeline.window_count, "status": pipeline.status(),
            "wall_seconds": time.perf_counter()-started, "complete_source_path": False, "full_program_passed": False})
        raise


if __name__ == "__main__": main()
