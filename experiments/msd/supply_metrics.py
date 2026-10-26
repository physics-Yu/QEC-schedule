"""Windowed supply accounting reconstructed from saved inventory and line audits."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

from modules.logical_compiler.src.estimation.metrics import interval_union_us

type _LedgerIndex = tuple[
    dict[str, Any], dict[str, tuple[float | None, float | None, str]]
]


def _time(value: Any) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError("INVALID_SUPPLY_METRIC_TIME")
    return float(value)


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("INVALID_SUPPLY_METRIC_IDENTITY")
    return value


def _sample(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean_us": sum(values) / len(values) if values else None,
    }


def _series(
    intervals: list[tuple[float, float]], low: float, high: float
) -> dict[str, Any]:
    time = age = 0.0
    maximum = None
    changes: dict[float, int] = defaultdict(int)
    for start, end in intervals:
        if end < start:
            raise ValueError("SUPPLY_INTERVAL_TIME_REVERSED")
        left, right = max(low, start), min(high, end)
        if left >= right:
            continue
        time += right - left
        age += ((left - start) + (right - start)) * (right - left) / 2
        maximum = max(maximum or 0.0, right - start)
        changes[left] += 1
        changes[right] -= 1
    current = peak = 0
    for at in sorted(changes):
        current += changes[at]
        peak = max(peak, current)
    return {
        "time_us": time,
        "peak": peak,
        "mean": time / (high - low) if high > low else None,
        "age_integral_us2": age,
        "mean_age_us": age / time if time else None,
        "max_age_us": maximum,
    }


@dataclass
class _Entry:
    reservation: str
    owner: str
    reserved_at: float | None
    published_at: float | None
    consumer: str | None = None
    state: str = "offered"


def _resources(case: Mapping[str, Any]) -> Mapping[str, Any]:
    value = case.get("resources")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("INVALID_SUPPLY_LEDGER_EVIDENCE")
    for field in ("tokens", "audit"):
        if value.get(field) is not None and not isinstance(value[field], list):
            raise TypeError("INVALID_SUPPLY_LEDGER_EVIDENCE")
    return value


def _ledger(case: Mapping[str, Any]) -> _LedgerIndex:
    resources = _resources(case)
    rows = resources.get("tokens") or ()
    tokens = {t["token_id"]: t for t in rows}
    if len(tokens) != len(rows):
        raise ValueError("DUPLICATE_SUPPLY_LEDGER_TOKEN")
    terminal = {}
    for event in resources.get("audit") or ():
        if event["action"] not in ("consume", "discard"):
            continue
        identity = _name(event["token_id"])
        at = None if event.get("at_us") is None else _time(event["at_us"])
        safe = (
            None
            if event.get("safe_exit_at_us") is None
            else _time(event["safe_exit_at_us"])
        )
        if identity in terminal or (
            event["action"] == "consume"
            and at is not None
            and safe is not None
            and safe < at
        ):
            raise ValueError("INVALID_SUPPLY_LEDGER_TERMINAL_EVENT")
        terminal[identity] = (
            at,
            safe,
            "consumed" if event["action"] == "consume" else "discarded",
        )
    return tokens, terminal


def _unknown_buffer(reason: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "reason": reason,
        **{
            key: None
            for key in (
                "occupied_slot_time_us",
                "published_token_time_us",
                "peak_occupied_slots",
                "mean_occupied_slots",
                "peak_published_tokens",
                "mean_published_tokens",
                "residence_age_integral_us2",
                "token_time_weighted_mean_age_us",
                "maximum_residence_age_us",
            )
        },
        "completed_residences": {"count": None, "mean_us": None},
        "completed_claim_waits": {"count": None, "mean_us": None},
    }


def _buffer(
    snapshot: Mapping[str, Any],
    case: Mapping[str, Any],
    low: float,
    high: float,
    ledger: _LedgerIndex,
) -> tuple[dict[str, Any], dict[str, float | None] | None]:
    capacity, duration = snapshot["capacity"], _time(case["duration_us"])
    pending_final, items = snapshot["pending"], snapshot["items"]
    if (
        type(capacity) is not int
        or capacity < 1
        or not isinstance(pending_final, Mapping)
        or not isinstance(items, list)
        or type(snapshot["occupied"]) is not int
        or type(snapshot["closed"]) is not bool
        or snapshot["occupied"] != len(pending_final) + len(items)
        or not 0 <= snapshot["occupied"] <= capacity
    ):
        raise ValueError("INVALID_SUPPLY_BUFFER_SNAPSHOT")
    final_items = {_name(item["token_id"]): item for item in items}
    if len(final_items) != len(items):
        raise ValueError("DUPLICATE_SUPPLY_FINAL_ITEM")
    final_reservations = [_name(item["reservation_id"]) for item in items]
    if (
        len(set(final_reservations)) != len(final_reservations)
        or set(final_reservations) & pending_final.keys()
        or any(
            item["status"] not in ("offered", "reserved", "consumed", "discarded")
            for item in items
        )
    ):
        raise ValueError("INVALID_SUPPLY_FINAL_ITEM_STATE")
    for reservation, owner in pending_final.items():
        _name(reservation)
        _name(owner)
    if "audit" not in snapshot or snapshot["audit"] is None:
        return _unknown_buffer("missing_audit"), None
    audit = snapshot["audit"]
    if not isinstance(audit, list):
        raise TypeError("INVALID_SUPPLY_BUFFER_AUDIT")
    tokens, terminal = ledger
    pending: dict[str, tuple[str, float | None]] = {}
    live: dict[str, _Entry] = {}
    reservations: set[str] = set()
    published: dict[str, float | None] = {}
    slots: list[tuple[float, float]] = []
    residences: list[tuple[float, float]] = []
    completed, claims = [], []
    known, closed, previous = True, False, 0.0
    for event in audit:
        value = event.get("at_us")
        at = None if value is None else _time(value)
        if at is None:
            known = False
        elif not previous <= at <= duration:
            raise ValueError("SUPPLY_AUDIT_TIME_REVERSED_OR_AFTER_CASE")
        else:
            previous = at
        action = event["action"]
        if action == "reserve_capacity":
            reservation, owner = _name(event["reservation_id"]), _name(event["owner"])
            if (
                reservation in reservations
                or closed
                or len(pending) + len(live) >= capacity
            ):
                raise ValueError("INVALID_SUPPLY_RESERVATION")
            reservations.add(reservation)
            pending[reservation] = owner, at
        elif action == "abort_reservation":
            reservation, owner = _name(event["reservation_id"]), _name(event["owner"])
            if reservation not in pending or pending[reservation][0] != owner:
                raise ValueError("INVALID_SUPPLY_RESERVATION_ABORT")
            _, start = pending.pop(reservation)
            if start is not None and at is not None:
                slots.append((start, at))
        elif action == "publish":
            reservation, identity = (
                _name(event["reservation_id"]),
                _name(event["token_id"]),
            )
            if reservation not in pending or identity in published:
                raise ValueError("INVALID_SUPPLY_PUBLICATION")
            owner, start = pending.pop(reservation)
            live[identity] = _Entry(reservation, owner, start, at)
            published[identity] = at
        elif action == "close":
            closed = True  # TokenBuffer.close is deliberately idempotent.
        elif action in ("claim", "consume", "abort_token", "remove"):
            identity = _name(event["token_id"])
            if identity not in live:
                raise ValueError("UNKNOWN_SUPPLY_TOKEN_EVENT")
            entry = live[identity]
            if action == "claim":
                if entry.state != "offered" or entry.consumer is not None:
                    raise ValueError("INVALID_SUPPLY_CLAIM")
                entry.consumer = _name(event["consumer"])
                entry.state = "reserved"
                if (
                    at is not None
                    and entry.published_at is not None
                    and low <= at < high
                ):
                    claims.append(at - entry.published_at)
            elif action == "consume":
                if (
                    entry.state != "reserved"
                    or _name(event["consumer"]) != entry.consumer
                ):
                    raise ValueError("INVALID_SUPPLY_CONSUMPTION")
                entry.state = "consumed"
            elif action == "abort_token":
                if entry.state not in ("offered", "reserved") or _name(
                    event["owner"]
                ) != (entry.consumer or entry.owner):
                    raise ValueError("INVALID_SUPPLY_TOKEN_ABORT")
                if identity in terminal and terminal[identity][2] != "discarded":
                    raise ValueError("SUPPLY_ABORT_CONFLICTS_WITH_LEDGER")
                entry.state = "discarded"
            else:
                proof = terminal.get(identity)
                if proof is not None:
                    used_at, safe_at, _ = proof
                    if used_at is None or safe_at is None:
                        known = False
                    elif at is not None and max(used_at, safe_at) > at:
                        raise ValueError("SUPPLY_REMOVE_BEFORE_TERMINAL_SAFE_EXIT")
                    if entry.state == "offered" and proof[2] != "discarded":
                        raise ValueError("SUPPLY_CONSUMPTION_WITHOUT_CLAIM")
                elif entry.state not in ("consumed", "discarded"):
                    if _resources(case).get("audit") is None:
                        known = False
                    else:
                        raise ValueError("SUPPLY_REMOVE_TERMINAL_PROOF_MISSING")
                if at is not None:
                    if entry.reserved_at is not None:
                        slots.append((entry.reserved_at, at))
                    if entry.published_at is not None:
                        residences.append((entry.published_at, at))
                        if low <= at < high:
                            completed.append(at - entry.published_at)
                del live[identity]
        else:
            raise ValueError(f"UNKNOWN_SUPPLY_AUDIT_ACTION: {action}")
    if (
        {key: value[0] for key, value in pending.items()} != dict(pending_final)
        or set(live) != set(final_items)
        or closed != snapshot["closed"]
        or len(pending) + len(live) != snapshot["occupied"]
    ):
        raise ValueError("SUPPLY_AUDIT_FINAL_STATE_MISMATCH")
    for identity, entry in live.items():
        item, token = final_items[identity], tokens.get(identity)
        expected_status = token["status"] if token is not None else entry.state
        if (
            item["reservation_id"] != entry.reservation
            or item["status"] != expected_status
        ):
            raise ValueError("SUPPLY_FINAL_ITEM_MISMATCH")
        if item.get("queued_at_us") is None:
            known = False
        elif (
            entry.published_at is not None
            and _time(item["queued_at_us"]) != entry.published_at
        ):
            raise ValueError("SUPPLY_FINAL_PUBLICATION_TIME_MISMATCH")
        if token is not None and any(
            item.get(key) != token.get(key) for key in ("carrier_id", "epoch")
        ):
            raise ValueError("SUPPLY_FINAL_TOKEN_IDENTITY_MISMATCH")
        if token is not None and (
            token["status"] in ("reserved", "consumed")
            and token["consumer"] != entry.consumer
            or token["status"] == "offered"
            and entry.state != "offered"
            or entry.state in ("consumed", "discarded")
            and token["status"] != entry.state
        ):
            raise ValueError("SUPPLY_FINAL_TOKEN_LIFECYCLE_MISMATCH")
        if entry.reserved_at is not None:
            slots.append((entry.reserved_at, duration))
        if entry.published_at is not None:
            residences.append((entry.published_at, duration))
    slots.extend(
        (start, duration) for _, start in pending.values() if start is not None
    )
    if not known:
        return _unknown_buffer("missing_event_timestamp"), published
    occupied, residence = _series(slots, low, high), _series(residences, low, high)
    return {
        "status": "known",
        "capacity": capacity,
        "occupied_slot_time_us": occupied["time_us"],
        "published_token_time_us": residence["time_us"],
        "peak_occupied_slots": occupied["peak"],
        "mean_occupied_slots": occupied["mean"],
        "peak_published_tokens": residence["peak"],
        "mean_published_tokens": residence["mean"],
        "residence_age_integral_us2": residence["age_integral_us2"],
        "token_time_weighted_mean_age_us": residence["mean_age_us"],
        "maximum_residence_age_us": residence["max_age_us"],
        "completed_residences": _sample(completed),
        "completed_claim_waits": _sample(claims),
        "residence_basis": "publish until explicit remove, including claimed/consumed/discarded items still occupying capacity",
    }, published


def _backlog(
    result: Mapping[str, Any],
    published: dict[str, float | None] | None,
    low: float,
    high: float,
) -> dict[str, Any]:
    case, supply = result["case"], result["supply"]
    identifiers = result.get("level1_factories")
    missing = None
    if identifiers is None or published is None:
        missing = "missing_level1_identity_or_publication_audit"
    elif (
        not isinstance(identifiers, list)
        or not identifiers
        or len(set(identifiers)) != len(identifiers)
        or any(i not in case["factories"] for i in identifiers)
    ):
        raise ValueError("INVALID_SUPPLY_PRODUCER_IDENTITIES")
    intervals: list[tuple[float, float]] = []
    published_waits: list[float] = []
    retained_waits: list[float] = []
    seen: set[str] = set()
    duration = _time(case["duration_us"])
    if missing is None:
        assert published is not None and identifiers is not None
        waiting, retained = (
            set(supply.get("waiting_producer_outputs", ())),
            set(supply.get("retained_outputs", ())),
        )
        if (
            len(waiting) != len(supply.get("waiting_producer_outputs", ()))
            or len(retained) != len(supply.get("retained_outputs", ()))
            or waiting & (published.keys() | retained)
        ):
            raise ValueError("DUPLICATE_OR_INCONSISTENT_SUPPLY_SOURCE_INVENTORY")
        for factory in identifiers:
            for output in case["factories"][factory].get("outputs", ()):
                token = _name(output["token_id"])
                if token in seen:
                    raise ValueError("DUPLICATE_SUPPLY_SOURCE_OUTPUT")
                seen.add(token)
                ready = _time(output["ready_at_us"])
                sample = None
                if token in published:
                    end = published[token]
                    sample = published_waits
                elif output.get("retention") is not None and token in retained:
                    end = _time(output["retained_at_us"])
                    if (
                        output["retention"].get("token_id") != token
                        or output["retention"].get("retained_at_us") != end
                    ):
                        raise ValueError("SUPPLY_SOURCE_RETENTION_MISMATCH")
                    sample = retained_waits
                elif token in waiting:
                    end = duration
                else:
                    end = None
                if end is None:
                    missing = "missing_output_publication_or_retention_endpoint"
                    continue
                if not ready <= end <= duration:
                    raise ValueError("SUPPLY_SOURCE_BACKLOG_TIME_MISMATCH")
                intervals.append((ready, end))
                if sample is not None and low <= end < high:
                    sample.append(end - ready)
        if not waiting <= seen or not retained <= seen or not published.keys() <= seen:
            raise ValueError("SUPPLY_SOURCE_FINAL_IDENTITY_MISMATCH")
    if missing is not None:
        return {
            "status": "unknown",
            "reason": missing,
            **{
                key: None
                for key in (
                    "token_time_us",
                    "peak_tokens",
                    "mean_tokens",
                    "age_integral_us2",
                    "token_time_weighted_mean_age_us",
                    "maximum_age_us",
                )
            },
        }
    values = _series(intervals, low, high)
    return {
        "status": "known",
        "token_time_us": values["time_us"],
        "peak_tokens": values["peak"],
        "mean_tokens": values["mean"],
        "age_integral_us2": values["age_integral_us2"],
        "token_time_weighted_mean_age_us": values["mean_age_us"],
        "maximum_age_us": values["max_age_us"],
        "completed_publication_waits": _sample(published_waits),
        "completed_retention_waits": _sample(retained_waits),
        "basis": "each accepted source output from ready until first publication, explicit retention, or known current waiting endpoint; retained inventory is not freed",
    }


def _unconsumed_unknown(reason: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "reason": reason,
        **{
            key: None
            for key in (
                "token_time_us",
                "age_integral_us2",
                "token_time_weighted_mean_age_us",
                "maximum_age_us",
                "peak_outputs",
                "mean_outputs",
                "unconsumed_at_case_end",
            )
        },
        "completed_use_ages": {"count": None, "mean_us": None, "samples": None},
        "completed_discard_ages": {"count": None, "mean_us": None, "samples": None},
    }


def _unconsumed_outputs(
    result: Mapping[str, Any],
    ledger: _LedgerIndex,
    low: float,
    high: float,
) -> dict[str, Any]:
    """Measure ready-to-use lifetime, independently of inventory reclamation."""
    case, identifiers = result["case"], result.get("level1_factories")
    resources = _resources(case)
    if (
        identifiers is None
        or not isinstance(resources.get("tokens"), list)
        or not isinstance(resources.get("audit"), list)
    ):
        return _unconsumed_unknown("missing_level1_or_ledger_evidence")
    if (
        not isinstance(identifiers, list)
        or not identifiers
        or len(set(identifiers)) != len(identifiers)
        or any(i not in case["factories"] for i in identifiers)
    ):
        raise ValueError("INVALID_UNCONSUMED_OUTPUT_FACTORY_IDENTITIES")
    outputs = [
        output
        for identity in identifiers
        for output in case["factories"][identity].get("outputs", ())
    ]
    tokens, terminal = ledger
    identities = [_name(output["token_id"]) for output in outputs]
    if len(set(identities)) != len(identities):
        raise ValueError("DUPLICATE_UNCONSUMED_OUTPUT_TOKEN")
    if any(identity not in tokens for identity in identities):
        return _unconsumed_unknown("missing_output_token_evidence")
    intervals = []
    uses: list[dict[str, Any]] = []
    discards: list[dict[str, Any]] = []
    living = 0
    duration = _time(case["duration_us"])
    for output in outputs:
        identity = output["token_id"]
        token, proof = tokens[identity], terminal.get(identity)
        if token.get("ready_at_us") is None or output.get("ready_at_us") is None:
            return _unconsumed_unknown("missing_output_ready_time")
        ready = _time(output["ready_at_us"])
        if token["ready_at_us"] != ready or any(
            key in output and output[key] != token.get(key)
            for key in ("carrier_id", "epoch")
        ):
            raise ValueError("UNCONSUMED_OUTPUT_LEDGER_IDENTITY_MISMATCH")
        state = token.get("status")
        sample = None
        if state in ("consumed", "discarded"):
            if proof is None or proof[0] is None:
                return _unconsumed_unknown("missing_output_terminal_event_time")
            end = proof[0]
            field = "consumed_at_us" if state == "consumed" else "discarded_at_us"
            if token.get(field) is None:
                return _unconsumed_unknown("missing_output_terminal_token_time")
            if proof[2] != state or _time(token[field]) != end:
                raise ValueError("UNCONSUMED_OUTPUT_TERMINAL_TIME_MISMATCH")
            sample = uses if state == "consumed" else discards
        elif state in ("offered", "reserved"):
            if (
                proof is not None
                or token.get("consumed_at_us") is not None
                or token.get("discarded_at_us") is not None
            ):
                raise ValueError("UNCONSUMED_OUTPUT_TERMINAL_STATE_MISMATCH")
            end = duration
            living += 1
        else:
            raise ValueError("INVALID_UNCONSUMED_OUTPUT_TOKEN_STATE")
        if not ready <= end <= duration:
            raise ValueError("UNCONSUMED_OUTPUT_LIFETIME_TIME_MISMATCH")
        intervals.append((ready, end))
        if sample is not None and low <= end < high:
            sample.append({"token_id": identity, "at_us": end, "age_us": end - ready})
    values = _series(intervals, low, high)
    return {
        "status": "known",
        "token_time_us": values["time_us"],
        "age_integral_us2": values["age_integral_us2"],
        "token_time_weighted_mean_age_us": values["mean_age_us"],
        "maximum_age_us": values["max_age_us"],
        "peak_outputs": values["peak"],
        "mean_outputs": values["mean"],
        "unconsumed_at_case_end": living,
        "completed_use_ages": {
            **_sample([row["age_us"] for row in uses]),
            "samples": uses,
        },
        "completed_discard_ages": {
            **_sample([row["age_us"] for row in discards]),
            "samples": discards,
        },
        "basis": "resource-output lifetime from ready until actual ledger use (including adopt) or discard; includes transport and operations, not idle-only time or a quantum-noise estimate; unused and retained outputs age through case end",
    }


def _waits(case: Mapping[str, Any], low: float, high: float) -> dict[str, Any]:
    reasons = {
        "consumer_waiting_for_accepted_input": (
            "consumer_starvation",
            "waiting_supply",
        ),
        "producer_buffer_backpressure": ("producer_backpressure", "waiting_buffer"),
    }
    totals: dict[str, dict[str, float]] = {kind: {} for kind, _ in reasons.values()}
    intervals: dict[str, list[tuple[float, float]]] = {kind: [] for kind in totals}
    unknown = []
    duration = _time(case["duration_us"])
    for factory, line in case.get("factories", {}).items():
        states = [
            m
            for m in line.get("milestones", ())
            if m.get("kind") == "line_state_changed"
        ]
        finish = line.get("completed_at_us", line.get("finished_at_us"))
        finish = duration if finish is None else _time(finish)
        known = bool(states) and all(m.get("at_us") is not None for m in states)
        previous = 0.0
        for state in states:
            if state.get("at_us") is None:
                continue
            at = _time(state["at_us"])
            if not previous <= at <= finish <= duration:
                raise ValueError("SUPPLY_WAIT_TIME_REVERSED_OR_AFTER_FINISH")
            previous = at
            if state["state"] in (
                "waiting_supply",
                "waiting_buffer",
            ) and not isinstance(state.get("reason"), str):
                known = False
        if not known or states[0]["at_us"] > low:
            unknown.append(factory)
            continue
        for index, state in enumerate(states):
            entry = reasons.get(state.get("reason"))
            if entry is None:
                continue
            kind, expected_state = entry
            if state["state"] != expected_state:
                raise ValueError("SUPPLY_WAIT_REASON_STATE_MISMATCH")
            end = states[index + 1]["at_us"] if index + 1 < len(states) else finish
            left, right = max(low, state["at_us"]), min(high, end)
            if left < right:
                intervals[kind].append((left, right))
                totals[kind][factory] = totals[kind].get(factory, 0.0) + right - left
    if not case.get("factories") or unknown:
        return {
            "status": "unknown",
            "unresolved_factories": unknown,
            **{kind: {"factory_sum_us": None, "union_us": None} for kind in totals},
        }
    return {
        "status": "known",
        **{
            kind: {
                "factory_sum_us": sum(totals[kind].values()),
                "union_us": interval_union_us(intervals[kind]),
                "by_factory_us": dict(sorted(totals[kind].items())),
            }
            for kind in totals
        },
    }


def summarize_supply_window(
    result: Mapping[str, Any],
    *,
    warmup_us: float,
    stop_us: float,
) -> dict[str, Any]:
    """Integrate saved FIFO occupancy, resource lifetimes, backlog and waits.

    Events and completed residence/claim samples use [warmup, stop); intervals
    are clipped to the observed case duration. Mean ages are token-time weighted,
    maximum ages are suprema, and completed samples retain their full durations.
    Occupancy peaks are over positive-duration residence intervals, not terminal
    snapshots or zero-duration bookkeeping spikes. Capacity is producer-held
    inventory, never an allocation of dedicated physical buffer atoms.
    Unconsumed-output age ends at ledger use/discard, not safe exit or remove;
    retained outputs continue aging to case end without an invented consumption.

    Missing audit/timestamps return explicit unknown/null metrics for that domain.
    Invalid ordering, identity, capacity or final inventory raises ValueError.
    This function is read-only and never compiles, samples or infers output error.
    """
    low, stop, duration = (
        _time(warmup_us),
        _time(stop_us),
        _time(result["case"]["duration_us"]),
    )
    if stop <= low:
        raise ValueError("INVALID_SUPPLY_OBSERVATION_WINDOW")
    high = max(low, min(stop, duration))
    ledger = _ledger(result["case"])
    buffer, published = _buffer(
        result["supply"]["buffer"], result["case"], low, high, ledger
    )
    return {
        "schema": "nadit.msd.supply_window_metrics/1",
        "requested_window_us": [low, stop],
        "actual_window_us": [low, high],
        "observed_duration_us": high - low,
        "requested_window_complete": duration >= stop,
        "boundary_convention": "[warmup_us, stop_us); residence maximum is a supremum",
        "buffer": buffer,
        "source_backlog": _backlog(result, published, low, high),
        "unconsumed_outputs": _unconsumed_outputs(result, ledger, low, high),
        "waits": _waits(result["case"], low, high),
        "actual_output_error": None,
    }
