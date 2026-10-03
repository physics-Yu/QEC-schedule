"""Export and run complete ideal N=15 Shor; no encoded/physical claim."""
import argparse
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_experiments.qec_pbc.shor15 import arithmetic_prefix, build_shor15, run_shor15, simulate_shor15
from neutral_atom_experiments.qec_pbc.shor_frontend import compile_arithmetic, resource_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--max-attempts', type=int, default=16)
    parser.add_argument('--phase-bits', type=int, default=8)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    circuit = build_shor15(phase_bits=args.phase_bits)
    report = run_shor15(seed=args.seed, max_attempts=args.max_attempts, phase_bits=args.phase_bits)
    prefix = arithmetic_prefix(circuit)
    prefix_pauli = compile_arithmetic(prefix)
    prefix_resources = resource_report(prefix)
    prefix_resources.update(prefix_only=True, complete_shor=False,
                            pauli_rotations=len(prefix_pauli.rotations),
                            residual_clifford_gates=len(prefix_pauli.residual_clifford))
    report['arithmetic_prefix_resources'] = prefix_resources
    args.output.mkdir(parents=True, exist_ok=True)
    for name, document in (('logical_circuit.json', circuit.to_dict()), ('report.json', report),
                           ('logical_pauli_prefix.json', prefix_pauli.to_dict())):
        (args.output / name).write_text(json.dumps(document, indent=2), encoding='utf-8')
    _, probabilities = simulate_shor15(circuit)
    with (args.output / 'phase_distribution.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(('outcome', 'probability', 'bits_msb_first'))
        writer.writerows((i, float(p), format(i, f'0{args.phase_bits}b')) for i, p in enumerate(probabilities))
    print(json.dumps({'success': report['success'], 'factors': report['factors'], 'order': report['order'],
                      'attempts': len(report['attempts']), 'qubits': report['qubits'],
                      'gates': report['gate_count'], 'audit': report['audit'],
                      'output': str(args.output.resolve()), 'physical_executed': False}, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
