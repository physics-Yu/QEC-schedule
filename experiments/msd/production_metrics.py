"""Windowed production accounting from whole-world shared-wave action traces.

Point events use [warmup, stop); intervals are clipped to the same window. Every
execution wave is counted once, irrespective of its number of member receipts.
Move records contain endpoints but no within-action trajectory. A window cutting
a Move therefore has unknown movement distance and visited bounds, never a linear
interpolation presented as evidence. Full moves use native endpoint displacement.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet
from copy import deepcopy
from dataclasses import dataclass
from math import hypot, isclose, isfinite
from time import perf_counter
from typing import Any

from nadit_physical_compiler.activity import AtomActivity, derive_activity
from nadit_physical_compiler.cost.base import require_validated
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import (
    decode_layout,
    decode_program,
    encode_device,
)
from nadit_physical_compiler.state import SLMHolder

from modules.logical_compiler.src.estimation.metrics import interval_union_us
from modules.logical_compiler.src.protocols.protocol_intents import (
    RESOURCE_WAIT_INSTRUMENTATION_SCHEMA,
)

from .joint_transition import apply_joint_transition
from .standard import ExperimentWorld

type TraceSource = Mapping[str, Mapping[str, Any]] | Callable[[str], Mapping[str, Any]]
type _AuditEvent = tuple[int, Mapping[str, Any]]


@dataclass(frozen=True)
class _DeliveryIndex:
    consumes: dict[str, list[_AuditEvent]]
    releases: dict[tuple[str, int, str], list[_AuditEvent]]
    preparations: dict[tuple[str, int], _AuditEvent]
    next_preparations: dict[tuple[str, int], _AuditEvent]
    offers: dict[str, list[_AuditEvent]]
    reserves: dict[str, list[_AuditEvent]]
    discards: dict[str, list[_AuditEvent]]


def _index_delivery_audit(audit: list[Mapping[str, Any]]) -> _DeliveryIndex:
    """Index the ledger once; historical releases are tied to carrier epochs."""
    consumes: dict[str, list[_AuditEvent]] = defaultdict(list)
    releases: dict[tuple[str, int, str], list[_AuditEvent]] = defaultdict(list)
    preparations: dict[tuple[str, int], _AuditEvent] = {}
    following: dict[tuple[str, int], _AuditEvent] = {}
    previous: dict[str, int] = {}
    offers: dict[str, list[_AuditEvent]] = defaultdict(list)
    reserves: dict[str, list[_AuditEvent]] = defaultdict(list)
    discards: dict[str, list[_AuditEvent]] = defaultdict(list)
    for index, event in enumerate(audit):
        action = event["action"]
        if action not in (
            "consume",
            "complete_use",
            "begin_preparation",
            "offer",
            "reserve",
            "discard",
        ):
            continue
        _time(event["at_us"])
        record = (index, event)
        if action in ("offer", "reserve", "discard"):
            target = {"offer": offers, "reserve": reserves, "discard": discards}[action]
            identity = (
                event["token"]["token_id"] if action == "offer" else event["token_id"]
            )
            target[identity].append(record)
            continue
        if action == "consume":
            consumes[event["token_id"]].append(record)
            continue
        carrier, epoch = event["carrier_id"], event["epoch"]
        if type(epoch) is not int or epoch < (
            1 if action == "begin_preparation" else 0
        ):
            raise ValueError("INVALID_OUTPUT_DELIVERY_AUDIT_EPOCH")
        if action == "complete_use":
            releases[(carrier, epoch, event["owner"])].append(record)
        else:
            if carrier in previous:
                if epoch <= previous[carrier]:
                    raise ValueError("INVALID_OUTPUT_DELIVERY_PREPARATION_ORDER")
                following[(carrier, previous[carrier])] = record
            preparations[(carrier, epoch)] = record
            previous[carrier] = epoch
    return _DeliveryIndex(
        consumes, releases, preparations, following, offers, reserves, discards
    )


def _verified_offer(
    token: Mapping[str, Any], audit: _DeliveryIndex
) -> Mapping[str, Any]:
    records = audit.offers.get(token["token_id"], ())
    if len(records) != 1:
        raise ValueError("OUTPUT_TRANSFER_OFFER_AUDIT_MISMATCH")
    offered = records[0][1]
    mutable = {"status", "consumer", "consumed_at_us", "usage_kind"}
    if offered["token"].get("status") != "offered" or any(
        token.get(key) != value
        for key, value in offered["token"].items()
        if key not in mutable
    ):
        raise ValueError("OUTPUT_TRANSFER_TOKEN_IDENTITY_CHANGED")
    return offered


def _verify_handoff(
    output: Mapping[str, Any],
    token: Mapping[str, Any],
    audit: _DeliveryIndex,
    history: _BindingHistory,
    duration: float,
) -> dict[str, Any]:
    receipt = output["handoff"]
    if not isinstance(receipt, Mapping) or any(
        receipt.get(key) != output.get(key)
        for key in (
            "token_id",
            "carrier_id",
            "handoff_at_us",
            "replacement_carrier_id",
            "replacement_ready_at_us",
        )
    ):
        raise ValueError("OUTPUT_HANDOFF_RECEIPT_MISMATCH")
    consumer = receipt.get("consumer")
    at, replacement_ready = (
        _time(receipt["handoff_at_us"]),
        _time(receipt["replacement_ready_at_us"]),
    )
    if (
        not isinstance(consumer, str)
        or not consumer
        or not max(token["ready_at_us"], token["exit_at_us"]) <= at <= duration
        or replacement_ready > duration
        or receipt["replacement_carrier_id"] == output["carrier_id"]
        or receipt["replacement_carrier_id"] not in history.positions
        or token.get("consumer") != consumer
    ):
        raise ValueError("OUTPUT_HANDOFF_LIFECYCLE_MISMATCH")
    _verified_offer(token, audit)
    reserved = audit.reserves.get(token["token_id"], ())
    if (
        len(reserved) != 1
        or reserved[0][1]["consumer"] != consumer
        or not token["ready_at_us"] <= _time(reserved[0][1]["at_us"]) <= at
    ):
        raise ValueError("OUTPUT_HANDOFF_RESERVATION_AUDIT_MISMATCH")
    consumed, discarded = (
        audit.consumes.get(token["token_id"], ()),
        audit.discards.get(token["token_id"], ()),
    )
    if token["status"] == "reserved":
        valid_final = not consumed and not discarded
    elif token["status"] == "consumed":
        valid_final = (
            len(consumed) == 1
            and not discarded
            and consumed[0][1]["consumer"] == consumer
            and consumed[0][1]["at_us"] == token["consumed_at_us"]
            and _time(token["consumed_at_us"]) >= at
        )
    elif token["status"] == "discarded":
        valid_final = (
            len(discarded) == 1
            and not consumed
            and _time(discarded[0][1]["at_us"]) >= at
        )
    else:
        valid_final = False
    if not valid_final:
        raise ValueError("OUTPUT_HANDOFF_HISTORICAL_LIFECYCLE_MISMATCH")
    evidence = receipt.get("evidence")
    if (
        not isinstance(evidence, Mapping)
        or not evidence.get("scope")
        or not isinstance(evidence.get("delivery_trace_ref"), str)
    ):
        raise ValueError("OUTPUT_HANDOFF_NATIVE_EVIDENCE_REQUIRED")
    history.verify_delivery(
        output["carrier_id"],
        evidence["delivery_trace_ref"],
        max(token["ready_at_us"], token["exit_at_us"]),
        at,
    )
    return {
        "output_disposition": "handoff",
        "handoff_lifecycle_verified": True,
        "handoff_position_um": history.position(output["carrier_id"], at),
    }


def _verify_retention(
    output: Mapping[str, Any],
    token: Mapping[str, Any],
    audit: _DeliveryIndex,
    carriers: Mapping[str, Mapping[str, Any]],
    history: _BindingHistory,
    duration: float,
) -> dict[str, Any]:
    receipt = output["retention"]
    if (
        not isinstance(receipt, Mapping)
        or any(
            receipt.get(key) != output.get(key)
            for key in ("token_id", "carrier_id", "retained_at_us")
        )
        or receipt.get("reason") != output.get("retention_reason")
        or not isinstance(receipt.get("reason"), str)
        or not receipt["reason"]
        or not isinstance(receipt.get("evidence"), Mapping)
        or not receipt["evidence"]
    ):
        raise ValueError("OUTPUT_RETENTION_RECEIPT_MISMATCH")
    at = _time(receipt["retained_at_us"])
    offered = _verified_offer(token, audit)
    carrier = carriers.get(output["carrier_id"], {})
    owner = receipt.get("producer_owner")
    if (
        token["status"] != "offered"
        or token.get("consumer") is not None
        or token.get("consumed_at_us") is not None
        or token.get("usage_kind") is not None
        or not max(token["ready_at_us"], token["exit_at_us"]) <= at <= duration
        or not isinstance(owner, str)
        or not owner
        or offered["owner"] != owner
        or carrier.get("owner") != owner
        or carrier.get("phase") != "resource"
        or carrier.get("epoch") != token["epoch"]
        or audit.reserves.get(token["token_id"])
        or audit.consumes.get(token["token_id"])
        or audit.discards.get(token["token_id"])
        or audit.releases.get((output["carrier_id"], output["epoch"], owner))
    ):
        raise ValueError("OUTPUT_RETENTION_LIFECYCLE_MISMATCH")
    return {
        "output_disposition": "retained",
        "retention_lifecycle_verified": True,
        "retained_position_um": history.position(output["carrier_id"], at),
    }


def _verify_output_delivery(
    output: Mapping[str, Any], token: Mapping[str, Any], audit: _DeliveryIndex
) -> bool:
    """Verify complete reported delivery, preserving explicitly undelivered outputs."""
    fields = ("deliverable_at_us", "consumed_at_us", "released_at_us")
    delivery = output.get("delivery")
    if all(output[field] is None for field in fields):
        if delivery is not None:
            raise ValueError("INCONSISTENT_OUTPUT_DELIVERY_RECEIPT")
        return False
    if not isinstance(delivery, Mapping) or any(
        output[field] is None for field in fields
    ):
        raise ValueError("INCOMPLETE_OUTPUT_DELIVERY_RECEIPT")
    consumer = delivery.get("consumer")
    if (
        not isinstance(consumer, str)
        or not consumer.strip()
        or any(
            delivery.get(field) != output[field]
            for field in (*fields, "token_id", "carrier_id")
        )
        or token.get("status") != "consumed"
        or token.get("consumer") != consumer
        or token.get("consumed_at_us") != output["consumed_at_us"]
    ):
        raise ValueError("OUTPUT_DELIVERY_TOKEN_MISMATCH")
    for field in fields:
        _time(delivery[field])
    consumed, released = _time(token["consumed_at_us"]), output["released_at_us"]
    if consumed < _time(token["exit_at_us"]):
        raise ValueError("OUTPUT_DELIVERY_PRECEDES_SAFE_EXIT")
    epoch_key = (output["carrier_id"], output["epoch"])
    consume_events = audit.consumes.get(output["token_id"], ())
    release_events = audit.releases.get((*epoch_key, consumer), ())
    begin = audit.preparations.get(epoch_key)
    if len(consume_events) != 1 or len(release_events) != 1 or begin is None:
        raise ValueError("OUTPUT_DELIVERY_AUDIT_COVERAGE_MISMATCH")
    consume_index, consume = consume_events[0]
    release_index, release = release_events[0]
    if (
        consume["consumer"] != consumer
        or consume["at_us"] != consumed
        or release["at_us"] != released
        or not consumed <= _time(consume["safe_exit_at_us"]) <= released
        or consume.get("usage_kind") != token.get("usage_kind")
        or not (begin[1]["at_us"], begin[0])
        <= (consumed, consume_index)
        <= (released, release_index)
        or begin[1]["at_us"] > output["ready_at_us"]
    ):
        raise ValueError("OUTPUT_DELIVERY_AUDIT_TIME_OR_OWNER_MISMATCH")
    next_begin = audit.next_preparations.get(epoch_key)
    if next_begin is not None and (next_begin[1]["at_us"], next_begin[0]) < (
        released,
        release_index,
    ):
        raise ValueError("OUTPUT_DELIVERY_CARRIER_REUSED_BEFORE_RELEASE")
    return True


def _time(value: Any) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError("INVALID_PRODUCTION_METRIC_TIME")
    return float(value)


def _clip(
    start: float, end: float, low: float, high: float
) -> tuple[float, float] | None:
    if end < start:
        raise ValueError("REVERSED_PRODUCTION_INTERVAL")
    left, right = max(start, low), min(end, high)
    return (left, right) if right > left else None


def _bounds(points: list[tuple[float, float]]) -> list[float] | None:
    if not points:
        return None
    xs, ys = zip(*points, strict=True)
    return [min(xs), min(ys), max(xs), max(ys)]


def _trace(
    document: Mapping[str, Any], key: str, world: ExperimentWorld
) -> tuple[AtomActivity, tuple[str | None, ...]]:
    if canonical_hash(document) != key:
        raise ValueError("PRODUCTION_TRACE_HASH_MISMATCH")
    require_validated(document)
    if document["device"] != encode_device(world.device):
        raise ValueError("UNSUPPORTED_PRODUCTION_TRACE_DEVICE_MISMATCH")
    activity = derive_activity(document)
    if {atom.atom_id for atom in activity.per_atom} != {
        a.id for a in world.state.atoms
    }:
        raise ValueError("PRODUCTION_TRACE_ATOM_MISMATCH")
    program = decode_program(document["program"])
    resources: list[str | None] = []
    for event in activity.events:
        action = program.steps[event.step_index].actions[event.action_index]
        if hasattr(action, "grid"):
            resources.append("aod:" + action.grid.aod_id)
        elif hasattr(action, "channel"):
            resources.append("channel:" + action.channel)
        else:
            resources.append(None)
    return activity, tuple(resources)


def _advance_world(
    document: Mapping[str, Any],
    key: str,
    world: ExperimentWorld,
    wave: Mapping[str, Any],
    calls: Mapping[str, Mapping[str, Any]],
) -> ExperimentWorld:
    """Verify each wave's entry and committed world chain, including cache hits."""
    entry = decode_layout(document["entry_state"])
    if entry.atoms != world.state.atoms or entry.aod_grids != world.state.aod_grids:
        raise ValueError("PRODUCTION_WAVE_ENTRY_WORLD_MISMATCH")
    transition = wave.get("state_transition")
    if transition is None:
        if (
            document.get("transport_goals")
            or document["exit_state"] != document["entry_state"]
        ):
            raise ValueError("UNSUPPORTED_PRODUCTION_TRACE_NON_HOME_WORLD")
        return world
    if transition["trace_sha256"] != key or transition[
        "entry_world_sha256"
    ] != canonical_hash(world.document()):
        raise ValueError("PRODUCTION_TRANSITION_ENTRY_CHAIN_MISMATCH")
    action = {
        "schema": "nadit.joint_actions/1",
        "validation_ok": True,
        "trace_sha256": key,
        "members": {
            calls[identity]["component_id"]
            + ":"
            + ",".join(calls[identity]["participant_blocks"]): {}
            for identity in wave["invocations"]
        },
        "state_transition": {
            "schema": "nadit.joint_world_transition/1",
            "entry_state_sha256": canonical_hash(document["entry_state"]),
            "exit_state_sha256": canonical_hash(document["exit_state"]),
            "bindings": transition["bindings"],
        },
    }
    following = apply_joint_transition(world, action, document)
    if transition["exit_world_sha256"] != canonical_hash(following.document()):
        raise ValueError("PRODUCTION_TRANSITION_EXIT_CHAIN_MISMATCH")
    return following


