"""Run and export the six QEC/PBC component experiments."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_experiments.qec_pbc.visual_report import build_experiment_data, write_visual_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qasm', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--shots', type=int, default=20000, help='Shots per curve point: 30 points total')
    parser.add_argument('--seed', type=int, default=17)
    args = parser.parse_args()
    data = build_experiment_data(args.qasm, shots=args.shots, seed=args.seed)
    print(write_visual_report(args.output, data))
    print(data['validation'])


if __name__ == '__main__':
    main()
