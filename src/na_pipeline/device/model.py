"""Local geometry helpers, independent of compiled actions and runtime state."""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from .spec import _finite_number, validate_device


class DeviceModelError(ValueError):
    """Invalid device or model input; never silently substitute a default."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("; ".join(f"{e['code']} {e['path']}: {e['message']}" for e in errors))


def _require_device(device: dict) -> None:
    errors = validate_device(device)
    if errors:
        raise DeviceModelError(errors)


def _point(value: Any, path: str) -> tuple[float, float]:
    if type(value) not in (list, tuple) or len(value) != 2 or not all(_finite_number(v) for v in value):
        raise DeviceModelError([{"code": "INVALID_POSITION", "path": path, "message": "Expected two finite coordinates in um."}])
    return float(value[0]), float(value[1])


def move_duration_us(device: dict, start_um: list, end_um: list) -> float:
    """Minimum duration with independent, simultaneously moving linear axes.

    Return zero for no displacement; that means no move action is needed.
    Pickup/drop and dependencies must be accounted for by the caller.
    """
    _require_device(device)
    start = _point(start_um, "/start_um")
    end = _point(end_um, "/end_um")
    duration = max(abs(a - b) for a, b in zip(start, end)) / device["movement"]["speed_um_per_us"]
    if not math.isfinite(duration):
        raise DeviceModelError([{"code": "NUMERIC_OVERFLOW", "path": "/duration_us", "message": "Motion exceeds finite numeric range."}])
    return duration


def _inside(zone: dict, point: tuple[float, float]) -> bool:
    for axis, coordinate in zip(("x", "y"), point):
        lower, upper = zone[f"{axis}_range_um"]
        if (lower is not None and coordinate < lower) or (upper is not None and coordinate > upper):
            return False
    return True


def position_in_zone(device: dict, zone_id: str, position_um: list) -> bool:
    """Closed boundary convention; null range endpoints are unbounded."""
    _require_device(device)
    if type(zone_id) is not str or zone_id not in device["zones"]:
        raise DeviceModelError([{"code": "UNKNOWN_ZONE", "path": "/zone_id", "message": "Zone is not declared in DeviceSpec."}])
    return _inside(device["zones"][zone_id], _point(position_um, "/position_um"))


def broadcast_pairs(device: dict, positions: dict[str, list]) -> dict:
    """Derive the entire illumination set and all CZ edges from full geometry.

    Input must include every present atom, not just the intended gate targets.
    No matching/degree filter is applied. This is an abstract gate model only.
    """
    _require_device(device)
    if type(positions) is not dict or any(type(key) is not str or not key for key in positions):
        raise DeviceModelError([{"code": "INVALID_ATOMS", "path": "/positions", "message": "Expected atom_id to position mapping."}])
    points = {key: _point(value, f"/positions/{key}") for key, value in positions.items()}
    zone = device["zones"][device["broadcast"]["zone_id"]]
    illuminated = sorted(key for key, point in points.items() if _inside(zone, point))
    distance = device["geometry"]["gate_pair_distance_um"]
    tolerance = device["geometry"]["distance_tolerance_um"]
    pairs = [[a, b] for a, b in combinations(illuminated, 2)
             if abs(math.dist(points[a], points[b]) - distance) <= tolerance]
    return {"illuminated_atoms": illuminated, "pairs": pairs}


def validate_aod_transition(device: dict, group_id: str, before: dict, after: dict, duration_us: float) -> list[dict]:
    """Check *all active* line endpoints for one shared linear motion segment.

    before/after = {"rows": {line_id: y_um}, "columns": {line_id: x_um}}.
    The caller must supply all lines including unoccupied and spectator lines.
    Stable endpoint order implies non-crossing throughout a linear segment.
    Identity, atom binding and occupancy checks belong to the schedule layer.
    """
    errors = validate_device(device)
    if errors:
        return errors

    def error(code: str, path: str, message: str) -> None:
        errors.append({"code": code, "path": path, "message": message})

    if type(group_id) is not str or group_id not in device["aod_groups"]:
        error("UNKNOWN_AOD_GROUP", "/group_id", "AOD group must be declared.")
    if not _finite_number(duration_us) or duration_us <= 0:
        error("INVALID_DURATION", "/duration_us", "A move segment requires positive finite time.")
    for label, snapshot in (("before", before), ("after", after)):
        if type(snapshot) is not dict or set(snapshot) != {"rows", "columns"}:
            error("INVALID_LINES", f"/{label}", "Both rows and columns, and no unknown fields, are required.")
            continue
        for axis, lines in snapshot.items():
            if type(lines) is not dict or any(type(k) is not str or not k or not _finite_number(v) for k, v in lines.items()):
                error("INVALID_LINES", f"/{label}/{axis}", "Expected line ID to finite coordinate mapping.")
    if errors:
        return errors
    speed = device["movement"]["speed_um_per_us"]
    moved = False
    for axis in ("rows", "columns"):
        source, target = before[axis], after[axis]
        if source.keys() != target.keys():
            error("LINE_IDENTITY_CHANGED", f"/after/{axis}", "Cannot create, remove or rename a line during a move.")
            continue
        ordered = sorted(source, key=source.get)
        if len(set(source.values())) != len(source) or len(set(target.values())) != len(target):
            error("LINE_COLLISION", f"/after/{axis}", "Active lines must have distinct coordinates at both endpoints.")
        if any(target[a] >= target[b] for a, b in zip(ordered, ordered[1:])):
            error("LINE_CROSSING", f"/after/{axis}", "Line order reverses or collapses in the linear segment.")
        for line_id in ordered:
            displacement = abs(target[line_id] - source[line_id])
            moved = moved or displacement > 0
            required = displacement / speed
            if not math.isfinite(required) or duration_us < required:
                error("SPEED_EXCEEDED", f"/after/{axis}/{line_id}", "Line displacement exceeds axis speed times duration.")
    if not moved:
        error("NO_MOTION", "/after", "No line moves; use an explicit wait rather than a move action.")
    return errors
