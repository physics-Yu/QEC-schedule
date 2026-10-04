"""Independent offline geometry review for the declared native-paired profile.

This module consumes the saved operation stream. It neither imports the old ENV
nor repairs routes, and is never called by the trusted event hot path. With an
explicit initial RF configuration, every ordered active/disabled axis is retained,
bounded, spaced, and included in transport time. The full active Cartesian product
is checked, including empty intersections. Unused lines close when STORE finishes.
The smaller loaded-coordinate contract is separately labelled in review reports.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations, product
from math import hypot, isclose, isfinite, sqrt


_DEFAULTS = {
    "profile_id": "native-paired-v1", "slm_grid_um": 5.0,
    "slm_origin_um": (0.0, 0.0), "aod_rows": 16, "aod_columns": 16,
    "aod_capacity": 128, "aod_axis_spacing_um": 2.0,
    "transport_clearance_um": 1.0, "cz_radius_um": 6.0,
    "cz_nonpartner_um": 10.0, "raman_separation_um": 5.0,
    "load_duration_us": 15.0, "store_duration_us": 15.0,
    "cz_duration_us": .36, "raman_duration_us": 1.0,
    "measurement_duration_us": 500.0, "reset_duration_us": 100.0,
    "move_scale_us": 200.0, "move_reference_um": 110.0,
}


class _Violation(ValueError):
    def __init__(self, code, reason):
        self.code, self.reason = code, reason
        super().__init__(reason)


def _require(condition, code, reason):
    if not condition:
        raise _Violation(code, reason)


def _field(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _point(value):
    _require(len(value) == 2, "INVALID_POINT", "Coordinates require x and y")
    point = tuple(float(v) for v in value)
    _require(all(isfinite(v) for v in point), "INVALID_POINT", "Coordinates must be finite")
    return point


def _rectangle(value):
    if isinstance(value, Mapping):
        if "lower" in value:
            value = (*value["lower"], *value["upper"])
        elif "min" in value:
            value = (*value["min"], *value["max"])
        elif "x" in value:
            value = (value["x"][0], value["y"][0], value["x"][1], value["y"][1])
        elif "x_min" in value:
            value = tuple(value[k] for k in ("x_min", "y_min", "x_max", "y_max"))
        else:
            value = tuple(value[k] for k in ("min_x", "min_y", "max_x", "max_y"))
    elif len(value) == 2:
        value = (*value[0], *value[1])
    _require(len(value) == 4, "INVALID_PROFILE", "Rectangle requires xmin,ymin,xmax,ymax")
    rectangle = tuple(float(v) for v in value)
    _require(all(isfinite(v) for v in rectangle) and rectangle[0] <= rectangle[2]
             and rectangle[1] <= rectangle[3], "INVALID_PROFILE", "Invalid rectangle bounds")
    return rectangle


def _inside(point, rectangle):
    return rectangle[0] - 1e-8 <= point[0] <= rectangle[2] + 1e-8 and rectangle[1] - 1e-8 <= point[1] <= rectangle[3] + 1e-8


def _segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    progress = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length)) if length else 0.0
    return hypot(point[0] - start[0] - progress * dx, point[1] - start[1] - progress * dy)


def _moving_pair_distance(a0, a1, b0, b1):
    return _segment_distance((0.0, 0.0), (a0[0] - b0[0], a0[1] - b0[1]), (a1[0] - b1[0], a1[1] - b1[1]))


def _distance(a, b):
    return hypot(a[0] - b[0], a[1] - b[1])


def _plain(value):
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


class _Reviewer:
    def __init__(self, initial_positions, initial_holders, profile, gates, initial_axes=None):
        self.profile = dict(_DEFAULTS, **profile)
        self.points = {q: _point(p) for q, p in initial_positions.items()}
        self.holders = {q: "slm" for q in self.points} if initial_holders is None else dict(initial_holders)
        _require(set(self.holders) == set(self.points), "INITIAL_IDENTITY", "Initial holder mapping must cover exactly all atoms")
        _require(all(h in {"slm", "AOD_0"} for h in self.holders.values()), "UNSUPPORTED_AOD_PROFILE", "This review profile supports only slm and AOD_0")
        self.gates = {_field(g, "id"): g for g in gates}
        _require(len(self.gates) == len(gates), "GATE_IDENTITY", "Gate specifications must have unique IDs")
        self.completed, self.operation_ids = set(), set()
        self.time_us = 0.0
        p = self.profile
        _require("bounds_um" in p, "PROFILE_REQUIRED", "Explicit bounds_um are required for physical qualification")
        self.bounds = _rectangle(p["bounds_um"])
        for key, value in p.items():
            if key.endswith(("_um", "_us")) and isinstance(value, (int, float)):
                _require(not isinstance(value, bool) and isfinite(value) and value > 0,
                         "INVALID_PROFILE", f"{key} must be finite and positive")
        for key in ("aod_rows", "aod_columns", "aod_capacity"):
            _require(type(p[key]) is int and 0 < p[key] <= 128, "INVALID_PROFILE", f"{key} must be an integer in 1..128")
        _require(p["aod_capacity"] <= 128, "INVALID_PROFILE", "AOD capacity cannot exceed 128")
        _require(isclose(p["cz_radius_um"], 6.0) and isclose(p["slm_grid_um"], 5.0),
                 "PROFILE_PHYSICAL_THRESHOLD", "native-paired-v1 requires finite CZ radius6um and SLM lattice5um")
        for key, minimum in (("raman_separation_um", 5.0), ("transport_clearance_um", 1.0),
                             ("cz_nonpartner_um", 10.0), ("aod_axis_spacing_um", 2.0)):
            _require(p[key] >= minimum, "PROFILE_PHYSICAL_THRESHOLD", f"{key} cannot be below {minimum}")
        for key in ("load_duration_us", "store_duration_us", "cz_duration_us", "raman_duration_us",
                    "measurement_duration_us", "reset_duration_us", "move_scale_us", "move_reference_um"):
            _require(isclose(p[key], _DEFAULTS[key], rel_tol=0, abs_tol=1e-9),
                     "PROFILE_HARDWARE_TIMING", f"native-paired-v1 fixed hardware timing changed: {key}")
        self.full_axes = self.read_axes(initial_axes or p.get("initial_axes")) if initial_axes is not None or p.get("initial_axes") is not None else None
        for q, point in self.points.items():
            self.in_bounds(point, q)
            if self.holders[q] == "slm":
                self.slm_point(point, q)
        self.atom_clearance(self.points)
        self.check_axes(self.points, self.holders)

    def in_bounds(self, point, label):
        _require(_inside(point, self.bounds), "OUT_OF_BOUNDS", f"{label} is outside declared platform bounds")

    def slm_point(self, point, label):
        self.in_bounds(point, label)
        pitch, origin = self.profile["slm_grid_um"], self.profile["slm_origin_um"]
        _require(all(isclose((point[i] - origin[i]) / pitch, round((point[i] - origin[i]) / pitch), abs_tol=1e-8) for i in (0, 1)),
                 "INVALID_SLM_SITE", f"{label} is not on the declared SLM lattice")

    def atom_clearance(self, points):
        clearance = self.profile["transport_clearance_um"]
        for a, b in combinations(points, 2):
            _require(_distance(points[a], points[b]) >= clearance - 1e-8,
                     "ATOM_COLLISION", f"Atoms {a} and {b} violate {clearance}um clearance")

    def read_axes(self, value):
        if isinstance(value, Mapping) and "AOD_0" in value:
            value = value["AOD_0"]
        if isinstance(value, Mapping) and "x_um" in value:
            value = {"columns": value["x_um"], "rows": value["y_um"]}
        _require(isinstance(value, Mapping) and set(value) >= {"columns", "rows"}, "AOD_AXIS_METADATA", "Full axes require columns and rows vectors")
        axes = {k: tuple(float(v) for v in value[k]) for k in ("columns", "rows")}
        p = self.profile
        _require(len(axes["columns"]) == p["aod_columns"] and len(axes["rows"]) == p["aod_rows"]
                 and len(axes["columns"]) * len(axes["rows"]) <= p["aod_capacity"],
                 "AOD_CAPACITY", "Full RF axes must match declared fixed capacity (including disabled spares)")
        for key, lo, hi in (("columns", self.bounds[0], self.bounds[2]), ("rows", self.bounds[1], self.bounds[3])):
            values = axes[key]
            _require(all(isfinite(v) and lo - 1e-8 <= v <= hi + 1e-8 for v in values),
                     "AOD_AXIS_BOUNDS", "An active or disabled RF coordinate is outside platform bounds")
            _require(all(b - a >= p["aod_axis_spacing_um"] - 1e-8 for a, b in zip(values, values[1:])),
                     "AOD_AXIS_SPACING", "Full ordered RF axes, including disabled spares, violate minimum spacing")
        return axes

    @staticmethod
    def axis_index(values, coordinate):
        candidates = [i for i, value in enumerate(values) if isclose(value, coordinate, rel_tol=0, abs_tol=1e-8)]
        _require(len(candidates) == 1, "AOD_AXIS_SUPPORT", "Loaded atom is not supported by exactly one declared full RF axis")
        return candidates[0]

    def axes(self, points, holders, full_axes=None):
        loaded = {q: p for q, p in points.items() if holders[q] == "AOD_0"}
        full_axes = self.full_axes if full_axes is None else full_axes
        if full_axes is not None:
            for point in loaded.values():
                self.axis_index(full_axes["columns"], point[0])
                self.axis_index(full_axes["rows"], point[1])
        return loaded, tuple(sorted({p[0] for p in loaded.values()})), tuple(sorted({p[1] for p in loaded.values()}))

    def check_axes(self, points, holders, full_axes=None):
        loaded, xs, ys = self.axes(points, holders, full_axes)
        p = self.profile
        _require(len(xs) <= p["aod_columns"] and len(ys) <= p["aod_rows"]
                 and len(xs) * len(ys) <= p["aod_capacity"], "AOD_CAPACITY", "Full active Cartesian product exceeds declared AOD rows/columns/capacity")
        for coordinates in (xs, ys):
            _require(all(b - a >= p["aod_axis_spacing_um"] - 1e-8 for a, b in zip(coordinates, coordinates[1:])),
                     "AOD_AXIS_SPACING", "Active ordered axes violate minimum spacing")
        for cell in product(xs, ys):
            self.in_bounds(cell, "Active Cartesian AOD cell")
            for q, point in points.items():
                if holders[q] == "slm":
                    _require(_distance(cell, point) >= p["transport_clearance_um"] - 1e-8,
                             "EMPTY_TRAP_STATIC_OVERLAP", f"Active Cartesian intersection {cell} overlaps static atom {q}")
        return loaded, xs, ys

    def timing(self, actual, expected):
        _require(isfinite(actual) and isclose(actual, expected, rel_tol=0, abs_tol=1e-7),
                 "DURATION_MISMATCH", f"Operation duration {actual}us differs from declared hardware duration {expected}us")

    def effect_ids(self, op, kind, atoms):
        ids = tuple(_field(op, "gate_ids", ()))
        _require(len(ids) == len(set(ids)) and not self.completed.intersection(ids), "DUPLICATE_GATE_EFFECT", "Gate effect IDs must commit exactly once")
        if kind in {"GATE", "CZ", "MEASURE", "RESET"}:
            _require(bool(ids), "GATE_IDENTITY", "Every physical gate/readout/reset effect requires original gate IDs")
        else:
            _require(not ids, "GATE_IDENTITY", "Transport/wait cannot commit logical gate effects")
        if self.gates:
            for gid in ids:
                _require(gid in self.gates, "GATE_IDENTITY", f"Unknown original gate {gid}")
                gate = self.gates[gid]
                _require(set(_field(gate, "atoms")) <= set(atoms), "GATE_ATOM_MAPPING", f"Original gate {gid} targets different atoms")
                _require(set(_field(gate, "depends_on", ())) <= self.completed, "GATE_DEPENDENCY", f"Original gate {gid} has unfinished dependencies")
                gate_kind = _field(gate, "kind").upper()
                expected = {"GATE": {"H", "X", "Y", "Z", "T"}, "CZ": {"CZ"}, "MEASURE": {"MEASURE", "MZ", "M"}, "RESET": {"RESET"}}
                _require(gate_kind in expected[kind], "GATE_KIND", f"Original gate {gid} kind does not match operation")
                _require(len(_field(gate, "atoms")) == (2 if kind == "CZ" else 1),
                         "GATE_ATOM_MAPPING", f"Original gate {gid} has invalid physical arity")
            if kind in {"GATE", "MEASURE", "RESET"}:
                _require({q for gid in ids for q in _field(self.gates[gid], "atoms")} == set(atoms),
                         "GATE_ATOM_MAPPING", "Physical effect targets must exactly match original gate atoms")
        return ids

    def cz(self, op, atoms, metadata):
        zones = metadata.get("zone_bounds")
        authoritative = self.profile.get("cz_zones_um")
        if authoritative is not None:
            _require(isinstance(authoritative, Mapping), "INVALID_PROFILE", "cz_zones_um must map native zone IDs to bounds")
            zone_ids = metadata.get("zone_ids", tuple(authoritative))
            _require(all(k in authoritative for k in zone_ids), "CZ_ZONE", "CZ references an undeclared profile illumination zone")
            if zones is not None:
                _require(isinstance(zones, Mapping) and all(k in zones and _rectangle(zones[k]) == _rectangle(authoritative[k]) for k in zone_ids),
                         "CZ_ZONE_BINDING", "Operation illumination bounds differ from the authoritative profile")
            zones = tuple(authoritative[k] for k in zone_ids)
        elif "cz_zone_um" in self.profile:
            if zones is not None:
                supplied_zones = tuple(zones[k] for k in metadata.get("zone_ids", tuple(zones))) if isinstance(zones, Mapping) else tuple(zones)
                _require(len(supplied_zones) == 1 and _rectangle(supplied_zones[0]) == _rectangle(self.profile["cz_zone_um"]),
                         "CZ_ZONE_BINDING", "Operation illumination bounds differ from the authoritative profile")
            zones = (self.profile["cz_zone_um"],)
        elif zones is None:
            _require("cz_zone_um" in self.profile, "PROFILE_REQUIRED", "CZ needs explicit illumination zone bounds")
            zones = (self.profile["cz_zone_um"],)
        elif isinstance(zones, Mapping):
            zone_ids = metadata.get("zone_ids", tuple(zones))
            _require(all(k in zones for k in zone_ids), "CZ_ZONE", "CZ references an unknown illumination zone")
            zones = tuple(zones[k] for k in zone_ids)
        else:
            zones = tuple(zones)
        rectangles = tuple(_rectangle(z) for z in zones)
        _require(bool(rectangles), "CZ_ZONE", "CZ must declare at least one illuminated zone")
        illuminated = tuple(q for q, point in self.points.items() if any(_inside(point, rectangle) for rectangle in rectangles))
        _require(set(atoms) <= set(illuminated), "CZ_ZONE", "Requested CZ atom is outside its illuminated zones")
        pairs = metadata.get("cz_pairs", metadata.get("pairs"))
        if pairs is None and self.gates:
            pairs = tuple(_field(self.gates[g], "atoms") for g in _field(op, "gate_ids"))
        _require(pairs is not None, "CZ_PAIR_MAPPING", "CZ requires original requested pairs")
        requested = {tuple(sorted(pair)) for pair in pairs}
        _require(all(len(pair) == 2 and pair[0] != pair[1] and set(pair) <= set(atoms) for pair in requested)
                 and len(requested) == len(pairs), "CZ_PAIR_MAPPING", "CZ requested pairs must be distinct mapped atom pairs")
        if self.gates:
            expected = {tuple(sorted(_field(self.gates[g], "atoms"))) for g in _field(op, "gate_ids")}
            _require(requested == expected, "CZ_PAIR_MAPPING", "CZ requested pairs differ from original gate identities")
        actual = {tuple(sorted((a, b))) for a, b in combinations(illuminated, 2) if _distance(self.points[a], self.points[b]) <= self.profile["cz_radius_um"] + 1e-8}
        _require(actual == requested, "CZ_ACTUAL_PAIRS", f"Finite-range CZ pairs differ: requested={sorted(requested)}, actual={sorted(actual)}")
        _require(len({q for pair in requested for q in pair}) == 2 * len(requested), "CZ_PAIR_MAPPING", "Parallel CZ pairs cannot share an atom")
        for a, b in combinations(illuminated, 2):
            if tuple(sorted((a, b))) not in requested:
                _require(_distance(self.points[a], self.points[b]) >= self.profile["cz_nonpartner_um"] - 1e-8,
                         "CZ_NONPARTNER_CLEARANCE", f"Illuminated nonpartners {a}/{b} violate minimum separation")

    def apply(self, op):
        oid, kind = _field(op, "id"), _field(op, "kind").upper()
        _require(oid and oid not in self.operation_ids, "OPERATION_IDENTITY", "Operation IDs must be globally unique")
        atoms = tuple(_field(op, "atoms", ()))
        _require(len(atoms) == len(set(atoms)) and set(atoms) <= set(self.points), "ATOM_IDENTITY", "Operation contains duplicate or unknown atoms")
        _require(kind in {"CONFIGURE", "LOAD", "MOVE", "STORE", "GATE", "CZ", "MEASURE", "RESET", "WAIT"}, "OPERATION_KIND", f"Unsupported operation kind {kind}")
        _require(_field(op, "aod_id", "AOD_0") == "AOD_0", "UNSUPPORTED_AOD_PROFILE", "Native reviewer qualifies only AOD_0")
        _require(bool(atoms) or kind in {"CONFIGURE", "WAIT"}, "ATOM_IDENTITY", "Physical operations require explicit atoms")
        metadata = _field(op, "metadata", {})
        duration = float(_field(op, "duration_us", 0))
        ids = self.effect_ids(op, kind, atoms)
        new_points, new_holders = dict(self.points), dict(self.holders)
        next_axes = self.full_axes
        if metadata.get("source_axes") is not None or metadata.get("target_axes") is not None:
            _require(self.full_axes is not None, "INITIAL_AXES_REQUIRED", "Full-RF operation review requires explicit initial_axes")
            source = self.read_axes(metadata.get("source_axes"))
            _require(source == self.full_axes, "AOD_AXIS_BINDING", "Operation source axes differ from committed full RF coordinates")
            next_axes = self.read_axes(metadata.get("target_axes"))
        supplied = {q: _point(point) for q, point in _field(op, "positions", ())}
        if kind == "CONFIGURE":
            _require(self.full_axes is not None and next_axes is not None and metadata.get("target_axes") is not None,
                     "AOD_AXIS_METADATA", "CONFIGURE requires explicitly bound full RF axes")
            _require(not atoms and not supplied and all(holder != "AOD_0" for holder in self.holders.values()),
                     "CONFIGURE_LOADED_DEVICE", "Only an empty, disabled AOD can CONFIGURE its full RF coordinates")
            delta = max(abs(a - b) for key in ("columns", "rows") for a, b in zip(self.full_axes[key], next_axes[key]))
            self.timing(duration, self.profile["move_scale_us"] * sqrt(delta / self.profile["move_reference_um"]))
        elif kind == "MOVE":
            _require(set(supplied) == set(atoms) and all(self.holders[q] == "AOD_0" for q in atoms), "MOVE_HOLDER", "MOVE must target exactly its declared already-loaded atoms")
            new_points.update(supplied)
            old_loaded, xs, ys = self.axes(self.points, self.holders)
            mappings = []
            for dim, coordinates in enumerate((xs, ys)):
                axis_map = {}
                for q, point in old_loaded.items():
                    target = new_points[q][dim]
                    _require(point[dim] not in axis_map or isclose(axis_map[point[dim]], target, abs_tol=1e-8),
                             "AOD_SHARED_AXIS_SPLIT", "Atoms sharing an active AOD row/column must move together")
                    axis_map[point[dim]] = target
                if self.full_axes is not None:
                    _require(metadata.get("target_axes") is not None, "AOD_AXIS_METADATA", "Full-RF MOVE requires explicit target axes")
                    axis_key = "columns" if dim == 0 else "rows"
                    for coordinate, target in axis_map.items():
                        index = self.axis_index(self.full_axes[axis_key], coordinate)
                        _require(isclose(next_axes[axis_key][index], target, rel_tol=0, abs_tol=1e-8),
                                 "AOD_AXIS_SUPPORT", "Atom MOVE targets differ from their fixed RF row/column identities")
                ends = [axis_map[v] for v in coordinates]
                _require(all(b - a >= self.profile["aod_axis_spacing_um"] - 1e-8 for a, b in zip(ends, ends[1:])),
                         "AOD_AXIS_CROSSING", "Ordered AOD axes cannot cross, merge or violate spacing")
                mappings.append(axis_map)
            cells = tuple(product(xs, ys))
            clearance = self.profile["transport_clearance_um"]
            for cell in cells:
                end = (mappings[0][cell[0]], mappings[1][cell[1]])
                self.in_bounds(end, "Moved Cartesian AOD cell")
                for q, point in self.points.items():
                    if self.holders[q] == "slm":
                        _require(_segment_distance(point, cell, end) >= clearance - 1e-8,
                                 "AOD_STATIC_SWEEP", f"Loaded or empty Cartesian cell sweeps static atom {q}")
            for a, b in combinations(self.points, 2):
                _require(_moving_pair_distance(self.points[a], new_points[a], self.points[b], new_points[b]) >= clearance - 1e-8,
                         "ATOM_SWEEP_COLLISION", f"Continuous atom trajectories {a}/{b} violate clearance")
            max_axis = (max(abs(a - b) for key in ("columns", "rows") for a, b in zip(self.full_axes[key], next_axes[key]))
                        if self.full_axes is not None else max((abs(new_points[q][d] - self.points[q][d]) for q in old_loaded for d in (0, 1)), default=0.0))
            self.timing(duration, self.profile["move_scale_us"] * sqrt(max_axis / self.profile["move_reference_um"]))
        elif kind in {"LOAD", "STORE"}:
            _require(self.full_axes is None or next_axes == self.full_axes, "TRANSFER_AXIS_MOTION", "LOAD/STORE cannot implicitly move RF coordinates")
            _require(not supplied or set(supplied) == set(atoms) and all(_distance(supplied[q], self.points[q]) <= 1e-8 for q in atoms),
                     "TRANSFER_TELEPORTATION", "LOAD/STORE cannot change atom coordinates")
            source, target = ("slm", "AOD_0") if kind == "LOAD" else ("AOD_0", "slm")
            _require(all(self.holders[q] == source for q in atoms), "TRANSFER_HOLDER", f"{kind} source holders are inconsistent")
            for q in atoms:
                self.slm_point(self.points[q], q)
                new_holders[q] = target
            self.timing(duration, self.profile["load_duration_us" if kind == "LOAD" else "store_duration_us"])
            if kind == "LOAD":
                _, nx, ny = self.axes(new_points, new_holders, next_axes)
                omitted = [q for q, point in self.points.items() if self.holders[q] == "slm" and q not in atoms
                           and any(_distance(point, cell) < self.profile["transport_clearance_um"] - 1e-8 for cell in product(nx, ny))]
                _require(not omitted, "OMITTED_CARTESIAN_CAPTURE", f"LOAD active Cartesian cells capture undeclared static atoms {omitted}")
        else:
            _require(self.full_axes is None or next_axes == self.full_axes, "OPERATION_AXIS_MOTION", "Gate/readout/reset/wait cannot implicitly change RF coordinates")
            _require(not supplied, "OPERATION_TELEPORTATION", "Gate/readout/reset/wait cannot change coordinates")
            if kind == "GATE":
                gate_kind = metadata.get("gate_kind")
                if gate_kind is None and self.gates:
                    gate_kind = _field(self.gates[ids[0]], "kind")
                _require(gate_kind in {"H", "X", "Y", "Z", "T"}, "GATE_KIND", "1Q operation requires an explicit supported gate kind")
                if self.gates:
                    _require(all(_field(self.gates[gid], "kind") == gate_kind for gid in ids), "GATE_KIND", "Parallel 1Q effects must have identical gate types")
                for q in atoms:
                    for other, point in self.points.items():
                        if q != other:
                            _require(_distance(self.points[q], point) >= self.profile["raman_separation_um"] - 1e-8,
                                     "RAMAN_SEPARATION", f"Addressed atom {q} is too close to spectator/target {other}")
                self.timing(duration, self.profile["raman_duration_us"])
            elif kind == "CZ":
                self.cz(op, atoms, metadata)
                self.timing(duration, self.profile["cz_duration_us"])
            elif kind in {"MEASURE", "RESET"}:
                _require("measurement_zone_um" in self.profile, "PROFILE_REQUIRED", "Readout/reset needs explicit measurement zone bounds")
                zone = _rectangle(self.profile["measurement_zone_um"])
                _require(all(self.holders[q] == "slm" and _inside(self.points[q], zone) for q in atoms),
                         "READOUT_ZONE_SUPPORT", "Measurement/reset requires stable SLM support in MZ")
                self.timing(duration, self.profile["measurement_duration_us" if kind == "MEASURE" else "reset_duration_us"])
            elif kind == "WAIT":
                _require(isfinite(duration) and duration >= 0 and not atoms, "DURATION_MISMATCH", "WAIT requires a finite nonnegative duration and no target atoms")
        self.atom_clearance(new_points)
        _, active_xs, active_ys = self.check_axes(new_points, new_holders, next_axes)
        for key, expected in (("active_columns", active_xs), ("active_rows", active_ys)):
            if key in metadata:
                supplied_active = tuple(sorted(float(v) for v in metadata[key]))
                _require(len(supplied_active) == len(expected) and all(isclose(a, b, rel_tol=0, abs_tol=1e-8) for a, b in zip(supplied_active, expected)),
                         "AOD_ACTIVE_MASK_BINDING", "Recorded active RF coordinates differ from the complete loaded-atom support")
        self.points, self.holders = new_points, new_holders
        self.full_axes = next_axes
        self.completed.update(ids)
        self.operation_ids.add(oid)
        self.time_us += duration


def audit_operations(initial_positions, operations, profile, *, initial_holders=None, gates=(), initial_axes=None):
    """Return PASS/FAIL with the first independent physical failure retained.

    ``operations`` accepts immutable Operation values or equivalent mappings.
    ``gates`` optionally binds all original gate identities and dependencies;
    when supplied, omitted effects are also rejected at final completion.
    ``initial_axes`` accepts columns/rows vectors (or a device-keyed AOD_0 map).
    Only the declared AOD_0 native profile is qualified by this reviewer.
    No later operation is reviewed after a failure using a guessed successor.
    """
    operations, gates = tuple(operations), tuple(gates)
    effective = dict(_DEFAULTS, **profile)
    result = {
        "schema": "native-kernel-strict-review/1", "status": "FAIL", "passed": False,
        "execution_mode": "offline_strict", "profile": _plain(effective),
        "geometry_contract": {
            "name": "experimental_native_loaded_coordinate_ordered_axes/1",
            "active_axes": "unique loaded x coordinates by unique loaded y coordinates, including every empty Cartesian intersection",
            "movement": "ordered axes with shared-coordinate consistency; straight simultaneous interpolation at equal normalized progress",
            "selective_store": "support transfers at completion; close only axes unused by remaining loaded atoms; check all remaining Cartesian intersections",
            "dormant_axes": "No physical coordinates are assigned to disabled lines; no hidden empty-device positioning cost is claimed",
            "scope": "one native AOD_0; no multi-AOD native scheduling qualification, quantum dynamics or optical waveform simulation",
        },
        "operation_count": len(operations), "checked_operations": 0, "failures": [],
    }
    reviewer, current = None, None
    try:
        reviewer = _Reviewer(initial_positions, initial_holders, effective, gates, initial_axes)
        if reviewer.full_axes is not None:
            result["geometry_contract"].update(
                name="experimental_native_full_rf_ordered_axes/1",
                active_axes="explicit full RF rows/columns; active coordinates follow all loaded atoms; check complete active Cartesian product",
                dormant_axes="disabled RF axes retain explicit coordinates; all full-capacity coordinates, bounds, spacing and MOVE/CONFIGURE travel time are reviewed",
                selective_store="STORE preserves all RF coordinates; support transfers at completion and only unused RF lines deactivate")
        for current in operations:
            reviewer.apply(current)
            result["checked_operations"] += 1
        current = None
        if reviewer.gates:
            missing = set(reviewer.gates) - reviewer.completed
            _require(not missing, "MISSING_GATE_EFFECT", f"Original gates were not executed: {sorted(missing)}")
        result.update(status="PASS", passed=True)
    except _Violation as error:
        result["failures"].append({"op_id": _field(current, "id") if current is not None else None,
            "source_line": _field(current, "metadata", {}).get("source_line") if current is not None else None,
            "code": error.code, "reason": error.reason})
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        result["failures"].append({"op_id": _field(current, "id") if current is not None else None,
            "source_line": _field(current, "metadata", {}).get("source_line") if current is not None else None,
            "code": "MALFORMED_REVIEW_INPUT", "reason": str(error)})
    if reviewer is not None:
        result["final_reviewed_state"] = {"time_us": reviewer.time_us, "positions": _plain(reviewer.points),
            "holders": dict(reviewer.holders), "completed_gate_ids": sorted(reviewer.completed)}
        if reviewer.full_axes is not None:
            result["final_reviewed_state"]["axes"] = _plain(reviewer.full_axes)
    return result


verify_operations = audit_operations
