"""Independent checks for preparation events and the 15-input reference model."""

from itertools import product

import numpy as np
import pytest

from modules.codes.rotated_surface_d3.probabilities.factory import (
    factory_mx_port,
    output_quality,
    preparation_quality,
)
from modules.codes.rotated_surface_d3.probabilities.preparation import preparation_port


@pytest.mark.parametrize(
    "preparation", ["initialize_0", "initialize_plus", "raw_t_postselection"]
)
def test_preparation_joint_values_are_complete_without_physical_bits(preparation):
    port = preparation_port(preparation)
    assert port.to_dict()["model"]["kind"] == "ideal_exact"
    accepted = [o for o in port.outcomes if dict(o.values)["accepted"]]
    assert sorted(dict(o.values)["byproduct_class"] for o in accepted) == list(
        range(16)
    )
    assert all(o.probability == 1 / 16 for o in accepted)
    assert all(
        set(dict(o.values)) == {"accepted", "byproduct_class"} for o in port.outcomes
    )
    assert sum(o.probability for o in port.outcomes) == 1
    assert port.content_sha256 == preparation_port(preparation).content_sha256


def test_unknown_preparation_is_rejected():
    with pytest.raises(ValueError, match="preparation"):
        preparation_port("raw_t")


@pytest.mark.parametrize("p", [0, 1e-4, 0.01, 0.1, 0.5, 1])
def test_full_joint_mx_distribution_against_error_enumeration(p):
    # The 15 columns of the four checks are every nonzero 4-bit vector.
    # The output row is selected by odd total column weight in this convention.
    expected = np.zeros((16, 2))
    for bits in product((0, 1), repeat=15):
        weight = sum(bits)
        syndrome, logical_error = 0, 0
        for column, bit in enumerate(bits, 1):
            if bit:
                syndrome ^= column
                logical_error ^= 1 ^ (column.bit_count() % 2)
        expected[syndrome, logical_error] += p**weight * (1 - p) ** (15 - weight)
    port = factory_mx_port(input_z_error=p)
    assert len(port.outcomes) == 16
    for outcome in port.outcomes:
        values = dict(outcome.values)
        syndrome = sum(values[f"m_w{i + 2}"] << i for i in range(4))
        assert outcome.probability == pytest.approx(expected[syndrome].sum(), abs=2e-13)
        assert values["accepted"] is (syndrome == 0)
        assert "logical_error" not in values  # Hidden error is never feedback.
    model = port.to_dict()["model"]
    assert model["parameters"]["input_z_error"] == p
    assert model["evidence"]["conditional_output_z_error"] == pytest.approx(
        expected[0, 1] / expected[0].sum(), abs=2e-13
    )
    x = 1 - 2 * p
    assert expected[0].sum() == pytest.approx((1 + 15 * x**8) / 16)


@pytest.mark.parametrize("p", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_factory_model_rejects_invalid_error_parameter(p):
    with pytest.raises(ValueError, match="input_z_error"):
        factory_mx_port(input_z_error=p)


def test_small_error_limit_and_model_boundary():
    port = factory_mx_port(input_z_error=1e-5)
    doc = port.to_dict()
    assert doc["model"]["evidence"][
        "conditional_output_z_error"
    ] / 1e-15 == pytest.approx(35, rel=2e-4)
    assert "assumed" in " ".join(doc["model"]["assumptions"]).lower()
    assert (
        doc["model"]["evidence"]["t_consumption_bits"]
        == "independent fair bits under this reference model"
    )


def test_quality_is_code_owned_and_carries_next_consumption_parameters():
    raw = preparation_quality("raw_t_postselection", {"input_z_error": 0.01})
    assert raw["consumption_parameters"] == {"input_z_error": 0.01}
    assert raw["status"] == "assumed_reference"
    port = factory_mx_port(input_z_error=0.01)
    output = output_quality(port)
    assert output["source_port_sha256"] == port.content_sha256
    assert output["consumption_parameters"]["input_z_error"] == pytest.approx(
        port.to_dict()["model"]["evidence"]["conditional_output_z_error"]
    )
    assert output["condition"] == "factory accepted and output canonicalized"
    with pytest.raises(ValueError, match="preparation"):
        preparation_quality("initialize_plus")
    with pytest.raises(ValueError, match="parameter"):
        preparation_quality("raw_t_postselection", {"raw_rejection": 0.15})
    with pytest.raises(ValueError, match="factory"):
        output_quality(preparation_port("raw_t_postselection"))
