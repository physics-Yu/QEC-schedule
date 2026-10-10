"""Sequential isolated cost samples, using R7's public budget launcher."""
import json
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time


def read_status(path):
    if os.name != "nt":
        return json.loads(path.read_text(encoding="utf-8"))
    # A reader must allow FILE_SHARE_DELETE while the supervisor atomically
    # replaces status.json. Ordinary Python open can briefly block os.replace.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "Unable to read job status")
    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        return json.load(stream)


parser = argparse.ArgumentParser()
parser.add_argument("--out-dir", default="examples/atom/profiles/T402")
parser.add_argument("--rounds", nargs="+", type=int, choices=[1, 2, 5], default=[1, 2, 5])
parser.add_argument("--modes", nargs="+", choices=["plain", "traced"], default=["plain", "traced"])
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
base = root / args.out_dir
base.mkdir(parents=True, exist_ok=True)
for rounds in args.rounds:
    for mode in args.modes:
        traced = mode == "traced"
        label = f"rounds-{rounds}-{'traced' if traced else 'plain'}"
        jobdir = base / (label + "-job")
        if jobdir.exists():
            raise RuntimeError(f"Preserve existing evidence; choose a new run directory before rerunning: {jobdir}")
        command = [sys.executable, str(root / "scripts/jobs.py"), "launch", "--job-dir", str(jobdir),
                   "--wall-seconds", "300", "--memory-gib", "2", "--parallelism", "1",
                   "--search-expansions", "1000000", "--", sys.executable,
                   str(root / "examples/atom/profile_t402.py"), "--rounds", str(rounds),
                   "--out", str(base / (label + ".json"))]
        if traced:
            command.append("--tracemalloc")
        launched = subprocess.run(command, cwd=root, text=True, encoding="utf-8", capture_output=True)
        if launched.returncode:
            raise RuntimeError(launched.stderr or launched.stdout)
        print(launched.stdout.strip(), flush=True)
        # Supervisor alone enforces wall/memory limits and retains diagnostics.
        while True:
            statusfile = jobdir / "status.json"
            if statusfile.exists():
                state = read_status(statusfile)
                if state.get("status") not in {"dispatched_not_completed", "running", "starting"}:
                    print(json.dumps({"case": label, "supervisor": state}, ensure_ascii=False), flush=True)
                    if state.get("status") != "completed":
                        raise RuntimeError(f"Profile did not complete: {label}")
                    break
            time.sleep(.2)
