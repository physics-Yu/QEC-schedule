"""Complete first factory stage in the full carrier world, with persistent evidence.

This is a protocol-stage qualification input, not a claim to have executed the
algorithm predecessors of its logical demand or the remaining adaptive stages.
"""
import argparse
import gzip
import json
from pathlib import Path
import time

from na_pipeline.backend import compile_physical_dag
from na_pipeline.qec import build_physical_dag_bundle, materialize_factory_protocol, build_factory_physical_dag
from na_pipeline.runtime import EventSession, bind_physical_plan, make_scenario
from na_pipeline.runtime.resource_pool import FiniteResourcePool
from na_pipeline.validation.dag_observer import EnolaStageObserver


def save(path, data):
    raw = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--world", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter(); status = {"scope": "full_first_factory_stage_in_complete_world", "full_program_passed": False, "complete_factory_protocol": False}
    save(args.out/"status.json", status)
    try:
        world = json.loads(gzip.decompress(args.world.read_bytes()))
        logical, device, initial = world["logical_dag"], world["device"], world["initial_state"]
        bundle = build_physical_dag_bundle(logical)
        demand = next(n for n in logical["nodes"] if n["operation"] == "T" and n["condition"] is None)
        session = EventSession(device, initial, run_id="T405-factory-stage-in-205-world")
        pool = FiniteResourcePool(bundle["resource_requirements"], initial)
        lease = pool.acquire(demand["id"], "T", demand["patch_operands"]["block"], session)
        protocol = materialize_factory_protocol(bundle, demand["id"], epoch=lease["epoch"])
        stage_id = protocol["entry"]
        dag = build_factory_physical_dag(protocol, stage_id)
        context = session.compilation_context(dag)
        save(args.out/"input.json.gz", {"device": device, "initial_state": initial, "physical_dag": dag,
                                       "execution_context": context, "protocol": protocol, "resource_pool": pool.snapshot(),
                                       "source_demand": demand, "scope": status["scope"]})
        status.update(stage="physical_compile", physical_operations=len(dag["nodes"]), groups=len(dag["groups"]), atoms=len(initial["atoms"]))
        save(args.out/"status.json", status); print(json.dumps(status), flush=True)
        with EnolaStageObserver(Path(__file__).resolve().parents[3]/"third_party/enola/upstream") as observer:
            plan = compile_physical_dag(dag, device, session.snapshot()["world_state"], execution_context=context,
                                        budget={"max_operations": 100000, "max_wall_seconds": 3000.})
        save(args.out/"physical-plan.json.gz", plan); save(args.out/"enola-observation.json.gz", observer.evidence())
        atom = bind_physical_plan(plan, context); scenario = make_scenario(atom, value=1)
        status.update(stage="event_execution", compile=plan["atom_program"]["stats"])
        save(args.out/"status.json", status)
        session.submit(atom, scenario, expected_revision=context["revision"]); session.advance()
        save(args.out/"execution.json.gz", {"atom_program": atom, "scenario": scenario, "event_trace": session.export_trace(),
                                           "checkpoint": session.checkpoint(), "resource_pool": pool.snapshot()})
        status.update(stage="completed_first_factory_stage_only", complete=True, wall_seconds=time.perf_counter()-started,
                      trace_stats=session.export_trace()["stats"], ready_magic_tokens=[], independent_validation="pending_R6")
        save(args.out/"status.json", status); print(json.dumps(status), flush=True)
    except Exception as exc:
        status.update(stage="incomplete", complete=False, wall_seconds=time.perf_counter()-started,
                      error={"type": type(exc).__name__, "message": str(exc), "details": getattr(exc, "details", None)})
        save(args.out/"status.json", status); raise


if __name__ == "__main__": main()
