"""Stop only the explicitly named local benchmark and retain censored outcomes."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import sys
import psutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.zac_benchmark import write_json
from neutral_atom_experiments.zac_benchmark_report import write_dashboard


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--reason',required=True)
    args=parser.parse_args()
    root=args.output.resolve()
    path=root/'benchmark.json'
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if manifest['status']!='running':
        raise SystemExit('Benchmark is not running')
    matched=[]
    for process in psutil.process_iter(['pid','cmdline']):
        cmd=process.info['cmdline'] or []
        if '--output' in cmd and any(Path(a).name=='benchmark_zac_reuse.py' for a in cmd):
            if Path(cmd[cmd.index('--output')+1]).resolve()==root:
                matched.append(process)
    if len(matched)!=1:
        raise SystemExit(f'Expected one exact benchmark parent, found {len(matched)}; no processes stopped')
    parent=matched[0]
    children=parent.children(recursive=True)
    parent.terminate()  # stop the queue before stopping its own workers
    parent.wait(timeout=10)
    for child in children:
        try: child.terminate()
        except psutil.NoSuchProcess: pass
    psutil.wait_procs(children,timeout=10)
    cancelled=0
    for case in manifest['cases']:
        for mode in case['variants']:
            result_path=root/case['id']/mode/'worker.json'
            if result_path.exists():
                record=json.loads(result_path.read_text(encoding='utf-8'))
            else:
                result_path.parent.mkdir(parents=True,exist_ok=True)
                record=dict(status='cancelled',phase='worker_process',
                            error=dict(type='Cancelled',message=args.reason),
                            process_elapsed_seconds=None)
                write_json(result_path,record)
                cancelled+=1
            case['variants'][mode]=record
    manifest.update(status='finished',finished_utc=datetime.now(timezone.utc).isoformat(),
                    cancellation_reason=args.reason)
    write_json(path,manifest)
    write_dashboard(manifest,root)
    print(json.dumps(dict(cancelled=cancelled,stopped_parent=parent.pid,children=[p.pid for p in children])))
