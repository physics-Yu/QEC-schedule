"""Initialize M0, inspect the logical frontier, commit WAIT and save a checkpoint."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_env.simulation import make_demo_state, Executor
from neutral_atom_env.domain.models import SimulationEvent, EventType
from neutral_atom_env.replay.serializer import canonical_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('artifacts/milestone0'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    state = make_demo_state()
    print('Initial ready gates:', [g.id for g in state.dag.ready_gates()])
    ex = Executor(state)
    ex.schedule(SimulationEvent(1, EventType.WAIT_COMPLETED))
    ex.run()
    (args.output/'checkpoint.json').write_text(state.snapshot(), encoding='utf-8')
    (args.output/'metrics.json').write_text(canonical_json(state.metrics()), encoding='utf-8')
    state.trace.write(args.output/'trace.jsonl')
    print('Checkpoint:', (args.output/'checkpoint.json').resolve())


if __name__ == '__main__':
    main()
