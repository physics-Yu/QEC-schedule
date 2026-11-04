"""Re-time a fixed, measurement-feedback-free Atom IR schedule and its additive cost."""

import json
from collections import Counter
from collections.abc import Mapping
from math import hypot, isclose, log1p
from typing import Any

from ..activity import derive_activity
from ..atom_ir import (
    AtomProgram,
    CZPulse,
    GlobalRY,
    Load,
    LocalU,
    Measure,
    Move,
    Reset,
    Rotation,
    Store,
)
from ..cost import evaluate as evaluate_cost
from ..cost.additive import resolved_params
from ..cost.base import require_validated, result_hash
from ..device import Device, Timing, loads_device
from ..provenance import canonical_hash
from ..replay import apply_step
from ..serialization import decode_layout, decode_program
from ..state import AtomLayout, SLMHolder
from ..validation_durations import TOLERANCE_US

SCHEMA = "nadit.retiming/1"
KINDS: dict[type, str] = {
    Load: "load",
    Store: "store",
    Move: "move",
    CZPulse: "cz",
    Rotation: "rotation",
    LocalU: "rotation",
    GlobalRY: "global_ry",
    Reset: "reset",
    Measure: "measure",
}
TERMS = ("cz", "single", "readout", "reset", "transfer", "idle", "heating")
DURATION_TOLERANCE_US = 1e-6
TERM_TOLERANCE = 1e-9


class UnsupportedSchedule(ValueError):
    """The schedule falls outside the v1 re-timing model."""


def reference_timing(device: Device) -> dict[str, Any]:
    """Return the Device durations as re-timing parameters."""
    timing = device.timing
    return {
        "move_profile": timing.move_profile,
        "move_us_per_um": timing.move_us_per_um,
        "load_us": timing.load_us,
        "store_us": timing.store_us,
        "cz_us": device.cz.duration_us if device.cz else None,
        "rotation_us": device.local.rotation_us if device.local else None,
        "reset_us": device.local.reset_us if device.local else None,
        "global_ry_us": (
            device.global_control.rotation_us if device.global_control else None
        ),
        "measure_us": device.readout.duration_us if device.readout else None,
        "latency_us": device.readout.latency_us if device.readout else 0.0,
    }


def duration(kind: str, move_um: float | None, timing: Mapping[str, Any]) -> float:
    """Device duration of one action kind under the given timing parameters."""
    if kind == "move":
        assert move_um is not None
        return Timing(
            timing["load_us"],
            timing["store_us"],
            timing["move_us_per_um"],
            timing["move_profile"],
        ).move_duration(move_um)
    value = timing[f"{kind}_us"]
    if value is None:
        raise ValueError(f"Timing has no duration for {kind!r}.")
    return float(value)


def _check_supported(program: AtomProgram, timing: Mapping[str, Any]) -> None:
    for index, step in enumerate(program.steps):
        if sum(isinstance(action, Move) for action in step.actions) > 1:
            raise UnsupportedSchedule(f"step {index}: several Move actions.")
        for action in step.actions:
            kind = KINDS.get(type(action))
            if kind is None:
                raise UnsupportedSchedule(
                    f"step {index}: unsupported {type(action).__name__}."
                )
            if isinstance(action, Measure) and not action.retain_atoms:
                raise UnsupportedSchedule(f"step {index}: atoms are removed.")
            if not isinstance(action, Move) and not isclose(
                action.duration_us,
                duration(kind, None, timing),
                rel_tol=0,
                abs_tol=TOLERANCE_US,
            ):
                raise UnsupportedSchedule(
                    f"step {index}: {kind} duration differs from device timing."
                )


def _holder(layout: AtomLayout) -> dict[int, str]:
    return {
        atom.id: "slm" if isinstance(atom.holder, SLMHolder) else "aod"
        for atom in layout.atoms
    }