class _BindingHistory:
    """Keep only changed carrier bindings and transition references, not worlds."""

    def __init__(self, world: ExperimentWorld):
        self.positions = {
            patch.binding.block_id: [(0.0, patch.binding.origin)]
            for patch in world.patches
        }
        self.transports: dict[
            str, list[tuple[float, float, str, Mapping[str, Any]]]
        ] = defaultdict(list)
        self.by_trace: dict[
            tuple[str, str], list[tuple[float, float, str, Mapping[str, Any]]]
        ] = defaultdict(list)

    def record(self, wave: Mapping[str, Any], key: str) -> None:
        for update in wave["state_transition"]["bindings"].values():
            carrier = update["exit"]["block_id"]
            self.positions[carrier].append(
                (wave["end_us"], Position(**update["exit"]["origin"]))
            )
            self.transports[carrier].append(
                (wave["start_us"], wave["end_us"], key, update)
            )
            self.by_trace[carrier, key].append(self.transports[carrier][-1])

    def verify_delivery(
        self, carrier: str, key: str, earliest: float, at_us: float
    ) -> None:
        records = self.by_trace.get((carrier, key), ())
        index = bisect_right(records, at_us, key=lambda row: row[1]) - 1
        if index < 0 or records[index][0] < earliest:
            raise ValueError("OUTPUT_HANDOFF_NATIVE_TRANSPORT_HISTORY_MISMATCH")
        origin = records[index][3]["exit"]["origin"]
        if self.position(carrier, at_us) != [origin["x"], origin["y"]]:
            raise ValueError("OUTPUT_HANDOFF_DESTINATION_CHANGED")

    def position(self, carrier: str, at_us: float) -> list[float]:
        if carrier not in self.positions:
            raise ValueError("UNSUPPORTED_PRODUCTION_OUTPUT_CARRIER")
        history = self.positions[carrier]
        index = bisect_right(history, at_us, key=lambda row: row[0]) - 1
        movements = self.transports.get(carrier, ())
        current = bisect_right(movements, at_us, key=lambda row: row[0]) - 1
        if current >= 0 and movements[current][0] < at_us < movements[current][1]:
            raise ValueError("UNSUPPORTED_OUTPUT_POSITION_DURING_RELOCATION")
        origin = history[index][1]
        return [origin.x, origin.y]


