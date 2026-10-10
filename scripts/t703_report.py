"""Package byte-verified T703 evidence without changing the R6 decision."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dispatch", type=Path, required=True)
    parser.add_argument("--checks", type=Path, required=True)
    parser.add_argument("--validation", type=Path, help="New R6 report for the exact same saved run; old report remains")
    args = parser.parse_args()
    manifest = read(args.run / "manifest.json")
    for key, item in manifest["files"].items():
        if sha(args.run / item["path"]) != item["byte_sha256"]:
            raise ValueError("DELIVERY_BYTE_MISMATCH: " + key)
    run, report, evidence = (read(args.run / f"{name}.json") for name in ("run", "validation", "enola_evidence"))
    original_report = report
    if args.validation:
        report = read(args.validation)
        receipt = read(args.validation.with_suffix(".receipt.json"))
        if receipt.get("source_snapshot_stable") is not True or receipt["source_byte_sha256"] != sha(args.run / "run.json") or receipt["report_byte_sha256"] != sha(args.validation):
            raise ValueError("REVALIDATION_IDENTITY_UNVERIFIED")
        for name, value in (("run", run), ("device", read(args.run / "device.json")), ("strategies", read(args.run / "strategies.json")), ("enola_evidence", evidence)):
            actual = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            if report["input_hashes"][name] != actual:
                raise ValueError("REVALIDATION_INPUT_MISMATCH: " + name)
    dispatch = read(args.dispatch)
    status = read(args.dispatch.parent / "observed-status.json")
    tests = read(args.checks)
    if tests["passed"] is not True or manifest["source_snapshot_stable"] is not True:
        raise ValueError("ENGINEERING_CHECK_OR_SOURCE_IDENTITY_UNVERIFIED")
    diagnostic = []
    for instance in run["instances"]:
        cid = instance["call_id"]
        observation = evidence["binding_observations"][cid]
        before, after = instance["library_stats_before"], instance["library_stats_after"]
        diagnostic.append({"call_id": cid, "encoded_call_id": instance.get("encoded_call_id"), "recorded_retries": len(instance.get("composition_retries", [])), "observed_binding_attempts": observation["binding_attempt_count"], "counter_delta": {k: after[k]-before[k] for k in ("strategy_compile_count", "placement_search_count", "routing_search_count", "bind_count", "composition_check_count", "cache_hit_count")}, "observed_upstream_search_returns": observation["record_count"], "observed_project_search_calls": observation.get("project_search_counts"), "scope": "diagnostic only; not a replacement R6 qualification"})
    viewer = ROOT / "viewer/t703-enola-strategies.html"
    if args.validation:
        from viewer import export_view
        export_view(args.run / "atom.json", viewer, trace_path=args.run / "trace.json", device_path=args.run / "device.json", report_path=args.validation, run_path=args.run / "run.json", strategies_path=args.run / "strategies.json")
    else:
        viewer.write_bytes((args.run / "viewer.html").read_bytes())
    summary = {"schema_version": "r7-t703-delivery/0.1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(), "kb_revision": "kb-0005", "planning_revision": "plan-0007", "source_pin": read(ROOT / "third_party/enola/pin.json"), "local_environment": read(ROOT / "scripts/outputs/T703/environment-final.json"), "remote_dispatch": str(args.dispatch), "snapshot_bundle_sha256": dispatch["bundle_sha256"], "remote_project": dispatch["project"], "job": status["status"], "actual_run_manifest": str(args.run / "manifest.json"), "source_snapshot_stable": True, "all_manifest_bytes_match": True, "logical_call_count": len(run["instances"]), "atom_count": len(run["atom_program"]["initial_state"]["atoms"]), "action_count": len(run["atom_program"]["actions"]), "result_count": len(run["event_trace"]["results"]), "runtime_group_count": len(run["group_metrics"]), "duration_us": run["event_trace"]["stats"]["duration_us"], "backend_used": sorted({i["backend_used"] for i in run["instances"]}), "library_stats": run["snapshot"]["library_stats"], "r6_passed": report["passed"], "r6_failure_counts": dict(Counter(f["code"] for f in report["failures"])), "r6_unverified": report["unverified"], "r6_t000_case_metrics": report["metrics"].get("t000_cases"), "binding_diagnostic": diagnostic, "author_checks": str(args.checks), "viewer": str(viewer), "viewer_byte_sha256": sha(viewer), "user_visual_acceptance": "pending", "browser_engineering_check": "blocked_by_prior_file_protocol_policy; DOM shim is not a browser check", "t000_qualified": False, "hardware_executed": False, "quantum_state_simulated": False, "full_shor_executed": False, "scope": "T703 source/environment/CLI/viewer author delivery; R6/R0 acceptance stays separate"}
    out = ROOT / "scripts/outputs/T703/delivery.json"
    summary["original_r6_report_preserved"] = {"passed": original_report["passed"], "failure_counts": dict(Counter(f["code"] for f in original_report["failures"])), "path": str(args.run / "validation.json"), "byte_sha256": sha(args.run / "validation.json")}
    summary["revalidation"] = {"path": str(args.validation), "byte_sha256": sha(args.validation), "receipt": str(args.validation.with_suffix(".receipt.json"))} if args.validation else None
    summary["viewer_source_byte_sha256"] = {name: sha(ROOT / "viewer" / name) for name in ("__init__.py", "viewer.html", "viewer.js", "viewer.css")}
    out.write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    (viewer.with_suffix(".receipt.json")).write_bytes((json.dumps({"original_server_viewer": str(args.run / "viewer.html"), "same_bytes_as_server_viewer": sha(viewer) == sha(args.run / "viewer.html"), "same_saved_atom_program_and_trace": True, "sha256": sha(viewer), "delivery_receipt": str(out), "r6_passed": report["passed"], "user_visual_acceptance": "pending"}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"delivery": str(out), "viewer": str(viewer), "manifest_bytes_verified": True, "r6_passed": report["passed"], "r6_failure_counts": summary["r6_failure_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
