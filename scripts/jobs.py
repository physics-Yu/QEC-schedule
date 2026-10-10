"""Detached supervisor with durable logs, explicit budgets, and resumable CLI stages.

Only the managed process tree is terminated on a diagnostic budget. Memory is
sampled process-tree RSS, not a kernel reservation or hard cgroup/job quota.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_bytes((json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
    # A Windows status reader can briefly deny replacement while holding its
    # file handle. Do not terminate a healthy child for this reporting race.
    deadline = time.monotonic() + 5
    while True:
        try:
            os.replace(temp, path)
            break
        except PermissionError:
            if os.name != 'nt' or time.monotonic() >= deadline:
                raise
            time.sleep(.05)


def read(path):
    return json.loads(path.read_bytes().decode("utf-8"))


def rss_bytes(pid):
    if os.name != "nt":
        try:
            line = next(x for x in Path(f"/proc/{pid}/status").read_text().splitlines() if x.startswith("VmRSS:"))
            return int(line.split()[1]) * 1024
        except (OSError, StopIteration):
            return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(x, ctypes.c_size_t) for x in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        return None
    counter = Counters()
    counter.cb = ctypes.sizeof(counter)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    try:
        return counter.WorkingSetSize if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counter), counter.cb) else None
    finally:
        kernel.CloseHandle(handle)


def process_tree(root_pid):
    parents = {}
    if os.name == "nt":
        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            return {root_pid}
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
    else:
        for path in Path("/proc").glob("[0-9]*/status"):
            try:
                ppid = next(x for x in path.read_text().splitlines() if x.startswith("PPid:"))
                parents[int(path.parent.name)] = int(ppid.split()[1])
            except (OSError, StopIteration):
                continue
    descendants = {root_pid}
    while True:
        additional = {pid for pid, parent in parents.items() if parent in descendants} - descendants
        if not additional:
            return descendants
        descendants.update(additional)


def detached_kwargs():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_child(child):
    if child.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    else:
        os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            child.kill()
        else:
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


def supervisor(job_dir):
    spec = read(job_dir / "job.json")
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT), "PYTHONIOENCODING": "utf-8", "OMP_NUM_THREADS": str(spec["parallelism"]), "OPENBLAS_NUM_THREADS": str(spec["parallelism"]), "NA_SEARCH_EXPANSIONS": str(spec["search_expansions"])})
    started = time.monotonic()
    state = {"status": "starting", "supervisor_pid": os.getpid(), "started_at_utc": datetime.now(timezone.utc).isoformat(), "peak_root_rss_bytes": 0, "peak_tree_rss_bytes": 0, "root_rss_measured": False, "job": str(job_dir)}
    child = None
    try:
        with (job_dir / "stdout.log").open("ab", buffering=0) as stdout, (job_dir / "stderr.log").open("ab", buffering=0) as stderr:
            child = subprocess.Popen(spec["command"], cwd=spec["cwd"], env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, **detached_kwargs())
            state.update(status="running", child_pid=child.pid)
            while child.poll() is None:
                elapsed = time.monotonic() - started
                rss = rss_bytes(child.pid)
                samples = {pid: rss_bytes(pid) for pid in process_tree(child.pid)}
                tree_rss = sum(value for value in samples.values() if value is not None)
                state["peak_tree_rss_bytes"] = max(state["peak_tree_rss_bytes"], tree_rss)
                if rss is not None:
                    state["root_rss_measured"] = True
                    state["peak_root_rss_bytes"] = max(state["peak_root_rss_bytes"], rss)
                state.update(elapsed_seconds=elapsed, root_rss_bytes=rss, tree_rss_bytes=tree_rss, memory_scope="sampled_process_tree_rss", processes_measured=sum(v is not None for v in samples.values()), memory_unreadable_pids=[pid for pid, value in samples.items() if value is None])
                reason = "wall_seconds" if elapsed > spec["wall_seconds"] else "tree_rss_bytes" if tree_rss > spec["memory_gib"] * 1024 ** 3 else None
                if reason:
                    state.update(status="budget_exhausted_incomplete", budget_reason=reason)
                    stop_child(child)
                    break
                write(job_dir / "status.json", state)
                time.sleep(0.2)
            state.update(returncode=child.wait(), elapsed_seconds=time.monotonic() - started)
            if state["status"] == "running":
                state["status"] = "completed" if child.returncode == 0 else "failed_incomplete"
    except Exception as exc:
        if child is not None:
            stop_child(child)
        state.update(status="supervisor_failed_incomplete", error=str(exc))
    finally:
        state["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write(job_dir / "status.json", state)
    return 0 if state["status"] == "completed" else 1


def launch(args):
    if not all(math.isfinite(v) for v in (args.wall_seconds,args.memory_gib,args.parallelism,args.search_expansions)) or args.wall_seconds <= 0 or args.memory_gib <= 0 or args.parallelism < 1 or args.search_expansions < 0:
        raise ValueError("Wall/memory/parallelism must be positive and finite; declared search budget must be nonnegative")
    args.job_dir = args.job_dir.resolve()
    if args.job_dir.exists():
        raise ValueError("Job directory exists; use a fresh job directory. Resume pipeline with a new job and --resume CLI argument.")
    command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not command:
        raise ValueError("Explicit command required")
    args.job_dir.mkdir(parents=True)
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
    from na_pipeline.cli import code_identity
    spec = {"schema_version": "na-job/0.1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(), "cwd": str(ROOT), "command": command, "interpreter": sys.executable, "source_byte_sha256": code_identity(), "inputs": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.input}, "wall_seconds": args.wall_seconds, "memory_gib": args.memory_gib, "parallelism": args.parallelism, "search_expansions": args.search_expansions, "limits": {"wall": "enforced by supervisor; child terminated with incomplete status", "memory": "sampled process-tree RSS; not a kernel hard quota; unreadable processes recorded", "parallelism": "thread environment limits only; program must respect them", "search": "recorded and environment only; R4 search-budget API not implemented"}, "recovery": "For slice, start a NEW job with same --out and --resume. Compile checkpoint requires exact code/input/byte identity. Runtime and validation always rerun."}
    write(args.job_dir / "job.json", spec)
    write(args.job_dir / "status.json", {"status": "dispatched_not_completed"})
    with (args.job_dir / "supervisor.log").open("ab", buffering=0) as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_supervise", str(args.job_dir)], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **detached_kwargs())
    print(json.dumps({"status": "dispatched_not_completed", "supervisor_pid": child.pid, "job": str(args.job_dir)}, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="mode", required=True)
    p = subs.add_parser("launch")
    p.add_argument("--job-dir", type=Path, required=True)
    p.add_argument("--wall-seconds", type=float, required=True)
    p.add_argument("--memory-gib", type=float, required=True)
    p.add_argument("--parallelism", type=int, required=True)
    p.add_argument("--search-expansions", type=int, required=True)
    p.add_argument("--input", type=Path, action="append", default=[])
    p.add_argument("argv", nargs=argparse.REMAINDER)
    for mode in ("status", "_supervise"):
        p = subs.add_parser(mode)
        p.add_argument("job_dir", type=Path)
    args = parser.parse_args()
    if args.mode == "launch":
        return launch(args)
    if args.mode == "_supervise":
        return supervisor(args.job_dir)
    print(json.dumps(read(args.job_dir / "status.json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