def _outputs(
    case: Mapping[str, Any],
    world: ExperimentWorld,
    low: float,
    high: float,
    history: _BindingHistory | None = None,
) -> list[dict[str, Any]]:
    result, seen = [], set()
    tokens = {token["token_id"]: token for token in case["resources"]["tokens"]}
    if len(tokens) != len(case["resources"]["tokens"]):
        raise ValueError("DUPLICATE_PRODUCTION_LEDGER_TOKEN")
    patches = {patch.binding.block_id: patch for patch in world.patches}
    delivery_audit = _index_delivery_audit(case["resources"]["audit"])
    history = _BindingHistory(world) if history is None else history
    carriers = {row["carrier_id"]: row for row in case["resources"].get("carriers", ())}
    for factory, line in case["factories"].items():
        for output in line.get("outputs", ()):
            identity = output["token_id"]
            if identity in seen:
                raise ValueError("DUPLICATE_PRODUCTION_OUTPUT")
            seen.add(identity)
            token = tokens.get(identity)
            if (
                token is None
                or token["carrier_id"] != output["carrier_id"]
                or token["ready_at_us"] != output["ready_at_us"]
                or token["epoch"] != output["epoch"]
                or type(token["epoch"]) is not int
                or type(output["epoch"]) is not int
                or token["quality"] != output["quality"]
            ):
                raise ValueError("PRODUCTION_OUTPUT_LEDGER_MISMATCH")
            patch = patches.get(output["carrier_id"])
            if patch is None:
                raise ValueError("UNSUPPORTED_PRODUCTION_OUTPUT_CARRIER")
            ready = _time(output["ready_at_us"])
            previous = ready
            missing = False
            for field in ("deliverable_at_us", "consumed_at_us", "released_at_us"):
                value = output[field]
                if value is not None:
                    value = _time(value)
                    if missing or value < previous or value > case["duration_us"]:
                        raise ValueError("PRODUCTION_OUTPUT_TIME_MISMATCH")
                    previous = value
                else:
                    missing = True
            if ready > case["duration_us"]:
                raise ValueError("PRODUCTION_OUTPUT_AFTER_EXECUTION")
            delivered = output["deliverable_at_us"]
            kinds = [
                name
                for name in ("delivery", "handoff", "retention")
                if output.get(name) is not None
            ]
            if len(kinds) > 1:
                raise ValueError("CONFLICTING_OUTPUT_DISPOSITIONS")
            transferred = kinds and kinds[0] in ("handoff", "retention")
            if transferred and any(
                output[field] is not None
                for field in ("deliverable_at_us", "consumed_at_us", "released_at_us")
            ):
                raise ValueError("OUTPUT_TRANSFER_IS_NOT_TERMINAL_DELIVERY")
            extra = (
                _verify_handoff(
                    output, token, delivery_audit, history, case["duration_us"]
                )
                if output.get("handoff") is not None
                else _verify_retention(
                    output,
                    token,
                    delivery_audit,
                    carriers,
                    history,
                    case["duration_us"],
                )
                if output.get("retention") is not None
                else {}
            )
            verified = (
                False
                if transferred
                else _verify_output_delivery(output, token, delivery_audit)
            )
            result.append(
                {
                    **deepcopy(dict(output)),
                    "factory_id": factory,
                    "position_um": history.position(output["carrier_id"], ready),
                    "output_disposition": "terminal_delivery"
                    if verified
                    else "pending",
                    **extra,
                    "delivery_lifecycle_verified": verified,
                    "accepted_in_window": low <= ready < high,
                    "delivered_in_window": delivered is not None
                    and low <= delivered < high,
                    "handed_off_in_window": output.get("handoff") is not None
                    and low <= output["handoff_at_us"] < high,
                    "retained_in_window": output.get("retention") is not None
                    and low <= output["retained_at_us"] < high,
                }
            )
    return result


