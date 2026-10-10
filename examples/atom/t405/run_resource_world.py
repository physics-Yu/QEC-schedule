"""Full source/resource inventory placement stage; no full physical run claim."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from na_pipeline.backend import place_resource_requirements
from na_pipeline.device import preinitialized_device
from na_pipeline.frontend import build_logical_dag, build_shor15, synthesize_feedback
from na_pipeline.qec import physical_resource_requirements
from na_pipeline.validation.dag_observer import EnolaStageObserver


def save(path, data):
    raw = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    status = {"stage": "frontend", "full_program_passed": False}
    save(args.out/"status.json", status)
    try:
        logical = build_logical_dag(synthesize_feedback(build_shor15()))
        requirements = physical_resource_requirements(logical)
        device = preinitialized_device()
        save(args.out/"input.json.gz", {"logical_dag": logical, "requirements": requirements, "device": device})
        status.update(stage="whole_world_placement", logical_nodes=len(logical["nodes"]), resource_count=requirements["physical_qubit_count"])
        save(args.out/"status.json", status)
        with EnolaStageObserver(Path(__file__).resolve().parents[3]/"third_party/enola/upstream") as observer:
            placement = place_resource_requirements(logical, requirements, device, seed=7,
               budget={"max_iterations": 1000, "moves_per_iteration": 400, "initial_moves": 100,
                       "max_moves": 400100, "max_wall_seconds": 600.})
        world = placement["initial_state"]
        actual = {a["qubit_id"] for a in world["atoms"]}
        if actual != set(requirements["physical_qubit_ids"]): raise ValueError("WHOLE_WORLD_IDENTITY_MISMATCH")
        output = {"logical_dag": logical, "requirements": requirements, "device": device,
                  "patch_placement": placement, "initial_state": world, "observation": observer.evidence()}
        save(args.out/"world.json.gz", output)
        status.update(stage="completed_inventory_placement_only", complete=True, wall_seconds=time.perf_counter()-start,
                      atoms=len(world["atoms"]), patches=len(placement["placements"]), nonpatch_atoms=len(requirements["nonpatch_atoms"]),
                      cost=placement["cost"], search=placement["search"], source_observation_stable=observer.evidence()["source_unchanged"],
                      independent_validation="pending_R6", physical_execution=False, ready_magic_tokens=world["ready_magic_tokens"],
                      output_sha256=sha256((args.out/"world.json.gz").read_bytes()).hexdigest())
        save(args.out/"status.json", status); print(json.dumps(status, ensure_ascii=False))
    except Exception as exc:
        status.update(stage="incomplete", complete=False, error={"type": type(exc).__name__, "message": str(exc)}, wall_seconds=time.perf_counter()-start)
        save(args.out/"status.json", status); raise


if __name__ == "__main__": main()
