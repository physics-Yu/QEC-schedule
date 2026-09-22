"""Run larger matched ZAC reuse benchmarks with full physical records."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_experiments.zac_benchmark import run_suite, FAMILIES
from neutral_atom_experiments.zac_reuse import DEFAULT_SOURCE


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=Path('artifacts/zac-reuse/benchmark-large'))
    p.add_argument('--sizes', type=int, nargs='+', default=[16,32,64,128])
    p.add_argument('--depth', type=int, default=8)
    p.add_argument('--families', choices=FAMILIES, nargs='+', default=list(FAMILIES))
    p.add_argument('--seeds', type=int, nargs='+', default=[20260921])
    p.add_argument('--timeout', type=float, default=600)
    p.add_argument('--hard-timeout', type=float, default=1200)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--bounded-spares', action='store_true', help='Fit unused AOD axes inside existing bounds')
    args = p.parse_args()
    result = run_suite(args.output, sizes=args.sizes, depth=args.depth, families=args.families,
                       seeds=args.seeds, timeout_s=args.timeout, hard_timeout_s=args.hard_timeout,
                       workers=args.workers, source=args.source, resume=args.resume,
                       bounded_spares=args.bounded_spares)
    completed = sum(v['status']=='completed' for c in result['cases'] for v in c['variants'].values())
    print(f"Finished: {completed}/{2*len(result['cases'])} completed. Report: {args.output / 'index.html'}")
    raise SystemExit(0 if completed == 2*len(result['cases']) else 2)
