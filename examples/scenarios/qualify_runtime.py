"""Reproduce T501 authors' tests and real R1/R3/R4 -> R5 -> R6 evidence."""

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from na_pipeline.backend import compile_physical
from na_pipeline.device import default_device
from na_pipeline.qec import build_two_block_slice
from na_pipeline.runtime import run
from na_pipeline.validation import validate, make_scenario


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "examples/scenarios/two_block_runtime"
EVIDENCE = ROOT / "knowledge/roles/R5/evidence"


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def source_hashes():
    paths = [*ROOT.glob("src/na_pipeline/**/*.py"), *ROOT.glob("tests/runtime/*.py"), Path(__file__).resolve(), ROOT / "examples/scenarios/make_scenario.py"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "canonical_sha256": content_hash(obj)}


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    before = source_hashes()
    test_started = time.perf_counter()
    test = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests/runtime", "-v"],
                          cwd=ROOT, env=dict(os.environ, PYTHONPATH="src;." if os.name == "nt" else "src:.", PYTHONIOENCODING="utf-8"),
                          capture_output=True, text=True, encoding="utf-8", check=False)
    (EVIDENCE / "unit-tests.log").write_bytes((test.stdout+test.stderr).encode("utf-8"))
    evidence = {"schema_version": "R5Qualification/0.1", "kb_revision": "kb-0004",
                "contract": "IF-MVP-001/0.2.1-draft", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "interpreter": sys.executable, "python_version": platform.python_version(), "host": platform.node(),
                "unit_test_exit_code": test.returncode, "unit_test_wall_seconds": time.perf_counter()-test_started,
                "budget": {"scope": "complete two-block T010 slice only", "parallelism": 1, "max_ops": 1000,
                           "full_shor_started": False, "server_used": False},
                "source_hashes_before": before, "artifacts": {}, "runs": {}}
    if test.returncode:
        write(EVIDENCE / "qualification.json", evidence)
        return test.returncode
    started = time.perf_counter()
    device, physical = default_device(), build_two_block_slice(rounds=1)
    evidence["build_wall_seconds"] = time.perf_counter()-started
    started = time.perf_counter()
    atom = compile_physical(physical, device, max_ops=1000)
    evidence["compile_wall_seconds"] = time.perf_counter()-started
    for name, obj in (("device", device), ("physical_program", physical), ("atom_program", atom)):
        evidence["artifacts"][name] = write(OUT / f"{name}.json", obj)
    for value in (0, 1):
        scenario = make_scenario(atom, value=value)
        trace = run(atom, scenario, device)
        report = validate(atom, device, trace=trace, physical_program=physical)
        evidence["runs"][str(value)] = {"stats": trace["stats"], "passed": report["passed"], "checks": report["checks"],
                                        "failure_codes": dict(Counter(f["code"] for f in report["failures"])),
                                        "unverified": report["unverified"], "input_hashes": trace["input_hashes"]}
        for name, obj in (("scenario", scenario), ("trace", trace), ("validation", report)):
            key = f"{name}_{value}"
            evidence["artifacts"][key] = write(OUT / f"{key}.json", obj)
    evidence["source_hashes_after"] = source_hashes()
    evidence["code_changed_during_run"] = before != evidence["source_hashes_after"]
    evidence["engineering_acceptance"] = "pending_R0" if all(r["passed"] for r in evidence["runs"].values()) and not evidence["code_changed_during_run"] else "pending_integration_fix"
    evidence["user_visual_acceptance"] = "pending"
    write(EVIDENCE / "qualification.json", evidence)
    print(json.dumps({"evidence": "knowledge/roles/R5/evidence/qualification.json", "unit_tests": "passed",
                      "runs": {k: {"passed": v["passed"], "failure_codes": v["failure_codes"], "stats": v["stats"]} for k, v in evidence["runs"].items()},
                      "code_changed_during_run": evidence["code_changed_during_run"]}, ensure_ascii=False))
    return 0 if evidence["engineering_acceptance"] == "pending_R0" else 2


if __name__ == "__main__":
    raise SystemExit(main())
