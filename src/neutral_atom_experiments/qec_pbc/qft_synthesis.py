"""Pinned gridsynth integration for complete Shor Clifford+T approximation.

No order-dependent QFT deletion. Global phases from CP decomposition and
gridsynth are retained outside the existing integer-phase Pauli frontend.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version
import math

import numpy as np

from .logical_pauli import LogicalGate, compile_logical_pauli
from .shor15 import Shor15Circuit, apply_gates, build_shor15
from .shor_frontend import ArithmeticProgram, expand_clifford_t

_M = {'H': np.array([[1, 1], [1, -1]]) / math.sqrt(2),
      'X': np.array([[0, 1], [1, 0]]), 'S': np.diag([1, 1j]),
      'Sdg': np.diag([1, -1j]), 'T': np.diag([1, np.exp(1j * math.pi / 4)]),
      'Tdg': np.diag([1, np.exp(-1j * math.pi / 4)])}


@lru_cache(maxsize=128)
def _rz_synthesis(theta: float, epsilon: float, seed: int) -> tuple[tuple[str, ...], float, float]:
    eighths = round(theta / (math.pi / 4))
    if abs(theta - eighths * math.pi / 4) < 1e-14:
        names = ('T' if eighths >= 0 else 'Tdg',) * abs(eighths)
        phase = (-eighths * math.pi / 8) % (2 * math.pi)
        unitary = np.eye(2, dtype=complex)
        for name in names:
            unitary = _M[name] @ unitary
        target = np.diag([np.exp(-1j * theta / 2), np.exp(1j * theta / 2)])
        return names, phase, float(np.linalg.norm(np.exp(1j * phase) * unitary - target, ord=2))
    try:
        import mpmath
        from pygridsynth.gridsynth import gridsynth_circuit
    except ImportError as error:
        raise ImportError('Install pinned requirements-qft-synthesis.txt in an isolated dependency directory') from error
    if version('pygridsynth') != '1.2.0':
        raise ValueError('Only audited pygridsynth==1.2.0 is supported')
    with mpmath.workdps(80):
        circuit = gridsynth_circuit(theta=mpmath.mpf(repr(theta)), epsilon=mpmath.mpf(repr(epsilon)),
                                    seed=seed, dps=80, up_to_phase=False)
        # Upstream QuantumCircuit multiplies gates from the right. Our IR is
        # chronological, so reverse it. W is a scalar phase, not a qubit gate.
        names = []
        phase = circuit.phase
        for gate in reversed(circuit):
            name = gate.to_simple_str()
            if name == 'W':
                phase += mpmath.mp.pi / 4
            elif name in ('H', 'T', 'S', 'X'):
                names.append(name)
            else:
                raise ValueError(f'Unsupported gridsynth gate {name!r}')
        phase = float(phase % (2 * mpmath.mp.pi))
    unitary = np.eye(2, dtype=complex)
    for name in names:
        unitary = _M[name] @ unitary
    unitary *= np.exp(1j * phase)
    target = np.diag([np.exp(-1j * theta / 2), np.exp(1j * theta / 2)])
    error = float(np.linalg.norm(unitary - target, ord=2))
    if error > epsilon + 1e-12:
        raise AssertionError('gridsynth output failed independent phase-sensitive operator verification')
    return tuple(names), phase, error


@dataclass(frozen=True)
class SynthesizedShor15:
    source: Shor15Circuit
    wires: tuple[str, ...]
    gates: tuple[LogicalGate, ...]
    global_phase_radians: float
    total_error_budget: float
    local_error_budget: float
    rz_certificates: tuple[dict, ...]
    source_gate_spans: tuple[dict, ...]

    def compile_pauli(self):
        """Normalize CT gates; caller must retain external global_phase_radians."""
        return compile_logical_pauli(self.gates, wires=self.wires)

    def to_dict(self) -> dict:
        counts = Counter(g.name for g in self.gates)
        return {'schema': 'shor15-clifford-t-synthesis-v1', 'modulus': self.source.modulus, 'base': self.source.base,
                'wires': list(self.wires), 'bit_order': 'little-endian wire index, matching source Shor15Circuit',
                'gates': [{'name': g.name, 'wires': list(g.wires)} for g in self.gates],
                'global_phase_radians': self.global_phase_radians,
                'unitary_convention': 'U_approx=exp(i*global_phase_radians)*chronological_CT_gate_product',
                'pauli_frontend_contract': 'compile_pauli() excludes the external global phase; preserve it in the wrapper',
                'gate_counts': dict(counts), 'gate_count': len(self.gates),
                't_resource_consumptions': counts['T'] + counts['Tdg'],
                'qft_cp_count': len(self.rz_certificates) // 3, 'rz_synthesis_count': len(self.rz_certificates),
                'total_operator_error_budget': self.total_error_budget, 'local_operator_error_budget': self.local_error_budget,
                'telescoping_design_bound': self.local_error_budget * len(self.rz_certificates),
                'measured_local_error_sum': sum(c['operator_error'] for c in self.rz_certificates),
                'rz_certificates': list(self.rz_certificates), 'source_gate_spans': list(self.source_gate_spans),
                'synthesizer': {'package': 'pygridsynth', 'version': '1.2.0', 'license': 'MIT', 'up_to_phase': False},
                'complete_shor_clifford_t': True, 'encoded': False, 'physical_executed': False,
                'magic_buffer_peak': None, 'physical_atom_peak': None}


def synthesize_shor15(circuit: Shor15Circuit | None = None, *, total_error_budget: float = 1e-3,
                      seed: int = 7) -> SynthesizedShor15:
    circuit = circuit or build_shor15()
    if not math.isfinite(total_error_budget) or not 1e-8 <= total_error_budget <= 0.1:
        raise ValueError('Total operator error budget must be in [1e-8, 0.1]')
    wires = tuple(f'phase{i}' for i in range(circuit.phase_bits)) + tuple(f'work{i}' for i in range(4))
    cp_count = sum(g.name == 'CP' for g in circuit.gates)
    local_budget = total_error_budget / (6 * cp_count) if cp_count else total_error_budget
    gates, certificates, spans = [], [], []
    phase = 0.0
    for source_index, gate in enumerate(circuit.gates):
        begin = len(gates)
        if gate.name != 'CP':
            arithmetic = ArithmeticProgram(wires, ((gate.name, gate.qubits),), 'explicit source Shor15 gate')
            gates.extend(expand_clifford_t(arithmetic))
        else:
            c, t = gate.qubits
            theta = gate.angle_radians
            phase += theta / 4
            # CP(theta)=exp(i theta/4) Rz_c(theta/2) Rz_t(theta/2)
            #          CX(c,t) Rz_t(-theta/2) CX(c,t), chronologically.
            recipe = ((c, theta / 2), (t, theta / 2), None, (t, -theta / 2), None)
            for item in recipe:
                if item is None:
                    gates.append(LogicalGate('CX', (wires[c], wires[t])))
                    continue
                q, angle = item
                names, local_phase, error = _rz_synthesis(angle, local_budget, seed)
                rz_begin = len(gates)
                gates.extend(LogicalGate(name, (wires[q],)) for name in names)
                phase += local_phase
                certificates.append({'source_gate_index': source_index, 'source_cp_angle_radians': theta,
                                     'wire': wires[q], 'rz_angle_radians': angle,
                                     'global_phase_radians': local_phase, 'operator_error': error,
                                     'gate_span': [rz_begin, len(gates)]})
        spans.append({'source_gate_index': source_index, 'stage': gate.stage, 'name': gate.name,
                      'source_cp_angle_radians': gate.angle_radians, 'gate_span': [begin, len(gates)]})
    return SynthesizedShor15(circuit, wires, tuple(gates), phase % (2 * math.pi), total_error_budget,
                            local_budget, tuple(certificates), tuple(spans))


def apply_synthesized(program: SynthesizedShor15, state: np.ndarray, *, stage: str | None = None) -> np.ndarray:
    """Little-endian reference; optional stage applies its matching global phase."""
    result = np.array(state, dtype=complex, copy=True)
    if result.ndim != 1 or len(result) & (len(result) - 1):
        raise ValueError('State must be a power-of-two vector')
    indices = np.arange(len(result))
    phase = program.global_phase_radians
    selected = program.gates
    if stage is not None:
        spans = [span for span in program.source_gate_spans if span['stage'] == stage]
        selected = tuple(g for span in spans for g in program.gates[slice(*span['gate_span'])])
        ids = {span['source_gate_index'] for span in spans}
        phase = sum(c['global_phase_radians'] for c in program.rz_certificates if c['source_gate_index'] in ids)
        phase += sum(span['source_cp_angle_radians'] / 4 for span in spans if span['name'] == 'CP')
    for gate in selected:
        qs = tuple(program.wires.index(w) for w in gate.wires)
        if gate.name == 'CX':
            target = indices ^ (((indices >> qs[0]) & 1) << qs[1])
            result = result[target]
            continue
        q = qs[0]
        low = indices[(indices & (1 << q)) == 0]
        high = low | (1 << q)
        a, b = result[low].copy(), result[high].copy()
        matrix = _M[gate.name]
        result[low], result[high] = matrix[0, 0] * a + matrix[0, 1] * b, matrix[1, 0] * a + matrix[1, 1] * b
    return np.exp(1j * phase) * result


def audit_qft_synthesis(program: SynthesizedShor15) -> dict:
    """Complete phase-register operator, plus arbitrary entangled/full-state probes."""
    n = program.source.phase_bits
    size = 1 << n
    approximate = np.column_stack([apply_synthesized(program, np.eye(size, dtype=complex)[:, i], stage='inverse_qft') for i in range(size)])
    exact = np.fft.fft(np.eye(size), axis=0) / math.sqrt(size)
    operator_error = float(np.linalg.norm(approximate - exact, ord=2))
    rng = np.random.default_rng(20261003)
    probe = rng.normal(size=16 * size) + 1j * rng.normal(size=16 * size)
    probe /= np.linalg.norm(probe)
    target = (np.fft.fft(probe.reshape(16, size), axis=1) / math.sqrt(size)).ravel()
    qft_probe_error = float(np.linalg.norm(apply_synthesized(program, probe, stage='inverse_qft') - target))
    full_target = apply_gates(probe, program.source.gates)
    full_error = float(np.linalg.norm(apply_synthesized(program, probe) - full_target))
    if max(operator_error, qft_probe_error, full_error) > program.total_error_budget:
        raise AssertionError('Complete QFT/entangled/full Shor synthesis exceeded total error budget')
    return {'passed': True, 'scope': 'complete ideal unencoded Clifford+T synthesis',
            'qft_operator_columns_checked': size, 'qft_operator_error': operator_error,
            'qft_entangled_probe_l2_error': qft_probe_error, 'full_shor_probe_l2_error': full_error,
            'total_error_budget': program.total_error_budget,
            't_resource_consumptions': sum(g.name in ('T', 'Tdg') for g in program.gates),
            'encoded': False, 'physical_executed': False}


def audit_complete_shor_pbc(program: SynthesizedShor15, *, seed: int = 7,
                            reference_qubits: int = 1, include_measurement_records: bool = False) -> dict:
    """Execute every magic measurement for zero input and an entangled probe.

    Array bit reversal converts the Shor little-endian convention to the
    adaptive executor's big-endian data/reference convention and back.  The
    arbitrary external global phase is then actually applied to the output.
    """
    from .adaptive_pbc import compile_adaptive_pbc, execute_reference
    if type(reference_qubits) is not int or reference_qubits < 1:
        raise ValueError('Generic channel probe requires at least one reference qubit')
    pauli = program.compile_pauli()
    adaptive = compile_adaptive_pbc(pauli, resource_quality='ideal_reference',
                                    resource_provenance='Explicit external ideal resource vectors; no physical preparation')
    cases = []
    rng = np.random.default_rng(seed)
    for name, reference in (('algorithm_zero_input', 0), ('generic_entangled_probe', reference_qubits)):
        total = len(program.wires) + reference
        dimension = 1 << total
        state = np.zeros(dimension, dtype=complex)
        if reference:
            state = rng.normal(size=dimension) + 1j * rng.normal(size=dimension)
            state /= np.linalg.norm(state)
        else:
            state[0] = 1
        indices = np.arange(dimension)
        reversed_indices = np.zeros(dimension, dtype=np.int64)
        for bit in range(total):
            reversed_indices |= ((indices >> bit) & 1) << (total - 1 - bit)
        actual = execute_reference(adaptive, state[reversed_indices], reference_qubits=reference, seed=seed)
        output = actual.state[reversed_indices] * np.exp(1j * program.global_phase_radians)
        phase = np.exp(1j * math.pi * actual.branch_global_phase_eighth_turns / 8)
        ideal_synthesis = apply_synthesized(program, state)
        exact_source = apply_gates(state, program.source.gates)
        instrument_error = float(np.linalg.norm(output - phase * ideal_synthesis))
        algorithm_error = float(np.linalg.norm(output - phase * exact_source))
        # Reference is a high-bit spectator register in little-endian arrays.
        p_actual = np.sum(abs(output.reshape(-1, 16, 1 << program.source.phase_bits)) ** 2, axis=(0, 1))
        p_exact = np.sum(abs(exact_source.reshape(-1, 16, 1 << program.source.phase_bits)) ** 2, axis=(0, 1))
        total_variation = float(np.sum(abs(p_actual - p_exact)) / 2)
        if instrument_error > 2e-11 or algorithm_error > program.total_error_budget or total_variation > program.total_error_budget:
            raise AssertionError('Full Shor resource-measurement execution failed instrument/algorithm budget')
        case = {'name': name, 'reference_qubits': reference, 'state_dimension': dimension,
                'magic_consumptions': len(adaptive.injections), 'measurements': len(actual.measurement_records),
                'instrument_l2_error': instrument_error, 'exact_shor_l2_error': algorithm_error,
                'phase_distribution_total_variation': total_variation,
                'branch_global_phase_eighth_turns': actual.branch_global_phase_eighth_turns,
                'log2_branch_probability': -2 * len(adaptive.injections),
                'all_resources_consumed': all(r['final_status'] == 'consumed' for r in actual.resource_lifecycle),
                'external_global_phase_radians_applied': program.global_phase_radians}
        if include_measurement_records:
            case['measurement_records'] = list(actual.measurement_records)
            case['resource_lifecycle'] = list(actual.resource_lifecycle)
        cases.append(case)
    return {'passed': True, 'scope': 'complete ideal unencoded Shor Clifford+T to adaptive resource measurement execution',
            'total_error_budget': program.total_error_budget, 'resource_consumptions': len(adaptive.injections),
            'measurement_count_per_execution': 2 * len(adaptive.injections), 'cases': cases,
            'source_cp_gates_retained': len(program.rz_certificates) // 3,
            'encoded_resource_preparation': False, 'encoded': False, 'physical_executed': False}


def main():
    """Export a reviewable second-stage complete logical compilation bundle."""
    import argparse
    import json
    from pathlib import Path
    from .adaptive_pbc import compile_adaptive_pbc
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--epsilon', type=float, default=1e-3)
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    program = synthesize_shor15(total_error_budget=args.epsilon, seed=args.seed)
    pauli = program.compile_pauli()
    adaptive = compile_adaptive_pbc(pauli, resource_quality='ideal_reference')
    report = {'synthesis': audit_qft_synthesis(program),
              'adaptive_pbc': audit_complete_shor_pbc(program, seed=args.seed, include_measurement_records=True)}
    args.output.mkdir(parents=True, exist_ok=True)
    documents = {'clifford_t.json': program.to_dict(), 'logical_pauli.json': pauli.to_dict(),
                 'adaptive_pbc.json': adaptive.to_dict(), 'audit.json': report}
    for name, document in documents.items():
        (args.output / name).write_text(json.dumps(document, indent=2), encoding='utf-8')
    summary = dict(report['adaptive_pbc'])
    summary['cases'] = [{k: v for k, v in case.items() if k not in ('measurement_records', 'resource_lifecycle')}
                        for case in report['adaptive_pbc']['cases']]
    print(json.dumps({'synthesis': report['synthesis'], 'adaptive_pbc': summary,
                      'output': str(args.output.resolve())}, indent=2))


if __name__ == '__main__':
    main()
