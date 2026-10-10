"""Pure geometric checks for the declared linear, point-atom model.

This is compiler validation, not the independent R6 acceptance validator.
"""
from __future__ import annotations

import math
from collections import Counter

EPS = 1e-8


def in_zone(position: list[float], zone: dict) -> bool:
    """Bounds are [[xmin,xmax],[ymin,ymax]]; None means unbounded."""
    return all((lo is None or p >= lo - EPS) and
               (hi is None or p <= hi + EPS)
               for p, (lo, hi) in zip(position, zone["bounds_um"]))


def broadcast_pairs(atoms: list[dict], zone: dict, distance: float,
                    tolerance: float = EPS) -> list[list[str]]:
    visible = [a for a in atoms if in_zone(a["position_um"], zone)]
    pairs = []
    for i, a in enumerate(visible):
        for b in visible[i + 1:]:
            if abs(math.dist(a["position_um"], b["position_um"]) - distance) <= tolerance:
                pairs.append(sorted([a["atom_id"], b["atom_id"]]))
    return sorted(pairs)


def validate_cz_pairs(pairs: list[list[str]]) -> list[dict]:
    """Keep every geometric edge; reject the currently unqualified many-body domain."""
    degrees = Counter(atom for pair in pairs for atom in pair)
    return [{"code": "UNSUPPORTED_MULTIBODY_BROADCAST", "atom_id": atom, "degree": degree}
            for atom, degree in sorted(degrees.items()) if degree > 1]


def _collision(a0, a1, b0, b1):
    d = [a0[i] - b0[i] for i in range(2)]
    v = [a1[i] - a0[i] - b1[i] + b0[i] for i in range(2)]
    vv = sum(x*x for x in v)
    s = max(0., min(1., -sum(d[i]*v[i] for i in range(2))/vv)) if vv else 0.
    return sum((d[i] + s*v[i])**2 for i in range(2)) < EPS**2


def validate_motion(atoms: list[dict], trajectories: list[dict],
                    aod_group: str) -> list[dict]:
    """Check entire linear sweep, shared-axis consistency, and noncrossing.

    AOD axes exist while occupied. An omitted resident is stationary; moving a
    shared axis without listing that resident is therefore rejected. For linear
    interpolation, preserving each strict axis order at both endpoints proves
    it at every intervening time. Atom coincidences use analytic closest time.
    """
    errors = []
    by_id = {a["atom_id"]: a for a in atoms}
    ends = {k: list(v["position_um"]) for k, v in by_id.items()}
    seen = set()
    for tr in trajectories:
        aid = tr["atom_id"]
        if aid not in by_id or aid in seen:
            errors.append({"code": "TRAJECTORY_ID", "atom_id": aid})
            continue
        seen.add(aid)
        a = by_id[aid]
        points = tr.get("from_um", []) + tr.get("to_um", [])
        if len(points) != 4 or any(not isinstance(p, (int, float)) or not math.isfinite(p) for p in points):
            errors.append({"code": "TRAJECTORY_COORDINATES", "atom_id": aid})
            continue
        if a["carrier"] != "AOD" or a["aod_group"] != aod_group:
            errors.append({"code": "CARRIER_BINDING", "atom_id": aid})
        if math.dist(a["position_um"], tr["from_um"]) > EPS:
            errors.append({"code": "TELEPORT", "atom_id": aid})
        for axis in ("row_id", "column_id"):
            if tr.get(axis) != a.get(axis):
                errors.append({"code": "AXIS_BINDING", "atom_id": aid, "axis": axis})
        ends[aid] = list(tr["to_um"])
    residents = [a for a in atoms if a["carrier"] == "AOD" and a["aod_group"] == aod_group]
    for axis, coordinate in (("column_id", 0), ("row_id", 1)):
        axes = {}
        for a in residents:
            k = a.get(axis)
            pair = (a["position_um"][coordinate], ends[a["atom_id"]][coordinate])
            if k is None:
                errors.append({"code": "MISSING_AXIS", "atom_id": a["atom_id"]})
            elif k in axes and any(abs(x-y) > EPS for x, y in zip(axes[k], pair)):
                errors.append({"code": "SHARED_AXIS", "axis": axis, "axis_id": k})
            else:
                axes[k] = pair
        ordered = sorted(axes.items(), key=lambda item: item[1][0])
        for (ka, pa), (kb, pb) in zip(ordered, ordered[1:]):
            if pb[0] - pa[0] <= EPS or pb[1] - pa[1] <= EPS:
                errors.append({"code": "AXIS_CROSSING", "axis": axis, "ids": [ka, kb]})
    for i, a in enumerate(atoms):
        for b in atoms[i + 1:]:
            if a["atom_id"] not in seen and b["atom_id"] not in seen:
                continue
            if _collision(a["position_um"], ends[a["atom_id"]],
                          b["position_um"], ends[b["atom_id"]]):
                errors.append({"code": "ATOM_COLLISION", "atoms": [a["atom_id"], b["atom_id"]]})
    return errors


def route_waypoints(start: list[float], end: list[float],
                    stationary: list[list[float]], pitch: float) -> list[list[float]]:
    """Finite deterministic waypoint search in the unbounded point model."""
    def clear(p, q):
        return all(not _collision(p, q, r, r) for r in stationary)
    if clear(start, end):
        return [list(end)]
    for fraction in (.5, -.5, 1.5, -1.5, 2.5, -2.5):
        via = [start[0] + pitch*fraction, start[1] + pitch*(fraction + .25)]
        if clear(start, via) and clear(via, end):
            return [via, list(end)]
    raise ValueError("ROUTE_SEARCH_EXHAUSTED: seven candidates tried; not an infeasibility proof")
