"""Acceptance of independent exclusive detector-flip channels, without a proxy."""

from collections import defaultdict
from collections.abc import Sequence
from math import fsum, isclose, isfinite, sqrt
from typing import Any

import numpy as np

MAX_DETECTORS = 20
MAX_STATE_BYTES = 64 * 1024 * 1024
NORMALIZATION_TOLERANCE = 1e-12
type FaultChannel = tuple[tuple[int, float], ...]


def xor_distribution(
    detector_count: int, channels: Sequence[Sequence[tuple[int, float]]]
) -> tuple[float, ...]:
    """Convolve independent channels with exclusive branches, bounded to 20 bits.

    Residual channel weight is identity; repeated masks are exclusive alternatives.
    This preserves the original d3 exact implementation and validation semantics.
    """
    if type(detector_count) is not int or not 1 <= detector_count <= MAX_DETECTORS:
        raise ValueError(f"Detector count must be between 1 and {MAX_DETECTORS}.")
    size = 1 << detector_count
    indices = np.arange(size)
    distribution = np.zeros(size)
    distribution[0] = 1
    for channel in channels:
        grouped: dict[int, list[float]] = defaultdict(list)
        total = []
        for mask, probability in channel:
            if type(mask) is not int or not 0 <= mask < size:
                raise ValueError("Fault branch mask is outside the detector space.")
            if (
                isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not isfinite(probability)
                or not 0 <= probability <= 1
            ):
                raise ValueError("Fault branch probability must be finite in [0,1].")
            total.append(probability)
            if mask:
                grouped[mask].append(probability)
        if fsum(total) > 1:
            raise ValueError("Exclusive fault branch probabilities exceed one.")
        weights = {mask: fsum(values) for mask, values in grouped.items()}
        if not weights:
            continue
        updated = (1 - fsum(weights.values())) * distribution
        for mask, probability in weights.items():
            updated += probability * distribution[indices ^ mask]
        distribution = updated
    if not isclose(float(distribution.sum()), 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError("Detector convolution lost probability mass.")
    return tuple(float(value) for value in distribution)


def _validated_channels(
    count: int, channels: Sequence[Sequence[tuple[int, float]]]
) -> tuple[FaultChannel, ...]:
    result = []
    for channel in channels:
        grouped: dict[int, list[float]] = defaultdict(list)
        total = []
        for mask, probability in channel:
            if type(mask) is not int or mask < 0 or mask.bit_length() > count:
                raise ValueError("Fault branch mask is outside the detector space.")
            if (
                isinstance(probability, bool)
                or not isinstance(probability, int | float)
                or not isfinite(probability)
                or not 0 <= probability <= 1
            ):
                raise ValueError("Fault branch probability must be finite in [0,1].")
            total.append(probability)
            if mask and probability:
                grouped[mask].append(probability)
        if fsum(total) > 1:
            raise ValueError("Exclusive fault branch probabilities exceed one.")
        result.append(tuple((mask, fsum(weights)) for mask, weights in grouped.items()))
    return tuple(result)


def _rank(channels: tuple[FaultChannel, ...]) -> int:
    basis: dict[int, int] = {}
    for channel in channels:
        for mask, _ in channel:
            while mask:
                pivot = mask.bit_length() - 1
                if pivot not in basis:
                    basis[pivot] = mask
                    break
                mask ^= basis[pivot]
    return len(basis)


def _limbs(mask: int) -> tuple[tuple[int, int], ...]:
    result = []
    while mask:
        index = ((mask & -mask).bit_length() - 1) // 64
        value = (mask >> (64 * index)) & ((1 << 64) - 1)
        result.append((index, value))
        mask ^= value << (64 * index)
    return tuple(result)


def _wilson(accepted: int, shots: int) -> list[float]:
    z = 1.959963984540054
    p = accepted / shots
    denominator = 1 + z * z / shots
    center = (p + z * z / (2 * shots)) / denominator
    radius = z * sqrt(p * (1 - p) / shots + z * z / (4 * shots * shots)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _sample(
    channels: tuple[FaultChannel, ...],
    shots: int,
    seed: int,
    batch_size: int,
) -> tuple[int, int, int]:
    packed = [
        tuple((_limbs(mask), probability) for mask, probability in channel)
        for channel in channels
        if channel
    ]
    indices = sorted(
        {index for channel in packed for limbs, _ in channel for index, _ in limbs}
    )
    columns = {index: column for column, index in enumerate(indices)}
    width = len(columns)
    if width * 8 > MAX_STATE_BYTES:
        raise ValueError("One packed detector state exceeds the memory budget.")
    actual_batch = min(shots, batch_size, MAX_STATE_BYTES // max(8, width * 8))
    generator = np.random.default_rng(seed)
    accepted = 0
    for offset in range(0, shots, actual_batch):
        count = min(actual_batch, shots - offset)
        states = np.zeros((count, width), dtype=np.uint64)
        for channel in packed:
            weights = [probability for _, probability in channel]
            active = fsum(weights)
            # Conditional on K~Binomial(n,p), a uniform K-subset is exactly the
            # set of independent active shots, avoiding draws for rare identity.
            hits = int(generator.binomial(count, active))
            if not hits:
                continue
            rows = (
                np.arange(count)
                if hits == count
                else generator.choice(count, size=hits, replace=False)
            )
            cumulative = np.array([fsum(weights[: i + 1]) for i in range(len(weights))])
            choices = np.searchsorted(
                cumulative, generator.random(hits) * active, side="right"
            )
            for branch, (limbs, _) in enumerate(channel):
                selected = rows[choices == branch]
                for index, value in limbs:
                    states[selected, columns[index]] ^= np.uint64(value)
        accepted += int(np.count_nonzero(~np.any(states, axis=1)))
    return accepted, actual_batch, width


def estimate_acceptance(
    detector_count: int,
    channels: Sequence[Sequence[tuple[int, float]]],
    *,
    method: str = "auto",
    shots: int = 262144,
    seed: int = 0,
    batch_size: int = 65536,
) -> dict[str, Any]:
    """Estimate probability that the XOR of all exclusive channel outcomes is zero.

    Auto uses exact convolution through 20 detectors; larger vectors use packed
    Monte Carlo with independent categorical channels. Sampling preserves all
    cross-channel cancellations and yields a Wilson 95% binomial interval.
    Memory is bounded by chunking and by storing only nonzero 64-bit word slots.
    Auto/exact return one analytically when every nonzero-weight signature is
    zero, after input validation; this shortcut allocates no exponential table.
    Reproduction requires the recorded seed, batch size and NumPy version.

    Raises ValueError for invalid counts, masks, probabilities, method, sampling
    controls, or an exact request beyond the fixed exponential allocation bound.
    """
    if type(detector_count) is not int or detector_count < 0:
        raise ValueError("Detector count must be a nonnegative integer.")
    if method not in ("auto", "exact", "monte_carlo"):
        raise ValueError("Method must be auto, exact, or monte_carlo.")
    if any(type(value) is not int or value <= 0 for value in (shots, batch_size)):
        raise ValueError("Shots and batch size must be positive integers.")
    if type(seed) is not int or seed < 0:
        raise ValueError("Seed must be a nonnegative integer.")
    normalized = _validated_channels(detector_count, channels)
    empty = not any(normalized)
    exact = (
        method == "exact"
        or method == "auto"
        and (detector_count <= MAX_DETECTORS or empty)
    )
    if exact and detector_count > MAX_DETECTORS and not empty:
        raise ValueError(f"Exact convolution is bounded to {MAX_DETECTORS} detectors.")
    metadata = {
        "detector_count": detector_count,
        "channel_count": len(normalized),
        "effective_channel_count": sum(bool(channel) for channel in normalized),
        "effective_detector_rank": _rank(normalized),
        "exclusive_branches_preserved": True,
        "cross_channel_cancellations_preserved": True,
        "normalization_absolute_tolerance": NORMALIZATION_TOLERANCE,
        "channel_probabilities_renormalized": False,
        "max_state_bytes": MAX_STATE_BYTES,
        "numpy_version": np.__version__,
    }
    if exact:
        probability = (
            xor_distribution(detector_count, normalized)[0] if not empty else 1.0
        )
        return metadata | {
            "probability": probability,
            "method": "exact_xor_convolution",
            "kind": "exact",
            "shots": None,
            "accepted": None,
            "seed": None,
            "ci95": None,
            "batch_size": None,
            "sampling": None,
            "ci_method": None,
            "calculation": "empty_xor_exact" if empty else "finite_xor_convolution",
        }
    accepted, actual_batch, width = _sample(normalized, shots, seed, batch_size)
    return metadata | {
        "probability": accepted / shots,
        "method": "exclusive_channel_monte_carlo",
        "kind": "estimated",
        "shots": shots,
        "accepted": accepted,
        "seed": seed,
        "ci95": _wilson(accepted, shots),
        "batch_size": actual_batch,
        "ci_method": "wilson_score",
        "packed_word_count": width,
        "state_allocation_bytes": actual_batch * width * 8,
        "calculation": "independent_exclusive_channel_samples",
        "sampling": {
            "rng": "numpy.PCG64",
            "active_shots": "binomial_uniform_subset",
            "branches": "conditional_categorical",
            "requested_batch_size": batch_size,
            "confidence_interval": "Wilson score, two-sided 95%",
        },
    }