def _ownership(
    case: Mapping[str, Any], world: ExperimentWorld, low: float, high: float
) -> dict[str, Any]:
    weights = {
        patch.binding.block_id: len(patch.binding.atom_ids) for patch in world.patches
    }
    opened: dict[str, float] = {}
    intervals: list[tuple[str, float, float]] = []
    audit = sorted(
        enumerate(case["resources"]["audit"]),
        key=lambda item: (item[1]["at_us"], item[0]),
    )
    for _, event in audit:
        action = event["action"]
        if action not in ("begin_preparation", "acquire_transport", "complete_use"):
            continue
        carrier, at = event["carrier_id"], _time(event["at_us"])
        if carrier not in weights or at > case["duration_us"]:
            raise ValueError("PRODUCTION_OWNERSHIP_WORLD_MISMATCH")
        if action in ("begin_preparation", "acquire_transport"):
            if carrier in opened:
                raise ValueError("OVERLAPPING_PRODUCTION_OWNERSHIP")
            opened[carrier] = at
        elif carrier not in opened:
            raise ValueError("UNMATCHED_PRODUCTION_RELEASE")
        else:
            intervals.append((carrier, opened.pop(carrier), at))
    intervals.extend(
        (carrier, start, case["duration_us"]) for carrier, start in opened.items()
    )
    edges: Counter[float] = Counter()
    atom_time = 0.0
    for carrier, start, end in intervals:
        overlap = _clip(start, end, low, high)
        if overlap is not None:
            left, right = overlap
            edges[left] += weights[carrier]
            edges[right] -= weights[carrier]
            atom_time += weights[carrier] * (right - left)
    current = peak = 0
    for at in sorted(edges):
        current += edges[at]
        peak = max(peak, current)
    return {"peak_owned_atoms": peak, "owned_atom_time_us": atom_time}


