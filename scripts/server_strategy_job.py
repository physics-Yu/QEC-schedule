"""Snapshot/dispatch/fetch a T703 job inside a fresh SSH project directory."""
from datetime import datetime, timezone
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
HOST = "yyq@10.133.24.178"
OUT = ROOT / "scripts/outputs/T703/server"


def remote(code, *, timeout=45):
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST, "python3", "-"], input=code, text=True, capture_output=True, encoding="utf-8", timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"REMOTE_COMMAND_FAILED: {result.stderr[-3000:]} {result.stdout[-3000:]}")
    return json.loads(result.stdout)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def dispatch(args):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    job_id = stamp + "-" + args.case
    local = OUT / job_id
    local.mkdir(parents=True)
    selected = [ROOT / "pyproject.toml", ROOT / f"scripts/outputs/T703/requests/{args.case}.json"]
    selected += sorted((ROOT / "src/na_pipeline").rglob("*.py"))
    selected += [ROOT / "viewer" / name for name in ("__init__.py", "viewer.html", "viewer.css", "viewer.js")]
    selected += [ROOT / "scripts" / name for name in ("jobs.py", "remote_strategy_worker.py")]
    selected += [ROOT / "third_party/enola" / name for name in ("pin.json", "requirements.lock", "dependency-sources.json")]
    selected += sorted((ROOT / "third_party/enola/upstream/enola").rglob("*.py"))
    selected += [ROOT / "third_party/enola/upstream" / name for name in ("LICENSE", "README.md", "run.py")]
    frozen = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in selected}
    inventory = {name: hashlib.sha256(data).hexdigest() for name, data in frozen.items()}
    bundle = local / "source.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        for name, data in frozen.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    # No overwritten remote paths: the project directory is new for this dispatch.
    setup = remote("from pathlib import Path\nimport json\np=Path.home()/'na-platform-simulation'/'R7'/'T703'/" + repr(job_id) + "\np.mkdir(parents=True,exist_ok=False)\nprint(json.dumps({'project':str(p)}))\n")
    project = setup["project"]
    subprocess.run(["scp", "-q", str(bundle), HOST + ":" + project + "/source.tar.gz"], check=True, timeout=60)
    launch = remote("""from pathlib import Path
import hashlib,json,subprocess,tarfile,sys
root=Path(PROJECT)
expected=INVENTORY
with tarfile.open(root/'source.tar.gz') as archive: archive.extractall(root,filter='data')
for name,value in expected.items():
    p=(root/name).resolve()
    if not p.is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest()!=value: raise ValueError('SNAPSHOT_HASH_MISMATCH '+name)
command=[sys.executable,str(root/'scripts/jobs.py'),'launch','--job-dir',str(root/'scripts/outputs/T703/job'),'--wall-seconds','1800','--memory-gib','8','--parallelism','4','--search-expansions','1000000','--',sys.executable,str(root/'scripts/remote_strategy_worker.py'),CASE,'--fake-value',FAKE]
result=subprocess.run(command,cwd=root,capture_output=True,text=True)
if result.returncode:raise RuntimeError(result.stderr)
print(json.dumps({'dispatch':json.loads(result.stdout),'python':sys.version,'snapshot_files_verified':len(expected)}))
""".replace("PROJECT", repr(project)).replace("INVENTORY", repr(inventory)).replace("CASE", repr(args.case)).replace("FAKE", repr(str(args.fake_value))))
    record = {"schema_version": "t703-remote-dispatch/0.1.0", "host": HOST, "project": project, "job_id": job_id, "case": args.case, "fake_value": args.fake_value, "snapshot_byte_sha256": inventory, "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(), "launch": launch, "status": "dispatched_not_completed", "budget": {"wall_seconds": 1800, "memory_gib": 8, "parallelism": 4, "search_expansions_recorded": 1000000}}
    write(local / "dispatch.json", record)
    print(json.dumps({"dispatch": str(local / "dispatch.json"), "remote_project": project, "status": record["status"]}, ensure_ascii=False))


def inspect(args):
    dispatch = json.loads(args.dispatch.read_bytes())
    project = dispatch["project"]
    if not PurePosixPath(project).is_relative_to("/home/yyq/na-platform-simulation/R7/T703"):
        raise ValueError("REMOTE_PROJECT_OUT_OF_SCOPE")
    state = remote("from pathlib import Path\nimport json\np=Path(" + repr(project) + ")/'scripts/outputs/T703/job'\ns=json.loads((p/'status.json').read_text())\nprint(json.dumps({'status':s,'stdout_tail':(p/'stdout.log').read_text(errors='replace')[-4000:] if (p/'stdout.log').exists() else '', 'stderr_tail':(p/'stderr.log').read_text(errors='replace')[-4000:] if (p/'stderr.log').exists() else ''}))")
    progress = remote("from pathlib import Path\nimport json\np=Path(" + repr(project) + ")/'scripts/outputs/T703/remote-run/manifest.json'\nm=json.loads(p.read_text()) if p.exists() else {}\nprint(json.dumps({k:m.get(k) for k in ['status','current_stage','current_call_id','binding_retry_budget','stage_wall_seconds']}))")
    state["pipeline_progress"] = progress
    state["binding_progress"] = remote("from pathlib import Path\nimport json\np=Path(" + repr(project) + ")/'scripts/outputs/T703/remote-run/strategy-checkpoints/bind-progress.json'\nprint(p.read_text() if p.exists() else '{}')")
    write(args.dispatch.parent / "observed-status.json", state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    if args.fetch and state["status"]["status"] not in {"running", "starting", "dispatched_not_completed"}:
        result = remote("from pathlib import Path\nimport json,tarfile\nr=Path(" + repr(project) + ")\np=r/'result.tar.gz'\nwith tarfile.open(p,'w:gz') as a:a.add(r/'scripts/outputs/T703',arcname='T703')\nprint(json.dumps({'archive':str(p)}))")
        local = args.dispatch.parent / "result.tar.gz"
        subprocess.run(["scp", "-q", HOST + ":" + result["archive"], str(local)], check=True, timeout=60)
        extracted = args.dispatch.parent / "result"
        extracted.mkdir(exist_ok=True)
        with tarfile.open(local) as archive:
            archive.extractall(extracted, filter="data")
        print(json.dumps({"fetched": str(extracted), "archive_byte_sha256": hashlib.sha256(local.read_bytes()).hexdigest()}))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("dispatch")
    p.add_argument("--case", choices=("single", "two", "coupled"), required=True)
    p.add_argument("--fake-value", type=int, choices=(0, 1), default=0)
    p = sub.add_parser("status")
    p.add_argument("--dispatch", type=Path, required=True)
    p.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    dispatch(args) if args.mode == "dispatch" else inspect(args)


if __name__ == "__main__":
    main()
