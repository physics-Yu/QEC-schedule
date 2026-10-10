"""Execute a complete representative R3 factory recipe in the real 205-atom world.

This qualifies one T-resource route on explicit live encoded input. It is not
the full Shor path and never reports completion of the algorithm's prior gates.
"""
import argparse
import gzip
import json
from pathlib import Path
import time

from na_pipeline.backend import compile_physical_dag
from na_pipeline.qec import build_factory15to1_protocol
from na_pipeline.runtime import EventSession, FiniteResourcePool, FactoryExecution, bind_physical_plan, make_scenario
from na_pipeline.runtime.engine import digest


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    raw = gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw
    tmp = path.with_name(path.name+".tmp"); tmp.write_bytes(raw); tmp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--gate", choices=("T", "TDG"), default="T")
    parser.add_argument("--target", default="ctrl")
    parser.add_argument("--stage-budget-seconds", type=float, default=3600)
    parser.add_argument("--reject-terminal", action="store_true")
    parser.add_argument("--archive-history", action="store_true")
    args = parser.parse_args(); world = read(args.world)
    device, requirements = world["device"], world["requirements"]
    if args.resume:
        controller = FactoryExecution.restore(device, read(args.resume))
        session, pool = controller.session, controller.pool
    else:
        session = EventSession(device, world["initial_state"], run_id="T505-factory:"+digest(world)+":"+args.gate)
        pool = FiniteResourcePool(requirements, world["initial_state"])
        protocol = build_factory15to1_protocol(data_block_id=args.target, request_id="representative-live-data", gate=args.gate,
                                               epoch=pool.next_epoch, factory_id=requirements["factory_id"])
        controller = FactoryExecution(protocol, pool, session, owner="representative-live-T")
    args.out.mkdir(parents=True, exist_ok=True)
    save(args.out/"world-input.json.gz", world)
    save(args.out/"protocol.json.gz", controller.protocol)
    started = time.perf_counter()
    try:
        while controller.terminal is None:
            stage = controller.protocol["stages"][controller.stage_id]
            if stage["kind"] == "lifecycle":
                controller.advance_lifecycle()
                save(args.out/"checkpoint.json.gz", controller.checkpoint())
                continue
            sid = controller.stage_id
            save(args.out/"checkpoint.json.gz", controller.checkpoint())
            graph = controller.next_graph()
            context = session.compilation_context(graph)
            save(args.out/"status.json", {"status": "compiling", "stage_id": sid, "time_us": session.now_us,
                  "complete": False, "full_program_passed": False, "physical_operations": len(graph["nodes"]),
                  "per_stage_wall_budget_seconds": args.stage_budget_seconds, "max_operations": 100000})
            print(json.dumps({"phase": "compile", "stage_id": sid, "operations": len(graph["nodes"]), "time_us": session.now_us}), flush=True)
            plan = compile_physical_dag(graph, device, session.snapshot()["world_state"], execution_context=context,
                  budget={"max_operations": 100000, "max_wall_seconds": args.stage_budget_seconds})
            atom = bind_physical_plan(plan, context)
            controller.validate_submission(plan, atom)
            overrides = {}
            if args.reject_terminal and sid == "terminal_checks":
                overrides[controller.protocol["acceptance_checks"][0]["result_ids"][0]] = 1
            scenario = make_scenario(atom, value=0, overrides=overrides)
            save(args.out/(sid+"-plan.json.gz"), {"physical_plan": plan, "atom_program": atom, "scenario": scenario})
            session.submit(atom, scenario, expected_revision=context["revision"])
            session.advance()
            receipt = controller.commit_stage(plan, atom)
            save(args.out/(sid+"-receipt.json"), receipt)
            if args.archive_history:
                # All internal branch decisions are already committed. Keep
                # algorithm results for future guards, retire only this run's
                # completed payloads to immutable evidence chunks.
                keep = set(world["logical_dag"]["result_types"])
                session.retire_committed(args.out/"history"/(sid+".json.gz"), keep_result_ids=keep)
            save(args.out/"checkpoint.json.gz", controller.checkpoint())
            save(args.out/"factory-ledger.json", controller.snapshot())
            print(json.dumps({"phase": "committed", "stage_id": sid, "next": controller.stage_id,
                              "time_us": session.now_us, "actions": len(atom["actions"])}), flush=True)
        save(args.out/"event-trace.json.gz", session.export_trace())
        save(args.out/"status.json", {"status": "completed_representative_protocol", "outcome": controller.terminal,
             "complete": True, "full_program_passed": False, "wall_seconds": time.perf_counter()-started,
             "stats": session.export_trace()["stats"], "independent_validation": "pending_R6", "user_visual": "pending",
             "initial_world_sha256": digest(world), "sampled": False})
    except Exception as exc:
        # Preserve the latest healthy committed frontier. A failed current
        # prefix is diagnosis, not a resumable overwrite of that checkpoint.
        save(args.out/"failed-prefix.json.gz", controller.checkpoint())
        save(args.out/"status.json", {"status": "incomplete", "stage_id": controller.stage_id, "complete": False,
             "full_program_passed": False, "error": {"type": type(exc).__name__, "message": str(exc), "details": getattr(exc, "details", None)},
             "wall_seconds": time.perf_counter()-started, "time_us": session.now_us})
        raise


if __name__ == "__main__": main()
