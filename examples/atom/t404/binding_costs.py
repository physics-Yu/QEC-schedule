"""Recheck saved real binding inputs and measure unprofiled binding wall cost.

This does not execute a new fake run or reuse a runtime acceptance result.
The immutable strategy and exact world/request from the qualified run are read.
"""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from na_pipeline.backend import bind_strategy


parser = argparse.ArgumentParser()
parser.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent/"qualification-v3")
args = parser.parse_args()
root = args.dir.resolve()
run = json.load(gzip.open(root/"run.json.gz", "rt", encoding="utf-8"))
device = json.loads((root/"device.json").read_text(encoding="utf-8"))
records = []
for instance in run["instances"]:
    strategy = run["strategies"][instance["strategy_id"]]
    started = time.perf_counter()
    bound = bind_strategy(strategy, instance["binding"], device)
    elapsed = time.perf_counter()-started
    equal = bound["atom_program"] == instance["atom_program"] and bound["physical_program"] == instance["physical_program"]
    records.append({"call_id": instance["call_id"], "strategy_hash": strategy["strategy_hash"],
                    "binding_wall_seconds": elapsed, "matches_qualified_instance": equal,
                    "binding_report": bound["binding_report"]})
    if not equal:
        raise RuntimeError("Binding output changed for " + instance["call_id"])
out = {"scope": "fresh pure binding/composition recheck of saved actual input; no runtime execution or quantum state",
       "tracemalloc_enabled": False, "python_call_profiler_enabled": False,
       "run_file_sha256": sha256((root/"run.json.gz").read_bytes()).hexdigest(),
       "enola_zero_call_evidence_ref": "enola-observation.json.gz binding_observations (original observed binding)",
       "records": records, "all_matched": all(r["matches_qualified_instance"] for r in records),
       "total_binding_wall_seconds": sum(r["binding_wall_seconds"] for r in records)}
(root/"binding-costs.json").write_bytes((json.dumps(out, ensure_ascii=False, indent=2)+"\n").encode("utf-8"))
print(json.dumps({"all_matched": out["all_matched"], "calls": len(records), "total_binding_wall_seconds": out["total_binding_wall_seconds"],
                  "per_call_min_seconds": min(r["binding_wall_seconds"] for r in records),
                  "per_call_max_seconds": max(r["binding_wall_seconds"] for r in records)}))
