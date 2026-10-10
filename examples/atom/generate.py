"""Reproduce R4 owned examples using the actual R1/R3 public producers.

Run with PYTHONPATH=src. --with-runtime additionally saves both fake paths and
R6 reports; missing upstream implementations fail explicitly.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import time
import tracemalloc

from na_pipeline.backend import CompilationError, compile_physical
from na_pipeline.device import default_device
from na_pipeline.qec import build_two_block_slice


def save(path, obj):
    raw = (json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path.name), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-runtime", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = Path(__file__).resolve().parent / "two_block_slice"
    out.mkdir(exist_ok=True)
    device, physical = default_device(), build_two_block_slice(rounds=1)
    tracemalloc.start()
    began = time.perf_counter()
    atom = compile_physical(physical, device)
    wall = time.perf_counter() - began
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    profile = {"fixture": False, "scope": "R4 actual two Surface-17 software artifact; no full Shor/hardware/quantum execution",
               "python": sys.version, "executable": sys.executable, "host": platform.node(),
               "platform": platform.platform(), "kb_revision": "kb-0004", "rounds": 1,
               "inputs": atom["input_hashes"], "budget": {"max_ops": None, "threads": 1,
               "route_candidates_per_segment": 7, "layout_candidates_per_cz": 4,
               "time_limit_seconds": None, "memory_limit_bytes": None,
               "budget_scope": "small T401 slice; complete input; no global search or full Shor job"},
               "compile_wall_seconds_with_tracemalloc": wall, "peak_traced_python_bytes": peak,
               "memory_measurement_scope": "Python traced allocations; not OS RSS or server quota",
               "stats": atom["stats"], "artifacts": [], "code_sha256": {}}
    # Hash exact sources consumed at run time, independent of untracked git state.
    folders = ["src/na_pipeline/device", "src/na_pipeline/qec", "src/na_pipeline/backend"]
    if args.with_runtime:
        folders += ["src/na_pipeline/runtime", "src/na_pipeline/validation"]
    for folder in folders:
        for file in sorted((root / folder).glob("*.py")):
            profile["code_sha256"][file.relative_to(root).as_posix()] = sha256(file.read_bytes()).hexdigest()
    profile["code_sha256"]["examples/atom/generate.py"] = sha256(Path(__file__).read_bytes()).hexdigest()
    for name, artifact in (("device.json", device), ("physical_program.json", physical), ("atom_program.json", atom)):
        began = time.perf_counter()
        profile["artifacts"].append(save(out / name, artifact))
        profile.setdefault("output_wall_seconds", {})[name] = time.perf_counter() - began
    try:
        compile_physical(physical, device, max_ops=3)
    except CompilationError as exc:
        rejection = {**exc.to_dict(), "partial_complete": exc.partial_program["complete"],
                     "partial_physical_op_count": exc.partial_program["stats"]["physical_op_count"]}
        profile["artifacts"].append(save(out / "rejected_budget.json", rejection))
    else:
        raise AssertionError("Budget rejection was not raised")
    if args.with_runtime:
        from na_pipeline.runtime import make_scenario, run
        from na_pipeline.validation import validate
        profile["fake_paths"] = []
        for value in (0, 1):
            scenario = make_scenario(atom, value=value)
            trace = run(atom, scenario, device)
            report = validate(atom, device, trace=trace, physical_program=physical)
            for label, artifact in (("scenario", scenario), ("trace", trace), ("validation", report)):
                profile["artifacts"].append(save(out / f"{label}_{value}.json", artifact))
            profile["fake_paths"].append({"value": value, "passed": report["passed"],
                                           "failures": report["failures"], "unverified": report["unverified"],
                                           "stats": trace["stats"]})
        if not all(item["passed"] for item in profile["fake_paths"]):
            save(out / "profile.json", profile)
            raise AssertionError("Independent acceptance did not pass; inspect saved reports")
    else:
        profile["chain_status"] = "R4 compilation only; runtime and independent complete-chain acceptance not executed"
    save(out / "profile.json", profile)
    print(json.dumps({"directory": str(out), "physical_ops": atom["stats"]["physical_op_count"],
                      "atom_actions": atom["stats"]["action_count"], "atom_count": atom["stats"]["atom_count"],
                      "duration_us": atom["stats"]["duration_us"], "compile_wall_seconds": wall,
                      "peak_traced_python_bytes": peak, "with_runtime": args.with_runtime}, ensure_ascii=False))


if __name__ == "__main__":
    main()
