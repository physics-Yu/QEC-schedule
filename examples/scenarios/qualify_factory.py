"""Save T502 state-machine fixtures; never label them a 15-to-1 execution."""

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/runtime"))

from test_factory import accepted_fixture, rejected_fixture, specification
from na_pipeline.runtime import FactoryLedger


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    out = ROOT / "examples/scenarios/factory_protocol_fixture"
    evidence_dir = ROOT / "knowledge/roles/R5/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    test = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests/runtime", "-p", "test_factory.py", "-v"],
                          cwd=ROOT, env=dict(os.environ, PYTHONPATH="src;." if os.name == "nt" else "src:.", PYTHONIOENCODING="utf-8"),
                          capture_output=True, text=True, encoding="utf-8", check=False)
    (evidence_dir / "factory-tests.log").write_bytes((test.stdout+test.stderr).encode("utf-8"))
    report = {"schema_version": "R5FactoryQualification/0.1", "fixture": True,
              "timestamp_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(),
              "interpreter": sys.executable, "host": platform.node(), "kb_revision": "kb-0004",
              "protocol_contract": "R5-FACTORY-001/0.1.1-draft", "consumed_R3_contract": "R3-FACTORY-IF-001/0.2.0-draft",
              "test_exit_code": test.returncode, "physical_factory_executed": False,
              "production_integration": "not_implemented", "R6_independent_acceptance": "pending", "user_visual_acceptance": "pending",
              "boundary": "Minimal physical witnesses test protocol states only; not injection, 15-to-1 or T consumption correctness.",
              "artifacts": {}, "source_hashes": {}}
    if not test.returncode:
        for label, builder in (("accept_consume", accepted_fixture), ("reject_retry", rejected_fixture)):
            program, trace, events = builder()
            ledger = FactoryLedger(program, trace, specification())
            for event in events:
                ledger.apply(event)
            for kind, value in (("atom_program", program), ("trace", trace), ("specification", specification()),
                                ("boundaries", events), ("ledger", ledger.snapshot())):
                name = f"{label}_{kind}"
                report["artifacts"][name] = write(out / f"{name}.json", value)
    paths = [*ROOT.glob("src/na_pipeline/runtime/*.py"), *ROOT.glob("tests/runtime/*.py"), Path(__file__).resolve()]
    report["source_hashes"] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    write(evidence_dir / "factory-qualification.json", report)
    print(json.dumps({"test_exit_code": test.returncode, "fixture": True, "physical_factory_executed": False,
                      "evidence": "knowledge/roles/R5/evidence/factory-qualification.json", "artifacts": len(report["artifacts"])}, ensure_ascii=False))
    return test.returncode


if __name__ == "__main__":
    raise SystemExit(main())