def _footprint(document: Mapping[str, Any], device: Device) -> dict[str, Any]:
    program = decode_program(document["program"])
    layout = decode_layout(document["entry_state"])
    points = [(a.position.x, a.position.y) for a in layout.atoms]
    sites = {a.holder.site_id for a in layout.atoms if isinstance(a.holder, SLMHolder)}
    for step in program.steps:
        layout = apply_step(layout, step, device)
        points.extend((a.position.x, a.position.y) for a in layout.atoms)
        sites |= {
            a.holder.site_id for a in layout.atoms if isinstance(a.holder, SLMHolder)
        }

    def box(values: list[tuple[float, float]]) -> float:
        xs, ys = [p[0] for p in values], [p[1] for p in values]
        return (max(xs) - min(xs)) * (max(ys) - min(ys)) if values else 0.0

    declared = [(s.position.x, s.position.y) for s in device.slm_sites]
    for zone in device.zones:
        declared += [
            (zone.bounds.x_min, zone.bounds.y_min),
            (zone.bounds.x_max, zone.bounds.y_max),
        ]
    return {
        "bbox_um2": box(points),
        "slm_sites_used": len(sites),
        "device_um2": box(declared),
    }


def export(document: Mapping[str, Any]) -> dict[str, Any]:
    """Build a `nadit.retiming/1` document from a validated v2 result.

    Raises:
        UnsupportedSchedule: For feedback, unsupported actions, destructive
            readout, heterogeneous fixed durations or several Moves in one step.
    """
    require_validated(document)
    if any(node.get("condition") is not None for node in document["dag"]["nodes"]):
        raise UnsupportedSchedule(
            "Measurement feedback is outside the fixed-schedule model."
        )
    device = loads_device(json.dumps(document["device"]))
    program = decode_program(document["program"])
    timing = reference_timing(device)
    _check_supported(program, timing)
    layout = decode_layout(document["entry_state"])
    activity = derive_activity(document)
    events: dict[int, list[Any]] = {}
    for event in activity.events:
        events.setdefault(event.step_index, []).append(event)
    atom_ids = tuple(atom.id for atom in layout.atoms)
    keys: list[str] = []
    signatures: dict[str, dict[str, Any]] = {}
    for index, step in enumerate(program.steps):
        after = apply_step(layout, step, device)
        own: dict[int, set[str]] = {}
        moves = [a for a in step.actions if isinstance(a, Move)]
        move_um = None
        sum_d = sum_d2 = 0.0
        for event, action in zip(events.get(index, ()), step.actions, strict=True):
            kind = KINDS[type(action)]
            if isinstance(action, Move):
                distances = [
                    hypot(e[0] - s[0], e[1] - s[1])
                    for s, e in zip(event.starts, event.ends, strict=True)
                ]
                move_um = max(distances, default=0.0)
                sum_d = sum(distances)
                sum_d2 = sum(d * d for d in distances)
            for atom in event.atoms:
                own.setdefault(atom, set()).add(kind)
        holders = _holder(after)
        idle = Counter(holders[a] for a in atom_ids if a not in own)
        tail = Counter((tuple(sorted(own[a])), holders[a]) for a in own)
        signature = {
            "kinds": sorted({KINDS[type(a)] for a in step.actions}),
            "move_um": move_um,
            "idle": {h: idle.get(h, 0) for h in ("slm", "aod")},
            "tail": [[list(k), h, n] for (k, h), n in sorted(tail.items())],
            "moves": {"sum_d_um": sum_d, "sum_d2_um2": sum_d2} if moves else None,
        }
        key = canonical_hash(signature)
        signatures.setdefault(key, {"n": 0, **signature})["n"] += 1
        keys.append(key)
        layout = after
    order = list(signatures)
    measuring = [
        i
        for i, step in enumerate(program.steps)
        if any(isinstance(a, Measure) for a in step.actions)
    ]
    last_measure = None
    if measuring:
        after_last = Counter(order.index(k) for k in keys[measuring[-1] + 1 :])
        last_measure = {
            "signature": order.index(keys[measuring[-1]]),
            "after": [[s, n] for s, n in sorted(after_last.items())],
        }
    counts = {
        "cz": sum(len(e.pairs) for e in activity.events if e.kind == "CZPulse"),
        "single": sum(a.rotation_count for a in activity.per_atom),
        "readout": sum(a.measure_count for a in activity.per_atom),
        "reset": sum(a.reset_count for a in activity.per_atom),
        "transfer": sum(a.transfers for a in activity.per_atom),
    }
    final = Counter(_holder(layout).values())
    provenance = document.get("provenance", {})
    return {
        "schema": SCHEMA,
        "result_hash": result_hash(document),
        "compiler": provenance.get("compiler"),
        "reference": {
            "timing": timing,
            "duration_us": program.duration_us,
            "available_us": activity.duration_us,
        },
        "footprint": _footprint(document, device),
        "counts": counts,
        "final_holders": {h: final.get(h, 0) for h in ("slm", "aod")},
        "signatures": [signatures[k] for k in order],
        "last_measure": last_measure,
    }


