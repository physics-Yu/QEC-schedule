"""Scoped physical no-fault cost proxies, never quantum success probabilities.

The physical helper owns action admission and activity clipping. These pure ports
cross-check its frozen interval evidence and independently recompute the product
of Pauli-channel identity and physical-loss survival factors. No noise sampling,
syndrome interpretation, state propagation, output correction, or retry occurs.
"""

from collections.abc import Mapping
from hashlib import sha256
from math import exp, fsum, isclose, isfinite, log
from pathlib import Path
from re import fullmatch
from typing import Any

from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.provenance import canonical_hash

from ...contracts.event_probability import ProbabilityPort

EXPOSURE_PARTITION = (
    "original_activity_interval_intersections_with_merged_include_intervals"
)
CHANNEL_SIZES = {
    "PAULI_CHANNEL_1": 3,
    "PAULI_CHANNEL_2": 15,
    "X_ERROR": 1,
    "Z_ERROR": 1,
    "M": 1,
}


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return dict(value)


def _number(value: object, name: str, *, maximum: float | None = None) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number.")
    result = float(value)
    if result < 0 or maximum is not None and result > maximum:
        raise ValueError(f"{name} is outside its nonnegative range.")
    return result


def _hash(value: object, name: str) -> str:
    if not isinstance(value, str) or fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a canonical SHA-256.")
    return value


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array.")
    return value


def _indices(value: object, name: str) -> list[int]:
    result = _array(value, name)
    if any(type(i) is not int or i < 0 for i in result) or result != sorted(
        set(result)
    ):
        raise ValueError(f"{name} must contain sorted unique nonnegative indices.")
    return result


def _intervals(
    value: object, name: str, window: tuple[float, float], *, merged: bool = False
) -> list[list[float]]:
    result = []
    previous = None
    for item in _array(value, name):
        pair = _array(item, name)
        if len(pair) != 2:
            raise ValueError(f"{name} requires start/end pairs.")
        start, end = (_number(v, name) for v in pair)
        if not window[0] <= start < end <= window[1]:
            raise ValueError(f"{name} lies outside its window or has zero duration.")
        if previous is not None and (start < previous or merged and start == previous):
            raise ValueError(
                f"{name} must be sorted, disjoint, and canonically merged."
            )
        result.append([start, end])
        previous = end
    return result


def _within(start: float, duration: float, intervals: list[list[float]]) -> bool:
    return any(a <= start < b and start + duration <= b for a, b in intervals)


def _event_map(
    selection: dict[str, Any], indices: list[int], included: list[list[float]]
) -> None:
    """Check piece identities and intervals; source-kind admission belongs upstream."""
    source_indices: list[int] = []
    previous: tuple[int, float, float, int] | None = None
    for selected, entry in enumerate(
        _array(selection.get("event_index_map"), "event index map")
    ):
        event = _object(entry, "event map entry")
        original = event.get("source_event_id")
        if (
            type(event.get("selected_event_id")) is not int
            or event["selected_event_id"] != selected
            or type(original) is not int
            or original < 0
        ):
            raise ValueError("Event map contains inconsistent event identities.")
        start = _number(event.get("start_us"), "event start")
        duration = _number(event.get("duration_us"), "event duration")
        interval = next(
            (
                i
                for i, (a, b) in enumerate(included)
                if a <= start < b and start + duration <= b
            ),
            None,
        )
        if interval is None:
            raise ValueError("An event piece crosses a selected action boundary.")
        if previous is not None:
            old_source, old_start, old_duration, old_interval = previous
            if original < old_source:
                raise ValueError("Event map source identities must be nondecreasing.")
            if original == old_source and (
                duration <= 0
                or old_duration <= 0
                or start <= old_start
                or start < old_start + old_duration
                or interval <= old_interval
            ):
                raise ValueError(
                    "Repeated source pieces require positive, ordered, disjoint "
                    "durations in different merged included intervals."
                )
        if not source_indices or source_indices[-1] != original:
            source_indices.append(original)
        previous = (original, start, duration, interval)
    if source_indices != indices:
        raise ValueError("Event map does not cover selected source events exactly.")


