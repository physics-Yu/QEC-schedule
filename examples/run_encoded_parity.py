"""Run the complete three-patch encoded parity physical experiment."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_experiments.qec_pbc.encoded_ppm import encoded_parity_program
from neutral_atom_experiments.qec_pbc.encoded_physical import execute_encoded_parity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', choices=('X', 'Z'), default='Z')
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--wall-budget', type=float, default=1800)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path('artifacts/qec-shor15-2026-10-03') / f'encoded-{args.basis.lower()}{args.basis.lower()}-physical'
    protocol = encoded_parity_program(basis=args.basis, rounds=args.rounds)
    evidence = execute_encoded_parity(protocol, output, seed=args.seed,
        wall_budget_s=args.wall_budget,
        progress=lambda row: print(json.dumps(row), flush=True))
    print(json.dumps({k: evidence[k] for k in ('status', 'error', 'output_directory',
        'native_gate_count', 'plans', 'physical_pulse_count', 'max_parallel_cz', 'wall_seconds')}, indent=2))
    return 0 if evidence['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
