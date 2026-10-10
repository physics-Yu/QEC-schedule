"""Portable CI entry: dependency-free unittest suites, logs and exact code identity."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from na_pipeline.cli import code_identity, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/environment/R7/checks")
    args = parser.parse_args()
    suites = args.suite or ["tooling"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = args.out / stamp
    folder.mkdir(parents=True)
    report = {"schema_version": "na-checks/0.1.0", "created_at_utc": stamp, "python": sys.version, "source_byte_sha256": code_identity(), "suites": [], "scope": "author_engineering_selftest; not user visual acceptance"}
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT), PYTHONIOENCODING="utf-8")
    for suite in suites:
        if suite not in {p.name for p in (ROOT / "tests").iterdir() if p.is_dir()}:
            raise ValueError(f"Unknown test suite: {suite}")
        command = [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests" / suite), "-v"]
        started = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True)
        (folder / f"{suite}.log").write_bytes(result.stdout + result.stderr)
        item = {"suite": suite, "command": command, "returncode": result.returncode, "wall_seconds": time.monotonic() - started, "log": f"{suite}.log"}
        report["suites"].append(item)
        print(json.dumps(item, ensure_ascii=False))
    report["passed"] = all(s["returncode"] == 0 for s in report["suites"])
    write_json(folder / "checks.json", report)
    print(json.dumps({"report": str(folder / "checks.json"), "passed": report["passed"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
