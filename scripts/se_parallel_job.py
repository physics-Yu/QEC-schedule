"""Bounded SE optimization qualification, including shared-source consumers."""
from pathlib import Path
import argparse,json,sys,subprocess,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import compile_one,save
from component_parallel_demo import build as build_pair
from na_pipeline.qec import component_catalog,shor_component_requirements


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
    out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter();checks=[];components=[]
    names=['SE','S','SDG','PREPARE_ZERO','PREPARE_PLUS','PREPARE_Y_PLUS','PREPARE_Y_MINUS','factory.finish_04']
    catalog=component_catalog();catalog['components']=[r for r in catalog['components'] if r['id'] in names]
    save(out/'catalog.json',catalog);save(out/'shor-coverage.json',shor_component_requirements())
    def state(phase,status='running'):
        save(out/'status.json',{'status':status,'phase':phase,'checks':checks,'components':components,
            'wall_seconds':time.perf_counter()-start,'full_shor_executed':False,'user_visual_acceptance':'pending'})
    for suite in ('qec','backend','device','runtime','validation'):
        pattern='test_validation.py' if suite=='validation' else 'test*.py'
        r=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/'+suite,'-p',pattern,'-v'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        (out/(suite+'-tests.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        checks.append({'suite':suite,'exit_code':r.returncode});state('regressions');print(json.dumps(checks[-1]),flush=True)
    if any(c['exit_code'] for c in checks):state('regressions','failed');raise SystemExit(1)
    for name in names:
        components.append(compile_one(name,out,600));state('components')
        if components[-1]['status']!='passed':state('components','failed');raise SystemExit(1)
    build_pair(out);state('complete','passed')


if __name__=='__main__':main()
