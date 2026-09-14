"""Ideal-code checks separate from physical routing/trace acceptance."""
from math import isclose, sqrt

import pytest

from neutral_atom_env.experiments.surface_ghz import (
    X_CHECKS, LOGICAL_X, encoder, experiment_input, mask, verify,
    verify_gate_sequence,
)
from neutral_atom_env.visualization.workbench import validate_input


@pytest.mark.parametrize('plus', [False, True])
def test_encoder_dense_state_matches_css_coset_definition(plus):
    # Dense amplitudes are an independent oracle for the signed-Pauli engine.
    state = [0.0] * 512
    state[0] = 1.0
    for kind, qs in encoder(plus):
        updated = [0.0] * 512
        for value, amplitude in enumerate(state):
            if kind == 'H':
                bit = 1 << qs[0]
                updated[value & ~bit] += amplitude / sqrt(2)
                updated[value | bit] += amplitude * (-1 if value & bit else 1) / sqrt(2)
            else:
                target = value ^ (1 << qs[1]) if value >> qs[0] & 1 else value
                updated[target] += amplitude
        state = updated
    rows = [mask(qs) for qs in X_CHECKS] + ([mask(LOGICAL_X)] if plus else [])
    support = {0}
    for row in rows:
        support |= {value ^ row for value in support}
    assert len(support) == (32 if plus else 16)
    for value, amplitude in enumerate(state):
        assert isclose(amplitude, 1 / sqrt(len(support)) if value in support else 0,
                       abs_tol=1e-12)


def test_distance_and_all_signed_logical_ghz_stabilizers():
    report = verify()
    assert report['distance_exhaustively_verified'] == 3
    assert report['independent_target_stabilizers'] == 36
    assert report['native_CZ'] == 59
    assert report['native_H'] == 135
    assert report['negative_control_missing_last_layer'] == 'rejected'


@pytest.mark.parametrize('compiler', ['row_symmetric', 'row_greedy'])
def test_editable_experiment_uses_valid_schema_and_reordering_preserves_state(compiler):
    raw = experiment_input(compiler)
    value = validate_input(raw)
    assert (value['atom_count'], value['layout'], value['aod_traps']) == (36, 'row', 36)
    assert len(value['gates']) == 194
    assert verify_gate_sequence(value['gates'])
    # Editing out an entangler must not silently retain a success label.
    cz = next(i for i, gate in enumerate(value['gates']) if gate['gate_type'] == 'CZ')
    assert not verify_gate_sequence(value['gates'][:cz] + value['gates'][cz+1:])


def test_two_comparison_inputs_differ_only_in_policy_and_are_fresh():
    baseline = experiment_input('row_symmetric')
    planner = experiment_input('row_greedy')
    assert {k: v for k, v in baseline.items() if k != 'compiler'} == {
        k: v for k, v in planner.items() if k != 'compiler'}
    baseline['gates'].clear()
    assert len(experiment_input()['gates']) == 194
