"""Run a custom CZ circuit's nonvisual physical placement comparison."""
import argparse
import json
from pathlib import Path
from neutral_atom_experiments.initial_placement import run_experiment
from neutral_atom_strategies.placement import SearchConfig

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input',type=Path,required=True,help='JSON: atom_count, pairs, optional name')
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--iterations',type=int,default=1000)
parser.add_argument('--top-k',type=int,default=2)
parser.add_argument('--grid',type=int,default=10)
parser.add_argument('--seed',type=int,default=7)
args=parser.parse_args()
try:
    report=run_experiment(json.loads(args.input.read_text(encoding='utf-8')),args.output,
        SearchConfig(iterations=args.iterations,top_k=args.top_k,seed=args.seed),grid=args.grid)
except Exception as error:
    report=dict(status='failed',phase='experiment',error=dict(type=type(error).__name__,message=str(error)))
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
raise SystemExit(report['status']!='passed')
