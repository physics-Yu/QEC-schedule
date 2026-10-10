"""Scoped unlimited-readout correction, complete small components and regressions."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from component_gallery_job import compile_one, save


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args()
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True);checks=[];start=time.perf_counter()
    for folder,pattern in [('backend','test*.py'),('device','test*.py'),('runtime','test*.py'),('validation','test_validation.py')]:
        p=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/'+folder,'-p',pattern,'-v'],cwd=ROOT,text=True,capture_output=True)
        (out/(folder+'-tests.log')).write_text(p.stdout+p.stderr,encoding='utf-8')
        checks.append({'suite':folder,'pattern':pattern,'exit_code':p.returncode});print(json.dumps(checks[-1]),flush=True)
    components=[compile_one(name,out,120) for name in ['MEASURE_Z','READ_Z_CLEANUP','MEASURE_X','READ_X_CLEANUP']]
    passed=all(c['exit_code']==0 for c in checks) and all(c['status']=='passed' for c in components)
    save(out/'status.json',{'status':'passed' if passed else 'incomplete','checks':checks,'components':components,
        'wall_seconds':time.perf_counter()-start,'readout_limit':None,'configuration_source':'user explicitly requested unlimited readout',
        'scope':'Four logical destructive readout components; no quantum state or full Shor execution', 'user_visual_acceptance':'pending'})
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