def _waiting(case: Mapping[str, Any], low: float, high: float) -> dict[str, Any]:
    totals: dict[str, float] = defaultdict(float)
    for line in case["factories"].values():
        states = sorted(
            (m for m in line["milestones"] if m["kind"] == "line_state_changed"),
            key=lambda m: m["at_us"],
        )
        finish = line.get("completed_at_us")
        if finish is None:
            finish = case["duration_us"]
        for index, state in enumerate(states):
            end = states[index + 1]["at_us"] if index + 1 < len(states) else finish
            overlap = _clip(state["at_us"], end, low, high)
            if overlap is not None and state["state"].startswith("waiting_"):
                totals[state["state"]] += overlap[1] - overlap[0]
    waits = [
        interval
        for w in case["execution"].get("waits", ())
        if (interval := _clip(_time(w["start_us"]), _time(w["end_us"]), low, high))
        is not None
    ]
    declaration = case.get("wait_instrumentation", {})
    kinds = (
        declaration.get("resource_wait_kinds", ())
        if isinstance(declaration, Mapping)
        else ()
    )
    buffer_instrumented = (
        isinstance(declaration, Mapping)
        and declaration.get("schema") == RESOURCE_WAIT_INSTRUMENTATION_SCHEMA
        and isinstance(kinds, (list, tuple))
        and "buffer" in kinds
    )
    buffer_wait = totals.get("waiting_buffer", 0.0 if buffer_instrumented else None)
    return {
        "factory_wait_by_state_us": dict(totals),
        "factory_wait_basis": "sum of factory intervals; not global elapsed time",
        "global_wait_union_us": interval_union_us(waits),
        "buffer_wait_us": buffer_wait,
        "buffer_wait_status": "recorded"
        if buffer_wait is not None
        else "not_separately_instrumented",
    }


