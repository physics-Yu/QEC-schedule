"""Independent finite-profile, scheduled, multi-AOD pure transport review.

This is deliberately separate from the frozen single-AOD reviewer.  Every
binary float is lifted exactly to a rational.  Cubic relative trajectories are
certified by subdividing their Bezier convex hull, never by time sampling.
An unresolved near-contact is rejected.  LOAD activates the future Cartesian
union conservatively during handoff; STORE retains its old union to END.
These are audit envelopes, not extra transient holder states in the kernel.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from fractions import Fraction as F
import hashlib
import heapq
import json
import math
from pathlib import Path


CONTRACT = "occupied-row-column-union/full-cartesian/v1"
KINDS = {"CONFIGURE", "LOAD", "MOVE", "STORE", "WAIT"}


class ReviewError(ValueError):
    def __init__(self, code, reason, operation_id=None):
        super().__init__(reason)
        self.code, self.operation_id = code, operation_id


def _require(condition, code, reason, operation_id=None):
    if not condition:
        raise ReviewError(code, reason, operation_id)


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def review_input_sha256(initial_positions, operations, profile, *, initial_axes, initial_holders=None):
    """Canonical complete public input receipt shared with the transport adapter."""
    holders = {q: "slm" for q in initial_positions}
    holders.update(initial_holders or {})
    return _digest({"initial_positions": _plain(initial_positions),
                    "initial_holders": _plain(holders),
                    "initial_axes": _plain(initial_axes), "profile": _plain(profile),
                    "operations": [_plain(operation) for operation in operations]})


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value), "FINITE_NUMBER", "Coordinates and times must be finite numbers")
    return float(value)


def _point(value):
    _require(isinstance(value, (tuple, list)) and len(value) == 2, "POSITION_IDENTITY", "A position has exactly two coordinates")
    return tuple(map(_number, value))


def _axes(value):
    _require(isinstance(value, Mapping) and set(value) <= {"rows", "columns", "active_rows", "active_columns"}
             and {"rows", "columns"} <= set(value), "AXIS_IDENTITY", "Axes require known full row/column fields")
    return tuple(tuple(_number(x) for x in value[key]) for key in ("rows", "columns"))


def _axis_payload(axes, positions, holders, device):
    return {"rows": list(axes[0]), "columns": list(axes[1]),
            "active_rows": sorted({positions[q][1] for q in positions if holders[q] == device}),
            "active_columns": sorted({positions[q][0] for q in positions if holders[q] == device})}


def _profile(profile):
    p = _plain(profile)
    _require(p.get("active_axes_contract") == CONTRACT, "ACTIVE_AXES_CONTRACT", "Only occupied-union/full-Cartesian masks are qualified")
    _require(not any(p.get(key) for key in ("extra_active_empty_axes", "extra_empty_active_axes_supported")), "ACTIVE_AXES_CONTRACT", "Persistent independently active empty RF axes are unsupported")
    _require(type(p.get("profile_id")) is str and bool(p["profile_id"]), "PROFILE_IDENTITY", "Profile needs an explicit id")
    _require(isinstance(p.get("devices"), dict) and len(p["devices"]) == 2 and "slm" not in p["devices"], "DEVICE_IDENTITY", "This qualification requires two explicit AODs")
    p["bounds_um"] = tuple(map(_number, p["bounds_um"]))
    _require(len(p["bounds_um"]) == 4 and p["bounds_um"][0] < p["bounds_um"][2] and p["bounds_um"][1] < p["bounds_um"][3], "WORLD_BOUNDS", "World is a finite ordered rectangle")
    fixed = {"slm_grid_um": 5, "aod_axis_spacing_um": 2, "transport_clearance_um": 1,
             "load_duration_us": 15, "store_duration_us": 15, "move_scale_us": 200, "move_reference_um": 110}
    for key, expected in fixed.items():
        _require(_number(p.get(key)) == expected, "PROFILE_THRESHOLD", f"{key} must retain the declared native value {expected}")
    p["slm_origin_um"] = _point(p.get("slm_origin_um", [0, 0]))
    sites = [_point(point) for point in p["declared_slm_sites_um"]]
    _require(len(sites) == len(set(sites)), "SLM_IDENTITY", "Declared SLM sites must be unique")
    p["sites"] = set(sites)
    for point in sites:
        _require(_inside(point, p["bounds_um"]), "WORLD_BOUNDS", "Declared SLM site is outside the world")
        _require(all((F(x)-F(origin))/5 == int((F(x)-F(origin))/5) for x, origin in zip(point, p["slm_origin_um"])), "SLM_GRID", "Declared SLM site is off the explicit 5 um grid")
    for device, limits in p["devices"].items():
        _require(type(device) is str and bool(device), "DEVICE_IDENTITY", "AOD ids must be exact nonempty strings")
        for key in ("rows", "columns", "capacity"):
            _require(type(limits.get(key)) is int and 1 <= limits[key] <= 128, "RF_CAPACITY", "Finite device axis/cell capacities are required")
        _require(limits["rows"] * limits["columns"] == limits["capacity"], "RF_CAPACITY", "Capacity must include the full declared Cartesian product")
        limits["envelope_um"] = tuple(map(_number, limits["envelope_um"]))
        b, e = p["bounds_um"], limits["envelope_um"]
        _require(len(e) == 4 and b[0] <= e[0] < e[2] <= b[2] and b[1] <= e[1] < e[3] <= b[3], "DEVICE_ENVELOPE", "Device envelope must be finite and within world")
    return p


def _inside(point, bounds):
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def _check_axes(axes, p, device):
    limits = p["devices"][device]
    _require(tuple(map(len, axes)) == (limits["rows"], limits["columns"]), "RF_DIMENSIONS", "Full RF dimensions include disabled spare axes")
    for values in axes:
        _require(all(b-a >= 2 for a, b in zip(values, values[1:])), "RF_SPACING", "Ordered full RF axes require at least 2 um separation")
    envelope = limits["envelope_um"]
    _require(all(envelope[1] <= y <= envelope[3] for y in axes[0]) and all(envelope[0] <= x <= envelope[2] for x in axes[1]), "RF_ENVELOPE", "Full RF axes, including spares, must remain inside device envelope")


def _operations(values):
    result = []
    for value in values:
        o = _plain(value)
        _require(isinstance(o, dict), "OPERATION_SCHEMA", "Operations must be public payloads")
        for key, default in {"atoms": [], "positions": [], "gate_ids": [], "report_ids": [], "metadata": {}, "depends_on": [], "resources": [], "motion_profile": "row_column", "aod_id": "AOD_0"}.items():
            o.setdefault(key, default)
        _require(type(o.get("id")) is str and bool(o["id"]), "OPERATION_IDENTITY", "Operation ids must be exact nonempty strings")
        _require(o.get("kind") in KINDS, "PURE_TRANSPORT_SCOPE", "Only CONFIGURE/LOAD/MOVE/STORE/WAIT are qualified", o["id"])
        _require(not o["gate_ids"] and not o["report_ids"], "PURE_TRANSPORT_SCOPE", "Transport cannot declare gate or report effects", o["id"])
        for key in ("atoms", "depends_on", "resources"):
            _require(all(type(x) is str and x for x in o[key]) and len(o[key]) == len(set(o[key])), "OPERATION_IDENTITY", f"{key} must be unique exact string identities", o["id"])
        o["start_us"] = _number(o.get("start_us"))
        o["duration_us"] = _number(o.get("duration_us"))
        _require(o["start_us"] >= 0 and o["duration_us"] >= 0, "TIME_IDENTITY", "Scheduled time and duration must be nonnegative", o["id"])
        o["end_us"] = _number(o.get("end_us") if o.get("end_us") is not None else o["start_us"]+o["duration_us"])
        tol = 4 * sum(math.ulp(x) for x in (o["start_us"], o["end_us"], o["duration_us"]))
        _require(o["end_us"] >= o["start_us"] and abs((o["end_us"]-o["start_us"])-o["duration_us"]) <= tol
                 and (o["duration_us"] != 0 or o["end_us"] == o["start_us"]), "TIME_IDENTITY", "Authored start/end/duration disagree", o["id"])
        _require(o["motion_profile"] in ("row_column", "rigid"), "MOTION_PROFILE", "Only declared cubic or rigid-linear motion is qualified", o["id"])
        o["positions"] = [[q, list(_point(point))] for q, point in o["positions"]]
        _require(len(o["positions"]) == len({x[0] for x in o["positions"]}), "POSITION_IDENTITY", "Position bindings cannot repeat an atom", o["id"])
        _require(isinstance(o["metadata"], dict), "OPERATION_SCHEMA", "Metadata must be an object", o["id"])
        _require(not ({"gate_spec", "gate_specs", "effects", "enabled_rows", "enabled_columns", "enabled_cols", "extra_active_rows", "extra_active_columns"} & o["metadata"].keys()), "PURE_TRANSPORT_SCOPE", "Unsupported effects or independently enabled RF masks cannot be declared", o["id"])
        _require(not any(o["metadata"].get(key) for key in ("requires_report_ids", "gate_kind", "extra_active_rows", "extra_active_columns")), "PURE_TRANSPORT_SCOPE", "Unsupported effects or persistent empty active axes are not qualified", o["id"])
        result.append(o)
    _require(len(result) == len({o["id"] for o in result}), "OPERATION_IDENTITY", "Operation identities must be globally unique")
    _require(bool(result), "OPERATION_IDENTITY", "Qualification needs a nonempty actual operation stream")
    return result


def _controls(a, b, start, end, lo, hi, cubic=True):
    a, b, start, end, lo, hi = map(F, (a, b, start, end, lo, hi))
    if a == b or end == start:
        return (a,)*4
    def value(t):
        u = (t-start)/(end-start)
        return a+(b-a)*(3*u*u-2*u*u*u if cubic else u)
    def derivative(t):
        u = (t-start)/(end-start)
        return (b-a)/(end-start)*(6*u-6*u*u if cubic else 1)
    return value(lo), value(lo)+(hi-lo)*derivative(lo)/3, value(hi)-(hi-lo)*derivative(hi)/3, value(hi)


def _split(values):
    a, b, c, d = values
    ab, bc, cd = (a+b)/2, (b+c)/2, (c+d)/2
    abc, bcd = (ab+bc)/2, (bc+cd)/2
    middle = (abc+bcd)/2
    return (a, ab, abc, middle), (middle, bcd, cd, d)


def _certify_relative(x, y, stats, *, max_depth=24, max_nodes=8192):
    """Return a conservative exact lower bound on squared separation."""
    stack, minimum, nodes = [(x, y, 0)], None, 0
    while stack:
        x, y, depth = stack.pop()
        nodes += 1
        _require(nodes <= max_nodes, "UNCERTIFIED_CONTINUOUS_CLEARANCE", "Continuous clearance certificate exceeded its finite node budget")
        nearest = lambda v: min(v) if min(v) > 0 else -max(v) if max(v) < 0 else F(0)
        lower = nearest(x)**2+nearest(y)**2
        if lower >= 1:
            minimum = lower if minimum is None else min(minimum, lower)
            continue
        xm = (x[0]+3*x[1]+3*x[2]+x[3])/8
        ym = (y[0]+3*y[1]+3*y[2]+y[3])/8
        _require(all(xx*xx+yy*yy >= 1 for xx, yy in ((x[0], y[0]), (x[3], y[3]), (xm, ym))), "CONTINUOUS_COLLISION", "A continuous trajectory has separation below 1 um")
        _require(depth < max_depth, "UNCERTIFIED_CONTINUOUS_CLEARANCE", "Near-contact could not be certified without weakening clearance")
        xl, xr = _split(x); yl, yr = _split(y)
        stack.extend(((xr, yr, depth+1), (xl, yl, depth+1)))
    stats["certificate_nodes"] += nodes
    stats["pair_partition_checks"] += 1
    bound = float(minimum)
    stats["minimum_certified_lower_bound_um"] = min(stats["minimum_certified_lower_bound_um"], math.sqrt(bound))
    return minimum


def _geometry(positions, holders, axes, running, lo, hi, stats):
    motions = {c["o"]["aod_id"]: c for c in running.values() if c["o"]["kind"] in ("MOVE", "CONFIGURE")}
    def coordinate(device, dimension, index):
        c = motions.get(device)
        if c is None:
            return (F(axes[device][dimension][index]),)*4
        o = c["o"]
        return _controls(c["source_axes"][dimension][index], c["target_axes"][dimension][index], o["start_us"], o["end_us"], lo, hi, o["motion_profile"] == "row_column")
    curves = {}
    for q, point in positions.items():
        device = holders[q]
        if device in motions and motions[device]["o"]["kind"] == "MOVE":
            row, col = axes[device][0].index(point[1]), axes[device][1].index(point[0])
            curves[q] = coordinate(device, 1, col), coordinate(device, 0, row)
        else:
            curves[q] = (F(point[0]),)*4, (F(point[1]),)*4
    def check(a, b, category):
        stats[category] += 1
        _certify_relative(tuple(x-y for x, y in zip(a[0], b[0])), tuple(x-y for x, y in zip(a[1], b[1])), stats)
    ids = list(curves)
    for i, q in enumerate(ids):
        for r in ids[i+1:]:
            check(curves[q], curves[r], "atom_pair_checks")
    for device in axes:
        supported = {q for q in holders if holders[q] == device}
        for c in running.values():
            if c["o"]["aod_id"] == device and c["o"]["kind"] == "LOAD":
                supported.update(c["o"]["atoms"])
        rows = {axes[device][0].index(positions[q][1]) for q in supported}
        cols = {axes[device][1].index(positions[q][0]) for q in supported}
        for row in rows:
            for col in cols:
                point = coordinate(device, 1, col), coordinate(device, 0, row)
                for q in ids:
                    if q not in supported:
                        check(point, curves[q], "cartesian_spectator_checks")
    stats["timeline_partitions"] += 1


def _context(o, positions, holders, axes, profile):
    id, kind, device = o["id"], o["kind"], o["aod_id"]
    _require(set(o["atoms"]) <= positions.keys(), "ATOM_IDENTITY", "Unknown atom identity", id)
    if kind == "WAIT":
        wait_keys = {"label", "protocol_stage", "transport_batch", "origin", "schedule_binding", "profile_id",
                     "active_axes_contract", "module_aod_id", "gate_or_service_qualification"}
        _require(not o["positions"] and set(o["metadata"]) <= wait_keys, "PURE_TRANSPORT_SCOPE", "WAIT only reserves named atoms/resources and carries known descriptive metadata", id)
        # The default device has no resource/physical significance for WAIT.
        source = axes.get(device, ((), ()))
    else:
        _require(device in axes, "DEVICE_IDENTITY", "Transport names an undeclared AOD", id)
        source = axes[device]
    target = _axes(o["metadata"]["target_axes"]) if "target_axes" in o["metadata"] else source
    _require("target_axes" not in o["metadata"] or not ({"active_rows", "active_columns"} & o["metadata"]["target_axes"].keys()), "ACTIVE_AXES_CONTRACT", "Target axes cannot claim independent persistent active masks", id)
    if "source_axes" in o["metadata"]:
        claimed = o["metadata"]["source_axes"]
        _require(_axes(claimed) == source, "SOURCE_AXES", "Declared source RF differs from committed axes", id)
        current = _axis_payload(source, positions, holders, device)
        for key in ("active_rows", "active_columns"):
            _require(key not in claimed or list(claimed[key]) == current[key], "ACTIVE_AXES_CONTRACT", "Active masks must equal the occupied union", id)
    for key, expected in (("source_positions", {q: list(positions[q]) for q in o["atoms"]}), ("source_holders", {q: holders[q] for q in o["atoms"]})):
        if key in o["metadata"]:
            _require(o["metadata"][key] == expected, "SOURCE_IDENTITY", f"{key} does not match actual source", id)
    loaded = {q for q in holders if holders[q] == device}
    for key, expected in (("profile_id", profile["profile_id"]), ("active_axes_contract", CONTRACT),
                          ("gate_or_service_qualification", False), ("rf_axis_scope", "full-capacity-with-explicit-disabled-spares"),
                          ("motion_progress", "3s**2-2s**3")):
        _require(key not in o["metadata"] or (o["metadata"][key] == expected and (key != "gate_or_service_qualification" or o["metadata"][key] is False)), "METADATA_CONTRACT", f"Unsupported {key} claim", id)
    if kind != "WAIT":
        _check_axes(target, profile, device)
        _require(tuple(map(len, target)) == tuple(map(len, source)), "RF_DIMENSIONS", "Motion must preserve all RF dimensions", id)
    if kind == "CONFIGURE":
        _require(not loaded and not o["atoms"] and not o["positions"] and "target_axes" in o["metadata"], "CARRIER_STATE", "CONFIGURE requires an empty declared AOD", id)
    elif kind in ("LOAD", "MOVE", "STORE"):
        _require(bool(o["atoms"]), "ATOM_IDENTITY", "Transport requires explicit atoms", id)
        expected_holder = "slm" if kind == "LOAD" else device
        _require(all(holders[q] == expected_holder for q in o["atoms"]), "CARRIER_STATE", "Transport source holder mismatch", id)
        _require(not o["positions"] or {q for q, _ in o["positions"]} == set(o["atoms"]), "POSITION_IDENTITY", "Explicit targets must bind every operation atom exactly", id)
        _require(all(positions[q][1] in source[0] and positions[q][0] in source[1] for q in loaded | set(o["atoms"])), "RF_SUPPORT", "Every transfer/carrier must be supported by declared full RF axes", id)
        if kind == "MOVE":
            _require(set(o["atoms"]) == loaded and bool(o["positions"]) and "target_axes" in o["metadata"], "POSITION_IDENTITY", "MOVE must account for every carrier and all full target axes", id)
            targets = dict(o["positions"])
            for q in loaded:
                row, col = source[0].index(positions[q][1]), source[1].index(positions[q][0])
                _require(tuple(targets[q]) == (target[1][col], target[0][row]), "POSITION_IDENTITY", "Declared atom target differs from full RF cell trajectory", id)
        else:
            _require(target == source and all(tuple(point) == positions[q] for q, point in o["positions"]), "POSITION_IDENTITY", "LOAD/STORE cannot move or reconfigure RF", id)
            if kind == "STORE":
                _require(all(positions[q] in profile["sites"] for q in o["atoms"]), "SLM_IDENTITY", "STORE requires an actually declared finite SLM site", id)
    if kind in ("MOVE", "CONFIGURE"):
        displacement = max((abs(b-a) for dim in (0, 1) for a, b in zip(source[dim], target[dim])), default=0)
        expected = 200*math.sqrt(displacement/110)
        _require(abs(o["duration_us"]-expected) <= 4*(math.ulp(expected)+math.ulp(o["duration_us"])), "MOTION_DURATION", "Motion duration must follow the native full-axis hardware law within representation-only ULPs", id)
        if o["motion_profile"] == "rigid":
            _require(all(len({F(b)-F(a) for a, b in zip(s, t)}) <= 1 for s, t in zip(source, target)), "RIGID_DEFORMATION", "Rigid motion cannot deform full RF axes", id)
    elif kind in ("LOAD", "STORE"):
        _require(o["duration_us"] == 15, "TRANSFER_DURATION", "LOAD/STORE require the unchanged 15 us duration", id)
    future_positions, future_holders = dict(positions), dict(holders)
    if kind == "LOAD": future_holders.update({q: device for q in o["atoms"]})
    if kind == "STORE": future_holders.update({q: "slm" for q in o["atoms"]})
    if kind == "MOVE": future_positions.update({q: tuple(point) for q, point in o["positions"]})
    future_mask = _axis_payload(target, future_positions, future_holders, device)
    for key in ("active_rows", "active_columns"):
        _require(key not in o["metadata"] or list(o["metadata"][key]) == future_mask[key], "ACTIVE_AXES_CONTRACT", "Declared END mask differs from actual occupied union", id)
    resources = set(o["resources"]) | {"ATOM:"+q for q in o["atoms"]}
    if kind != "WAIT":
        resources.add(device)
        resources.update("ATOM:"+q for q in loaded)
    return {"o": o, "source_axes": source, "target_axes": target,
            "source_mask": _axis_payload(source, positions, holders, device),
            "resources": sorted(resources),
            "start_positions": [[q, list(point)] for q, point in positions.items() if kind == "MOVE" and holders[q] == device]}


def _start(c):
    o = c["o"]
    return {"event": "OPERATION_STARTED", "time_us": o["start_us"], "operation_id": o["id"], "kind": o["kind"],
            "atoms": o["atoms"], "start_us": o["start_us"], "end_us": o["end_us"], "aod_id": o["aod_id"],
            "positions": o["positions"], "gate_ids": [], "metadata": o["metadata"], "resources": c["resources"],
            "depends_on": o["depends_on"], "motion_profile": o["motion_profile"],
            "trajectory_profile": "cubic" if o["motion_profile"] == "row_column" else "linear",
            "source_axes": c["source_mask"], "target_axes": {"rows": list(c["target_axes"][0]), "columns": list(c["target_axes"][1])}, "start_positions": c["start_positions"]}


def _finish(c, positions, holders, axes):
    o = c["o"]; device, kind = o["aod_id"], o["kind"]
    before_axes = _axis_payload(axes.get(device, ((), ())), positions, holders, device)
    changed = []
    for q in o["atoms"]:
        before = [holders[q], *positions[q]]
        if kind == "LOAD": holders[q] = device
        if kind == "STORE": holders[q] = "slm"
        if kind == "MOVE": positions[q] = tuple(dict(o["positions"])[q])
        after = [holders[q], *positions[q]]
        if before != after: changed.append([q, before, after])
    if kind in ("CONFIGURE", "MOVE"):
        axes[device] = c["target_axes"]
    def vector(payload): return [payload[k] for k in ("rows", "columns", "active_rows", "active_columns")]
    return {"event": "OPERATION_COMPLETED", "time_us": o["end_us"], "operation_id": o["id"], "kind": kind,
            "start_us": o["start_us"], "end_us": o["end_us"], "changed_atoms": changed, "gate_ids": [], "reports": [],
            "report_source_cursor_before": None, "report_source_cursor_after": None,
            "axes_delta": None if kind == "WAIT" else [device, vector(before_axes), vector(_axis_payload(axes[device], positions, holders, device))],
            "resources": c["resources"], "motion_profile": o["motion_profile"],
            "trajectory_profile": "cubic" if o["motion_profile"] == "row_column" else "linear"}


def _actual(expected, journal, final, initial_positions, initial_holders, initial_axes, positions, holders, axes, clock, authored_operations):
    _require(journal is not None and final is not None, "ACTUAL_EVENT_SCOPE", "Actual verification requires both journal and final checkpoint")
    journal, final = _plain(journal), _plain(final)
    actual = [row for row in journal if row.get("event") in ("OPERATION_STARTED", "OPERATION_COMPLETED")]
    _require(len(actual) == len(expected), "ACTUAL_EVENT_IDENTITY", "Every operation must have exactly one actual START and END")
    for authored, observed in zip(expected, actual):
        _require(all(observed.get(key) == value for key, value in authored.items()), "ACTUAL_EVENT_BINDING", "Actual event differs from independently replayed source/effects/axes/resources", authored["operation_id"])
    previous_time = 0
    state_hash = _digest({"atoms": [[q, [initial_holders[q], *point]] for q, point in initial_positions.items()],
                          "aod_axes": {device: [list(a[0]), list(a[1]), sorted({initial_positions[q][1] for q in initial_positions if initial_holders[q] == device}), sorted({initial_positions[q][0] for q in initial_positions if initial_holders[q] == device})] for device, a in initial_axes.items()}, "gates": [], "source": None})
    allowed = {"BLOCK_STARTED", "BLOCK_COMPLETED", "WAIT_COMPLETED", "OPERATION_STARTED", "OPERATION_COMPLETED"}
    for index, row in enumerate(journal, 1):
        _require(row.get("event") in allowed and row.get("version") == index and _number(row.get("time_us")) >= previous_time, "JOURNAL_IDENTITY", "Actual journal must be a complete monotone pure-transport event history")
        previous_time = row["time_us"]
        state_hash = _digest([state_hash, row])
    _require(final.get("schema") == "neutral_atom_kernel" and final.get("version") == 2, "CHECKPOINT_SCHEMA", "Final checkpoint must use the frozen kernel schema")
    _require(final.get("checkpoint_digest") == _digest({k: v for k, v in final.items() if k != "checkpoint_digest"}), "CHECKPOINT_DIGEST", "Final checkpoint bytes are not integrity bound")
    _require(final.get("state_hash") == state_hash and final.get("state_version") == len(journal) and final.get("journal") == journal, "JOURNAL_DIGEST", "Final checkpoint must contain exactly the reviewed actual journal")
    _require(final.get("time_us") == clock, "FINAL_CLOCK", "Final clock differs from actual completed transport schedule")
    for key in ("active_block", "running", "serial_context", "report_source"):
        _require(final.get(key) is None, "FINAL_PENDING", "Final transport checkpoint has pending execution or report source")
    for key in ("inflight", "scheduled_events", "gates", "completed_gate_ids", "fragments", "report_commit_order"):
        _require(final.get(key) == [], "PURE_TRANSPORT_SCOPE", "Final checkpoint has effects or pending operations")
    for key in ("measurement_results", "measurement_completion_times_us", "report_bindings"):
        _require(final.get(key) == {}, "PURE_TRANSPORT_SCOPE", "Pure transport cannot commit report effects")
    expected_atoms = [{"id": q, "holder": holders[q], "position": list(point)} for q, point in positions.items()]
    _require(final.get("atoms") == expected_atoms, "FINAL_ATOM_IDENTITY", "Actual final atom identities/holders/positions differ")
    _require(final.get("aod_axes") == {device: _axis_payload(a, positions, holders, device) for device, a in axes.items()}, "FINAL_RF_IDENTITY", "Actual final full RF and active masks differ")
    # A separate public-kernel cold replay checks every actual journal field,
    # scheduler cursor/resource table, and otherwise-unused checkpoint field.
    # Geometry above never delegates its predicates to this replay oracle.
    from neutral_atom_kernel.model import Operation
    from neutral_atom_kernel.runtime import KernelExecutor
    blocks = [row for row in journal if row["event"] == "BLOCK_STARTED"]
    _require(len(blocks) == 1 and blocks[0]["time_us"] == 0 and blocks[0].get("block_start_us") == 0
             and blocks[0].get("execution_mode") == "scheduled", "ACTUAL_BLOCK_SCOPE", "Actual qualification currently requires one scheduled block from the original time-zero state")
    replay = KernelExecutor(initial_positions, initial_holders=initial_holders,
                            initial_aod_axes={device: {"rows": list(a[0]), "columns": list(a[1])} for device, a in initial_axes.items()})
    block = replay.bind_block(blocks[0]["block_id"], [Operation(**o) for o in authored_operations],
                              native_provenance=blocks[0]["native_provenance"], execution_mode="scheduled")
    waits = [row["time_us"] for row in journal if row["event"] == "WAIT_COMPLETED"]
    if waits:
        replay.run(block, until_us=waits[0])
        for time in waits[1:]: replay.wait_until(time)
        replay.run()
    else:
        replay.run(block)
    _require(replay.checkpoint(include_journal=True) == final, "INDEPENDENT_KERNEL_REPLAY", "Original-state public-kernel replay differs in full journal/checkpoint")
    return {"actual_start_end_events_bound": True, "journal_chain_and_checkpoint_digest": True,
            "actual_final_positions_holders_rf": True, "full_original_state_kernel_replay": True,
            "journal_events": len(journal), "completed_operations": len(expected)//2}


def audit_modular_operations(initial_positions, operations, profile, *, initial_axes, initial_holders=None, journal=None, final_checkpoint=None):
    """Review authored absolute scheduled operations; optionally bind real ENDs.

    A PASS without journal/checkpoint qualifies only the authored transport,
    never execution.  Geometry uses immutable binary-float preimages and bounded
    rational certificates; it rejects unresolved contacts conservatively.
    """
    result = {"schema": "modular-aod-independent-audit/1", "status": "FAIL", "passed": False,
              "scope": "two-AOD/pure-transport/finite-profile/common-cubic", "failures": [],
              "handoff_geometry": "LOAD future occupied union; STORE old union through END; kernel masks commit only at END",
              "empty_empty_rf_collision_rule": False, "quantum_gate_factory_shor_qualification": False,
              "actual_execution_verified": False}
    stats = {"timeline_partitions": 0, "pair_partition_checks": 0, "certificate_nodes": 0,
             "atom_pair_checks": 0, "cartesian_spectator_checks": 0, "minimum_certified_lower_bound_um": math.inf}
    try:
        authored_operations = [_plain(operation) for operation in operations]
        result["input_sha256"] = review_input_sha256(initial_positions, authored_operations, profile,
                                                      initial_axes=initial_axes, initial_holders=initial_holders)
        p = _profile(profile)
        positions = {q: _point(point) for q, point in initial_positions.items()}
        _require(bool(positions) and all(type(q) is str and q for q in positions), "ATOM_IDENTITY", "Initial atoms require unique nonempty identities")
        holders = dict(initial_holders) if initial_holders is not None else {q: "slm" for q in positions}
        _require(holders.keys() == positions.keys() and set(holders.values()) <= {"slm", *p["devices"]}, "CARRIER_IDENTITY", "Initial holders must cover every atom using declared devices")
        axes = {device: _axes(value) for device, value in initial_axes.items()}
        _require(axes.keys() == p["devices"].keys(), "DEVICE_IDENTITY", "Every declared device requires explicit initial full RF")
        for device, a in axes.items():
            _check_axes(a, p, device)
            expected_mask = _axis_payload(a, positions, holders, device)
            for key in ("active_rows", "active_columns"):
                _require(key not in initial_axes[device] or list(initial_axes[device][key]) == expected_mask[key], "ACTIVE_AXES_CONTRACT", "Initial active axes must be exactly occupied union")
        for q, point in positions.items():
            _require(_inside(point, p["bounds_um"]), "WORLD_BOUNDS", "Initial atom is outside world")
            _require(point in p["sites"] if holders[q] == "slm" else point[1] in axes[holders[q]][0] and point[0] in axes[holders[q]][1], "RF_SUPPORT", "Initial holder does not actually support the atom")
        original_positions, original_holders, original_axes = dict(positions), dict(holders), dict(axes)
        ops = _operations(authored_operations)
        lookup = {o["id"]: o for o in ops}
        events = [(o["start_us"], 1, i, o["id"], "start") for i, o in enumerate(ops)]
        heapq.heapify(events)
        running, completed, expected, clock = {}, set(), [], 0.0
        _geometry(positions, holders, axes, running, 0, 0, stats)
        while events:
            time, _, ordinal, id, event = heapq.heappop(events)
            if time > clock:
                _geometry(positions, holders, axes, running, clock, time, stats)
            clock = time
            o = lookup[id]
            if event == "end":
                c = running.pop(id)
                expected.append(_finish(c, positions, holders, axes))
                completed.add(id)
                _geometry(positions, holders, axes, running, clock, clock, stats)
            else:
                _require(all(parent in completed for parent in o["depends_on"]), "DEPENDENCY_NOT_READY", "An operation starts before its actual predecessor END", id)
                c = _context(o, positions, holders, axes, p)
                _require(not (set(c["resources"]) & {r for active in running.values() for r in active["resources"]}), "RESOURCE_CONFLICT", "Actual overlapping operations share a device/atom/global resource", id)
                running[id] = c
                expected.append(_start(c))
                heapq.heappush(events, (o["end_us"], 0, ordinal, id, "end"))
                _geometry(positions, holders, axes, running, clock, clock, stats)
        if journal is not None or final_checkpoint is not None:
            result["actual_execution"] = _actual(expected, journal, final_checkpoint, original_positions, original_holders, original_axes, positions, holders, axes, clock, authored_operations)
            result["actual_execution_verified"] = True
        result.update(status="PASS", passed=True, operation_count=len(ops), profile_id=p["profile_id"],
                      final_reviewed_state={"time_us": clock, "positions": _plain(positions), "holders": holders,
                                            "aod_axes": {device: _axis_payload(a, positions, holders, device) for device, a in axes.items()}},
                      initial_reviewed_state={"positions": _plain(original_positions), "holders": original_holders,
                                              "aod_axes": {device: _axis_payload(a, original_positions, original_holders, device) for device, a in original_axes.items()}})
    except (ReviewError, ValueError, TypeError, KeyError, IndexError) as error:
        result["failures"].append({"code": getattr(error, "code", "INPUT_SCHEMA"), "reason": str(error), "operation_id": getattr(error, "operation_id", None)})
    if math.isinf(stats["minimum_certified_lower_bound_um"]): stats["minimum_certified_lower_bound_um"] = None
    result["continuous_geometry"] = stats
    return result


def audit(directory):
    directory = Path(directory)
    paths = {name: directory/name for name in ("initial.json", "profile.json", "operations.json", "journal.json", "checkpoint-final.json")}
    data = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}
    initial = data["initial.json"]
    result = audit_modular_operations(initial["positions"], data["operations.json"], data["profile.json"],
                                      initial_axes=initial["initial_axes"], initial_holders=initial["holders"],
                                      journal=data["journal.json"], final_checkpoint=data["checkpoint-final.json"])
    result["artifact_sha256"] = {}
    for name, path in paths.items():
        with path.open("rb") as handle:
            result["artifact_sha256"][name] = hashlib.file_digest(handle, "sha256").hexdigest()
    result["auditor_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.directory)
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False, allow_nan=False)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
