"""Complete, unencoded N=15 Shor reference with explicit logical gates.

The circuit is constructed from N and a, without order or factor inputs.  The
small modular multipliers exploit N=2**4-1 and are independently checked on
every work-register basis state.  CP in the exact inverse QFT remains a
logical gate: this module does not claim Clifford+T or physical compilation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class ShorGate:
    name: str
    qubits: tuple[int, ...]
    stage: str
    angle_radians: float | None = None

    def __post_init__(self):
        object.__setattr__(self, 'qubits', tuple(self.qubits))
        arity = {'X': 1, 'H': 1, 'CX': 2, 'CCX': 3, 'CP': 2}
        if self.name not in arity or len(self.qubits) != arity[self.name]:
            raise ValueError('Unsupported logical gate or arity')
        if len(set(self.qubits)) != len(self.qubits) or any(type(q) is not int or q < 0 for q in self.qubits):
            raise ValueError('Gate operands must be distinct nonnegative integers')
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError('Gate stage is required')
        if self.name == 'CP':
            if self.angle_radians is None or not math.isfinite(self.angle_radians):
                raise ValueError('CP requires a finite angle in radians')
        elif self.angle_radians is not None:
            raise ValueError('Only CP accepts an angle')

    def inverse(self) -> ShorGate:
        return ShorGate(self.name, self.qubits, self.stage,
                        -self.angle_radians if self.name == 'CP' else None)

    def to_dict(self) -> dict:
        result = {'name': self.name, 'qubits': list(self.qubits), 'stage': self.stage}
        if self.angle_radians is not None:
            result['angle_radians'] = self.angle_radians
        return result


@dataclass(frozen=True)
class Shor15Circuit:
    phase_bits: int
    gates: tuple[ShorGate, ...]
    modular_constants: tuple[int, ...]
    modulus: int = 15
    base: int = 2

    def __post_init__(self):
        object.__setattr__(self, 'gates', tuple(self.gates))
        object.__setattr__(self, 'modular_constants', tuple(self.modular_constants))
        if self.modulus != 15 or self.base != 2:
            raise ValueError('This reference implements N=15, a=2 only')
        if type(self.phase_bits) is not int or not 4 <= self.phase_bits <= 10:
            raise ValueError('Reference phase width must be in [4, 10]')
        if self.modular_constants != tuple(pow(self.base, 1 << i, self.modulus) for i in range(self.phase_bits)):
            raise ValueError('Modular constants must be computed from N and a')
        if any(q >= self.qubit_count for gate in self.gates for q in gate.qubits):
            raise ValueError('Gate operand exceeds the declared registers')

    @property
    def qubit_count(self) -> int:
        return self.phase_bits + 4

    @property
    def phase_qubits(self) -> tuple[int, ...]:
        return tuple(range(self.phase_bits))

    @property
    def work_qubits(self) -> tuple[int, ...]:
        return tuple(range(self.phase_bits, self.qubit_count))

    def to_dict(self) -> dict:
        return {
            'schema': 'shor15-logical-reference-v1', 'modulus': self.modulus, 'base': self.base,
            'scope': 'complete ideal logical circuit; unencoded, no physical execution',
            'bit_order': 'little-endian: basis index = phase + (work << phase_bits)',
            'qubit_count': self.qubit_count,
            'registers': {'phase': list(self.phase_qubits), 'work': list(self.work_qubits)},
            'initial_state': 'all zero; the first X prepares work=1',
            'modular_constants': list(self.modular_constants),
            'gates': [dict(id=f'shor15.g{i:04d}', **g.to_dict()) for i, g in enumerate(self.gates)],
            'measurements': [{'qubit': q, 'basis': 'Z', 'bit': f'phase{q}'} for q in self.phase_qubits],
            'measurement_integer': 'sum(phase[i] * 2**i)',
            'postprocessing': 'continued fractions, verified order, gcd, retry on failure',
            'clifford_t_compiled': False, 'pbc_compiled': False, 'encoded': False,
            'physical_executed': False,
        }


def _swap(a: int, b: int, stage: str) -> tuple[ShorGate, ...]:
    return (ShorGate('CX', (a, b), stage), ShorGate('CX', (b, a), stage), ShorGate('CX', (a, b), stage))


def _fredkin(control: int, a: int, b: int, stage: str) -> tuple[ShorGate, ...]:
    return (ShorGate('CX', (a, b), stage), ShorGate('CCX', (control, b, a), stage),
            ShorGate('CX', (a, b), stage))


def controlled_modmul15(constant: int, control: int, work: Iterable[int],
                        *, stage: str = 'modexp') -> tuple[ShorGate, ...]:
    """Explicit controlled multiplication; invalid work value 15 is fixed.

    Multiplication by 2**k modulo 2**4-1 rotates four bits left by k.
    No period, factor, or exponent-register input is used in construction.
    """
    work = tuple(work)
    if constant not in (1, 2, 4, 8):
        raise ValueError('This mod-15 rotation multiplier supports constants 1, 2, 4, 8')
    if len(work) != 4 or len(set((control,) + work)) != 5 or any(type(q) is not int or q < 0 for q in (control,) + work):
        raise ValueError('Multiplier requires one control and four distinct work wires')
    swaps = {1: (), 2: ((2, 3), (1, 2), (0, 1)),
             4: ((0, 2), (1, 3)), 8: ((0, 1), (1, 2), (2, 3))}[constant]
    return tuple(g for i, j in swaps for g in _fredkin(control, work[i], work[j], stage))


def inverse_qft_gates(qubits: Iterable[int]) -> tuple[ShorGate, ...]:
    """Exact inverse Fourier transform for a little-endian integer register."""
    qubits = tuple(qubits)
    if not qubits or len(set(qubits)) != len(qubits) or any(type(q) is not int or q < 0 for q in qubits):
        raise ValueError('QFT requires distinct nonnegative wires')
    forward = []
    for target in range(len(qubits) - 1, -1, -1):
        forward.append(ShorGate('H', (qubits[target],), 'inverse_qft'))
        for control in range(target - 1, -1, -1):
            forward.append(ShorGate('CP', (qubits[control], qubits[target]), 'inverse_qft',
                                    math.pi / (1 << (target - control))))
    for i in range(len(qubits) // 2):
        forward.extend(_swap(qubits[i], qubits[-1 - i], 'inverse_qft'))
    return tuple(g.inverse() for g in reversed(forward))


def build_shor15(*, phase_bits: int = 8) -> Shor15Circuit:
    if type(phase_bits) is not int or not 4 <= phase_bits <= 10:
        raise ValueError('Reference phase width must be in [4, 10]')
    work = tuple(range(phase_bits, phase_bits + 4))
    constants = tuple(pow(2, 1 << i, 15) for i in range(phase_bits))
    gates = [ShorGate('X', (work[0],), 'initialize')]
    gates.extend(ShorGate('H', (q,), 'phase_prepare') for q in range(phase_bits))
    for q, constant in enumerate(constants):
        gates.extend(controlled_modmul15(constant, q, work))
    gates.extend(inverse_qft_gates(range(phase_bits)))
    return Shor15Circuit(phase_bits, tuple(gates), constants)


def basis_permutation_output(gates: Iterable[ShorGate], value: int) -> int:
    """Evaluate only the reversible X/CX/CCX basis mapping (never QFT)."""
    if type(value) is not int or value < 0:
        raise ValueError('Basis index must be a nonnegative integer')
    for gate in gates:
        if gate.name not in ('X', 'CX', 'CCX'):
            raise ValueError('Basis-permutation audit accepts X/CX/CCX only')
        if all(value >> q & 1 for q in gate.qubits[:-1]):
            value ^= 1 << gate.qubits[-1]
    return value


def apply_gates(state: np.ndarray, gates: Iterable[ShorGate]) -> np.ndarray:
    """Dense, phase-sensitive ideal reference, separate from the physical core."""
    state = np.array(state, dtype=complex, copy=True)
    if state.ndim != 1 or len(state) < 2 or len(state) & (len(state) - 1):
        raise ValueError('State must be a one-dimensional power-of-two vector')
    qubit_count = len(state).bit_length() - 1
    indices = np.arange(len(state))
    for gate in gates:
        if any(q >= qubit_count for q in gate.qubits):
            raise ValueError('Gate operand exceeds state dimension')
        if gate.name == 'CP':
            selected = ((indices >> gate.qubits[0]) & 1) & ((indices >> gate.qubits[1]) & 1)
            state[selected.astype(bool)] *= np.exp(1j * gate.angle_radians)
            continue
        target = gate.qubits[-1]
        mask = 1 << target
        selected = (indices & mask) == 0
        for q in gate.qubits[:-1]:
            selected &= ((indices >> q) & 1).astype(bool)
        low = indices[selected]
        high = low | mask
        a, b = state[low].copy(), state[high].copy()
        if gate.name == 'H':
            state[low], state[high] = (a + b) / math.sqrt(2), (a - b) / math.sqrt(2)
        else:
            state[low], state[high] = b, a
    return state


def simulate_shor15(circuit: Shor15Circuit | None = None) -> tuple[np.ndarray, np.ndarray]:
    circuit = circuit or build_shor15()
    state = np.zeros(1 << circuit.qubit_count, dtype=complex)
    state[0] = 1
    state = apply_gates(state, circuit.gates)
    probabilities = np.sum(abs(state.reshape(16, 1 << circuit.phase_bits)) ** 2, axis=0)
    return state, probabilities


def arithmetic_prefix(circuit: Shor15Circuit | None = None):
    """Export initialization/modexp to the existing exact Clifford+T frontend.

    The inverse QFT is deliberately excluded because its arbitrary-angle CP
    gates do not have an implemented Clifford+T synthesis contract.
    """
    from .shor_frontend import ArithmeticProgram
    circuit = circuit or build_shor15()
    wires = tuple(f'phase{i}' for i in range(circuit.phase_bits)) + tuple(f'work{i}' for i in range(4))
    return ArithmeticProgram(wires, tuple((g.name, g.qubits) for g in circuit.gates if g.stage != 'inverse_qft'),
                             'N=15,a=2 computed-constant controlled-bit-rotation preparation/modexp prefix')


def audit_shor15(circuit: Shor15Circuit | None = None) -> dict:
    """Compare explicit gates to arithmetic and an independent Fourier transform."""
    circuit = circuit or build_shor15()
    modmul_cases = 0
    for constant in sorted(set(circuit.modular_constants)):
        gates = controlled_modmul15(constant, 4, range(4))
        outputs = []
        for control in (0, 1):
            for work in range(16):
                basis = work | (control << 4)
                actual = basis_permutation_output(gates, basis)
                target = (constant * work) % 15 if control and work < 15 else work
                if actual != target | (control << 4):
                    raise AssertionError(f'Modular multiplication mismatch: {constant}, {control}, {work}')
                if basis_permutation_output(reversed(gates), actual) != basis:
                    raise AssertionError('Modular multiplier inverse mismatch')
                outputs.append(actual)
                modmul_cases += 1
        if len(set(outputs)) != 32:
            raise AssertionError('Modular multiplier is not a full-domain permutation')
    qsize = 1 << circuit.phase_bits
    prefix = tuple(g for g in circuit.gates if g.stage != 'inverse_qft')
    initial = np.zeros(16 * qsize, dtype=complex)
    initial[0] = 1
    actual_prefix = apply_gates(initial, prefix)
    expected_prefix = np.zeros((16, qsize), dtype=complex)
    for exponent in range(qsize):
        expected_prefix[pow(circuit.base, exponent, circuit.modulus), exponent] = 1 / math.sqrt(qsize)
    prefix_error = float(np.max(abs(actual_prefix - expected_prefix.ravel())))
    # np.fft.fft uses exp(-2*pi*i*x*y/Q), independently of the QFT gate recipe.
    expected_output = np.fft.fft(expected_prefix, axis=1) / math.sqrt(qsize)
    actual_output, probabilities = simulate_shor15(circuit)
    output_error = float(np.max(abs(actual_output - expected_output.ravel())))
    # This particular period can leave some QFT rotations inactive.  Test the
    # Fourier stage separately on a generic complex, work-entangled input so
    # a wrong rotation on an inactive algorithm branch cannot pass this audit.
    rng = np.random.default_rng(20261003)
    qft_probe = rng.normal(size=16 * qsize) + 1j * rng.normal(size=16 * qsize)
    qft_probe /= np.linalg.norm(qft_probe)
    expected_qft = (np.fft.fft(qft_probe.reshape(16, qsize), axis=1) / math.sqrt(qsize)).ravel()
    actual_qft = apply_gates(qft_probe, (g for g in circuit.gates if g.stage == 'inverse_qft'))
    qft_error = float(np.max(abs(actual_qft - expected_qft)))
    if max(prefix_error, output_error, qft_error) > 1e-12 or not np.isclose(probabilities.sum(), 1, atol=1e-12):
        raise AssertionError('Complete Shor amplitude/distribution validation failed')
    return {'modmul_control_work_cases': modmul_cases, 'exponent_cases': qsize,
            'statevector_amplitudes_checked': 16 * qsize,
            'modexp_amplitude_max_error': prefix_error, 'full_circuit_amplitude_max_error': output_error,
            'inverse_qft_entangled_probe_max_error': qft_error,
            'inverse_qft_probe_amplitudes_checked': 16 * qsize,
            'probability_sum': float(probabilities.sum()), 'passed': True}


def continued_fraction_convergents(numerator: int, denominator: int) -> tuple[tuple[int, int], ...]:
    if type(numerator) is not int or type(denominator) is not int or not 0 <= numerator < denominator:
        raise ValueError('Convergents require 0 <= numerator < positive denominator')
    result = []
    p0, p1, q0, q1 = 0, 1, 1, 0
    while denominator:
        term, remainder = divmod(numerator, denominator)
        p = term * p1 + p0
        q = term * q1 + q0
        result.append((p, q))
        p0, p1, q0, q1 = p1, p, q1, q
        numerator, denominator = denominator, remainder
    return tuple(result)


def _prime_divisors(value: int) -> tuple[int, ...]:
    divisors = []
    candidate = 2
    while candidate * candidate <= value:
        if value % candidate == 0:
            divisors.append(candidate)
            while value % candidate == 0:
                value //= candidate
        candidate += 1
    if value > 1:
        divisors.append(value)
    return tuple(divisors)


def validate_order(base: int, modulus: int, order: int) -> bool:
    """Verify minimal order, rather than accepting an arbitrary period multiple."""
    if any(type(v) is not int for v in (base, modulus, order)) or modulus <= 2 or order <= 0 or math.gcd(base, modulus) != 1:
        return False
    return pow(base, order, modulus) == 1 and all(pow(base, order // p, modulus) != 1 for p in _prime_divisors(order))


def postprocess_sample(outcome: int, *, phase_bits: int = 8, base: int = 2, modulus: int = 15) -> dict:
    """Recover factors only from a measured integer and checked convergents.

    A denominator failing pow(a, r, N)==1 is a failed shot.  No search over
    denominator multiples or precomputed period is used to rescue that shot.
    """
    if type(phase_bits) is not int or phase_bits < 1 or type(outcome) is not int or not 0 <= outcome < 1 << phase_bits:
        raise ValueError('Measurement integer must fit the phase register')
    if any(type(v) is not int for v in (base, modulus)) or modulus <= 2 or not 1 < base < modulus or math.gcd(base, modulus) != 1:
        raise ValueError('Postprocessing requires a coprime base inside (1, N)')
    convergents = continued_fraction_convergents(outcome, 1 << phase_bits)
    candidates = []
    result = {'outcome': outcome, 'phase_bits_little_endian': [(outcome >> i) & 1 for i in range(phase_bits)],
              'convergents': [list(pair) for pair in convergents], 'candidates': candidates,
              'order': None, 'factors': None, 'success': False, 'reason': 'zero_outcome' if outcome == 0 else 'order_not_recovered'}
    if outcome == 0:
        return result
    for numerator, denominator in convergents:
        if denominator >= modulus:
            break
        residue = pow(base, denominator, modulus)
        candidates.append({'numerator': numerator, 'denominator': denominator, 'modular_residue': residue})
        if residue != 1:
            continue
        order = denominator
        for prime in _prime_divisors(order):
            while order % prime == 0 and pow(base, order // prime, modulus) == 1:
                order //= prime
        if not validate_order(base, modulus, order):
            raise AssertionError('Candidate period reduction did not produce an exact order')
        result['order'] = order
        if order % 2:
            result['reason'] = 'odd_order'
            return result
        halfway = pow(base, order // 2, modulus)
        result['half_power_mod_N'] = halfway
        if halfway in (1, modulus - 1):
            result['reason'] = 'trivial_half_power'
            return result
        factors = sorted({math.gcd(halfway - 1, modulus), math.gcd(halfway + 1, modulus)})
        factors = [f for f in factors if 1 < f < modulus]
        if len(factors) == 2 and factors[0] * factors[1] == modulus:
            result.update(success=True, factors=factors, reason='factored')
        else:
            result['reason'] = 'trivial_factors'
        return result
    return result


def run_shor15(*, seed: int = 0, max_attempts: int = 16, phase_bits: int = 8,
               outcomes: Iterable[int] | None = None) -> dict:
    """Ideal independent shots with observable failures and bounded retry.

    outcomes is an explicit deterministic testing/replay hook.  By default
    every attempt is sampled from the complete gate-level output distribution.
    """
    if type(max_attempts) is not int or max_attempts <= 0:
        raise ValueError('max_attempts must be a positive integer')
    circuit = build_shor15(phase_bits=phase_bits)
    audit = audit_shor15(circuit)
    _, probabilities = simulate_shor15(circuit)
    rng = np.random.default_rng(seed)
    replay = iter(outcomes) if outcomes is not None else None
    attempts = []
    for _ in range(max_attempts):
        if replay is None:
            outcome = int(rng.choice(len(probabilities), p=probabilities / probabilities.sum()))
        else:
            try:
                outcome = next(replay)
            except StopIteration:
                break
        attempt = postprocess_sample(outcome, phase_bits=phase_bits, base=circuit.base, modulus=circuit.modulus)
        attempts.append(attempt)
        if attempt['success']:
            break
    success = bool(attempts and attempts[-1]['success'])
    return {'schema': 'shor15-result-v1', 'modulus': circuit.modulus, 'base': circuit.base,
            'seed': seed, 'qubits': circuit.qubit_count, 'phase_bits': phase_bits,
            'gate_counts': dict(Counter(g.name for g in circuit.gates)), 'gate_count': len(circuit.gates),
            'modular_constants': list(circuit.modular_constants), 'audit': audit,
            'nonzero_phase_distribution': [{'outcome': i, 'probability': float(p)} for i, p in enumerate(probabilities) if p > 1e-14],
            'sample_mode': 'explicit_replay' if replay is not None else 'seeded_ideal_sampling',
            'attempts': attempts, 'max_attempts': max_attempts, 'success': success,
            'order': attempts[-1]['order'] if success else None,
            'factors': attempts[-1]['factors'] if success else None,
            'scope': 'complete ideal unencoded Shor logical reference',
            'encoding_target': {'code_distance': 3, 'data_per_patch': 9, 'syndrome_per_patch': 8,
                                'algorithm_patches': circuit.qubit_count, 'base_patch_atoms': 17 * circuit.qubit_count,
                                'magic_and_bus_atoms': None, 'physical_atom_peak': None},
            'clifford_t_compiled': False, 'pbc_compiled': False, 'encoded': False, 'physical_executed': False,
            'limitations': ['Exact QFT CP rotations require future Clifford+T synthesis and an error budget.',
                            'No encoded PBC, magic production, decoder, transport or Executor evidence.']}
