"""Open the manual free-placement comparison workbench."""
import argparse
from pathlib import Path
from neutral_atom_app.visualization.placement_server import serve
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('artifacts/free-placement'))
    parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args();serve(args.output,args.port)
