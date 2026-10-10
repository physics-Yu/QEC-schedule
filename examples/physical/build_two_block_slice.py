"""Reproduce R3's bounded T301 artifact and qualification evidence.

Run with Python >= 3.12 and PYTHONPATH=src from the repository root.
Writes only examples/physical and knowledge/roles/R3/evidence.
"""

from collections import Counter
from hashlib import sha256
from itertools import islice
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import tracemalloc
import unittest

from na_pipeline.qec import build_two_block_slice, iter_physical_ops

ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256(data).hexdigest()


def main():
    if sys.version_info < (3, 12):
        raise RuntimeError("Python >= 3.12 required")
    started = time.perf_counter()
    program = build_two_block_slice()
    operations = list(iter_physical_ops(program))
    path = ROOT / "examples/physical/two_block_slice.json"
    artifact_hash = write_json(path, program)
    output = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests/qec"))
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    evidence_dir = ROOT / "knowledge/roles/R3/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "unittest.txt").write_bytes(output.getvalue().encode("utf-8"))
    large = build_two_block_slice(100_000_000)
    tracemalloc.start()
    prefix = list(islice(iter_physical_ops(large), 200))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    source_files = sorted((ROOT / "src/na_pipeline/qec").glob("*.py"))
    source_files += sorted((ROOT / "tests/qec").glob("*.py"))
    source_files.append(Path(__file__).resolve())
    probe = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    evidence = {
        "schema_version": "R3Qualification/0.1.0", "task_id": "T301", "kb_revision": "kb-0003",
        "date": "2026-10-06", "timezone": "Asia/Shanghai", "producer": "R3",
        "scope": "author_module_qualification", "independent_validation": "pending",
        "user_visual_acceptance": "pending", "quantum_state_simulated": False,
        "hardware_executed": False, "noise_simulated": False, "fixture": False,
        "environment": {"python": sys.version, "executable": sys.executable,
                        "host": platform.node(), "os": platform.platform(),
                        "dependencies": "Python standard library only",
                        "git_head": probe.stdout.strip() if probe.returncode == 0 else None,
                        "git_head_note": "source hashes bind uncommitted shared-workspace code"},
        "budget": {"workload": "34 qubits; rounds=1; algebraic checks and lazy prefix only",
                   "parallel_workers": 1, "search": "no placement/routing search in R3",
                   "full_shor_compilation": False},
        "artifact": {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": artifact_hash,
                     "size_bytes": path.stat().st_size},
        "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest() for p in source_files},
        "tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                  "passed": result.wasSuccessful(), "log": "knowledge/roles/R3/evidence/unittest.txt"},
        "counts": {"qubits": len(program["qubits"]), "templates": len(program["templates"]),
                   "calls": len(program["body"]), "operations": len(operations),
                   "kinds": dict(Counter(op["kind"] for op in operations)),
                   "gates": dict(Counter(op["params"]["name"] for op in operations if op["kind"] == "gate")),
                   "conditional_ops": sum(op["condition"] is not None for op in operations),
                   "unique_results": len({bit for op in operations for bit in op["writes"]})},
        "lazy_prefix": {"rounds_each_side": 100_000_000, "consumed_operations": len(prefix),
                        "tracemalloc_peak_bytes": peak, "scope": "expansion allocations only",
                        "stored_templates": len(large["templates"]), "stored_calls": len(large["body"]),
                        "complete_expansion": False},
        "elapsed_wall_seconds": time.perf_counter() - started,
        "unverified": program["metadata"]["unverified"] + ["independent_R6_validation", "R4_R5_R6_R7_chain", "user_visual_acceptance"],
    }
    write_json(evidence_dir / "qualification.json", evidence)
    invalid = build_two_block_slice()
    invalid["artifact_id"] = "r3-rejected-aliased-binding"
    invalid["provenance"]["fixture"] = True
    invalid["body"][0]["bindings"]["d0"] = "control/d1"
    invalid["metadata"]["expected_error"] = "BAD_BINDINGS"
    write_json(ROOT / "examples/physical/rejected_aliased_binding.json", invalid)
    print(json.dumps({"artifact": str(path), "tests_passed": result.wasSuccessful(),
                      "tests": result.testsRun, "counts": evidence["counts"],
                      "elapsed_seconds": evidence["elapsed_wall_seconds"],
                      "lazy_prefix_peak_bytes": peak}, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