def evaluate(
    retiming: Mapping[str, Any],
    timing: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute duration and additive log-fidelity terms for new parameters.

    Timing keys default to the reference; error keys follow cost/additive.py.
    """
    theta = {**retiming["reference"]["timing"], **(timing or {})}
    p = resolved_params(error or {})
    steps = retiming["signatures"]
    lengths = [
        max(duration(k, s["move_um"], theta) for k in s["kinds"]) if s["kinds"] else 0
        for s in steps
    ]
    program_us = sum(s["n"] * d for s, d in zip(steps, lengths, strict=True))
    available_us = program_us
    measure = retiming["last_measure"]
    if measure is not None:
        after = sum(n * lengths[s] for s, n in measure["after"])
        end = program_us - after - lengths[measure["signature"]]
        end += duration("measure", None, theta)
        available_us = max(program_us, end + theta["latency_us"])
    idle = {"slm": 0.0, "aod": 0.0}
    heating = 0.0
    for s, length in zip(steps, lengths, strict=True):
        for holder, count in s["idle"].items():
            idle[holder] += s["n"] * count * length
        for kinds, holder, count in s["tail"]:
            busy = max(duration(k, s["move_um"], theta) for k in kinds)
            idle[holder] += s["n"] * count * (length - busy)
        if s["moves"] is not None:
            heating += s["n"] * p["heating_per_um"] * s["moves"]["sum_d_um"]
            if p["heating_us_per_um2"] and s["moves"]["sum_d2_um2"]:
                heating += (
                    s["n"]
                    * p["heating_us_per_um2"]
                    * s["moves"]["sum_d2_um2"]
                    / duration("move", s["move_um"], theta)
                )
    for holder, count in retiming["final_holders"].items():
        idle[holder] += count * (available_us - program_us)
    counts = retiming["counts"]
    terms = {
        key: counts[key]
        * log1p(-p["transfer_loss" if key == "transfer" else key + "_infidelity"])
        for key in ("cz", "single", "readout", "reset", "transfer")
    }
    terms["idle"] = -sum(
        idle[h] / p[f"{h}_t2_us"] for h in idle if p[f"{h}_t2_us"] is not None
    )
    terms["heating"] = -heating
    return {
        "program_us": program_us,
        "available_us": available_us,
        "idle_us": idle,
        "terms": terms,
        "log_fidelity": sum(terms.values()),
    }


def accept(
    document: Mapping[str, Any],
    retiming: Mapping[str, Any],
    error: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare reference re-timing against recorded duration and cost.evaluate."""
    mine = evaluate(retiming, error=error)
    report = evaluate_cost(document, model="additive", params=dict(error))
    expected = report["metrics"]["contributions"]
    duration_ok = isclose(
        mine["program_us"],
        retiming["reference"]["duration_us"],
        rel_tol=0,
        abs_tol=DURATION_TOLERANCE_US,
    ) and isclose(
        mine["available_us"],
        retiming["reference"]["available_us"],
        rel_tol=0,
        abs_tol=DURATION_TOLERANCE_US,
    )
    mismatched = {
        key: {"retimed": mine["terms"][key], "cost": expected[key]}
        for key in TERMS
        if not isclose(
            mine["terms"][key], expected[key], rel_tol=TERM_TOLERANCE, abs_tol=1e-15
        )
    }
    return {
        "retiming_exact": duration_ok and not mismatched,
        "duration_us": {
            "retimed": mine["program_us"],
            "recorded": retiming["reference"]["duration_us"],
        },
        "term_mismatches": mismatched,
    }
