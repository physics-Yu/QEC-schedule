"""Read-only local/SSH resource probe; write a timestamped, byte-hashed report."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def command(argv, timeout=20):
    started = time.monotonic()
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return {"argv": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "wall_seconds": time.monotonic() - started}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "error": str(exc), "wall_seconds": time.monotonic() - started, "scope": "connectivity_or_probe_only"}


def local_resources():
    result = {"host": platform.node(), "platform": platform.platform(), "cpu_logical": os.cpu_count(), "python": sys.version, "executable": sys.executable}
    disk = shutil.disk_usage(ROOT)
    result["disk_bytes"] = dict(zip(("total", "used", "free"), disk))
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in ("total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended")]
        mem = MemoryStatus()
        mem.length = ctypes.sizeof(mem)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            raise OSError("GlobalMemoryStatusEx failed")
        result["memory_bytes"] = {"total": mem.total_phys, "available": mem.avail_phys}
        result["quota"] = {"status": "unknown", "note": "Physical free memory is not a per-user quota; no quota elevation attempted."}
    else:
        mem = {}
        if Path("/proc/meminfo").exists():
            mem = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()}
        result["memory_bytes"] = {"total": mem.get("MemTotal"), "available": mem.get("MemAvailable")}
        result["quota"] = {p: Path(p).read_text().strip() if Path(p).is_file() else "unknown" for p in ("/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current")}
        result["cpu_affinity_count"] = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    return result


def source_hashes():
    paths = [ROOT / "pyproject.toml", ROOT / "scripts/requirements-build.txt"]
    for directory in ("src", "viewer", "scripts"):
        paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file() and p.suffix in {".py", ".html", ".css", ".js", ".ps1"} and ".venv" not in p.parts)
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths)) if p.exists()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/environment/R7")
    parser.add_argument("--skip-ssh", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    local = local_resources()
    remote_script = "printf 'NA_PIPELINE_PROBE\\n'; uname -a; getconf _NPROCESSORS_ONLN; free -b; df -B1 .; command -v python3; python3 --version; command -v quota; quota -s; cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max 2>/dev/null"
    ssh = {"status": "not_attempted"} if args.skip_ssh else command(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1", "yyq@10.133.24.178", remote_script])
    connected = "NA_PIPELINE_PROBE" in ssh.get("stdout", "")
    available = local["memory_bytes"].get("available") or 0
    budget_gib = max(0.25, min(8, available / 2 / (1024 ** 3)))
    report = {"schema_version": "na-environment/0.1.0", "created_at_utc": stamp, "scope": "resource_probe_not_compile", "local": local, "ssh": ssh, "remote_connected": connected, "server_resources_verified": connected, "migration_performed": False, "full_job_started": False,
              "git": command(["git", "status", "--short"]), "git_revision": command(["git", "rev-parse", "HEAD"]), "source_byte_sha256": source_hashes(),
              "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
              "recommended_local_budget": {"stage": "representative_slice", "wall_seconds": 1800, "memory_gib": round(budget_gib, 2), "parallelism": min(4, local["cpu_logical"] or 1), "search_expansions": 1000000, "search_limit_enforcement": "requires_backend_support; recorded_only", "full_scope_policy": "Measure representative stages first; full Shor budget requires R0 sizing. Never truncate input.", "quota_limitation": "shared available resources; recommendations are not reserved allocations"}}
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"environment-{stamp}.json"
    path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    print(json.dumps({"report": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "remote_connected": connected, "local": local, "budget": report["recommended_local_budget"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
