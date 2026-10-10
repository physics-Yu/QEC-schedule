"""Verify saved manifest bytes and summarize the bounded R7 delivery evidence."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/environment/R7"


def read(path):
    return json.loads(path.read_bytes().decode("utf-8"))


def main():
    runs = {}
    for name in ("delivery-zero", "delivery-one"):
        folder = BASE / name
        manifest = read(folder / "manifest.json")
        for key, item in manifest["files"].items():
            path = folder / item["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["byte_sha256"]:
                raise ValueError(f"Byte identity changed: {name}/{key}")
        atom, trace, report = (read(folder / f"{p}.json") for p in ("atom", "trace", "validation"))
        assert manifest["status"] == "completed" and manifest["source_snapshot_stable"] is True
        assert manifest["fixture"] is False and report["passed"] is True
        runs[name] = {"manifest": str((folder / "manifest.json").relative_to(ROOT)), "all_manifest_byte_hashes_match": True, "source_snapshot_stable": True, "r6_passed": report["passed"], "r6_failure_count": len(report["failures"]), "r6_unverified": report["unverified"], "atom_count": atom["stats"]["atom_count"], "physical_ops": atom["stats"]["physical_op_count"], "actions": len(atom["actions"]), "duration_us": trace["stats"]["duration_us"], "executed_actions": trace["stats"]["executed_action_count"], "skipped_actions": trace["stats"]["skipped_action_count"], "result_values": dict(Counter(str(r["value"]) for r in trace["results"].values())), "cli_stage_wall_seconds": manifest["stage_wall_seconds"], "r4_stage_wall_seconds": atom["stats"].get("stage_wall_seconds"), "viewer_byte_sha256": manifest["files"]["viewer"]["byte_sha256"]}
    wheel = BASE / "wheel/na_pipeline-0.1.0-py3-none-any.whl"
    job = read(BASE / "jobs/delivery-zero/status.json")
    assert job["status"] == "completed" and job["returncode"] == 0
    result = {"schema_version": "r7-delivery/0.1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(), "kb_revision": "kb-0004", "interface_document": "IF-MVP-001/0.2.1-draft", "scope": "two_Surface17_real_software_chain_fake_results", "runs": runs, "background_job": job, "wheel_byte_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "author_tests": "artifacts/environment/R7/checks/20261006T093529863978Z/checks.json", "browser_engineering_check": "blocked_by_file_protocol_policy_not_attempted_elsewhere", "user_visual_acceptance": "pending", "quantum_state_simulated": False, "hardware_executed": False, "full_shor_completed": False, "server_migration_performed": False}
    path = BASE / "delivery-receipt.json"
    path.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"path": str(path), "byte_hashes_verified": True, "zero_and_one_r6_passed": True, "background_job_completed": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
