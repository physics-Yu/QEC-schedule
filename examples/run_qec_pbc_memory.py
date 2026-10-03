"""Compile and physically execute the entire d=3 QEC/PBC memory protocol."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main():
    from neutral_atom_env.replay.serializer import canonical_json
    from neutral_atom_experiments.qec_pbc.neutral_atom import build_native_qec_inputs
    from neutral_atom_experiments.qec_pbc.physical import execute_memory
    from neutral_atom_experiments.qec_pbc.surface import memory_program
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', choices=('X', 'Z'), default='Z')
    parser.add_argument('--rounds', type=int, default=3, help='Storage rounds after preparation r0')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--strategy', choices=('sparse', 'dense'), default='sparse')
    parser.add_argument('--wall-budget', type=float, default=900)
    parser.add_argument('--output', default=None)
    args = parser.parse_args()
    path = args.output or f'artifacts/qec-pbc-2026-10-02/memory-{args.basis.lower()}-{args.strategy}'
    inputs = build_native_qec_inputs(memory_program(basis=args.basis, rounds=args.rounds), seed=args.seed)
    result = execute_memory(inputs, path, strategy=args.strategy, wall_budget_s=args.wall_budget,
                            progress=lambda item: print(canonical_json(item), flush=True))
    print(canonical_json({k: result[k] for k in ('status', 'output_directory', 'native_gate_count',
                                               'plans', 'wall_seconds', 'metrics')}), flush=True)
    if result['error']:
        print(canonical_json({'error_type': result['error']['type'],
                              'diagnostic_codes': [d['code'] for d in result['diagnostics']],
                              'detail': 'See result.json for full diagnostics'}), flush=True)
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
