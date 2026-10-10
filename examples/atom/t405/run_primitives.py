"""Real R3 physical DAG -> R4 joint planner -> R5 fake component evidence."""
from pathlib import Path
import argparse
from hashlib import sha256
import gzip
import json
import sys

from na_pipeline.backend import compile_physical_dag, place_patches
from na_pipeline.device import preinitialized_device
from na_pipeline.qec.physical_dag import build_patch_operation_spec
from na_pipeline.runtime import run, make_scenario
from na_pipeline.validation.dag_observer import EnolaStageObserver


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[3]
    paths = [p for part in ("device", "qec", "backend", "runtime", "validation") for p in (root/"src/na_pipeline"/part).glob("*.py")]
    def hashes(): return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths}
    before, results = hashes(), []
    device = preinitialized_device()
    for operation in ("SE", "H", "X", "Z", "RESET", "CX", "CZ", "MEASURE"):
        spec = build_patch_operation_spec(operation, params={"basis": "X"} if operation == "MEASURE" else None)
        dag = spec["physical_dag"]
        blocks = list(dict.fromkeys(q["block_id"] for q in dag["qubits"]))
        patches = {p: {"aod_group": "data", "basis": "Z", "value": 0} for p in blocks}
        interactions = [{"node_id": "component-coupling", "patch_operands": blocks, "layer": 0}] if len(blocks) == 2 else []
        # Component geometry only; full logical placement evidence is separate.
        placement = place_patches(patches, interactions, device, seed=7)
        with EnolaStageObserver(root/"third_party/enola/upstream") as observer:
            plan = compile_physical_dag(dag, device, placement["initial_state"])
        atom = plan["atom_program"]
        scenario = make_scenario(atom, value=1)
        trace = run(atom, scenario, device)
        record = {"operation": operation, "scope": "single_R3_physical_DAG_component", "device": device,
                  "spec": spec, "physical_dag": dag, "patch_placement": placement, "physical_plan": plan,
                  "scenario": scenario, "event_trace": trace, "enola_observation": observer.evidence(),
                  "full_shor": False, "independent_validation": "pending_R6", "user_visual_acceptance": "pending"}
        name = operation.lower()+".json.gz"
        (args.out/name).write_bytes(gzip.compress(encoded(record), mtime=0))
        results.append({"operation": operation, "file": name, "byte_sha256": sha256((args.out/name).read_bytes()).hexdigest(),
                        "compile": atom["stats"], "run": trace["stats"],
                        "original_scheduler_calls": observer.evidence()["call_counts"].get("enola/scheduler/gate_scheduler.py:gate_scheduling", 0)})
    after = hashes()
    summary = {"scope": "eight_physical_operation_components", "full_shor": False,
               "fixture": False, "python": sys.version, "source_before": before, "source_after": after,
               "source_stable": before == after, "results": results, "independent_validation": "pending_R6"}
    (args.out/"summary.json").write_bytes(encoded(summary))
    print(json.dumps({"source_stable": before == after, "operations": [{"name": r["operation"], "actions": r["compile"]["action_count"], "scheduler_calls": r["original_scheduler_calls"]} for r in results]}))
    if before != after: raise SystemExit(2)


if __name__ == "__main__":
    main()
