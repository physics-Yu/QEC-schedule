"""Scoped calibrated cost on logical role activity, without an atom simulation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import exp, expm1, fsum, isfinite, log1p
from typing import Any, Literal

from ...contracts.event_probability import ProbabilityPort
from .fast_profile import FastLayout, FastPatch, FastProfile

type CostScope = Literal["legacy_raw_excluded_proxy", "full_line_diagnostic"]


@dataclass(frozen=True)
class FastCostCall:
    """An admitted component occurrence with its actual logical start time."""

    invocation_id: str
    component_id: str
    participants: tuple[FastPatch, ...]
    start_us: float
    selection: Mapping[str, Any] | None = None
    parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = ()


def _time(value: Any) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError("INVALID_FAST_COST_TIME")
    return float(value)


def _intervals(
    window: tuple[float, float], raw_horizons: Iterable[tuple[float, float]]
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    start, end = map(_time, window)
    if start >= end:
        raise ValueError("INVALID_FAST_COST_WINDOW")
    excluded: list[tuple[float, float]] = []
    for a, b in sorted((_time(a), _time(b)) for a, b in raw_horizons):
        if a < start - 1e-7 or b <= a or b > end + 1e-7:
            raise ValueError("INVALID_FAST_RAW_HORIZON")
        a, b = max(a, start), min(b, end)
        if excluded and a <= excluded[-1][1]:
            excluded[-1] = (excluded[-1][0], max(b, excluded[-1][1]))
        else:
            excluded.append((a, b))
    included = []
    cursor = start
    for a, b in excluded:
        if a > cursor:
            included.append((cursor, a))
        cursor = b
    if cursor < end:
        included.append((cursor, end))
    return included, excluded


def _pieces(
    start: float, end: float, included: list[tuple[float, float]]
) -> Iterable[float]:
    for a, b in included:
        if min(end, b) > max(start, a):
            yield min(end, b) - max(start, a)


def evaluate_factory_cost(
    profile: FastProfile,
    calls: Iterable[FastCostCall],
    *,
    layout: FastLayout,
    factory_id: str,
    window: tuple[float, float],
    raw_horizons: Iterable[tuple[float, float]],
    scope: CostScope = "legacy_raw_excluded_proxy",
) -> dict[str, Any]:
    """Estimate calibrated physical no-fault cost on an explicit line/time scope.

    Discrete gate/transport contributions are frozen by calibration. Holder
    residence and each idle/transport T2 interval depend on this run's schedule.
    ``full_line_diagnostic`` includes raw actions and all carriers' waits during
    raw production. Its no-fault probability never controls factory acceptance.
    The default preserves the historical proxy's raw-union exclusion and its
    coverage gaps; it is not a complete physical-loss or storage diagnostic.
    Calls on other lines are ignored; cross-line
    calls, overlapping role activity and partially selected pulses raise errors.
    This estimates the physical cost model and performs no physical validation.
    Invalid scopes, windows and raw-horizon provenance raise ValueError.
    """
    if scope not in ("legacy_raw_excluded_proxy", "full_line_diagnostic"):
        raise ValueError("INVALID_FAST_COST_SCOPE")
    included, raw_union = _intervals(window, raw_horizons)
    start, end = map(float, window)
    full_line = scope == "full_line_diagnostic"
    excluded = [] if full_line else raw_union
    if full_line:
        included = [(start, end)]
    factory = next((f for f in layout.factories if f.factory_id == factory_id), None)
    if factory is None:
        raise ValueError("UNKNOWN_FAST_COST_FACTORY")
    bindings = layout.bindings
    spans: dict[tuple[int, int], list[tuple[float, float, str, str]]] = {
        (slot, role): [] for slot in range(6) for role in range(17)
    }
    discrete: list[float] = []
    selected_events = 0
    discrete_by_kind: dict[str, list[float]] = {}
    selected_calls: list[str] = []
    seen: set[str] = set()
    for call in calls:
        if not call.participants or call.participants[0].factory_id != factory_id:
            continue
        if call.invocation_id in seen:
            raise ValueError("DUPLICATE_FAST_COST_CALL")
        seen.add(call.invocation_id)
        if any(
            p.factory_id != factory_id or bindings.get(p.block_id) != p
            for p in call.participants
        ):
            raise ValueError("INVALID_FAST_COST_PARTICIPANTS")
        at = _time(call.start_us)
        entry = profile.lookup(
            call.component_id, call.participants, call.selection, call.parameters
        )
        if at >= end or at + entry.action_duration_us <= start:
            continue
        selected_calls.append(call.invocation_id)
        for event in entry.events:
            a, b = (
                at + event["offset_us"],
                at + event["offset_us"] + event["duration_us"],
            )
            selected = any(
                left - 1e-7 <= a < right and b <= right + 1e-7
                for left, right in included
            )
            overlap = fsum(_pieces(a, b, included))
            if not selected and overlap > 1e-7:
                raise ValueError("FAST_COST_ACTION_STRADDLES_SCOPE_BOUNDARY")
            if selected:
                discrete.append(event["log_survival"])
                discrete_by_kind.setdefault(event["kind"], []).append(
                    event["log_survival"]
                )
                selected_events += 1
        anchor = call.participants[0].slot
        for delta, role, offset, duration, kind, holder in entry.busy:
            key = anchor + delta, role
            if key not in spans:
                raise ValueError("UNCALIBRATED_FAST_SPECTATOR_GEOMETRY")
            spans[key].append((at + offset, at + offset + duration, kind, holder))
    exposure, transport = (
        profile.noise_params["exposure"],
        profile.noise_params["transport"],
    )
    residence: list[float] = []
    coherence: list[float] = []
    interval_count = 0
    patch_exposure: dict[int, dict[str, Any]] = {
        patch.slot: {
            "block_id": patch.block_id,
            "carrier_roles": 17,
            "included_role_time_us": 0.0,
            "raw_window_role_time_us": 0.0,
            "holder_role_time_us": {"slm": 0.0, "aod": 0.0},
            "log_holder_residence": 0.0,
            "log_dephasing": 0.0,
        }
        for patch in factory.patches
    }

    def charge(slot: int, a: float, b: float, kind: str, holder: str) -> None:
        nonlocal interval_count
        patch = patch_exposure[slot]
        for left, right in included:
            piece_start, piece_end = max(a, left), min(b, right)
            if piece_end <= piece_start:
                continue
            duration = piece_end - piece_start
            interval_count += 1
            loss_log = -duration * transport[holder + "_loss_per_us"]
            residence.append(loss_log)
            patch["included_role_time_us"] += duration
            patch["raw_window_role_time_us"] += fsum(
                _pieces(piece_start, piece_end, raw_union)
            )
            patch["holder_role_time_us"][holder] += duration
            patch["log_holder_residence"] += loss_log
            t2 = exposure[holder + "_t2_us"]
            if t2 is not None and (
                kind == "idle"
                or (exposure["include_transport"] and kind in ("Load", "Move", "Store"))
            ):
                coherence_log = log1p(0.5 * expm1(-duration / t2))
                coherence.append(coherence_log)
                patch["log_dephasing"] += coherence_log

    for (slot, _role), values in spans.items():
        cursor, previous_holder = start, "slm"
        for a, b, kind, holder in sorted(values):
            if b <= start or a >= end:
                continue
            if a < cursor - 1e-7:
                raise ValueError("OVERLAPPING_FAST_ROLE_ACTIVITY")
            if a > cursor:
                charge(slot, cursor, a, "idle", holder)
            charge(slot, a, b, kind, holder)
            cursor = max(cursor, b)
            previous_holder = (
                "aod" if kind == "Load" else "slm" if kind == "Store" else holder
            )
        if cursor < end:
            charge(slot, cursor, end, "idle", previous_holder)
    parts = {
        "discrete": fsum(discrete),
        "holder_residence": fsum(residence),
        "dephasing": fsum(coherence),
    }
    total = fsum(parts.values())
    return {
        "schema": "nadit.fast_factory_cost/1",
        "profile_sha256": profile.profile_sha256,
        "representation": "logical_estimate",
        "cost_kind": "profile_estimate",
        "physical_validation_run": False,
        "physical_execution": False,
        "factory_id": factory_id,
        "scope": scope,
        "purpose": "physical_no_fault_diagnostic" if full_line else "legacy_cost_proxy",
        "controls_factory_acceptance": not full_line,
        "window_us": list(window),
        "included_intervals_us": [list(v) for v in included],
        "excluded_raw_intervals_us": [list(v) for v in excluded],
        "raw_attempt_union_us": [list(v) for v in raw_union],
        "selected_calls": selected_calls,
        "selected_discrete_events": selected_events,
        "exposure_interval_count": interval_count,
        "exposure_by_patch": {
            values["block_id"]: values for values in patch_exposure.values()
        },
        "discrete_event_log_by_kind": {
            kind: fsum(values) for kind, values in sorted(discrete_by_kind.items())
        },
        "metrics": {
            "no_fault_probability": exp(total),
            "log_no_fault_probability": total,
            "log_contributions": parts,
        },
        "logical_success_probability": None,
        "exposure_partition": (
            "calibrated_role_activity_intersections_with_full_line_window"
            if full_line
            else "calibrated_role_activity_intersections_with_own_raw_union_complement"
        ),
        "coverage": {
            "carrier_roles": 102,
            "patch_count": 6,
            "window_basis": "first_own_call_to_own_final_check",
            "raw_activity_included": full_line,
            "raw_physical_loss_included": full_line,
            "successful_patch_wait_during_raw_included": full_line,
            "physical_loss_events_sampled": False,
            "channels": ["calibrated_discrete_events", "holder_residence", "dephasing"],
            "legacy_gap": None
            if full_line
            else (
                "all_line_carriers_excluded_during_own_raw_union_including_waits_and_loss"
            ),
        },
        "peer_wait_included": True,
        "delivery_assessment": "output_X_and_post_decision_wait_not_included",
    }


def factory_probability_port(
    profile: FastProfile, report: Mapping[str, Any]
) -> ProbabilityPort:
    """Create a coarse factory cost event without claiming a logical success rate."""
    if report.get("scope") == "full_line_diagnostic":
        raise ValueError("DIAGNOSTIC_CANNOT_CONTROL_FACTORY_ACCEPTANCE")
    probability = report["metrics"]["no_fault_probability"]
    protocol = "rotated_surface_d3.factory_15_to_1.cost_proxy"
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": protocol,
            "protocol_id": protocol,
            "protocol_version": "1",
            "model": {
                "id": "factory_15_to_1.calibrated_no_fault_proxy.v1",
                "kind": "estimated",
                "assumptions": [
                    "Frozen independent Pauli/rates calibration",
                    "Logical output quality remains unknown",
                    "Own raw horizons excluded; peer storage included",
                    "No physical compilation or validation in this run",
                ],
                "parameters": {"profile_sha256": profile.profile_sha256},
                "evidence": dict(report),
            },
            "outcomes": [
                {
                    "key": key,
                    "probability": p,
                    "values": {"accepted": accepted, "proxy_no_fault": accepted},
                    "branch_id": key,
                }
                for key, p, accepted in (
                    ("accepted", probability, True),
                    ("rejected", 1 - probability, False),
                )
            ],
            "branches": [
                {"key": "accepted", "transition": "deliver", "steps": []},
                {"key": "rejected", "transition": "retry", "steps": []},
            ],
        }
    )
