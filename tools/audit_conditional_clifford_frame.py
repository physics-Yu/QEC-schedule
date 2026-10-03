"""Audit a supplied complete Shor CT export; no synthesis install or ENV import."""
from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
import math
from pathlib import Path

import numpy as np

from neutral_atom_experiments.qec_pbc.adaptive_pbc import compile_adaptive_pbc
from neutral_atom_experiments.qec_pbc.conditional_clifford_frame import (
    audit_deferred_program, execute_deferred_reference, execute_terminal_z, framed_inventory)
from neutral_atom_experiments.qec_pbc.logical_pauli import LogicalGate
from neutral_atom_experiments.qec_pbc.qft_synthesis import SynthesizedShor15, apply_synthesized
from neutral_atom_experiments.qec_pbc.shor15 import apply_gates, build_shor15, postprocess_sample


def load_synthesis(path):
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get('schema') != 'shor15-clifford-t-synthesis-v1' or data.get('modulus') != 15 or data.get('base') != 2:
        raise ValueError('Input must be the complete N=15, a=2 Shor CT export')
    source = build_shor15()
    wires = tuple(data['wires'])
    expected_wires = tuple(f'phase{i}' for i in range(8)) + tuple(f'work{i}' for i in range(4))
    gates = tuple(LogicalGate(g['name'], tuple(g['wires'])) for g in data['gates'])
    if wires != expected_wires or data['gate_count'] != len(gates) or any(not set(g.wires).issubset(wires) for g in gates):
        raise ValueError('Complete Shor wire order/gate count is inconsistent')
    spans, certificates = tuple(data['source_gate_spans']), tuple(data['rz_certificates'])
    if len(spans) != len(source.gates) or len(certificates) != 84:
        raise ValueError('All 72 source gates and all 28 CP decompositions must remain explicit')
    position = 0
    for index, (span, gate) in enumerate(zip(spans, source.gates)):
        begin, end = span['gate_span']
        if (span['source_gate_index'] != index or span['name'] != gate.name or span['stage'] != gate.stage or
                span['source_cp_angle_radians'] != gate.angle_radians or begin != position or not begin <= end <= len(gates)):
            raise ValueError('Source provenance spans are inconsistent')
        position = end
    if position != len(gates) or data['qft_cp_count'] != 28:
        raise ValueError('CT export is truncated or omitted a source CP')
    phase, budget, local = (float(data[k]) for k in ('global_phase_radians', 'total_operator_error_budget', 'local_operator_error_budget'))
    if any(not math.isfinite(v) for v in (phase, budget, local)) or not 0 < local * len(certificates) <= budget:
        raise ValueError('Synthesis phase/error budget is invalid')
    if sum(c['operator_error'] for c in certificates) > budget:
        raise ValueError('Source synthesis certificates exceed the stated budget')
    return SynthesizedShor15(source, wires, gates, phase, budget, local, certificates, spans), sha256(raw).hexdigest()


def reverse_indices(dimension):
    indices = np.arange(dimension)
    reversed_indices = np.zeros(dimension, dtype=np.int64)
    for bit in range(dimension.bit_length() - 1):
        reversed_indices |= ((indices >> bit) & 1) << (dimension.bit_length() - 2 - bit)
    return reversed_indices


def audit_complete_frame(synthesis, *, seed=7, include_measurement_records=False):
    source = synthesis.compile_pauli()
    if len(source.rotations) != 3500:
        raise ValueError('This checkpoint audit requires the actual default 3500-resource CT export')
    rng = np.random.default_rng(seed)
    cases = []
    for name, refs in (('algorithm_zero_input', 0), ('generic_entangled_probe', 1)):
        dim = 1 << (len(source.wires) + refs)
        psi = np.zeros(dim, dtype=complex)
        if refs:
            psi = rng.normal(size=dim) + 1j * rng.normal(size=dim)
            psi /= np.linalg.norm(psi)
        else:
            psi[0] = 1
        reverse = reverse_indices(dim)
        ct_target = apply_synthesized(synthesis, psi)
        actual, audit = audit_deferred_program(source, input_state=psi[reverse], reference_qubits=refs,
                seed=seed, expected_state=ct_target[reverse],
                external_global_phase_radians=synthesis.global_phase_radians,
                include_measurement_records=include_measurement_records)
        output = actual.realize(external_global_phase_radians=synthesis.global_phase_radians)[reverse]
        branch_phase = np.exp(1j * np.pi * actual.branch_global_phase_eighth_turns / 8)
        exact = apply_gates(psi, synthesis.source.gates)
        error = float(np.linalg.norm(output - branch_phase * exact))
        p = np.sum(abs(output.reshape(-1, 16, 256)) ** 2, axis=(0, 1))
        p_exact = np.sum(abs(exact.reshape(-1, 16, 256)) ** 2, axis=(0, 1))
        tv = float(np.sum(abs(p - p_exact)) / 2)
        if max(error, tv) > synthesis.total_error_budget:
            raise AssertionError('Deferred complete Shor exceeded the original total error budget')
        labels = actual.terminal_z_labels(synthesis.wires[:8])
        measured, records = execute_terminal_z(actual, synthesis.wires[:8], seed=seed)
        # Independent semantic-output Z projections check terminal instrument.
        expected = actual.realize()
        terminal_error = 0.0
        for i, record in enumerate(records):
            indices = np.arange(dim)
            bit = (indices >> (len(source.wires) + refs - 1 - i)) & 1
            projected = np.where(bit == record['outcome'], expected, 0)
            probability = float(np.vdot(projected, projected).real)
            terminal_error = max(terminal_error, abs(probability - record['conditional_probability']))
            expected = projected / math.sqrt(probability)
        terminal_error = max(terminal_error, float(np.linalg.norm(measured.realize() - expected)))
        if terminal_error > 2e-11:
            raise AssertionError('Deferred terminal Z instrument disagrees with semantic Z projections')
        audit.update({'name': name, 'exact_shor_l2_error': error, 'phase_distribution_total_variation': tv,
                      'terminal_instrument_error': terminal_error,
                      'terminal_z_labels': [p.to_dict() for p in labels], 'terminal_measurements': list(records),
                      'sampled_phase_integer': sum(record['outcome'] << i for i, record in enumerate(records))})
        if not refs:
            audit['classical_postprocessing'] = postprocess_sample(audit['sampled_phase_integer'])
        cases.append(audit)
    return {'passed': True, 'scope': 'full Shor ideal deferred-frame resource instrument and terminal projections',
            'seed': seed, 'source_cp_gates_retained': 28, 'resource_consumptions_per_case': 3500,
            'total_error_budget': synthesis.total_error_budget, 'cases': cases,
            'encoded': False, 'fault_tolerant': False, 'physical_executed': False, 'native_s_implemented': False}