def _scope(
    report: dict[str, Any], evidence: dict[str, Any], stage: str
) -> dict[str, Any]:
    if (
        not isinstance(evidence.get("scope_id"), str)
        or not evidence["scope_id"].strip()
    ):
        raise ValueError("scope_id must be nonempty.")
    if (
        evidence.get("stage") != stage
        or evidence.get("action_boundaries_checked") is not True
    ):
        raise ValueError("Scope has the wrong stage or unchecked action boundaries.")
    window = _array(evidence.get("window_us"), "scope.window_us")
    if len(window) != 2:
        raise ValueError("scope.window_us requires two endpoints.")
    start, end = (_number(v, "scope.window_us") for v in window)
    if start >= end:
        raise ValueError("scope.window_us must have positive duration.")
    included = _intervals(
        evidence.get("included_intervals_us"),
        "included intervals",
        (start, end),
        merged=True,
    )
    excluded = _intervals(
        evidence.get("excluded_raw_intervals_us"),
        "raw exclusion intervals",
        (start, end),
    )
    if any(max(a, c) < min(b, d) for a, b in included for c, d in excluded):
        raise ValueError("Included scope overlaps an already sampled raw interval.")
    cursor = start
    for left, right in sorted(included + excluded):
        if left != cursor:
            raise ValueError("Included and raw-excluded intervals leave a scope gap.")
        cursor = right
    if cursor != end:
        raise ValueError("Included and raw-excluded intervals must cover the window.")
    if _hash(evidence.get("source_result_hash"), "source_result_hash") != _hash(
        report.get("result_hash"), "report.result_hash"
    ):
        raise ValueError("Scope and noise report have different source result hashes.")
    if (
        report.get("time_scope") != "disjoint_include_intervals"
        or report.get("probability_kind") != "physical_no_fault_proxy"
    ):
        raise ValueError("A sliced physical no-fault proxy report is required.")
    selection = _object(report.get("interval_selection"), "interval_selection")
    expected = {
        "schema": "nadit.physical_cost_intervals/1",
        "time_basis": "absolute_us",
        "exposure_partition": EXPOSURE_PARTITION,
        "discrete_channels": "complete_action_ownership",
        "noise_profile": "independent_pauli_rates_v1",
    }
    if (
        any(selection.get(k) != v for k, v in expected.items())
        or selection.get("full_trace_probability_equivalence_claimed") is not False
    ):
        raise ValueError("Unsupported interval-selection or T2 partition semantics.")
    if _number(selection.get("source_horizon_us"), "source horizon") < end:
        raise ValueError("Scope extends beyond the source activity horizon.")
    if selection.get("include_intervals") != evidence["included_intervals_us"]:
        raise ValueError("Scope differs from actual selected intervals.")
    duration = _number(selection.get("selected_duration_us"), "selected duration")
    if not isclose(
        duration, fsum(b - a for a, b in included), rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError("Selected duration does not match the included intervals.")
    _hash(selection.get("source_activity_sha256"), "source activity hash")
    selected_hash = _hash(
        selection.get("selected_activity_sha256"), "selected activity hash"
    )
    if (
        _hash(evidence.get("scoped_activity_hash"), "scoped activity hash")
        != selected_hash
    ):
        raise ValueError("Scope differs from actual selected activity hash.")
    indices = _indices(evidence.get("original_event_indices"), "original event indices")
    if (
        _indices(selection.get("selected_event_indices"), "selected event indices")
        != indices
    ):
        raise ValueError("Scope differs from actual selected event indices.")
    _event_map(selection, indices, included)
    return selection


def _params(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("model") != "noise" or report.get("version") != "v1.1":
        raise ValueError("Cost proxy requires a noise/v1 v1.1 report.")
    params = resolve(_object(report.get("params"), "noise parameters"))
    if report.get("params_hash") != canonical_hash(params):
        raise ValueError("Resolved noise params_hash mismatch.")
    gates = [params["single"], params["cz"], *params["single_overrides"].values()]
    if (
        any(gate["backend"] != "pauli" for gate in gates)
        or params["transport"]["backend"] != "rates/v1"
    ):
        raise ValueError("Cost proxy supports explicit Pauli gates and rates/v1 only.")
    return params


def _location(record: dict[str, Any], selection: dict[str, Any]) -> None:
    start = _number(record.get("start_us"), "noise start")
    duration = _number(record.get("duration_us"), "noise duration")
    if not _within(start, duration, selection["include_intervals"]):
        raise ValueError("A noise channel lies outside the selected scope.")
    if "event_id" in record:
        event_id = record["event_id"]
        events = selection["event_index_map"]
        if type(event_id) is not int or not 0 <= event_id < len(events):
            raise ValueError("A noise channel references an unknown selected event.")
        event = events[event_id]
        if start != event["start_us"] or duration != event["duration_us"]:
            raise ValueError("Noise channel timing differs from its selected action.")


def _product(factors: list[float]) -> float:
    return 0.0 if 0 in factors else exp(fsum(log(v) for v in factors))


def _probability(report: dict[str, Any], selection: dict[str, Any]) -> float:
    noise = _object(report.get("noise"), "noise")
    if noise.get("schema") != "nadit.noise/1":
        raise ValueError("Unsupported noise report schema.")
    if (
        report.get("upstream")
        or noise.get("upstream_records")
        or noise.get("gate_diagnostics")
    ):
        raise ValueError(
            "Native/coherent/leakage reports are outside the Pauli cost proxy."
        )
    factors = []
    for entry in _array(noise.get("channels"), "noise.channels"):
        channel = _object(entry, "noise channel")
        instruction = channel.get("instruction")
        size = CHANNEL_SIZES.get(instruction) if isinstance(instruction, str) else None
        weights = _array(channel.get("probabilities"), "channel probabilities")
        if (
            size is None
            or len(weights) != size
            or channel.get("diagnostics")
            or channel.get("upstream_record_id")
        ):
            raise ValueError("Unsupported native/non-Pauli noise channel.")
        total = fsum(_number(p, "channel probability", maximum=1) for p in weights)
        if total > 1 + 1e-12:
            raise ValueError("Exclusive channel probabilities exceed one.")
        _location(channel, selection)
        factors.append(max(0.0, 1 - total))
    loss = _object(noise.get("loss"), "noise.loss")
    survival = []
    for entry in _array(loss.get("events"), "loss.events"):
        event = _object(entry, "loss event")
        _location(event, selection)
        survival.append(
            _number(event.get("survival_probability"), "loss survival", maximum=1)
        )
    aggregate = _number(
        loss.get("all_atoms_survive_probability"), "aggregate survival", maximum=1
    )
    if not isclose(aggregate, _product(survival), rel_tol=1e-10, abs_tol=1e-14):
        raise ValueError("Loss event product differs from aggregate survival.")
    actual = _number(
        _object(report.get("metrics"), "metrics").get("no_fault_probability"),
        "no_fault_probability",
        maximum=1,
    )
    recomputed = _product(factors + survival)
    if not isclose(actual, recomputed, rel_tol=1e-10, abs_tol=1e-14):
        raise ValueError(
            "no_fault_probability differs from independent channel/loss product."
        )
    return actual


def _port(
    noise_report: Mapping[str, Any], scope_evidence: Mapping[str, Any], stage: str
) -> ProbabilityPort:
    report = _object(noise_report, "noise report")
    scope = _object(scope_evidence, "scope evidence")
    # Validate the whole frozen evidence, including caller-added report fields.
    try:
        report_hash, scope_hash = canonical_hash(report), canonical_hash(scope)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Noise report and scope must be finite JSON evidence."
        ) from error
    selection = _scope(report, scope, stage)
    params = _params(report)
    probability = _probability(report, selection)
    factory = stage == "factory"
    name = "factory_15_to_1" if factory else "algorithm"
    keys = ("accepted", "rejected") if factory else ("no_fault", "fault")
    identity = f"rotated_surface_d3.{name}.cost_proxy"
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": identity,
            "protocol_id": identity,
            "protocol_version": "1",
            "model": {
                "id": f"{name}.no_fault_cost_proxy.v1",
                "kind": "estimated",
                "assumptions": [
                    "Cost proxy only; not detector acceptance, quantum fidelity, "
                    "or logical success",
                    "Independent explicit Pauli channels and rates/v1 physical loss",
                    "Already sampled raw-preparation intervals are excluded "
                    "from this scope",
                    "The activity helper validated complete discrete action ownership",
                    "Split-source action eligibility is admitted by the physical "
                    "helper; this port checks piece identities and intervals only",
                    "T2 no-fault uses frozen original-interval intersections; "
                    "arbitrary repartition changes this event",
                    "Ideal-reference quantum routes choose actions only; "
                    "actual resource quality remains unknown",
                    "Factory acceptance precedes output X; its delivery actions "
                    "belong to a later consumer scope",
                ],
                "parameters": {"stage": stage, "noise_params": params},
                "evidence": {
                    "scope": scope,
                    "scope_sha256": scope_hash,
                    "noise_report_sha256": report_hash,
                    "estimator_source_sha256": sha256(
                        Path(__file__).read_bytes()
                    ).hexdigest(),
                    "source_result_hash": report["result_hash"],
                    "source_activity_sha256": selection["source_activity_sha256"],
                    "scoped_activity_hash": selection["selected_activity_sha256"],
                    "params_hash": report["params_hash"],
                    "interval_selection": selection,
                    "exposure_partition": EXPOSURE_PARTITION,
                    "full_trace_probability_equivalence_claimed": False,
                    "logical_success_probability": None,
                    "quantum_quality": "unknown",
                    "no_fault_probability": probability,
                    "physical_loss_included_once": True,
                    "probability_calculation": (
                        "product(channel identity) * product(loss event survival)"
                    ),
                },
            },
            "outcomes": [
                {
                    "key": key,
                    "probability": p,
                    "values": (
                        {"accepted": accepted, "proxy_no_fault": accepted}
                        if factory
                        else {"proxy_success": accepted, "no_fault": accepted}
                    ),
                    "branch_id": key,
                }
                for key, p, accepted in zip(
                    keys, (probability, 1 - probability), (True, False), strict=True
                )
            ],
            "branches": [
                {
                    "key": key,
                    "transition": ("deliver" if i == 0 else "retry")
                    if factory
                    else "continue",
                    "steps": [],
                }
                for i, key in enumerate(keys)
            ],
        }
    )


def factory_proxy_port(
    noise_report: Mapping[str, Any], scope_evidence: Mapping[str, Any]
) -> ProbabilityPort:
    """Return a scoped factory accept/retry cost proxy with unknown output quality.

    Args: noise_report is a physical helper's sliced noise/v1 report; scope_evidence
        identifies the factory prefix ending after final MX readiness, before X.
    Returns: A frozen finite proxy port; it executes no correction or retry.
    Raises: ValueError for unsupported noise, inconsistent scope/hash, or product.
    """
    return _port(noise_report, scope_evidence, "factory")


def algorithm_proxy_port(
    noise_report: Mapping[str, Any], scope_evidence: Mapping[str, Any]
) -> ProbabilityPort:
    """Return a diagnostic consumer no-fault/fault cost proxy, never a retry.

    Args: noise_report and scope_evidence include owned delivery X, waiting and
        actual consumer actions, excluding earlier factory/raw assessed scopes.
    Returns: Both outcomes continue; logical success remains unknown metadata.
    Raises: ValueError for unsupported noise, inconsistent scope/hash, or product.
    """
    return _port(noise_report, scope_evidence, "algorithm")
