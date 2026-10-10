"""Actual R2 -> R4 Enola SAPlacer -> R1 t=0 placement evidence, not a full run."""
from pathlib import Path
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import platform
import sys
import time

from na_pipeline.backend import place_logical_dag
from na_pipeline.device import preinitialized_device
from na_pipeline.frontend import build_patch_dag_example


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[3]
    paths = [p for part in ("device", "frontend", "backend") for p in (root/"src/na_pipeline"/part).glob("*.py")]
    paths.append(Path(__file__))
    def identities():
        return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths}
    before = identities()
    device, dag = preinitialized_device(), build_patch_dag_example()
    observed = []
    def observer(frame, event, arg):
        if event == "return" and frame.f_code.co_name == "run" and frame.f_code.co_filename.replace("\\", "/").endswith("enola/placer/placer.py"):
            s = frame.f_locals["self"]
            observed.append({"filename": frame.f_code.co_filename, "function": "SAPlacer.run",
                             "chip_dim": list(s.chip_dim), "n_qubit": s.n_qubit, "layers": deepcopy(s.list_gate),
                             "best_mapping": [list(p) for p in s.best_mapping], "best_cost": s.best_cost})
    start = time.perf_counter()
    sys.setprofile(observer)
    try:
        placement = place_logical_dag(dag, device, seed=7, budget={"max_iterations": 1000})
    finally:
        sys.setprofile(None)
    elapsed = time.perf_counter() - start
    after = identities()
    for name, value in (("device.json", device), ("logical-dag.json", dag), ("patch-placement.json", placement),
                        ("initial-state.json", placement["initial_state"]), ("placer-observation.json", observed)):
        save(args.out/name, value)
    summary = {"scope": "actual_R2_nontrivial_patch_placement_component", "fixture": False,
               "physical_compilation_complete": False, "runtime_executed": False, "full_shor": False,
               "patch_count": len(dag["patches"]), "logical_nodes": len(dag["nodes"]),
               "cost": placement["cost"], "search": placement["search"], "wall_seconds_with_observer": elapsed,
               "host": platform.node(), "python": sys.version, "source_before": before, "source_after": after,
               "source_stable": before == after, "original_run_observed": len(observed) == 1,
               "original_mapping_matches": observed[0]["best_mapping"] == placement["enola"]["raw_output"]["best_mapping"],
               "independent_validation": "pending_R6", "user_visual_acceptance": "pending",
               "files": {p.name: sha256(p.read_bytes()).hexdigest() for p in args.out.iterdir() if p.is_file()}}
    save(args.out/"summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("scope", "patch_count", "logical_nodes", "cost", "source_stable", "original_run_observed")}, ensure_ascii=False))
    if not all(summary[k] for k in ("source_stable", "original_run_observed", "original_mapping_matches")):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
