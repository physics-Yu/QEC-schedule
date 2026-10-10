"""Grouped geometry and readout profile; no routing, quantum state or results."""

from __future__ import annotations

from copy import deepcopy
import json
import math

from .spec import _finite_number, default_device, validate_device
from .model import DeviceModelError, _inside, _point

_DATA = [f"d{i}" for i in range(9)]
_ANCILLA = [f"{p}{i}" for p in ("x", "z") for i in range(4)]
_ALL = _DATA + _ANCILLA


def _profile() -> dict:
    home = {name: {"position_um": [10.0 * (i % 3), 10.0 * (i // 3)],
                   "row_id": f"r{i // 3}", "column_id": f"c{i % 3}"}
            for i, name in enumerate(_DATA)}
    for row, prefix in enumerate(("x", "z"), start=4):
        for i in range(4):
            home[f"{prefix}{i}"] = {"position_um": [10.0 * i, 10.0 * row],
                                      "row_id": f"r{row}", "column_id": f"c{i}"}
    entry = deepcopy(home)
    for slot in entry.values():
        slot["position_um"][1] -= 100.0
    mz = {name: deepcopy(home[name]) for name in _ANCILLA}
    for slot in mz.values():
        slot["position_um"][1] += 50.0
    return {
        "schema_version": "grouped-device-profile/0.1", "profile_id": "surface17-grouped-v1",
        "provenance": {
            "kind": "project_assumption", "calibrated": False,
            "source_refs": ["R8-PLATFORM-001@0.9.0:UA-26/27", "R8-SYNC-001@0.1.0", "ADR-0006@1.0.0", "R1-GROUP-IF-001@0.1.0"],
            "scope": "Explicit Surface-17 local ports and per-bank readout model; not hardware calibration.",
        },
        "initialization_zone": {"x_range_um": [None, None], "y_range_um": [-110.0, -40.0], "boundary": "closed"},
        "layouts": {
            "patch_initialization": {"zone_id": "initialization", "carrier": "SLM", "slots": entry},
            "patch_home": {"zone_id": "storage_entanglement", "carrier": "SLM", "slots": home},
            "ancilla_readout": {"zone_id": "measurement", "carrier": "SLM", "slots": mz},
        },
        "groups": {
            "patch_initialization_transport": {
                "members": list(_ALL), "source_layout": "patch_initialization", "target_layout": "patch_home", "return_layout": None,
            },
            "maintenance_readout": {
                "members": list(_ANCILLA), "source_layout": "patch_home", "target_layout": "ancilla_readout", "return_layout": "patch_home",
            },
        },
        "capture": {"model": "cartesian_product", "tolerance_ref": "geometry.distance_tolerance_um", "selective_atom_mask": False},
        "readout": {"model": "per_site_parallel", "bank_capacity": 8, "resource_scope": "instantiated_bank_and_site",
                    "independent_banks": True, "basis": "Z", "timing_ref": "timings_us"},
    }


def grouped_device(*, readout_capacity: int = 8) -> dict:
    """New opt-in profile. The legacy default_device is deliberately unchanged."""
    if type(readout_capacity) is not int or not 1 <= readout_capacity <= 8:
        raise DeviceModelError([{"code": "INVALID_CAPACITY", "path": "/readout_capacity", "message": "An eight-site bank supports 1 to 8 simultaneous readouts."}])
    device = default_device()
    device["artifact_id"] = f"device:surface17-grouped-v1:readout-{readout_capacity}"
    device["device_id"] = "neutral-atom-grouped-engineering-reference"
    device["provenance"].update(kb_revision="kb-0005", interface_version="IF-STRATEGY-001/0.1.0",
                                 source_refs=["ADR-0006@1.0.0", "R8-PLATFORM-001@0.9.0", "R1-GROUP-IF-001@0.1.0"])
    device["zones"]["storage_entanglement"]["y_range_um"] = [0.0, 70.0]
    device["zones"]["measurement"]["y_range_um"] = [80.0, 110.0]
    device["parameter_provenance"]["/zones"]["source_refs"] = ["R1-GROUP-IF-001@0.1.0", "R8-PLATFORM-001@0.9.0:UA-26/27"]
    device["grouped_profile"] = _profile()
    device["grouped_profile"]["readout"]["bank_capacity"] = readout_capacity
    return device


def _preinitialized_profile() -> dict:
    """Current entry profile: deliberately contains no initialization port."""
    profile = _profile()
    profile["schema_version"] = "grouped-device-profile/0.2"
    profile["profile_id"] = "surface17-preinitialized-v1"
    profile.pop("initialization_zone")
    profile["layouts"].pop("patch_initialization")
    profile["groups"].pop("patch_initialization_transport")
    profile["provenance"]["source_refs"] = ["ADR-0008@1.0.0", "R1-PREINITIALIZED-IF-001@0.1.0"]
    profile["provenance"]["scope"] = "Preinitialized encoded entry, local patch ports and per-bank readout; no startup transport or hardware calibration."
    for name, slot in profile["layouts"]["ancilla_readout"]["slots"].items():
        slot["position_um"][1] = 1020.0 if name.startswith("x") else 1030.0
    return profile


def _issue(code, path, message):
    return {"code": code, "path": path, "message": message}


def _zone(device, zone_id):
    return device["grouped_profile"]["initialization_zone"] if zone_id == "initialization" else device["zones"][zone_id]


def validate_grouped_profile(device: dict) -> list[dict]:
    """Extension validation, called by validate_device after base validation."""
    profile = device.get("grouped_profile")
    current = type(profile) is dict and profile.get("schema_version") == "grouped-device-profile/0.2"
    expected = _preinitialized_profile() if current else _profile()
    errors = []
    try:
        json.dumps(profile, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return [_issue("NON_JSON_VALUE", "/grouped_profile", "Grouped profile needs finite JSON values.")]

    def check(actual, reference, path):
        if type(reference) is dict:
            if type(actual) is not dict:
                errors.append(_issue("INVALID_TYPE", path, "Expected object."))
                return
            if set(actual) != set(reference):
                errors.append(_issue("GROUP_PROFILE_FIELDS", path, "Missing or unsupported grouped profile fields/slots."))
            for key in actual.keys() & reference.keys():
                check(actual[key], reference[key], f"{path}/{key}")
        elif type(reference) is list:
            if type(actual) is not list:
                errors.append(_issue("INVALID_TYPE", path, "Expected array."))
            elif path.endswith(("position_um", "range_um")):
                if len(actual) != 2 or any(not _finite_number(v) and not (v is None and path.endswith("range_um")) for v in actual):
                    errors.append(_issue("INVALID_GEOMETRY", path, "Expected two finite coordinates (null allowed only for range bounds)."))
            elif not actual or any(type(v) is not str or not v for v in actual) or len(actual) != len(set(actual)):
                errors.append(_issue("INVALID_LIST", path, "Expected unique nonempty string entries."))
        elif type(reference) is bool:
            if type(actual) is not bool or actual != reference:
                errors.append(_issue("UNSUPPORTED_GROUP_MODEL", path, "Unsupported group capability flag."))
        elif type(reference) is int:
            if type(actual) is not int or actual <= 0:
                errors.append(_issue("INVALID_CAPACITY", path, "Capacity must be a positive integer."))
        elif reference is None:
            if actual is not None:
                errors.append(_issue("UNSUPPORTED_GROUP_MODEL", path, "Initialization does not imply a return operation."))
        elif type(actual) is not str or not actual.strip():
            errors.append(_issue("INVALID_TYPE", path, "Expected a nonempty string."))

    check(profile, expected, "/grouped_profile")
    if errors:
        return errors
    for section in ("capture", "readout"):
        for key, value in expected[section].items():
            if key != "bank_capacity" and profile[section][key] != value:
                errors.append(_issue("UNSUPPORTED_GROUP_MODEL", f"/grouped_profile/{section}/{key}", "Unknown capture or readout semantics."))
    for key in ("schema_version", "profile_id"):
        if profile[key] != expected[key]:
            errors.append(_issue("UNSUPPORTED_GROUP_MODEL", f"/grouped_profile/{key}", "Unknown grouped profile version."))
    if profile["provenance"]["kind"] != "project_assumption":
        errors.append(_issue("PROVENANCE_KIND", "/grouped_profile/provenance", "Grouped geometry/concurrency remain project assumptions."))
    if not current:
        init_zone = profile["initialization_zone"]
        if init_zone["boundary"] != "closed":
            errors.append(_issue("UNSUPPORTED_GROUP_MODEL", "/grouped_profile/initialization_zone", "Closed boundaries are required."))
        for axis in ("x", "y"):
            lo, hi = init_zone[f"{axis}_range_um"]
            if lo is not None and hi is not None and lo >= hi:
                errors.append(_issue("INVALID_RANGE", f"/grouped_profile/initialization_zone/{axis}_range_um", "Range endpoints are reversed or equal."))
    for lid, layout in profile["layouts"].items():
        ref = expected["layouts"][lid]
        if layout["zone_id"] != ref["zone_id"] or layout["carrier"] != "SLM":
            errors.append(_issue("INVALID_LAYOUT_PORT", f"/grouped_profile/layouts/{lid}", "Layout has unsupported region or carrier."))
            continue
        positions = []
        axis_maps = {"row_id": {}, "column_id": {}}
        for slot, value in layout["slots"].items():
            point = value["position_um"]
            positions.append(tuple(point))
            if not _inside(_zone(device, layout["zone_id"]), point):
                errors.append(_issue("SITE_OUTSIDE_ZONE", f"/grouped_profile/layouts/{lid}/slots/{slot}", "Declared site is outside its region."))
            for field, axis in (("row_id", 1), ("column_id", 0)):
                axis_map = axis_maps[field]
                if value[field] in axis_map and axis_map[value[field]] != point[axis]:
                    errors.append(_issue("SHARED_AXIS_INCONSISTENT", f"/grouped_profile/layouts/{lid}/slots/{slot}", "One row/column ID maps to multiple coordinates."))
                axis_map[value[field]] = point[axis]
        if len(set(positions)) != len(positions):
            errors.append(_issue("DUPLICATE_SITE", f"/grouped_profile/layouts/{lid}", "Two slots occupy one site."))
        for field, axis_map in axis_maps.items():
            if len(set(axis_map.values())) != len(axis_map):
                errors.append(_issue("LINE_COLLISION", f"/grouped_profile/layouts/{lid}/{field}", "Different lines cannot share a coordinate."))
    for purpose, group in profile["groups"].items():
        if set(group["members"]) != set(expected["groups"][purpose]["members"]):
            errors.append(_issue("GROUP_MEMBERS", f"/grouped_profile/groups/{purpose}", "Surface-17 group has incomplete or extra members."))
        for key in ("source_layout", "target_layout", "return_layout"):
            if group[key] != expected["groups"][purpose][key]:
                errors.append(_issue("INVALID_GROUP_PORT", f"/grouped_profile/groups/{purpose}/{key}", "Group port does not match the declared lifecycle."))
    if profile["readout"]["bank_capacity"] > len(profile["layouts"]["ancilla_readout"]["slots"]):
        errors.append(_issue("READOUT_SITE_CAPACITY", "/grouped_profile/readout/bank_capacity", "Concurrent capacity exceeds receiver site count."))
    return errors


def _require_grouped(device):
    errors = validate_device(device)
    if not errors and "grouped_profile" not in device:
        errors = [_issue("GROUP_PROFILE_REQUIRED", "/grouped_profile", "The legacy device does not declare grouped ports/readout.")]
    if errors:
        raise DeviceModelError(errors)


def group_layout(device: dict, layout_id: str, *, offset_um=(0, 0)) -> dict:
    _require_grouped(device)
    layouts = device["grouped_profile"]["layouts"]
    if type(layout_id) is not str or layout_id not in layouts:
        raise DeviceModelError([_issue("UNKNOWN_GROUP_LAYOUT", "/layout_id", "Unknown layout port.")])
    dx, dy = _point(offset_um, "/offset_um")
    result = deepcopy(layouts[layout_id])
    for slot_id, slot in result["slots"].items():
        x, y = slot["position_um"]
        slot["position_um"] = [x + dx, y + dy]
        if not all(_finite_number(v) for v in slot["position_um"]) or not _inside(_zone(device, result["zone_id"]), slot["position_um"]):
            raise DeviceModelError([_issue("SITE_OUTSIDE_ZONE", f"/slots/{slot_id}", "Translated layout lies outside its region.")])
    return result


def _world(atoms):
    if type(atoms) is not dict or any(type(k) is not str or not k or type(v) is not dict for k, v in atoms.items()):
        raise DeviceModelError([_issue("INVALID_ATOMS", "/atoms", "Expected atom ID to state mapping.")])
    points = {}
    for aid, atom in atoms.items():
        if atom.get("carrier") not in ("SLM", "AOD"):
            raise DeviceModelError([_issue("INVALID_CARRIER", f"/atoms/{aid}", "Every present atom needs SLM/AOD carrier.")])
        points[aid] = _point(atom.get("position_um"), f"/atoms/{aid}/position_um")
    return points


def _capture(device, atoms, points, rows, columns):
    tol = device["geometry"]["distance_tolerance_um"]
    return sorted(aid for aid, (x, y) in points.items()
                  if atoms[aid]["carrier"] == "SLM"
                  and any(abs(y - r) <= tol for r in rows) and any(abs(x - c) <= tol for c in columns))


def capture_closure(device: dict, atoms: dict, rows_um: list, columns_um: list) -> list[str]:
    _require_grouped(device)
    points = _world(atoms)
    for name, coordinates in (("rows_um", rows_um), ("columns_um", columns_um)):
        if type(coordinates) is not list or any(not _finite_number(v) for v in coordinates) or len(coordinates) != len(set(coordinates)):
            raise DeviceModelError([_issue("INVALID_LINES", f"/{name}", "Expected unique finite line coordinates.")])
    return _capture(device, atoms, points, rows_um, columns_um)


def validate_group_transfer(device: dict, purpose: str, atoms: dict, bindings: dict, *, target_layout_id: str, offset_um=(0, 0), aod_group="data") -> list[dict]:
    """Single-batch endpoint/capture checks; not a whole-trajectory validator."""
    try:
        _require_grouped(device)
        points = _world(atoms)
        target = group_layout(device, target_layout_id, offset_um=offset_um)
    except DeviceModelError as exc:
        return exc.errors
    profile = device["grouped_profile"]
    if type(purpose) is not str or purpose not in profile["groups"]:
        return [_issue("UNKNOWN_GROUP", "/purpose", "Unknown group purpose.")]
    if type(aod_group) is not str or aod_group not in device["aod_groups"]:
        return [_issue("UNKNOWN_AOD_GROUP", "/aod_group", "Unknown AOD resource.")]
    contract = profile["groups"][purpose]
    if type(bindings) is not dict or set(bindings) != set(contract["members"]) or any(type(v) is not str or v not in atoms for v in bindings.values()):
        return [_issue("GROUP_MEMBERS", "/bindings", "Bindings must cover every declared formal slot with a present atom.")]
    if len(set(bindings.values())) != len(bindings):
        return [_issue("ALIASED_ATOM", "/bindings", "Group members cannot share an atom.")]
    allowed_targets = [contract["target_layout"]]
    if contract["return_layout"] is not None:
        allowed_targets.append(contract["return_layout"])
    if target_layout_id not in allowed_targets:
        return [_issue("INVALID_GROUP_PORT", "/target_layout_id", "Target is outside the group's declared forward/return ports.")]
    members = set(bindings.values())
    if any(atoms[aid]["carrier"] != "SLM" for aid in members):
        return [_issue("SOURCE_CARRIER", "/atoms", "This transfer starts with an explicit SLM pickup.")]
    errors = []
    source_layout_id = contract["source_layout"]
    if contract["return_layout"] is not None and target_layout_id == contract["return_layout"]:
        source_layout_id = contract["target_layout"]
    source_zone = _zone(device, profile["layouts"][source_layout_id]["zone_id"])
    for aid in members:
        if not _inside(source_zone, points[aid]):
            errors.append(_issue("SOURCE_OUTSIDE_ZONE", f"/atoms/{aid}", "Source lies outside the declared forward/return port region."))
    rows = sorted({points[aid][1] for aid in members})
    columns = sorted({points[aid][0] for aid in members})
    closure = set(_capture(device, atoms, points, rows, columns))
    if closure != members:
        errors.append(_issue("CAPTURE_CLOSURE", "/atoms", f"Row/column pickup captures unexpected atoms: {sorted(closure - members)}."))
    tol = device["geometry"]["distance_tolerance_um"]
    for label, coordinates in (("rows", rows), ("columns", columns)):
        if any(b - a <= tol for a, b in zip(coordinates, coordinates[1:])):
            errors.append(_issue("AMBIGUOUS_AXIS", f"/source/{label}", "Distinct source lines are within the numeric alignment tolerance."))
    targets = {aid: target["slots"][slot]["position_um"] for slot, aid in bindings.items()}
    for slot, aid in bindings.items():
        for other, point in points.items():
            if other != aid and math.dist(points[aid], point) <= tol:
                errors.append(_issue("SOURCE_OCCUPANCY", f"/atoms/{aid}", f"Source overlaps {other}."))
            if other not in members and math.dist(targets[aid], point) <= tol:
                errors.append(_issue("TARGET_OCCUPIED", f"/target/{slot}", f"Target is occupied by {other}."))
    for axis, label in ((0, "columns"), (1, "rows")):
        mapping = {}
        for aid in members:
            source, end = points[aid][axis], targets[aid][axis]
            if source in mapping and mapping[source] != end:
                errors.append(_issue("SHARED_AXIS_SPLIT", f"/target/{label}", "One source line maps to several target coordinates."))
            mapping[source] = end
        order = sorted(mapping)
        if any(mapping[a] >= mapping[b] for a, b in zip(order, order[1:])):
            errors.append(_issue("LINE_CROSSING", f"/target/{label}", "Target lines collapse or reverse source order."))
    return errors


def validate_readout_batch(device: dict, entries: list[dict]) -> list[dict]:
    """Validate actual event times/resources, without producing fake outcomes."""
    try:
        _require_grouped(device)
    except DeviceModelError as exc:
        return exc.errors
    required = {"atom_id", "bank_id", "site_id", "position_um", "t_start_us", "t_end_us", "earliest_ready_us", "result_id", "result_ready_us", "basis"}
    if type(entries) is not list or not entries:
        return [_issue("INVALID_READOUT_BATCH", "/entries", "A nonempty list of readout events is required.")]
    errors, parsed = [], []
    for i, event in enumerate(entries):
        path = f"/entries/{i}"
        if type(event) is not dict or set(event) != required:
            errors.append(_issue("READOUT_FIELDS", path, "Missing or unknown readout event fields."))
            continue
        if any(type(event[k]) is not str or not event[k] for k in ("atom_id", "bank_id", "site_id", "result_id", "basis")):
            errors.append(_issue("INVALID_ID", path, "IDs and basis must be nonempty strings."))
            continue
        try:
            point = _point(event["position_um"], path + "/position_um")
        except DeviceModelError as exc:
            errors.extend(exc.errors)
            continue
        if any(not _finite_number(event[k]) or event[k] < 0 for k in ("t_start_us", "t_end_us", "earliest_ready_us", "result_ready_us")):
            errors.append(_issue("INVALID_TIME", path, "Readout times must be finite and nonnegative."))
            continue
        parsed.append((i, event, point))
    if errors:
        return errors
    result_ids = set()
    site_positions, bank_offsets = {}, {}
    receiver = device["grouped_profile"]["layouts"]["ancilla_readout"]["slots"]
    for i, event, point in parsed:
        path = f"/entries/{i}"
        if event["basis"] != "Z":
            errors.append(_issue("READOUT_BASIS", path, "This profile reads in Z; apply required basis gates beforehand."))
        if not _inside(device["zones"]["measurement"], point):
            errors.append(_issue("SITE_OUTSIDE_ZONE", path, "Readout atom is outside MZ."))
        start, end = event["t_start_us"], event["t_end_us"]
        if end <= start or not math.isclose(end - start, device["timings_us"]["measure"], rel_tol=1e-12, abs_tol=1e-9):
            errors.append(_issue("READOUT_DURATION", path, "Readout duration differs from the declared positive device duration."))
        if start < event["earliest_ready_us"]:
            errors.append(_issue("READOUT_BEFORE_READY", path, "Last coupling/basis/transport prerequisite is not complete."))
        if event["result_ready_us"] < end + device["timings_us"]["result_latency"]:
            errors.append(_issue("RESULT_BEFORE_READY", path, "Result appears before readout end plus device latency."))
        if event["result_id"] in result_ids:
            errors.append(_issue("DUPLICATE_RESULT", path, "Each measurement needs an independent result ID."))
        result_ids.add(event["result_id"])
        key = (event["bank_id"], event["site_id"])
        if key in site_positions and site_positions[key] != point:
            errors.append(_issue("SITE_IDENTITY", path, "A bank/site ID cannot denote different positions."))
        site_positions[key] = point
        if event['bank_id']=='rigid-mz':
            from .rigid_readout import rigid_site_id
            try:
                if event['site_id']!=rigid_site_id(device,point):
                    errors.append(_issue('RIGID_SITE_IDENTITY',path,'Grid site ID must identify its exact declared lattice coordinate.'))
            except ValueError as exc:
                errors.append(_issue('RIGID_SITE_GEOMETRY',path,str(exc)))
        elif event["site_id"] not in receiver:
            errors.append(_issue("UNKNOWN_READOUT_SITE", path, "site_id must name a receiver slot within its bank (x0..x3/z0..z3)."))
        else:
            local = receiver[event["site_id"]]["position_um"]
            offset = (point[0] - local[0], point[1] - local[1])
            bank = event["bank_id"]
            if bank in bank_offsets and offset != bank_offsets[bank]:
                errors.append(_issue("READOUT_BANK_GEOMETRY", path, "All sites of an instantiated bank must share one declared-layout translation."))
            bank_offsets[bank] = offset
    default_capacity = device["grouped_profile"]["readout"]["bank_capacity"]
    max_sites = len(device["grouped_profile"]["layouts"]["ancilla_readout"]["slots"])
    for bank in {event["bank_id"] for _, event, _ in parsed}:
        bank_events = [event for _, event, _ in parsed if event["bank_id"] == bank]
        site_limit=max_sites
        capacity=default_capacity
        if bank=='rigid-mz' and 'rigid_readout' in device:
            from .rigid_readout import rigid_readout_capacity
            capacity=rigid_readout_capacity(device)
            pitch=device['rigid_readout']['site_pitch_um'];zone=device['zones']['measurement']
            site_limit=(float('inf') if zone['x_range_um']==[None,None] else
                        math.prod(round((zone[a+'_range_um'][1]-zone[a+'_range_um'][0])/pitch)+1 for a in ('x','y')))
        if len({event["site_id"] for event in bank_events}) > site_limit:
            errors.append(_issue("READOUT_SITE_CAPACITY", "/entries", f"Bank {bank} declares more than {site_limit} receiver sites."))
        changes = sorted([(event["t_start_us"], 1) for event in bank_events] + [(event["t_end_us"], -1) for event in bank_events])
        active = 0
        for _, delta in changes:
            active += delta
            if capacity is not None and active > capacity:
                errors.append(_issue("READOUT_CAPACITY_EXCEEDED", "/entries", f"Bank {bank} needs {active} concurrent readouts, capacity {capacity}."))
                break
    tol = device["geometry"]["distance_tolerance_um"]
    for n, (_, a, pa) in enumerate(parsed):
        for j, b, pb in parsed[n + 1:]:
            if max(a["t_start_us"], b["t_start_us"]) < min(a["t_end_us"], b["t_end_us"]):
                same_site = (a["bank_id"], a["site_id"]) == (b["bank_id"], b["site_id"])
                if same_site or a["atom_id"] == b["atom_id"] or math.dist(pa, pb) <= tol:
                    errors.append(_issue("READOUT_RESOURCE_CONFLICT", f"/entries/{j}", "Overlapping events share an atom, site, or physical position."))
    return errors