def _waves(case: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], str]]:
    calls = {c["invocation_id"]: c for c in case["execution"]["calls"]}
    if len(calls) != len(case["execution"]["calls"]):
        raise ValueError("DUPLICATE_PRODUCTION_CALL")
    seen_calls: set[str] = set()
    seen_waves: set[str] = set()
    result = []
    previous = 0.0
    for wave in sorted(case["execution"]["waves"], key=lambda w: w["start_us"]):
        start, end = _time(wave["start_us"]), _time(wave["end_us"])
        if start < previous or end < start or end > case["duration_us"]:
            raise ValueError("UNSUPPORTED_OVERLAPPING_OR_INVALID_PRODUCTION_WAVE")
        previous = end
        members = wave["invocations"]
        if (
            wave["batch_id"] in seen_waves
            or not members
            or len(set(members)) != len(members)
            or seen_calls.intersection(members)
        ):
            raise ValueError("DUPLICATE_PRODUCTION_WAVE")
        seen_waves.add(wave["batch_id"])
        seen_calls.update(members)
        hashes = set()
        for identity in members:
            call = calls[identity]
            if call["start_us"] != start or call["action_end_us"] != end:
                raise ValueError("PRODUCTION_CALL_WAVE_TIME_MISMATCH")
            key = call.get(
                "joint_trace_sha256",
                call.get("provenance", {}).get("joint_trace_sha256"),
            )
            if not isinstance(key, str) or not key:
                raise ValueError("PRODUCTION_REQUIRES_JOINT_TRACE_RECEIPTS")
            hashes.add(key)
        if len(hashes) != 1:
            raise ValueError("PRODUCTION_WAVE_TRACE_MISMATCH")
        result.append((wave, hashes.pop()))
    if seen_calls != set(calls):
        raise ValueError("PRODUCTION_CALL_MISSING_WAVE")
    return result


