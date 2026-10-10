"""Reproducible small-slice independent audit, not a full Shor benchmark."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import time
import tracemalloc
import zipfile

from . import make_scenario, validate
from .checker import _hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Report directory")
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    from na_pipeline.device import default_device
    from na_pipeline.qec import build_two_block_slice
    from na_pipeline.backend import compile_physical
    from na_pipeline.runtime import run
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    code_root = Path(__file__).resolve().parents[1]
    def source_hashes():
        return {str(path.relative_to(code_root)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest() for path in sorted(code_root.rglob("*.py"))}
    initial_sources = source_hashes()
    phases = []
    def stage(name, fn):
        tracemalloc.start()
        start = time.perf_counter()
        cpu = time.process_time()
        try:
            value = fn()
            _, peak = tracemalloc.get_traced_memory()
            phases.append({"stage": name, "wall_seconds": time.perf_counter()-start, "cpu_seconds": time.process_time()-cpu, "python_allocated_peak_bytes": peak})
            return value
        finally:
            tracemalloc.stop()
    device = stage("device", default_device)
    physical = stage("physical_structure", lambda: build_two_block_slice(rounds=args.rounds))
    atom = stage("placement_routing_schedule", lambda: compile_physical(physical, device))
    reports = {}
    traces = {}
    bundle = {"device.json": device, "physical_program.json": physical, "atom_program.json": atom}
    for value in (0, 1):
        scenario = make_scenario(atom, value=value, artifact_id=f"R6/two-block/fake-{value}")
        trace = stage(f"runtime_fake_{value}", lambda: run(atom, scenario, device))
        report = stage(f"validation_fake_{value}", lambda: validate(atom, device, trace, physical))
        reports[f"fake-{value}"] = report
        traces[f"fake-{value}"] = {"sha256": _hash(trace), "stats": trace["stats"], "scenario_sha256": _hash(scenario)}
        bundle[f"scenario-fake-{value}.json"] = scenario
        bundle[f"trace-fake-{value}.json"] = trace
    sources = source_hashes()
    evidence = {"scope": "real R1/R3/R4/R5 artifacts; two Surface-17 blocks; explicit uniform fake paths", "fixture": False, "rounds": args.rounds, "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(), "host": platform.node()}, "resource_budget": {"execution_host": "local", "parallel_workers": 1, "search_budget": "producer default deterministic finite route candidates", "scope_limit": "small T010 slice only; no full Shor/QEC expansion", "memory_measurement": "tracemalloc Python allocations, not RSS", "timing_note": "instrumented once; no cold/hot speedup claim"}, "phases": phases, "input_hashes": {"device": _hash(device), "physical_program": _hash(physical), "atom_program": _hash(atom)}, "source_file_sha256": sources, "traces": traces, "reports": {key: {"passed": value["passed"], "scoped_pass": value["scoped_pass"], "failure_count": len(value["failures"]), "unverified": value["unverified"], "metrics": value["metrics"]} for key,value in reports.items()}, "user_visual_acceptance": "pending", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False}
    evidence["source_files_unchanged_during_run"] = initial_sources == sources
    evidence["source_file_sha256_before"] = initial_sources
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / "two-block-inputs.zip"
    export_start = time.perf_counter()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as saved:
        for name, value in bundle.items():
            saved.writestr(name, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    evidence["input_archive"] = {"path": archive.name, "sha256": sha256(archive.read_bytes()).hexdigest(), "bytes": archive.stat().st_size, "members_sha256": {name: _hash(value) for name,value in bundle.items()}, "export_wall_seconds": time.perf_counter()-export_start}
    for name, value in {**reports, "benchmark": evidence}.items():
        (args.output / f"{name}.json").write_bytes((json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n").encode("utf-8"))
    print(json.dumps(evidence["reports"], indent=2, ensure_ascii=False))
    return 0 if all(r["passed"] for r in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
