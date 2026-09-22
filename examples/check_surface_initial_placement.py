"""Run full surface-code GHZ initial-placement acceptance without rendering."""
import argparse
import json
from pathlib import Path
from neutral_atom_experiments.surface_initial_placement import run_experiment

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=Path('artifacts/initial-placement/surface-ghz2'))
args=parser.parse_args()
report=run_experiment(args.output)
print(json.dumps(report,indent=2))
raise SystemExit(report['status']!='passed')