def summarize_production(
    case: Mapping[str, Any],
    world: ExperimentWorld,
    traces: TraceSource,
    *,
    warmup_us: float = 0,
    stop_us: float,
    output_factory_ids: AbstractSet[str] | None = None,
) -> dict[str, Any]:
    """Summarize one continuous trajectory using actual whole-world wave traces.

    ``traces`` maps exact trace hashes to saved result documents, or loads them
    through a callable. Same-code stateful waves must provide verified native
    transition and world-chain evidence. output_factory_ids filters outputs and
    cost denominators only; all levels' physical actions and waits remain counted.
    Raises ValueError for duplicate outputs/waves, mismatched worlds or absent
    joint evidence. No compiler, sampler or quality model is invoked.
    """
    started = perf_counter()
    low, stop, duration = _time(warmup_us), _time(stop_us), _time(case["duration_us"])
    if stop < low:
        raise ValueError("INVALID_PRODUCTION_OBSERVATION_WINDOW")
    if len(world.device.aods) != 1 or any(
        not isinstance(a.holder, SLMHolder) for a in world.state.atoms
    ):
        raise ValueError("UNSUPPORTED_PRODUCTION_WORLD")
    high = min(stop, duration)
    elapsed = max(0.0, high - low)
    selected_factories = (
        set(case["factories"])
        if output_factory_ids is None
        else set(output_factory_ids)
    )
    if (
        output_factory_ids is not None
        and not isinstance(output_factory_ids, AbstractSet)
        or not selected_factories
        or not selected_factories <= case["factories"].keys()
    ):
        raise ValueError("INVALID_PRODUCTION_OUTPUT_FACTORY_FILTER")
    failures = [
        deepcopy(line["failure"])
        for line in case["factories"].values()
        if line.get("failure") is not None
    ]
    if case.get("failure") is not None:
        failures.append(deepcopy(case["failure"]))
    early_failure = any(f.get("at_us", 0) < stop for f in failures) or (
        case["status"] != "complete" and not failures
    )
    complete = duration >= stop and not early_failure
    records: dict[str, tuple[AtomActivity, tuple[str | None, ...]]] = {}
    documents: dict[str, Mapping[str, Any]] = {}
    history = _BindingHistory(world)
    current_world = world
    transitions = 0
    calls_by_id = {call["invocation_id"]: call for call in case["execution"]["calls"]}
    resource_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    exposure: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "action_count": 0,
            "atom_events": 0,
            "overlapping_actions": 0,
            "atom_us": 0.0,
        }
    )
    idle: dict[str, float] = defaultdict(float)
    busy = move_distance = load_seconds = activity_seconds = 0.0
    partial_moves = waves_in_window = 0
    points: list[tuple[float, float]] = []
    validations = []
    previous_end = 0.0
    outside = 0.0
    for wave, key in _waves(case):
        offset, end = wave["start_us"], wave["end_us"]
        gap = _clip(previous_end, offset, low, high)
        if gap is not None:
            outside += gap[1] - gap[0]
            idle["slm"] += len(current_world.state.atoms) * (gap[1] - gap[0])
            points.extend(
                (atom.position.x, atom.position.y) for atom in current_world.state.atoms
            )
        previous_end = end
        overlap = _clip(offset, end, low, high)
        if key not in records:
            before = perf_counter()
            document = traces(key) if callable(traces) else traces[key]
            load_seconds += perf_counter() - before
            before = perf_counter()
            records[key] = _trace(document, key, current_world)
            documents[key] = document
            activity_seconds += perf_counter() - before
            validations.append(document.get("validation", {}).get("ok") is True)
        following = _advance_world(
            documents[key], key, current_world, wave, calls_by_id
        )
        wave_world = current_world
        current_world = following
        if wave.get("state_transition") is not None:
            transitions += 1
            history.record(wave, key)
        activity, resources = records[key]
        if not isclose(activity.duration_us, end - offset, abs_tol=1e-7):
            raise ValueError("PRODUCTION_WAVE_TRACE_DURATION_MISMATCH")
        if overlap is None:
            continue
        waves_in_window += 1
        local_start = overlap[0] - offset
        positions = {a.id: (a.position.x, a.position.y) for a in wave_world.state.atoms}
        for event in activity.events:
            if (
                event.kind == "Move"
                and event.start_us + event.duration_us <= local_start
            ):
                positions.update(zip(event.atoms, event.ends, strict=True))
        points.extend(positions.values())
        for atom in activity.per_atom:
            intervals = [
                interval
                for part in atom.busy
                if (
                    interval := _clip(
                        offset + part.start_us, offset + part.end_us, low, high
                    )
                )
                is not None
            ]
            busy += interval_union_us(intervals)
            for part in atom.idle:
                interval = _clip(
                    offset + part.start_us, offset + part.end_us, low, high
                )
                if interval is not None:
                    idle[part.holder] += interval[1] - interval[0]
        for event, resource in zip(activity.events, resources, strict=True):
            start, finish = (
                offset + event.start_us,
                offset + event.start_us + event.duration_us,
            )
            interval = _clip(start, finish, low, high)
            row = exposure[event.kind]
            if low <= start < high:
                row["action_count"] += 1
                row["atom_events"] += len(event.atoms)
            if interval is not None:
                row["overlapping_actions"] += 1
                row["atom_us"] += len(event.atoms) * (interval[1] - interval[0])
                if resource is not None:
                    resource_intervals[resource].append(interval)
            relevant = interval is not None or (
                event.duration_us == 0 and low <= start < high
            )
            if event.kind == "Move" and relevant:
                if start < low or finish > high:
                    partial_moves += 1
                else:
                    move_distance += sum(
                        hypot(b[0] - a[0], b[1] - a[1])
                        for a, b in zip(event.starts, event.ends, strict=True)
                    )
                    points.extend(event.starts)
                    points.extend(event.ends)
    atom_count = len(world.state.atoms)
    gap = _clip(previous_end, duration, low, high)
    if gap is not None:
        outside += gap[1] - gap[0]
        idle["slm"] += atom_count * (gap[1] - gap[0])
        points.extend(
            (atom.position.x, atom.position.y) for atom in current_world.state.atoms
        )
    outputs = [
        row
        for row in _outputs(case, world, low, high, history)
        if row["factory_id"] in selected_factories
    ]
    accepted = sum(row["accepted_in_window"] for row in outputs)
    delivered = sum(row["delivered_in_window"] for row in outputs)
    atom_time, idle_time = atom_count * elapsed, sum(idle.values())
    if not isclose(busy + idle_time, atom_time, abs_tol=max(1e-6, atom_time * 1e-10)):
        raise ValueError("PRODUCTION_ATOM_TIME_NOT_CONSERVED")
    bounds = world.placement_plan.occupied_bounds
    area = (bounds.x_max - bounds.x_min) * (bounds.y_max - bounds.y_min)
    ownership = _ownership(case, world, low, high)
    waiting = _waiting(case, low, high)
    raw_calls = [
        c for c in case.get("calls", ()) if c["component_id"] == "raw_t_postselection"
    ]
    raw_ids = {c["invocation_id"].split("/attempt[", 1)[0] for c in raw_calls}
    raw_rejections = sum(
        e["values"].get("accepted") is False and low <= e["released_at_us"] < high
        for e in case.get("events", ())
        if e["occurrence"]["invocation_id"] in raw_ids
    )
    decisions = [
        m
        for line in case["factories"].values()
        for m in line["milestones"]
        if m["kind"] == "batch_decision" and low <= m["at_us"] < high
    ]
    deliverable_times = [
        row["deliverable_at_us"]
        for row in outputs
        if row["deliverable_at_us"] is not None
    ]
    costs = {
        "configured_atom_time_us": atom_time,
        "occupied_bbox_area_time_um2_us": area * elapsed,
        "transport_elapsed_us": interval_union_us(
            i
            for name, intervals in resource_intervals.items()
            if name.startswith("aod:")
            for i in intervals
        ),
        "idle_atom_time_us": idle_time,
    }
    output_costs = {
        **costs,
        "movement_distance_atom_um": None if partial_moves else move_distance,
    }
    return {
        "schema": "nadit.production_metrics/1",
        "case_id": case.get("case_id"),
        "requested_window_us": [low, stop],
        "actual_end_us": high,
        "actual_observation_us": elapsed,
        "requested_window_complete": complete,
        "window_status": "failed"
        if early_failure
        else "complete"
        if complete
        else "incomplete",
        "count_boundary_convention": "start <= event_time < end; interval overlap clipped exactly",
        "run_status": case["status"],
        "failures": failures,
        "retry_exhaustions": [
            f
            for f in failures
            if f.get("code")
            in (
                "input_supply_exhausted",
                "distillation_rejected",
                "expansion_budget_exhausted",
                "production_cycle_budget_exhausted",
            )
        ],
        "startup_deliverable_latency_us": min(deliverable_times)
        if deliverable_times
        else None,
        "outputs": outputs,
        "output_factory_ids": sorted(selected_factories),
        "accepted_outputs": accepted,
        "delivered_outputs": delivered,
        "accepted_outputs_total": len(outputs),
        "terminal_deliveries_total": sum(
            row["delivery_lifecycle_verified"] for row in outputs
        ),
        "handed_off_outputs": sum(row["handed_off_in_window"] for row in outputs),
        "retained_outputs": sum(row["retained_in_window"] for row in outputs),
        "handed_off_outputs_total": sum(
            row["output_disposition"] == "handoff" for row in outputs
        ),
        "retained_outputs_total": sum(
            row["output_disposition"] == "retained" for row in outputs
        ),
        "accepted_outputs_per_second": accepted * 1e6 / elapsed
        if complete and elapsed
        else None,
        "delivered_outputs_per_second": delivered * 1e6 / elapsed
        if complete and elapsed
        else None,
        "raw_attempts": sum(low <= c["start_us"] < high for c in raw_calls),
        "raw_retry_attempts": sum(
            low <= c["start_us"] < high
            and "/attempt[" in c["invocation_id"]
            and "/attempt[0]/" not in c["invocation_id"]
            for c in raw_calls
        ),
        "raw_rejections": raw_rejections,
        "final_rejections": sum(m["accepted"] is False for m in decisions),
        "final_retry_batches": sum(
            m["batch"] > 0 and low <= m["at_us"] < high
            for line in case["factories"].values()
            for m in line["milestones"]
            if m["kind"] == "batch_started"
        ),
        "configured_atoms": atom_count,
        **ownership,
        **costs,
        "busy_atom_time_us": busy,
        "idle_by_holder_atom_us": dict(idle),
        "between_wave_idle_atom_us": atom_count * outside,
        "occupied_footprint_um": [
            bounds.x_min,
            bounds.y_min,
            bounds.x_max,
            bounds.y_max,
        ],
        "occupied_footprint_area_um2": area,
        "area_time_basis": "fixed bounding rectangle of configured home code-block footprints; includes gaps; excludes infinite domains",
        "actual_occupied_bbox_area_time_um2_us": None,
        "actual_area_time_status": "not_integrated_from_native_actions",
        "actual_visited_bounds_um": None if partial_moves else _bounds(points),
        "movement_distance_atom_um": None if partial_moves else move_distance,
        "fully_contained_move_distance_atom_um": move_distance,
        "partial_move_actions": partial_moves,
        "movement_distance_basis": "native Move endpoint displacement; partial trajectories unavailable",
        "exposure_by_action": dict(exposure),
        "resource_busy_union_us": {
            name: interval_union_us(intervals)
            for name, intervals in resource_intervals.items()
        },
        "resource_intervals_us": dict(resource_intervals),
        **waiting,
        "per_accepted_output": {
            name: value / accepted if accepted and value is not None else None
            for name, value in output_costs.items()
        },
        "per_delivered_output": {
            name: value / delivered if delivered and value is not None else None
            for name, value in output_costs.items()
        },
        "exposure_per_accepted_output": {
            kind: {
                name: value / accepted if accepted else None
                for name, value in row.items()
            }
            for kind, row in exposure.items()
        },
        "wave_instances_in_window": waves_in_window,
        "state_transitions_verified": transitions,
        "exit_world_sha256": canonical_hash(current_world.document()),
        "unique_traces_loaded": len(records),
        "all_loaded_traces_validated": all(validations) if validations else None,
        "actual_output_error": None,
        "noise_scope": "operation exposure only; no noise or logical-quality estimate",
        "software_times_seconds": {
            "trace_load": load_seconds,
            "activity_and_trace_checks": activity_seconds,
            "total_metrics": perf_counter() - started,
        },
    }
