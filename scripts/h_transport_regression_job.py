"""Rerun only the two modules whose first frozen job lacked fixture files."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);checks=[]
    for folder, pattern in [('backend','test_physical_strategy.py'),('runtime','test_logical_scheduler.py')]:
        p=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/'+folder,'-p',pattern,'-v'],capture_output=True,text=True)
        (out/(folder+'-tests.log')).write_text(p.stdout+p.stderr,encoding='utf-8')
        checks.append({'suite':folder,'pattern':pattern,'exit_code':p.returncode})
        print(json.dumps(checks[-1]),flush=True)
    passed=all(c['exit_code']==0 for c in checks)
    (out/'status.json').write_text(json.dumps({'status':'passed' if passed else 'incomplete','checks':checks,
        'reason':'First job omitted examples/atom/t405/reuse_workload.py and knowledge/roles/R5/dag-scheduler-example.json; no compiler/runtime change.'},indent=2)+'\n',encoding='utf-8')
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
