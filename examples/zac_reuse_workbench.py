"""Serve the editable ZAC reuse on/off physical experiment on loopback."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_app.visualization.zac_reuse_server import serve
from neutral_atom_experiments.zac_reuse import DEFAULT_SOURCE

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--output',type=Path,default=Path('artifacts/zac-reuse'))
    parser.add_argument('--source',type=Path,default=DEFAULT_SOURCE)
    args=parser.parse_args()
    serve(output=args.output,source=args.source,port=args.port)
