"""Complete ideal Shor shots from PBC resources through phase readout/retry.

Each attempt starts a new logical zero register and fresh ideal resources.
All resource projections, feedforward, residual Clifford, external global
phase, eight final Z projections, and classical order verification execute.
This is an unencoded reference, never a physical or magic-factory claim.
"""
from collections.abc import Iterable
import math

import numpy as np

from .adaptive_pbc import compile_adaptive_pbc, execute_reference
from .qft_synthesis import SynthesizedShor15, synthesize_shor15
from .shor15 import postprocess_sample


def run_shor15_pbc(program: SynthesizedShor15 | None = None, *, seed=7,
                   max_attempts=16, outcomes: Iterable[int] | None = None,
                   include_measurement_records=False):
    if type(seed) is not int or seed < 0:
        raise ValueError('Nonnegative integer seed required')
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError('Positive integer max_attempts required')
    program = program or synthesize_shor15(seed=seed)
    if not isinstance(program, SynthesizedShor15):
        raise TypeError('SynthesizedShor15 required')
    adaptive = compile_adaptive_pbc(program.compile_pauli(), resource_quality='ideal_reference',
        resource_provenance='Fresh ideal logical resources per actual Shor attempt; no encoded factory')
    width = len(program.wires)
    dimension = 1 << width
    indices = np.arange(dimension)
    reverse = np.zeros(dimension, dtype=np.int64)
    for bit in range(width):
        reverse |= ((indices >> bit) & 1) << (width - 1 - bit)
    phase_bits = program.source.phase_bits
    rng, replay = np.random.default_rng(seed), iter(outcomes) if outcomes is not None else None
    attempts = []
    for attempt_number in range(1, max_attempts+1):
        if replay is not None:
            try:
                supplied = next(replay)
            except StopIteration:
                break
            if type(supplied) is not int or not 0 <= supplied < (1 << phase_bits):
                raise ValueError('Phase readout replay must contain in-range integer outcomes')
        initial = np.zeros(dimension, dtype=complex)
        initial[0] = 1
        instrument = execute_reference(adaptive, initial, seed=seed+attempt_number-1)
        state = instrument.state[reverse] * np.exp(1j * program.global_phase_radians)
        probabilities = np.sum(abs(state.reshape(16, 1 << phase_bits))**2, axis=0)
        probabilities /= probabilities.sum()
        outcome = supplied if replay is not None else int(rng.choice(len(probabilities), p=probabilities))
        if probabilities[outcome] < 1e-30:
            raise ValueError('Phase readout replay selects an impossible output branch')
        readout, log2_readout = [], 0.
        for bit in range(phase_bits):
            value = (outcome >> bit) & 1
            matching = ((indices >> bit) & 1) == value
            probability = float(np.sum(abs(state[matching])**2))
            if probability <= 0:
                raise AssertionError('Final phase projection is impossible')
            state = np.where(matching, state, 0) / math.sqrt(probability)
            log2_readout += math.log2(probability)
            readout.append({'id': f'phase.m{bit}', 'wire': program.wires[bit], 'basis': 'Z',
                'bit': value, 'conditional_probability': probability, 'projected': True})
        classical = postprocess_sample(outcome, phase_bits=phase_bits,
            base=program.source.base, modulus=program.source.modulus)
        record = {'attempt': attempt_number, 'resource_instance_namespace': f'shot{attempt_number}',
            'fresh_logical_zero_input': True, 'ideal_resource_consumptions': len(adaptive.injections),
            'resource_measurement_count': len(instrument.measurement_records),
            'all_resources_consumed': all(r['final_status'] == 'consumed' for r in instrument.resource_lifecycle),
            'phase_readout': readout, 'phase_outcome': outcome,
            'phase_outcome_probability': float(probabilities[outcome]),
            'log2_resource_branch_probability': -2*len(adaptive.injections),
            'log2_phase_readout_probability': log2_readout,
            'external_global_phase_radians_applied': program.global_phase_radians,
            'projected_state_norm': float(np.linalg.norm(state)),
            'projected_phase_register_verified': bool(np.all(abs(state[(indices & ((1 << phase_bits)-1)) != outcome]) == 0)),
            'classical_postprocessing': classical}
        if include_measurement_records:
            record['resource_measurement_records'] = list(instrument.measurement_records)
            record['resource_lifecycle'] = list(instrument.resource_lifecycle)
        attempts.append(record)
        if classical['success']:
            break
    success = bool(attempts and attempts[-1]['classical_postprocessing']['success'])
    classical = attempts[-1]['classical_postprocessing'] if success else {}
    return {'schema': 'shor15-complete-pbc-run/1',
        'scope': 'complete synthesized ideal unencoded PBC Shor, actual final projections and validated retry',
        'seed': seed, 'modulus': program.source.modulus, 'base': program.source.base,
        'operator_error_budget': program.total_error_budget,
        'attempts': attempts, 'max_attempts': max_attempts, 'success': success,
        'order': classical.get('order'), 'factors': classical.get('factors'),
        'total_resource_consumptions': sum(a['ideal_resource_consumptions'] for a in attempts),
        'total_resource_measurements': sum(a['resource_measurement_count'] for a in attempts),
        'total_phase_measurements': sum(len(a['phase_readout']) for a in attempts),
        'clifford_t_compiled': True, 'pbc_executed': True, 'encoded': False,
        'encoded_resource_preparation': False, 'physical_executed': False}
