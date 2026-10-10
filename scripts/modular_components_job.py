"""Dependency-first T044 build, then search-free complete protocol consumers."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse
import json
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import compile_one,save
from component_protocol_job import execute
from na_pipeline.qec import component_catalog,shor_component_requirements


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True)
    ap.add_argument('--mode',choices=('representative','full'),default='representative')
    ap.add_argument('--workers',type=int,default=4);args=ap.parse_args()
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter();checks=[];completed=[]
    catalog=component_catalog();save(out/'catalog.json',catalog);save(out/'shor-coverage.json',shor_component_requirements())
    for folder in ('qec','backend','device','runtime','validation'):
        pattern='test_validation.py' if folder=='validation' else 'test*.py'
        p=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/'+folder,'-p',pattern,'-v'],cwd=ROOT,capture_output=True,text=True)
        (out/(folder+'-tests.log')).write_text(p.stdout+p.stderr,encoding='utf-8')
        checks.append({'suite':folder,'exit_code':p.returncode});print(json.dumps(checks[-1]),flush=True)
    selected=['CX','CZ','S','PREPARE_A','PREPARE_Y_PLUS','JOINT_ZZ','factory.initialize','factory.rotate_04']
    if args.mode=='full':selected=[r['id'] for r in catalog['components'] if r['kind']=='physical']
    # Foundations precede factory recipes. Independent factory stages may build
    # in parallel; no T consumer is dispatched until every stage is ready.
    foundational=[n for n in selected if not n.startswith('factory.')]
    stages=[n for n in selected if n.startswith('factory.')]
    def record(result):
        completed.append(result)
        save(out/'status.json',{'status':'running','phase':'build_dependencies','mode':args.mode,'checks':checks,'components':completed})
    for name in foundational:record(compile_one(name,out,1800))
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for f in as_completed([pool.submit(compile_one,n,str(out),1800) for n in stages]):record(f.result())
    protocols=[]
    if args.mode=='full' and all(c['status']=='passed' for c in completed):
        from component_parallel_demo import build
        build(out)
        save(out/'status.json',{'status':'running','phase':'compose_and_execute_protocols','checks':checks,'components':completed,'protocols':protocols})
        with ProcessPoolExecutor(max_workers=min(2,args.workers)) as pool:
            for f in as_completed([pool.submit(execute,name,str(out/'protocols')) for name in ('T','TDG','REJECT_RETRY')]):
                protocols.append(f.result())
                save(out/'status.json',{'status':'running','phase':'compose_and_execute_protocols','checks':checks,'components':completed,'protocols':protocols})
    passed=all(c['exit_code']==0 for c in checks) and all(c['status']=='passed' for c in completed) and all(p['status']=='passed' for p in protocols)
    save(out/'status.json',{'status':'passed' if passed else 'incomplete','mode':args.mode,'checks':checks,'components':completed,'protocols':protocols,
                          'wall_seconds':time.perf_counter()-started,'user_visual_acceptance':'pending','quantum_state_simulated':False,'hardware_executed':False})
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
