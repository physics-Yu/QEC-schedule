"""Exclusive-branch algebra, packed high bits and independently computed intervals."""

from math import sqrt

import pytest

from modules.codes._support import detector_probability as engine


@pytest.mark.parametrize("count", (2, 128))
def test_exclusive_alternatives_never_create_an_identity_sample(count):
    value = engine.estimate_acceptance(
        count,
        (((1, 0.5), (1 << (count - 1), 0.5)),),
        method="monte_carlo",
        shots=1031,
        batch_size=127,
    )
    assert value["accepted"] == 0
    assert value["probability"] == 0
    assert value["ci95"][0] == pytest.approx(0)


def test_deterministic_channels_cancel_across_arbitrary_length_masks():
    mask = (1 << 130) | (1 << 70) | 1
    value = engine.estimate_acceptance(
        131, (((mask, 1),), ((mask, 1),)), shots=1031, batch_size=127
    )
    assert value["accepted"] == value["shots"] == 1031
    assert value["probability"] == 1
    assert value["packed_word_count"] == 3
    assert value["effective_detector_rank"] == 1


def test_mc_matches_exact_exclusive_convolution_and_is_reproducible():
    channels = (((1, 0.2), (1, 0.1), (2, 0.15), (0, 0.2)), ((1, 0.3),), ((3, 0.05),))
    exact = engine.estimate_acceptance(2, channels)
    sampled = engine.estimate_acceptance(
        2, channels, method="monte_carlo", shots=131072, seed=143, batch_size=8192
    )
    assert sampled == engine.estimate_acceptance(
        2, channels, method="monte_carlo", shots=131072, seed=143, batch_size=8192
    )
    assert sampled["probability"] == pytest.approx(exact["probability"], abs=0.005)
    assert exact["kind"] == "exact" and exact["sampling"] is None
    p, n, z = (
        sampled["accepted"] / sampled["shots"],
        sampled["shots"],
        1.959963984540054,
    )
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    assert sampled["ci95"] == pytest.approx([center - radius, center + radius])
    assert sampled["ci_method"] == "wilson_score"


@pytest.mark.parametrize("count", (0, 12, 100000))
@pytest.mark.parametrize("method", ("auto", "exact"))
def test_empty_xor_is_exact_after_validation_without_a_table(
    monkeypatch, count, method
):
    monkeypatch.setattr(
        engine.np,
        "zeros",
        lambda *args, **kwargs: pytest.fail("unexpected table allocation"),
    )
    value = engine.estimate_acceptance(count, (((0, 0.9),), ()), method=method)
    assert value["probability"] == 1
    assert value["kind"] == "exact"
    assert value["calculation"] == "empty_xor_exact"
    assert value["effective_detector_rank"] == 0
    assert value["shots"] is value["accepted"] is value["seed"] is value["ci95"] is None


def test_sparse_word_storage_and_batch_memory_limit(monkeypatch):
    monkeypatch.setattr(engine, "MAX_STATE_BYTES", 32)
    mask = (1 << 99999) | 1
    value = engine.estimate_acceptance(
        100000,
        (((mask, 0.2),),),
        method="monte_carlo",
        shots=13,
        batch_size=13,
        seed=93,
    )
    assert value["packed_word_count"] == 2
    assert value["batch_size"] == 2
    assert value["state_allocation_bytes"] == 32
    assert value["shots"] == 13


@pytest.mark.parametrize(
    "kwargs",
    (
        {"detector_count": -1},
        {"detector_count": True},
        {"detector_count": 1.5},
        {"shots": 0},
        {"shots": True},
        {"batch_size": 0},
        {"seed": -1},
        {"seed": True},
        {"method": "approximate"},
    ),
)
def test_invalid_controls_rejected(kwargs):
    arguments = {"detector_count": 3, "channels": ()} | kwargs
    with pytest.raises(ValueError):
        engine.estimate_acceptance(**arguments)


@pytest.mark.parametrize(
    "channels",
    (
        (((2, 0.1),),),
        (((True, 0.1),),),
        (((1, -0.1),),),
        (((1, float("nan")),),),
        (((1, True),),),
        (((0, 0.7), (1, 0.4)),),
        (((0, 0.6), (0, 0.6)),),
    ),
)
def test_bad_channels_are_not_renormalized_or_hidden_by_shortcuts(channels):
    with pytest.raises(ValueError):
        engine.estimate_acceptance(1, channels)


def test_exact_large_space_is_guarded_before_allocation(monkeypatch):
    monkeypatch.setattr(
        engine.np,
        "zeros",
        lambda *args, **kwargs: pytest.fail("unexpected table allocation"),
    )
    with pytest.raises(ValueError, match="bounded"):
        engine.estimate_acceptance(21, (((1, 0.1),),), method="exact")
    # The legacy exact distribution retains its original positive 1..20 guard.
    for count in (0, 21):
        with pytest.raises(ValueError):
            engine.xor_distribution(count, ())
