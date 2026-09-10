"""Generate backend evidence: python examples/run_reconfigurable_aod.py --backend row_column."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.testing.row_column_report import build_report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Selectable AOD backend acceptance')
    parser.add_argument('--backend',choices=['rigid','row_column'],default='row_column')
    parser.add_argument('--output',default=None)
    args=parser.parse_args()
    root=args.output or f'artifacts/{args.backend}'
    results=build_report(root,args.backend)
    for result in results:print(f"{result['status']}: {result['backend']} / {result['scenario']}")
    print((Path(root)/'index.html').resolve())
