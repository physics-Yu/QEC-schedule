"""Rebuild actual CZ-carrier/MZ modules, then guarded continuous consumers."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse,json,subprocess,sys,time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import compile_one,save
from modular_protocol_recheck_job import observed_execute
from na_pipeline.qec import component_catalog,shor_component_requirements


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True);started=time.perf_counter();checks=[];completed=[];protocols=[]
    catalog=component_catalog();save(out/'catalog.json',catalog);save(out/'shor-coverage.json',shor_component_requirements())
    def status(phase,state='running'):
        save(out/'status.json',{'status':state,'phase':phase,'checks':checks,'components':completed,'protocols':protocols,
                              'wall_seconds':time.perf_counter()-started,'user_visual_acceptance':'pending','full_shor_executed':False})
    for folder in ('qec','backend','device','runtime','validation'):
        pattern='test_validation.py' if folder=='validation' else 'test*.py'
        r=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/'+folder,'-p',pattern,'-v'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        (out/(folder+'-tests.log')).write_text(r.stdout+r.stderr,encoding='utf-8');checks.append({'suite':folder,'exit_code':r.returncode});status('checks');print(json.dumps(checks[-1]),flush=True)
    if any(c['exit_code'] for c in checks):status('checks','failed');raise SystemExit(1)
    selected=[r['id'] for r in catalog['components'] if r['kind']=='physical']
    for name in (n for n in selected if not n.startswith('factory.')):
        completed.append(compile_one(name,out,1800));status('build_dependencies')
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(compile_one,n,str(out),1800) for n in selected if n.startswith('factory.')]):
            completed.append(f.result());status('build_dependencies')
    if any(c['status']!='passed' for c in completed):status('build_dependencies','failed');raise SystemExit(1)
    from component_parallel_demo import build
    build(out);status('compose_and_execute')
    with ProcessPoolExecutor(max_workers=3) as pool:
        for f in as_completed([pool.submit(observed_execute,n,str(out/'protocols'),False) for n in ('T','TDG','REJECT_RETRY')]):
            protocols.append(f.result());status('compose_and_execute')
    passed=all(p['status']=='passed' for p in protocols)
    status('complete','passed' if passed else 'failed')
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
