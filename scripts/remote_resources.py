"""Read remote quotas with Python over SSH stdin; no writes on the host."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
import json, os, platform, resource, shutil, sys
from pathlib import Path
def read(path):
    try: return Path(path).read_text().strip()
    except OSError as exc: return {"unavailable": str(exc)}
result={"host":platform.node(),"python":sys.version,"cpu_count":os.cpu_count(),"cpu_affinity":sorted(os.sched_getaffinity(0)),"rlimit_as":resource.getrlimit(resource.RLIMIT_AS),"rlimit_nproc":resource.getrlimit(resource.RLIMIT_NPROC),"cgroup_membership":read('/proc/self/cgroup'),"meminfo":read('/proc/meminfo'),"disk":dict(zip(['total','used','free'],shutil.disk_usage('.'))),"limits":{p:read(p) for p in ['/sys/fs/cgroup/cpu.max','/sys/fs/cgroup/memory.max','/sys/fs/cgroup/memory.current','/sys/fs/cgroup/cpu/cpu.cfs_quota_us','/sys/fs/cgroup/cpu/cpu.cfs_period_us','/sys/fs/cgroup/memory/memory.limit_in_bytes','/sys/fs/cgroup/memory/memory.usage_in_bytes']},"quota_command_available":shutil.which('quota'),"migration_performed":False}
result['cpu_affinity_count']=len(result['cpu_affinity'])
membership=result['cgroup_membership']
if isinstance(membership,str):
    rel=next((line.split(':',2)[2] for line in membership.splitlines() if line.startswith('0::')),None)
    if rel is not None:
        base=Path('/sys/fs/cgroup'); current=base/rel.lstrip('/')
        result['cgroup_ancestor_limits']={}
        while current==base or base in current.parents:
            result['cgroup_ancestor_limits'][str(current)]={name:read(current/name) for name in ['cpu.max','memory.max','memory.high','pids.max']}
            if current==base:break
            current=current.parent
print(json.dumps(result))
'''
def probe():
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "yyq@10.133.24.178", "python3", "-"], input=SOURCE, capture_output=True, text=True, timeout=30, encoding="utf-8")
        remote = json.loads(result.stdout) if result.returncode == 0 else None
        return {"schema_version": "r7-server-preflight/0.1", "created_at_utc": stamp, "host": "yyq@10.133.24.178", "returncode": result.returncode, "connected": result.returncode == 0, "stderr": result.stderr, "remote": remote, "job_started": False, "allocation_reserved": False}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"schema_version": "r7-server-preflight/0.1", "created_at_utc": stamp, "host": "yyq@10.133.24.178", "connected": False, "error": str(exc), "job_started": False, "allocation_reserved": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    out = args.out or ROOT / 'scripts/outputs/T704/preflight' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    report = probe()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    remote = report.get('remote') or {}
    mem = dict((line.split(':')[0], int(line.split()[1])*1024) for line in remote.get('meminfo','').splitlines() if len(line.split()) >= 2 and line.split()[1].isdigit())
    print(json.dumps({'report':str(out), 'connected':report['connected'], 'cpu_affinity_count':remote.get('cpu_affinity_count'), 'available_memory_bytes':mem.get('MemAvailable'), 'free_disk_bytes':remote.get('disk',{}).get('free'), 'cgroup_ancestor_limits':remote.get('cgroup_ancestor_limits'), 'error':report.get('error')}, ensure_ascii=False, indent=2))
    return 0 if report['connected'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
