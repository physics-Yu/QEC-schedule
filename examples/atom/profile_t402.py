"""One complete representative compile; launch via the R7 budget supervisor.

No runtime traces are produced. Use separate processes for traced/untraced runs
so their process peak RSS values remain meaningfully separated.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import tracemalloc

from na_pipeline.backend import compile_physical
from na_pipeline.device import default_device
from na_pipeline.qec import build_two_block_slice, iter_physical_ops


def rss():
    if os.name == "nt":
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (k, ctypes.c_size_t) for k in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage",
                "PeakPagefileUsage", "PrivateUsage")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return {"current_rss_bytes": counters.WorkingSetSize, "peak_rss_bytes": counters.PeakWorkingSetSize,
                "source": "Windows GetProcessMemoryInfo working set; full process"}
    import resource
    scale = 1 if sys.platform == "darwin" else 1024
    return {"peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale,
            "source": "getrusage RUSAGE_SELF ru_maxrss; full process"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", required=True, type=int, choices=[1, 2, 5])
    parser.add_argument("--tracemalloc", action="store_true")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    record = {"schema_version": "R4CostProfile/0.1.0", "task_id": "T402", "kb_revision": "kb-0004",
              "rounds": args.rounds, "complete": False, "fixture": False,
              "execution_kind": "compile_plan", "quantum_state_simulated": False,
              "hardware_executed": False, "loss_enabled": False,
              "tracemalloc_enabled": args.tracemalloc,
              "budget": {"wall_seconds": 300, "root_process_rss_bytes": 2*1024**3, "threads": 1,
                         "enforcement": "R7 jobs supervisor; sampled process-tree RSS, not a kernel hard cap"},
              "python": sys.version, "executable": sys.executable, "host": platform.node(),
              "rss_before": rss(), "phases_wall_seconds": {},
              "unverified": ["no runtime path or independent acceptance executed for this performance-only run",
                             "one observation per mode and rounds; no speedup significance or global optimum claim"]}
    if args.tracemalloc:
        tracemalloc.start()
    try:
        tick = time.perf_counter()
        device, program = default_device(), build_two_block_slice(rounds=args.rounds)
        record["phases_wall_seconds"]["structure_construction"] = time.perf_counter() - tick
        record["structure"] = {"template_count": len(program["templates"]),
            "stored_template_ops": sum(len(t["body"]) for t in program["templates"].values()),
            "body_nodes": len(program["body"]), "template_invocations": sum(n.get("repeat", 1) for n in program["body"] if n["kind"] == "call"),
            "structured_json_bytes": len(json.dumps(program, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))}
        tick = time.perf_counter()
        count = 0; stream = sha256()
        for operation in iter_physical_ops(program):
            count += 1
            stream.update(json.dumps(operation, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        record["phases_wall_seconds"]["standalone_stream_and_hash"] = time.perf_counter() - tick
        record["expanded_count"], record["operation_stream_sha256"] = count, stream.hexdigest()
        tick = time.perf_counter()
        atom = compile_physical(program, device)
        record["phases_wall_seconds"]["compile_including_its_own_expansion"] = time.perf_counter() - tick
        record["compiler_stats"], record["input_hashes"] = atom["stats"], atom["input_hashes"]
        assert atom["complete"] and atom["stats"]["physical_op_count"] == count
        work = Counter()
        for action in atom["actions"]:
            work[action["kind"]] += action["t_end_us"] - action["t_start_us"]
        record["action_work_us"] = dict(work)
        record["rss_after_compile"] = rss()
        # Stream to a temporary file in the allowed output directory, then let
        # NamedTemporaryFile close/remove that exact file; no retained full plan.
        tick = time.perf_counter(); digest = sha256(); byte_count = 0
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with tempfile.NamedTemporaryFile(dir=out.parent, prefix="r4-profile-", suffix=".tmp", delete=True) as tmp:
            for chunk in encoder.iterencode(atom):
                raw = chunk.encode("utf-8"); tmp.write(raw); digest.update(raw); byte_count += len(raw)
            tmp.flush()
        record["phases_wall_seconds"]["stream_json_hash_and_buffered_file_output"] = time.perf_counter() - tick
        record["output"] = {"bytes": byte_count, "sha256": digest.hexdigest(), "retained": False,
                            "durability": "buffered write/flush measured; no fsync or physical-disk latency claim"}
        record["complete"] = True
    except Exception as exc:
        record["failure"] = {"type": type(exc).__name__, "message": str(exc), "code": getattr(exc, "code", None)}
        raise
    finally:
        record["rss_final"] = rss()
        if args.tracemalloc:
            current, peak = tracemalloc.get_traced_memory()
            record["python_traced_bytes"] = {"current": current, "peak": peak, "scope": "tracked Python allocations, not RSS"}
            tracemalloc.stop()
        record["wall_seconds"] = time.perf_counter() - started
        root = Path(__file__).resolve().parents[2]
        record["code_sha256"] = {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
                                for folder in ("device", "qec", "backend")
                                for p in sorted((root / "src/na_pipeline" / folder).glob("*.py"))}
        record["code_sha256"]["examples/atom/profile_t402.py"] = sha256(Path(__file__).read_bytes()).hexdigest()
        out.write_bytes((json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print(json.dumps({"path": str(out), "complete": record["complete"], "wall_seconds": record["wall_seconds"],
                          "peak_rss_bytes": record["rss_final"]["peak_rss_bytes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
