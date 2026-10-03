"""Compile the pinned N=21 modular-exponentiation prefix to logical Pauli IR."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_experiments.qec_pbc.shor_frontend import (
    compile_arithmetic, import_gidney_modexp, resource_report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qasm', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    arithmetic = import_gidney_modexp(args.qasm)
    # Audit the permutation on all ten-bit exponents, without period/factor input.
    for exponent in range(1024):
        value = exponent << 5
        for kind, qs in arithmetic.gates:
            if kind == 'H':
                continue  # Inspect reversible body, with exponent fixed classically.
            if all(value >> q & 1 for q in qs[:-1]):
                value ^= 1 << qs[-1]
        if value >> 5 != exponent or value & 31 != pow(2, exponent, 21):
            raise ValueError(f'Modular exponentiation mismatch at exponent {exponent}')
    pauli = compile_arithmetic(arithmetic)
    report = resource_report(arithmetic)
    report.update(basis_cases=1024, modulus=21, base=2,
                  pauli_rotations=len(pauli.rotations),
                  residual_clifford_gates=len(pauli.residual_clifford),
                  claim='Pinned preparation/modexp unitary prefix only; no QFT, factory or physical execution')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'logical_pauli.json').write_text(json.dumps(pauli.to_dict(), indent=2), encoding='utf-8')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
