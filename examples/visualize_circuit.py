"""Application integration: observe execution without collecting full checkpoints."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.simulation.milestone2_factory import make_circuit_state
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.visualization import VisualRecorder,write_bundle


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scenario',choices=['repeat','switch_partner','three_gate','join','unsupported'],default='three_gate')
    parser.add_argument('--output',type=Path,default=Path('artifacts/visualization'))
    args=parser.parse_args()
    state=make_circuit_state(args.scenario)
    recorder=VisualRecorder(state)
    result=EagerScheduler(state).run(on_event=recorder.observe)
    recorder.write(args.output/'index.html')
    recorder.write_json(args.output/'recording.json')
    write_bundle(args.output)
    print(result.status, (args.output/'index.html').resolve())
    print('Compact frames:',len(recorder.frames),'bytes:',(args.output/'recording.json').stat().st_size)
    return 0 if result.status=='completed' else 2


if __name__=='__main__':
    raise SystemExit(main())
