"""Four-arm ZAC initial-placement and reuse experiment, with full physical replay."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.zac_initial import run_suite
from neutral_atom_experiments.zac_reuse import DEFAULT_SOURCE

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('artifacts/zac-reuse/benchmark-initial'))
    p.add_argument('--sizes',type=int,nargs='+',default=[16,32])
    p.add_argument('--families',nargs='+',choices=['repeat','butterfly','random'],default=['butterfly','random'])
    p.add_argument('--depth',type=int,default=8)
    p.add_argument('--seed',type=int,default=20260921)
    p.add_argument('--timeout',type=float,default=600)
    p.add_argument('--workers',type=int,default=2)
    p.add_argument('--source',type=Path,default=DEFAULT_SOURCE)
    p.add_argument('--resume',action='store_true')
    a=p.parse_args()
    result=run_suite(a.output,sizes=a.sizes,families=a.families,depth=a.depth,seed=a.seed,
                     timeout_s=a.timeout,workers=a.workers,source=a.source,resume=a.resume)
    good=sum(v['status']=='completed' for c in result['cases'] for v in c['variants'].values())
    print(f"Finished: {good}/{4*len(result['cases'])}; {a.output/'index.html'}")
    raise SystemExit(0 if good==4*len(result['cases']) else 2)
