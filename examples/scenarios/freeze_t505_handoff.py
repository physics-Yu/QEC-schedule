"""Freeze a read-only candidate and test those exact bytes before R7 dispatch."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT/"knowledge/roles/R5/evidence/T505"/("full-driver-freeze-"+stamp)
    out.mkdir(parents=True, exist_ok=False)
    selected = set((ROOT/"src/na_pipeline").rglob("*.py"))
    selected.update((ROOT/"tests/runtime").glob("*.py"))
    selected.update((ROOT/"third_party/enola/upstream/enola").rglob("*.py"))
    names = ["AGENTS.md", "pyproject.toml", "third_party/enola/pin.json", "third_party/enola/requirements.lock",
        "third_party/enola/dependency-sources.json", "third_party/enola/upstream/LICENSE",
        "examples/scenarios/run_full_shor_session.py", "examples/scenarios/T505-full-shor-job.json",
        "examples/scenarios/T505-exhaustion-job.json", "examples/scenarios/T505-reject-then-accept.json",
        "examples/scenarios/T505-attempts-exhausted.json", "examples/atom/t405/resource-world-server-v1/world.json.gz",
        "knowledge/roles/R5/dag-scheduler-example.json", "knowledge/interfaces/hierarchical-dag-contract.md",
        "knowledge/interfaces/server-job-coordination.md", "knowledge/charter.md", "knowledge/governance.md",
        "knowledge/roles/R1/preinitialized-interface.md", "knowledge/roles/R2/logical-dag-interface.md",
        "knowledge/roles/R3/physical-dag-interface.md", "knowledge/roles/R4/hierarchical-interface.md",
        "knowledge/roles/R4/physical-strategy-interface.md", "knowledge/roles/R6/hierarchical-interface.md",
        "knowledge/roles/R7/t704-interface.md", "knowledge/roles/R8/factory-phase-obligations.json",
        "knowledge/roles/R3/T304-retry-consumer-review.md", "knowledge/roles/R3/evidence/retry-consumption-20261007-v1/review.json",
        "knowledge/roles/R2/pipeline-consumption-evidence.json"]
    selected.update(ROOT/n for n in names)
    selected.update((ROOT/"knowledge/roles/R5").glob("*-interface.md"))
    selected.add(ROOT/"knowledge/roles/R5/full-shor-continuation.md")
    raw = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in sorted(selected)}
    manifest = {name: {"sha256": sha256(value).hexdigest(), "bytes": len(value)} for name, value in raw.items()}
    for name, value in raw.items():
        target = out/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(value)
    changed = [n for n, value in raw.items() if (ROOT/n).read_bytes() != value]
    if changed: raise RuntimeError("LIVE_SOURCE_CHANGED_DURING_FREEZE: "+str(changed))
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(out/"src")+os.pathsep+str(out)+os.pathsep+str(out/"tests/runtime"),
                       PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    started = time.perf_counter()
    test = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests/runtime", "-v"],
                          cwd=out, env=environment, capture_output=True, text=True, encoding="utf-8")
    (out/"author-tests.txt").write_bytes((test.stdout+test.stderr).encode("utf-8"))
    drift = [n for n, item in manifest.items() if sha256((out/n).read_bytes()).hexdigest() != item["sha256"]]
    report = {"schema_version": "R5-full-driver-freeze/0.1", "owner": "R5", "created_utc": stamp,
        "status": "frozen_author_checked_candidate" if test.returncode == 0 and not drift else "candidate_check_failed",
        "kb_revision": "kb-0006", "plan_revision": "plan-0008", "files": manifest,
        "author_tests": {"returncode": test.returncode, "wall_seconds": time.perf_counter()-started,
                         "log": "author-tests.txt", "log_sha256": sha256((out/"author-tests.txt").read_bytes()).hexdigest()},
        "frozen_source_drift": drift, "live_source_drift_after_tests": [n for n, item in manifest.items() if sha256((ROOT/n).read_bytes()).hexdigest() != item["sha256"]],
        "interpreter": {"path": sys.executable, "version": sys.version},
        "dispatch_owner": "R7", "new_server_job_started": False, "full_program_passed": False,
        "limitations": ["R7 must take its own complete deployable snapshot and fresh resource preflight",
                        "R4 raw Enola evidence and immutable strategy import interfaces may require a newer reviewed candidate",
                        "R2/R3 source reviews do not replace actual retry or full Shor execution qualification"]}
    (out/"freeze-manifest.json").write_bytes(json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    handoff = {"schema_version": "R5-server-dispatch-request/0.2", "owner": "R5", "dispatcher": "R7",
        "supersedes_without_overwriting": "knowledge/roles/R5/T505-server-dispatch-request.json",
        "freeze_manifest": str((out/"freeze-manifest.json").relative_to(ROOT)),
        "freeze_manifest_sha256": sha256((out/"freeze-manifest.json").read_bytes()).hexdigest(),
        "required_runtime_source_hashes": {n: m["sha256"] for n, m in manifest.items() if n.startswith("src/na_pipeline/runtime/")},
        "requests": [
            {"spec": "examples/scenarios/T505-full-shor-job.json", "input_files": ["examples/scenarios/run_full_shor_session.py", "examples/atom/t405/resource-world-server-v1/world.json.gz", "examples/scenarios/T505-reject-then-accept.json"]},
            {"spec": "examples/scenarios/T505-exhaustion-job.json", "input_files": ["examples/scenarios/run_full_shor_session.py", "examples/atom/t405/resource-world-server-v1/world.json.gz", "examples/scenarios/T505-attempts-exhausted.json"], "dependency": "R4 static import and compatible positive-run compilation artifacts"}],
        "author_test_returncode": test.returncode, "frozen_source_stable": not drift,
        "live_source_drift_after_tests": report["live_source_drift_after_tests"], "full_program_passed": False,
        "existing_job_to_preserve": "20261006T152948108065Z-r5-live-factory-complete-protocol"}
    (ROOT/"knowledge/roles/R5/T505-server-dispatch-request-v2.json").write_bytes(json.dumps(handoff, ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps({"freeze": str(out.relative_to(ROOT)), "returncode": test.returncode, "frozen_drift": drift,
                      "live_drift": report["live_source_drift_after_tests"], "tail": (test.stdout+test.stderr).splitlines()[-4:]}, ensure_ascii=False))
    if test.returncode or drift: raise SystemExit(test.returncode or 1)


if __name__ == "__main__": main()