def run_deferred_shor15(synthesis, *, seed=7, max_attempts=16, include_measurement_records=False):
    """Fresh framed quantum shots -> actual terminal projections -> CF/GCD.

    No eager or exact-circuit probabilities are used to select measurements.
    The CT unitary is evaluated once solely as a phase-sensitive audit oracle.
    """
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError('max_attempts must be a positive integer')
    source = synthesis.compile_pauli()
    base = compile_adaptive_pbc(source, resource_quality='ideal_reference')
    dim = 1 << len(source.wires)
    psi = np.zeros(dim, dtype=complex)
    psi[0] = 1
    reverse = reverse_indices(dim)
    expected = apply_synthesized(synthesis, psi)[reverse]
    attempts = []
    for attempt in range(max_attempts):
        namespace = f'shot.{attempt:03d}.'
        program = replace(base, injections=tuple(replace(injection,
                    resource=replace(injection.resource, wire=namespace + injection.resource.wire),
                    joint_measurement_id=namespace + injection.joint_measurement_id,
                    resource_measurement_id=namespace + injection.resource_measurement_id)
                    for injection in base.injections))
        # A fresh controller, vector and resource scope are allocated each shot.
        actual = execute_deferred_reference(program, psi, seed=seed + attempt)
        output = actual.realize(external_global_phase_radians=synthesis.global_phase_radians)
        phase = np.exp(1j * np.pi * actual.branch_global_phase_eighth_turns / 8)
        error = float(np.linalg.norm(output - phase * expected))
        if error > 2e-11:
            raise AssertionError('Fresh deferred Shor shot disagrees with CT unitary oracle')
        _, terminal = execute_terminal_z(actual, source.wires[:8], seed=seed + attempt)
        outcome = sum(record['outcome'] << bit for bit, record in enumerate(terminal))
        classical = postprocess_sample(outcome)
        entry = {'attempt': attempt + 1, 'seed': seed + attempt, 'namespace': namespace,
                 'resource_consumptions': len(program.injections), 'measurement_count': len(actual.measurement_records),
                 'instrument_source_l2_error': error, 'framed_inventory': framed_inventory(actual),
                 'terminal_measurements': list(terminal), 'classical_postprocessing': classical,
                 'sampling_source': 'actual pulled-back terminal projectors on the unrealized framed vector'}
        if include_measurement_records:
            entry.update(measurement_records=list(actual.measurement_records),
                         resource_lifecycle=list(actual.resource_lifecycle), frame=actual.frame.to_dict())
        attempts.append(entry)
        if classical['success']:
            break
    final = attempts[-1]['classical_postprocessing']
    return {'scope': 'full ideal deferred-frame Shor quantum instrument plus measured CF/order/GCD and bounded retry',
            'success': final['success'], 'factors': final['factors'], 'order': final['order'],
            'seed': seed, 'max_attempts': max_attempts, 'attempts': attempts,
            'total_resource_consumptions': sum(a['resource_consumptions'] for a in attempts),
            'total_terminal_measurements': sum(len(a['terminal_measurements']) for a in attempts),
            'encoded': False, 'fault_tolerant': False, 'physical_executed': False, 'native_s_implemented': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Complete Shor CT synthesis JSON export')
    parser.add_argument('--output', type=Path, help='New audit JSON path; existing files are never replaced')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--include-measurement-records', action='store_true')
    parser.add_argument('--max-attempts', type=int, default=16)
    args = parser.parse_args()
    program, fingerprint = load_synthesis(args.input)
    result = audit_complete_frame(program, seed=args.seed, include_measurement_records=args.include_measurement_records)
    result['algorithm_shots'] = run_deferred_shor15(program, seed=args.seed, max_attempts=args.max_attempts,
                                  include_measurement_records=args.include_measurement_records)
    result['input_sha256'] = fingerprint
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(encoded)
        print(json.dumps({'passed': result['passed'], 'output': str(args.output),
                          'shor_success': result['algorithm_shots']['success'],
                          'factors': result['algorithm_shots']['factors'],
                          'shot_outcomes': [a['classical_postprocessing']['outcome'] for a in result['algorithm_shots']['attempts']],
                          'cases': [{k: c[k] for k in ('name', 'deferred_eager_l2_error', 'source_l2_error', 'exact_shor_l2_error', 'framed_inventory')} for c in result['cases']]}))
    else:
        print(encoded, end='')


if __name__ == '__main__':
    main()
