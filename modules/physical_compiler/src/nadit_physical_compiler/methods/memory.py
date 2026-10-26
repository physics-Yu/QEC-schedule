"""Decoded memory sampling of an already exported Stim experiment."""

from hashlib import sha256
from math import sqrt
from typing import Any

from .clifford import dependency
from .stim_export import StimExport


def _interval(failures: int, shots: int) -> list[float]:
    z = 1.959963984540054
    fraction = failures / shots
    denominator = 1 + z * z / shots
    center = (fraction + z * z / (2 * shots)) / denominator
    half = (
        z
        * sqrt(fraction * (1 - fraction) / shots + z * z / (4 * shots * shots))
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def sample_memory(
    exported: StimExport,
    *,
    shots: int,
    seed: int,
    batch_size: int = 1024,
) -> dict[str, Any]:
    """Sample detectors, decode with MWPM, and count failed logical predictions.

    Loss and leakage remain separate estimates. Disjoint Pauli channel branches
    are approximated as independent mechanisms for decoder weights, not sampling.
    Fixed seeds are reproducible with the same versions and batch size.
    """
    if shots < 1 or batch_size < 1 or not 0 <= seed < 2**64:
        raise ValueError("shots/batch_size must be positive; seed must be uint64.")
    report = exported.report
    if report.get("schema") != "nadit.stim/1":
        raise ValueError("Expected nadit.stim/1 export.")
    if report["branch_semantics"] != "unconditional":
        raise ValueError(
            "Memory sampling requires an unconditional circuit, not a fixed case."
        )
    if sha256(exported.circuit.encode()).hexdigest() != report["circuit_sha256"]:
        raise ValueError("Stim circuit hash differs from its export report.")
    stim, pymatching = dependency("stim"), dependency("pymatching")
    circuit = stim.Circuit(exported.circuit)
    if not circuit.num_detectors or not circuit.num_observables:
        raise ValueError("Memory sampling requires detectors and logical observables.")
    dem = circuit.detector_error_model(
        decompose_errors=True, approximate_disjoint_errors=True
    )
    decoder = pymatching.Matching.from_detector_error_model(dem)
    sampler = circuit.compile_detector_sampler(seed=seed)
    failures = detection_events = completed = 0
    while completed < shots:
        count = min(batch_size, shots - completed)
        syndrome, actual = sampler.sample(shots=count, separate_observables=True)
        predicted = decoder.decode_batch(syndrome)
        failures += int((predicted != actual).any(axis=1).sum())
        detection_events += int(syndrome.sum())
        completed += count
    return {
        "schema": "nadit.memory/1",
        "method": "stim/v1",
        "scope": "pauli_readout_only",
        "shots": shots,
        "seed": seed,
        "batch_size": batch_size,
        "failures": failures,
        "logical_error_rate": failures / shots,
        "wilson_95": _interval(failures, shots),
        "detection_events": detection_events,
        "decoder": "pymatching-mwpm",
        "decoder_approximate_disjoint_errors": True,
        "stim_version": stim.__version__,
        "pymatching_version": pymatching.__version__,
        "result_hash": report["result_hash"],
        "circuit_sha256": report["circuit_sha256"],
        "noise_params_hash": report["noise_report"]["params_hash"],
        "workload": (report.get("annotations") or {}).get("workload"),
        "loss": report["noise_report"]["noise"]["loss"],
        "excluded_from_logical_error_rate": report["excluded_from_stim"],
    }
