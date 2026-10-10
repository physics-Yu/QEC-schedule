"""Explicit t=0 encoded-state preconditions and placement binding, not simulation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .groups import _preinitialized_profile, grouped_device, group_layout
from .model import DeviceModelError, _inside, _point
from .spec import _finite_number, validate_device


def _error(code, path, message):
    return {"code": code, "path": path, "message": message}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _geometry() -> dict:
    return {
        "schema_version": "patch-geometry/0.1",
        "code_profile": {"code": "rotated_surface", "distance": 3, "convention": "surface17-row-major-x-vertical/1"},
        "allowed_orientations": ["x_vertical_z_horizontal"],
        "local_layout_id": "patch_home", "occupied_bounds_um": [0.0, 0.0, 30.0, 50.0],
        "cell_extent_um": [40.0, 60.0], "suggested_anchor_step_um": [40.0, 60.0],
        "cell_boundary": "half_open", "anchor_zone_id": "storage_entanglement",
        "ports": {
            "data_coupling": {"layout_id": "patch_home", "members": [f"d{i}" for i in range(9)], "anchor_mode": "patch_relative"},
            "ancilla_departure": {"layout_id": "patch_home", "members": [f"{p}{i}" for p in ("x", "z") for i in range(4)], "anchor_mode": "patch_relative"},
            "measurement_receiver": {"layout_id": "ancilla_readout", "members": [f"{p}{i}" for p in ("x", "z") for i in range(4)], "anchor_mode": "global_mz_with_independent_bank_x"},
        },
        "provenance": {"kind": "project_assumption", "calibrated": False,
                       "source_refs": ["ADR-0008@1.0.0", "R1-PREINITIALIZED-IF-001@0.1.0"],
                       "scope": "Local occupied shape and placement cell only; not an Enola placement or hardware qualification."},
    }


def preinitialized_device(*, readout_capacity: int = 8) -> dict:
    device = grouped_device(readout_capacity=readout_capacity)
    device["artifact_id"] = f"device:surface17-preinitialized-v1:readout-{readout_capacity}"
    device["device_id"] = "neutral-atom-preinitialized-engineering-reference"
    device["entry_mode"] = "preinitialized"
    device["provenance"].update(kb_revision="kb-0006", interface_version="IF-HIERARCHICAL-DAG-001/0.1.0",
                                 source_refs=["ADR-0008@1.0.0", "R1-PREINITIALIZED-IF-001@0.1.0"])
    device["grouped_profile"] = _preinitialized_profile()
    device["grouped_profile"]["readout"]["bank_capacity"] = readout_capacity
    device["patch_geometry"] = _geometry()
    device["zones"]["storage_entanglement"]["y_range_um"] = [0.0, 1000.0]
    device["zones"]["measurement"]["y_range_um"] = [1020.0, 1040.0]
    device["parameter_provenance"]["/zones"]["source_refs"] = ["ADR-0008@1.0.0", "R1-PREINITIALIZED-IF-001@0.1.0"]
    return device


def _validate_patch_geometry(device):
    errors = []
    if device.get("entry_mode") != "preinitialized":
        errors.append(_error("ENTRY_MODE", "/entry_mode", "Current profile requires preinitialized t=0 entry."))
    geometry = device.get("patch_geometry")
    reference = _geometry()
    if type(geometry) is not dict or set(geometry) != set(reference):
        return errors + [_error("PATCH_GEOMETRY_FIELDS", "/patch_geometry", "Missing or unsupported geometry fields.")]
    if geometry.get('schema_version') == 'patch-geometry/0.2':
        reference.update(schema_version='patch-geometry/0.2',
                         allowed_orientations=['x_vertical_z_horizontal', 'canonical_rot90'])
        if geometry['cell_extent_um'] != [80., 80.] or geometry['occupied_bounds_um'] != [10., 10., 70., 70.]:
            errors.append(_error('ROTATED_CANONICAL_CELL', '/patch_geometry', 'Quarter-turn profile requires the canonical 80 um square cell.'))
    try:
        json.dumps(geometry, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return errors + [_error("NON_JSON_VALUE", "/patch_geometry", "Geometry requires finite JSON values.")]
    # This published geometry variant has fixed semantic identities. Coordinates
    # can vary only with matching bounds/cells; real anchors are instance inputs.
    for key in ("schema_version", "code_profile", "allowed_orientations", "local_layout_id", "cell_boundary", "anchor_zone_id", "ports"):
        if json.dumps(geometry[key], sort_keys=True) != json.dumps(reference[key], sort_keys=True):
            errors.append(_error("UNSUPPORTED_PATCH_GEOMETRY", f"/patch_geometry/{key}", "Unrecognized code, orientation, port or geometry convention."))
    for key, n in (("occupied_bounds_um", 4), ("cell_extent_um", 2), ("suggested_anchor_step_um", 2)):
        values = geometry[key]
        if type(values) is not list or len(values) != n or any(not _finite_number(v) for v in values):
            errors.append(_error("PATCH_GEOMETRY_NUMBERS", f"/patch_geometry/{key}", "Expected finite numeric geometry array."))
    provenance = geometry["provenance"]
    if type(provenance) is not dict or set(provenance) != set(reference["provenance"]) or provenance.get("kind") != "project_assumption" or provenance.get("calibrated") is not False:
        errors.append(_error("PATCH_PROVENANCE", "/patch_geometry/provenance", "Geometry needs explicit uncalibrated project assumptions."))
    elif type(provenance["scope"]) is not str or not provenance["scope"] or type(provenance["source_refs"]) is not list or not provenance["source_refs"] or any(type(x) is not str or not x for x in provenance["source_refs"]):
        errors.append(_error("PATCH_PROVENANCE", "/patch_geometry/provenance", "Source references and scope must be nonempty."))
    if errors:
        return errors
    slots = device["grouped_profile"]["layouts"]["patch_home"]["slots"]
    xs = [s["position_um"][0] for s in slots.values()]
    ys = [s["position_um"][1] for s in slots.values()]
    actual = [min(xs), min(ys), max(xs), max(ys)]
    if geometry["occupied_bounds_um"] != actual:
        errors.append(_error("PATCH_BOUNDS", "/patch_geometry/occupied_bounds_um", "Bounds must enclose and equal the declared local occupied shape."))
    extent = geometry["cell_extent_um"]
    if min(actual[:2]) < 0 or extent[0] <= actual[2] or extent[1] <= actual[3] or any(v <= 0 for v in geometry["suggested_anchor_step_um"]):
        errors.append(_error("PATCH_CELL", "/patch_geometry/cell_extent_um", "Positive half-open cell must contain every local slot."))
    return errors


def _require_current(device):
    errors = validate_device(device)
    if not errors and device.get("entry_mode") != "preinitialized":
        errors.append(_error("ENTRY_MODE", "/entry_mode", "Explicit preinitialized device required; legacy fixtures are not current entry."))
    if errors:
        raise DeviceModelError(errors)


def patch_geometry(device: dict) -> dict:
    _require_current(device)
    return deepcopy(device["patch_geometry"])


def build_preinitialized_state(device: dict, patches: dict, placements: dict, *, placement_ref: dict, resource_inventory: dict | None = None) -> dict:
    """Materialize a new run's t=0 input only. No movement/prepare is executed.

    Encoded logical states are explicit declared preconditions, not inferred
    from product states, fake measurements, previous runs, or magic inventory.
    """
    _require_current(device)
    if type(patches) is not dict or not patches or any(type(k) is not str or not k for k in patches):
        raise DeviceModelError([_error("PATCH_SPECS", "/patches", "Nonempty patch ID to initial encoded-state declarations required.")])
    if type(placements) is not dict or set(placements) != set(patches):
        raise DeviceModelError([_error("PLACEMENT_COVERAGE", "/placements", "Placement must cover exactly all declared patches.")])
    if type(placement_ref) is not dict or set(placement_ref) != {"artifact_id", "producer", "fixture"} or any(type(placement_ref[k]) is not str or not placement_ref[k] for k in ("artifact_id", "producer")) or type(placement_ref["fixture"]) is not bool:
        raise DeviceModelError([_error("PLACEMENT_REFERENCE", "/placement_ref", "Explicit artifact_id/producer/fixture reference required.")])
    anchors = {}
    for pid, declaration in patches.items():
        if type(declaration) is not dict or set(declaration) != {"aod_group", "basis", "value"}:
            raise DeviceModelError([_error("INITIAL_STATE_DECLARATION", f"/patches/{pid}", "Explicit AOD group and encoded Pauli-basis eigenstate required; magic inventory is not an entry state.")])
        if type(declaration["aod_group"]) is not str or declaration["aod_group"] not in device["aod_groups"]:
            raise DeviceModelError([_error("UNKNOWN_AOD_GROUP", f"/patches/{pid}/aod_group", "Undeclared AOD resource.")])
        if declaration["basis"] not in ("Z", "X") or type(declaration["value"]) is not int or declaration["value"] not in (0, 1):
            raise DeviceModelError([_error("INITIAL_LOGICAL_STATE", f"/patches/{pid}", "Only explicitly declared encoded Z/X eigenstates 0/1 are supported; not T states.")])
        placement = placements[pid]
        if type(placement) is not dict or set(placement) != {"anchor_um", "orientation"}:
            raise DeviceModelError([_error("PLACEMENT_FIELDS", f"/placements/{pid}", "Expected anchor_um and orientation, not runtime relocation actions.")])
        if placement["orientation"] not in device["patch_geometry"]["allowed_orientations"]:
            raise DeviceModelError([_error("PATCH_ORIENTATION", f"/placements/{pid}/orientation", "No qualified rotation/mirroring is declared.")])
        anchors[pid] = _point(placement["anchor_um"], f"/placements/{pid}/anchor_um")
    cx, cy = device["patch_geometry"]["cell_extent_um"]
    ids = sorted(patches)
    for n, pid in enumerate(ids):
        x, y = anchors[pid]
        for other in ids[n + 1:]:
            ox, oy = anchors[other]
            if max(x, ox) < min(x + cx, ox + cx) and max(y, oy) < min(y + cy, oy + cy):
                raise DeviceModelError([_error("PATCH_FOOTPRINT_OVERLAP", f"/placements/{pid}", f"Placement cell overlaps patch {other}.")])
    atoms, traps, patch_states = [], [], {}
    geometry = device["patch_geometry"]
    for pid in ids:
        declaration = patches[pid]
        layout = group_layout(device, "patch_home", offset_um=anchors[pid])
        if placements[pid]['orientation'] == 'canonical_rot90':
            ax, ay = anchors[pid]
            for local in layout['slots'].values():
                x, y = local['position_um']
                local['position_um'] = [ax + y - ay, ay + 80. - (x - ax)]
        block_atoms, data_ids, auxiliary_ids = [], [], []
        for slot, local in layout["slots"].items():
            aid, qid, tid = f"atom:{pid}/{slot}", f"{pid}/{slot}", f"slm:{pid}/{slot}"
            is_data = slot.startswith("d")
            state = {"kind": "encoded_member", "patch_id": pid} if is_data else {"kind": "physical_basis", "basis": "Z", "value": 0}
            atoms.append({"atom_id": aid, "qubit_id": qid, "patch_id": pid, "local_id": slot,
                          "position_um": list(local["position_um"]), "carrier": "SLM", "trap_id": tid,
                          "aod_group": declaration["aod_group"], "row_id": None, "column_id": None, "initial_state": state})
            traps.append({"trap_id": tid, "position_um": list(local["position_um"]), "zone_id": "storage_entanglement", "occupant": aid})
            block_atoms.append(aid)
            (data_ids if is_data else auxiliary_ids).append(aid)
        patch_states[pid] = {
            "logical_id": pid, "code_profile": deepcopy(geometry["code_profile"]),
            "anchor_um": list(anchors[pid]), "orientation": placements[pid]["orientation"],
            "aod_group": declaration["aod_group"], "atom_ids": block_atoms,
            "data_atom_ids": data_ids, "auxiliary_atom_ids": auxiliary_ids,
            "initial_logical_state": {"kind": "encoded_pauli_eigenstate", "basis": declaration["basis"], "value": declaration["value"], "origin": "declared_precondition"},
            "preparation_boundary": "Encoded input is assumed at t=0, not dynamically prepared or verified here.",
            "lifecycle": "prepared", "layout_profile": "patch_home", "magic_resource_ready": False,
        }
    entry_spec = {"patches": deepcopy(patches), "placements": deepcopy(placements), "placement_ref": deepcopy(placement_ref)}
    inventory, resource_counts = None, None
    if resource_inventory is not None:
        from .inventory import _bind_resource_inventory
        inventory, resource_counts = _bind_resource_inventory(device, resource_inventory, patches, placements, atoms, traps, patch_states)
        entry_spec["resource_inventory"] = deepcopy(inventory)
    device_hash = _hash(device)
    result = {
        "schema_version": "preinitialized-state/0.1", "artifact_id": "entry:" + _hash({"entry_spec": entry_spec, "device_hash": device_hash})[:24],
        "provenance": {"producer": "na_pipeline.device.initial/0.1.0", "kb_revision": "kb-0006", "source_refs": ["ADR-0008@1.0.0", "R1-PREINITIALIZED-IF-001@0.1.0"], "fixture": placement_ref["fixture"], "preparation": "declared_precondition_not_quantum_execution"},
        "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
        "entry_mode": "preinitialized", "t_start_us": 0.0, "device_ref": device["artifact_id"], "device_hash": device_hash,
        "placement_ref": deepcopy(placement_ref), "placement_binding_sha256": _hash(placements), "entry_spec": entry_spec,
        "patches": patch_states, "atoms": atoms, "slm_traps": traps, "aod_rows": [], "aod_columns": [],
        "startup_actions": [], "startup_duration_us": 0.0, "results": {}, "ready_magic_tokens": [],
    }
    if inventory is not None:
        result["resource_inventory"] = inventory
        result["resource_inventory_sha256"] = _hash(inventory)
        result["resource_counts"] = resource_counts
        result["provenance"]["producer"] = "na_pipeline.device.initial/0.2.0"
        result["provenance"]["fixture"] = placement_ref["fixture"] or inventory["provenance"]["fixture"]
    return result


def validate_preinitialized_state(state: dict, device: dict) -> list[dict]:
    """Reconstruct the declared t=0 mapping, rejecting later silent edits."""
    if type(state) is not dict:
        return [_error("INITIAL_STATE_TYPE", "/", "Expected an InitialState object.")]
    try:
        json.dumps(state, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return [_error("NON_JSON_VALUE", "/", "State requires finite JSON values.")]
    entry = state.get("entry_spec")
    required = {"patches", "placements", "placement_ref"}
    if type(entry) is not dict or set(entry) not in (required, required | {"resource_inventory"}):
        return [_error("INITIAL_ENTRY_SPEC", "/entry_spec", "Original declarations and placement binding are required.")]
    try:
        expected = build_preinitialized_state(device, **entry)
    except DeviceModelError as exc:
        return exc.errors
    errors = []
    if set(state) != set(expected):
        errors.append(_error("INITIAL_STATE_FIELDS", "/", "Missing or unsupported state fields, including unmodeled resource inventory."))
    for key in expected.keys() & state.keys():
        if json.dumps(state[key], sort_keys=True) != json.dumps(expected[key], sort_keys=True):
            errors.append(_error("INITIAL_STATE_MISMATCH", f"/{key}", "State must match the immutable t=0 declarations/device/placement; subsequent changes need actual actions."))
    return errors
