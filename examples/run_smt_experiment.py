"""Run each strategy in a fresh interpreter to avoid order-dependent caches."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


from neutral_atom_app.smt_experiment import isolated_comparison


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--one',choices=('greedy','smt_single','smt_multi'))
    parser.add_argument('--input');parser.add_argument('--output',default='artifacts/smt-batch/attempt2')
    parser.add_argument('--case');args=parser.parse_args()
    from neutral_atom_experiments.smt_comparison import demos,run_one
    if args.one:
        run_one(json.loads(Path(args.input).read_text(encoding='utf-8')),args.one,args.output);return
    if args.input:
        isolated_comparison(json.loads(Path(args.input).read_text(encoding='utf-8')),args.output,lambda p:print(p,flush=True));return
    suite={}
    for key,spec in demos().items():
        if args.case and key!=args.case:continue
        print(key,flush=True)
        suite[key]=isolated_comparison(spec,Path(args.output)/key,lambda p:print(p,flush=True))
    Path(args.output,'suite.json').write_text(json.dumps(suite,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
