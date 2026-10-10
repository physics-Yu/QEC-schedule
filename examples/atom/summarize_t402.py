"""Build a compact index of completed profiles, preserving the failed attempt."""
import json
from hashlib import sha256
from pathlib import Path

root = Path(__file__).resolve().parents[2]
base = root / "examples/atom/profiles"
summary = {"task_id": "T402", "schema_version": "R4CostSummary/0.1.0", "complete_profiles": [],
           "all_complete": False, "failed_attempts": [],
           "method": "one isolated process per rounds/mode; sequential jobs; plain timings are primary; tracemalloc overhead is not a cache speedup",
           "acceptance_scope": "cost measurement and source-stream equivalence only; no new runtime/physics qualification"}
for rounds in (1, 2, 5):
    modes = []
    for mode in ("plain", "traced"):
        label = f"rounds-{rounds}-{mode}"
        directory = base / ("T402-retry1" if (rounds, mode) == (5, "traced") else "T402")
        path = directory / (label + ".json")
        job = directory / (label + "-job")
        data = json.loads(path.read_text(encoding="utf-8"))
        status = json.loads((job / "status.json").read_text(encoding="utf-8"))
        if not data["complete"] or status["status"] != "completed":
            raise RuntimeError("Incomplete cost case: " + label)
        modes.append(data)
        summary["complete_profiles"].append({"case": label, "path": path.relative_to(root).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(), "job_status": status["status"],
            "physical_ops": data["expanded_count"], "actions": data["compiler_stats"]["action_count"],
            "makespan_us": data["compiler_stats"]["duration_us"], "structure": data["structure"],
            "phases_wall_seconds": data["phases_wall_seconds"], "compiler_stages": data["compiler_stats"]["stage_wall_seconds"],
            "worker_peak_rss_bytes": data["rss_final"]["peak_rss_bytes"],
            "sampled_process_tree_peak_bytes": status["peak_tree_rss_bytes"],
            "python_traced_peak_bytes": data.get("python_traced_bytes", {}).get("peak"),
            "output_bytes": data["output"]["bytes"], "operation_stream_sha256": data["operation_stream_sha256"],
            "input_hashes": data["input_hashes"]})
    if modes[0]["operation_stream_sha256"] != modes[1]["operation_stream_sha256"] or modes[0]["input_hashes"] != modes[1]["input_hashes"]:
        raise RuntimeError(f"Plain/traced source drift: rounds={rounds}")
failed = base / "T402/rounds-5-traced-job/status.json"
summary["failed_attempts"].append({"path": failed.relative_to(root).as_posix(),
    "status": json.loads(failed.read_text(encoding="utf-8")),
    "resolution": "Preserved failed attempt; own status reader now uses FILE_SHARE_DELETE; original full rounds=5 rerun completed in T402-retry1"})
summary["all_complete"] = True
summary["budget"] = {"per_job_wall_seconds": 300, "per_job_sampled_process_tree_rss_limit_bytes": 2*1024**3,
                     "per_job_compute_threads": 1,
                     "note": "Worker budget field root_process_rss_bytes is a legacy label; job.json/status.json confirm actual process-tree RSS enforcement"}
out = base / "T402/summary.json"
out.write_bytes((json.dumps(summary, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
print(json.dumps({"path": str(out), "all_complete": summary["all_complete"], "profiles": len(summary["complete_profiles"])}))
