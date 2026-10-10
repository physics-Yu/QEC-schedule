"""Author checks and pinned evidence for the T504 controller; no new compilation."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "knowledge/roles/R5/evidence/T504"


def hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [*ROOT.glob("src/na_pipeline/runtime/*.py"), *ROOT.glob("tests/runtime/*.py")]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = hashes()
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests/runtime", "-v"], cwd=ROOT,
                           env=dict(os.environ, PYTHONPATH="src;." if os.name == "nt" else "src:.", PYTHONIOENCODING="utf-8"),
                           capture_output=True, text=True, encoding="utf-8")
    log = tests.stdout+tests.stderr
    (OUT / "unit-tests.log").write_bytes(log.encode("utf-8"))
    match = re.search(r"Ran (\d+) tests in ([0-9.]+)s", log)
    report = {"schema_version": "R5ControllerQualification/0.1", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "kb_revision": "kb-0005", "plan_revision": "plan-0007", "python": sys.version, "executable": sys.executable,
              "host": platform.node(), "test_count": int(match[1]) if match else None,
              "unittest_seconds": float(match[2]) if match else None, "exit_code": tests.returncode,
              "source_hashes_before": before, "source_hashes_after": hashes(),
              "user_visual_acceptance": "pending", "quantum_state_simulated": False, "hardware_executed": False,
              "native_evidence": {}, "claim": "Author runtime checks; native integration qualifications remain separately scoped."}
    report["sources_stable"] = report["source_hashes_before"] == report["source_hashes_after"]
    for rel in ("examples/scenarios/T504-final-observed/report.json", "examples/scenarios/T504-final-observed/run.json",
                "examples/scenarios/T504-final-observed/validation.json", "examples/scenarios/T504-final-observed/enola-evidence.json.gz",
                "knowledge/roles/R6/evidence/T604/summary.json", "knowledge/roles/R6/evidence/T604/run-report.json"):
        path = ROOT / rel
        if path.exists(): report["native_evidence"][rel] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    native_path = ROOT / "examples/scenarios/T504-final-observed/run.json"
    if native_path.exists():
        from na_pipeline.frontend import build_t000_program
        native = json.loads(native_path.read_text(encoding="utf-8"))
        report["current_R2_input_matches_saved_execution_input"] = native["encoded_program"] == build_t000_program(rounds=3)
        report["frontend_source_sha256_at_handoff"] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("src/na_pipeline/frontend/*.py")}
        report["frontend_pin_scope"] = "Current handoff source, separately checked to regenerate the identical saved EncodedLogicalProgram; not claimed as a start-of-execution file capture."
    (OUT / "qualification.json").write_bytes((json.dumps(report, ensure_ascii=False, indent=2)+"\n").encode("utf-8"))
    print(json.dumps({"test_count": report["test_count"], "exit_code": tests.returncode, "sources_stable": report["sources_stable"]}))
    return tests.returncode


if __name__ == "__main__": raise SystemExit(main())
