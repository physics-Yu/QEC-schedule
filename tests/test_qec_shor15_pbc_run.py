import numpy as np
import pytest

pytest.importorskip('pygridsynth', reason='optional pinned complete PBC synthesis dependency')
from neutral_atom_experiments.qec_pbc.qft_synthesis import synthesize_shor15
from neutral_atom_experiments.qec_pbc.shor15_pbc_run import run_shor15_pbc


@pytest.fixture(scope='module')
def compiled():
    return synthesize_shor15(total_error_budget=1e-3, seed=7)


def test_measured_pbc_output_drives_failure_retry_and_verified_factorization(compiled):
    result = run_shor15_pbc(compiled, seed=7, outcomes=(128, 192))
    assert result['success'] and result['order'] == 4 and result['factors'] == [3, 5]
    assert not result['attempts'][0]['classical_postprocessing']['success']
    assert result['total_resource_consumptions'] == 7000
    assert result['total_resource_measurements'] == 14000
    assert result['total_phase_measurements'] == 16
    assert [a['resource_instance_namespace'] for a in result['attempts']] == ['shot1', 'shot2']
    for a in result['attempts']:
        assert a['all_resources_consumed'] and a['projected_phase_register_verified']
        assert np.isclose(a['projected_state_norm'], 1, atol=1e-12)
        assert np.isclose(2**a['log2_phase_readout_probability'], a['phase_outcome_probability'], atol=1e-12)
        assert sum(m['bit'] << i for i, m in enumerate(a['phase_readout'])) == a['phase_outcome']
    assert result['pbc_executed'] and not result['encoded'] and not result['physical_executed']


def test_seeded_sampling_uses_pbc_distribution_and_keeps_exhaustion(compiled):
    sampled = run_shor15_pbc(compiled, seed=7)
    assert sampled['success'] and [a['phase_outcome'] for a in sampled['attempts']] == [128, 192]
    failed = run_shor15_pbc(compiled, outcomes=(0,), max_attempts=1)
    assert not failed['success'] and failed['factors'] is None
    assert len(failed['attempts'][0]['phase_readout']) == 8


def test_invalid_readout_replay_is_rejected_before_consuming_resources(compiled):
    with pytest.raises(ValueError, match='in-range'):
        run_shor15_pbc(compiled, outcomes=(256,))
