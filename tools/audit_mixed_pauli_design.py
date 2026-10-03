"""Rebuild independent mixed-PPM design formula checks and optional inventory.

This is a small NumPy reference calculation, not an encoded backend, test-suite
extension, fault audit or physical execution. It imports no environment code,
installs nothing and reads an adaptive export only when --input is supplied.
"""
import argparse
from collections import Counter
from functools import reduce
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

import numpy as np


IDENTITY = np.eye(2, dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.diag([1, -1]).astype(complex)
S = np.diag([1, 1j])
H = (X + Z) / np.sqrt(2)
CX = np.array([[1, 0, 0, 0], [0, 1, 0, 0],
               [0, 0, 0, 1], [0, 0, 1, 0]], dtype=complex)
CZ = np.diag([1, 1, 1, -1])
CY = np.block([[IDENTITY, np.zeros((2, 2))],
               [np.zeros((2, 2)), Y]])


def _maximum_error(actual, expected):
    return float(np.max(np.abs(actual - expected)))


def _resource_kraus(pauli, direction, joint_bit, resource_bit, angle=np.pi / 2):
    """Contract actual PZ projection and resource X bra, column by column."""
    dimension = len(pauli)
    resource = np.array([1, np.exp(1j * direction * angle)]) / np.sqrt(2)
    projector = (np.eye(2 * dimension) +
                 (-1) ** joint_bit * np.kron(pauli, Z)) / 2
    readout_bra = np.array([1, (-1) ** resource_bit]) / np.sqrt(2)
    result = np.empty((dimension, dimension), dtype=complex)
    for column in range(dimension):
        vector = projector @ np.kron(np.eye(dimension)[:, column], resource)
        result[:, column] = vector.reshape(dimension, 2) @ readout_bra
    return result


def audit_formulae():
    """Check operators plus a complete noncommuting injection/reference probe."""
    errors = {
        'controlled_y': _maximum_error(np.kron(S, IDENTITY) @ CX @ CZ, CY),
        'cy_native_hczh': _maximum_error(
            np.kron(S, IDENTITY) @ np.kron(IDENTITY, H) @ CZ @
            np.kron(IDENTITY, H) @ CZ, CY),
    }
    paulis = [sign * reduce(np.kron, factors)
              for sign in (1, -1) for factors in product((X, Y, Z), repeat=2)]
    correction_error = frame_error = 0.0
    branch_count = 0
    for pauli in paulis:
        eye = np.eye(len(pauli))
        plus, minus = (eye + pauli) / 2, (eye - pauli) / 2
        for direction, m, r in product((1, -1), (0, 1), (0, 1)):
            clifford = plus + 1j * direction * minus
            actual = (pauli if m ^ r else eye) @ _resource_kraus(pauli, direction, m, r)
            expected = (1j * direction) ** m * (-1) ** (m * r) * clifford / 2
            correction_error = max(correction_error, _maximum_error(actual, expected))
            correction = (pauli if r else eye) @ (clifford if m else eye)
            for observable in paulis:
                anti = not np.allclose(pauli @ observable, observable @ pauli, atol=1e-14)
                expected = (-1) ** (r * anti) * (
                    1j * direction * pauli @ observable if m and anti else observable)
                actual = correction.conj().T @ observable @ correction
                frame_error = max(frame_error, _maximum_error(actual, expected))
            branch_count += 1
    errors['signed_clifford_resource_kraus'] = correction_error
    errors['signed_frame_pullback'] = frame_error

    # The final rotation anticommutes with the first two; order is retained.
    # Two data wires and one genuinely complex, entangled reference wire.
    rng = np.random.default_rng(7)
    initial = rng.normal(size=8) + 1j * rng.normal(size=8)
    initial /= np.linalg.norm(initial)
    axes = [np.kron(X, Y), -np.kron(Y, Z), np.kron(Z, IDENTITY)]
    directions = [1, -1, 1]
    residual = np.kron(H, IDENTITY) @ CZ
    external_phase = np.exp(0.371j)
    target = initial.copy()
    for pauli, direction in zip(axes, directions):
        rotation = (np.eye(4) + pauli) / 2 + (
            np.exp(1j * direction * np.pi / 4) * (np.eye(4) - pauli) / 2)
        target = np.kron(rotation, IDENTITY) @ target
    target = external_phase * np.kron(residual, IDENTITY) @ target

    complete_error = 0.0
    complete_branch_count = 0
    for outcomes in product(tuple(product((0, 1), repeat=2)), repeat=3):
        frame = np.eye(4, dtype=complex)
        physical = initial.copy()
        ledger = 1.0 + 0.0j
        for pauli, direction, (m, r) in zip(axes, directions, outcomes):
            pulled_axis = frame.conj().T @ pauli @ frame
            # Four injection branches have probability 1/4. Multiplication by
            # two normalizes the actual contracted Kraus without replacing it.
            instrument = _resource_kraus(pulled_axis, direction, m, r, angle=np.pi / 4)
            physical = np.kron(2 * instrument, IDENTITY) @ physical
            clifford = (np.eye(4) + pauli) / 2 + (
                1j * direction * (np.eye(4) - pauli) / 2)
            frame = (pauli if r else np.eye(4)) @ (
                clifford if m else np.eye(4)) @ frame
            ledger *= np.exp(1j * direction * np.pi / 4) ** m * (-1) ** (m * r)
        represented = external_phase * np.kron(residual @ frame, IDENTITY) @ physical
        complete_error = max(complete_error, _maximum_error(represented, ledger * target))
        complete_branch_count += 1
    errors['three_noncommuting_framed_injections_all_64_branches'] = complete_error
    tolerance = 1e-12
    if not all(np.isfinite(error) and error < tolerance for error in errors.values()):
        raise AssertionError(f'Design reference formula mismatch: {errors}')
    return {
        'schema': 'mixed-pauli-design-audit-v1',
        'scope': 'Independent design formula checks; no encoded protocol, FT or physical execution',
        'status': 'reference_math_passed',
        'matrix_tolerance': tolerance,
        'max_matrix_errors': errors,
        'signed_clifford_resource_branches': branch_count,
        'complete_framed_injection_branches': complete_branch_count,
        'probe': {'data_wires': 2, 'reference_wires': 1, 'seed': 7,
                  'external_phase_radians': 0.371},
        'encoded_protocol_executed': False,
        'fault_tolerance_audited': False,
        'physical_executed': False,
    }


def inventory(source):
    """Read caller-supplied eager labels, without deriving or changing a frame."""
    raw = source.read_bytes()
    program = json.loads(raw)
    if program.get('schema') != 'adaptive-pauli-resource-v1':
        raise ValueError('Input must be an adaptive-pauli-resource-v1 export')
    wires = tuple(program['wires'])
    if len(set(wires)) != len(wires):
        raise ValueError('Input data wires must be distinct')
    y_counts, lengths = Counter(), Counter()
    for injection in program['injections']:
        factors = injection['rotation']['observable']['factors']
        joint = injection['operations'][1]['observable']['factors']
        resource = injection['resource']['wire']
        if (any(w not in wires or basis not in ('X', 'Y', 'Z') for w, basis in factors)
                or len({w for w, _ in factors}) != len(factors)
                or len(joint) != len(factors) + 1
                or len({w for w, _ in joint}) != len(joint)
                or resource in wires
                or dict(joint) != dict((*factors, (resource, 'Z')))):
            raise ValueError('Observable/resource support is inconsistent')
        y_count = sum(basis == 'Y' for _, basis in factors)
        y_counts[y_count] += 1
        lengths[3 * (len(factors) + 1) + 2 * y_count] += 1
    return {
        'scope': 'Read-only eager-source inventory; not framed branches or physical execution',
        'source': str(source),
        'source_sha256': sha256(raw).hexdigest(),
        'source_injections': len(program['injections']),
        'source_y_factor_count_distribution': dict(sorted(y_counts.items())),
        'odd_y_source_joint_measurements': sum(v for k, v in y_counts.items() if k % 2),
        'even_positive_y_source_joint_measurements': sum(
            v for k, v in y_counts.items() if k and not k % 2),
        'actual_fixed_representative_max_cat_length': max(lengths, default=0),
        'fixed_representative_cat_lengths': dict(sorted(lengths.items())),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='Optional caller-supplied adaptive PBC export')
    parser.add_argument('--output', type=Path, help='New JSON artifact path; existing files are rejected')
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error(f'Output exists; choose a new artifact path: {args.output}')
    report = audit_formulae()
    if args.input is not None:
        report['eager_source_inventory'] = inventory(args.input)
    output = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also prevents a race from replacing another run.
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(output)
    print(output, end='')


if __name__ == '__main__':
    main()
