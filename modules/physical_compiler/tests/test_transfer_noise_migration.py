"""Reference Load/Store Pauli fields keep their zero defaults and explicit weights."""

from types import SimpleNamespace

import pytest
from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.cost.noise.transport import RateTransportModel


@pytest.mark.parametrize("kind", ("Load", "Store"))
def test_explicit_transfer_pauli_and_loss_are_both_retained(kind):
    key = kind.lower()
    params = resolve(
        {"transport": {key + "_pauli": [0.01, 0.02, 0.03], key + "_loss": 0.1}}
    )
    effect = RateTransportModel(params["transport"]).evaluate(
        SimpleNamespace(kind=kind), 0
    )
    assert effect.pauli == (0.01, 0.02, 0.03)
    assert effect.survival == pytest.approx(0.9)


def test_omitted_transfer_pauli_remains_zero_and_invalid_weights_fail():
    params = resolve({})
    assert params["transport"]["load_pauli"] == [0, 0, 0]
    assert params["transport"]["store_pauli"] == [0, 0, 0]
    with pytest.raises(ValueError):
        resolve({"transport": {"store_pauli": [0.6, 0.6, 0]}})
