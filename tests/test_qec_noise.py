import math
import pytest
from neutral_atom_experiments.qec_pbc.noise import Exposure, PauliNoise, exposure_report, require_loss_decoder


def test_tphi_preserves_expected_ramsey_contrast():
    model = PauliNoise('synthetic unit-test parameter', tphi_us=100)
    p = model.timed_channel(Exposure('Q0', 0, 100, 'idle', 'g'))['z_error']
    assert 1 - 2*p == pytest.approx(math.exp(-1))
    assert model.timed_channel(Exposure('Q0', 1, 1, 'move', 'g')) == {'z_error': 0, 'depolarize1': 0}


def test_exposure_partition_and_model_fail_closed():
    with pytest.raises(ValueError, match='Overlapping'):
        exposure_report([Exposure('Q0', 0, 3, 'idle', 'a'), Exposure('Q0', 2, 4, 'move', 'b')], PauliNoise('test'))
    with pytest.raises(ValueError):
        PauliNoise('', one_qubit=0.1)
    with pytest.raises(ValueError):
        PauliNoise('test', tphi_us=float('nan'))
    with pytest.raises(NotImplementedError, match='observable loss'):
        require_loss_decoder()
