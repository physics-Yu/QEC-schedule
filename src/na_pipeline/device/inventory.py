"""Finite t=0 resource inventory: patch carriers plus explicit single atoms."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import math

from .model import DeviceModelError, _inside, _point


def _fail(code, path, message):
    raise DeviceModelError([{"code": code, "path": path, "message": message}])


def _strings(record, fields, path):
    if any(type(record[k]) is not str or not record[k].strip() for k in fields):
        _fail("RESOURCE_ID", path, "Resource identities must be nonempty strings.")


def _bind_resource_inventory(device, inventory, patches, placements, atoms, traps, patch_states):
    """Validate before adding anything to the newly built, unpublished state."""
    fields = {"schema_version", "artifact_id", "provenance", "patch_roles", "nonpatch_atoms"}
    if type(inventory) is not dict or set(inventory) != fields:
        _fail("RESOURCE_INVENTORY_FIELDS", "/resource_inventory", "Expected version, artifact, provenance, complete patch roles and nonpatch atoms.")
    try:
        json.dumps(inventory, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError, OverflowError, RecursionError):
        _fail("NON_JSON_VALUE", "/resource_inventory", "Inventory requires finite JSON values and string keys.")
    if inventory["schema_version"] != "initial-resource-inventory/0.1":
        _fail("RESOURCE_INVENTORY_VERSION", "/resource_inventory/schema_version", "Unknown inventory schema.")
    _strings(inventory, ("artifact_id",), "/resource_inventory/artifact_id")
    provenance = inventory["provenance"]
    if type(provenance) is not dict or set(provenance) != {"producer", "fixture", "source_refs"}:
        _fail("RESOURCE_PROVENANCE", "/resource_inventory/provenance", "Explicit producer, fixture flag and source references required.")
    _strings(provenance, ("producer",), "/resource_inventory/provenance")
    if type(provenance["fixture"]) is not bool or type(provenance["source_refs"]) is not list or not provenance["source_refs"] or any(type(s) is not str or not s for s in provenance["source_refs"]):
        _fail("RESOURCE_PROVENANCE", "/resource_inventory/provenance", "Fixture must be boolean and source refs a nonempty string list.")
    roles = inventory["patch_roles"]
    if type(roles) is not dict or set(roles) != set(patches):
        _fail("RESOURCE_PATCH_COVERAGE", "/resource_inventory/patch_roles", "Role declarations must cover exactly the already placed patches.")
    slots = set()
    role_counts = Counter()
    for pid, role in roles.items():
        path = f"/resource_inventory/patch_roles/{pid}"
        if type(role) is not dict or set(role) != {"role", "pool_id", "slot_id"}:
            _fail("RESOURCE_PATCH_ROLE", path, "Expected role/pool_id/slot_id.")
        _strings(role, ("role", "pool_id", "slot_id"), path)
        if role["role"] not in ("algorithm", "factory", "scratch"):
            _fail("RESOURCE_PATCH_ROLE", path, "Patch role must be algorithm, factory or scratch.")
        if role["slot_id"] in slots:
            _fail("RESOURCE_SLOT_ALIAS", path, "One physical resource slot cannot represent two resources.")
        slots.add(role["slot_id"])
        role_counts[role["role"]] += len(patch_states[pid]["atom_ids"])
    nonpatch = inventory["nonpatch_atoms"]
    if type(nonpatch) is not dict or any(type(aid) is not str or not aid for aid in nonpatch):
        _fail("NONPATCH_ATOMS", "/resource_inventory/nonpatch_atoms", "Expected atom ID to explicit single-atom declarations.")
    atom_ids = {a["atom_id"] for a in atoms}
    qubit_ids = {a["qubit_id"] for a in atoms}
    trap_ids = {t["trap_id"] for t in traps}
    occupied = [(a["atom_id"], a["position_um"]) for a in atoms]
    pending_atoms, pending_traps = [], []
    extent = device["patch_geometry"]["cell_extent_um"]
    tolerance = device["geometry"]["distance_tolerance_um"]
    spec_fields = {"qubit_id", "trap_id", "position_um", "aod_group", "role", "pool_id", "slot_id", "basis", "value"}
    for aid, spec in sorted(nonpatch.items()):
        path = f"/resource_inventory/nonpatch_atoms/{aid}"
        if type(spec) is not dict or set(spec) != spec_fields:
            _fail("NONPATCH_ATOM_FIELDS", path, "Single atom needs explicit identities, position, role and Pauli-basis input state.")
        _strings(spec, ("qubit_id", "trap_id", "aod_group", "role", "pool_id", "slot_id", "basis"), path)
        if spec["role"] not in ("probe", "scratch_atom", "raw_magic_carrier"):
            _fail("NONPATCH_RESOURCE_ROLE", path, "A single carrier is not a surface-code patch or ready magic token.")
        if spec["basis"] not in ("Z", "X") or type(spec["value"]) is not int or spec["value"] not in (0, 1):
            _fail("INITIAL_RESOURCE_STATE", path, "Only explicit physical Z/X eigenstates 0/1 are supported; no initial T state.")
        if spec["aod_group"] not in device["aod_groups"]:
            _fail("UNKNOWN_AOD_GROUP", path, "Single atom uses an undeclared AOD group.")
        for value, collection, code in ((aid, atom_ids, "ATOM_ID_ALIAS"), (spec["qubit_id"], qubit_ids, "QUBIT_ID_ALIAS"),
                                         (spec["trap_id"], trap_ids, "TRAP_ID_ALIAS"), (spec["slot_id"], slots, "RESOURCE_SLOT_ALIAS")):
            if value in collection:
                _fail(code, path, "Identity is already bound to another initial carrier or slot.")
            collection.add(value)
        point = _point(spec["position_um"], path + "/position_um")
        zones = [zid for zid, zone in device["zones"].items() if _inside(zone, point)]
        if len(zones) != 1:
            _fail("RESOURCE_OUTSIDE_ZONE", path, "Single-atom site must belong to exactly one declared EZ/MZ region.")
        for other_id, other_position in occupied:
            if math.dist(point, other_position) <= tolerance:
                _fail("RESOURCE_OCCUPIED", path, f"Single-atom site overlaps existing carrier {other_id}.")
        for pid, placement in placements.items():
            x, y = placement["anchor_um"]
            if x <= point[0] < x + extent[0] and y <= point[1] < y + extent[1]:
                _fail("RESOURCE_IN_PATCH_CELL", path, f"Initial single-atom parking overlaps reserved patch cell {pid}.")
        occupied.append((aid, point))
        role_counts[spec["role"]] += 1
        pending_atoms.append({
            "atom_id": aid, "qubit_id": spec["qubit_id"], "trap_id": spec["trap_id"],
            "patch_id": None, "local_id": None, "position_um": list(point), "carrier": "SLM",
            "aod_group": spec["aod_group"], "row_id": None, "column_id": None,
            "resource_role": spec["role"], "pool_id": spec["pool_id"], "resource_slot_id": spec["slot_id"],
            "initial_state": {"kind": "physical_basis", "basis": spec["basis"], "value": spec["value"]},
        })
        pending_traps.append({"trap_id": spec["trap_id"], "position_um": list(point), "zone_id": zones[0], "occupant": aid})
    # All checks completed. Only local unpublished result objects are updated.
    for pid, state in patch_states.items():
        role = roles[pid]
        state.update(resource_role=role["role"], pool_id=role["pool_id"], resource_slot_id=role["slot_id"])
    for atom in atoms:
        role = roles[atom["patch_id"]]
        atom.update(resource_role=role["role"], pool_id=role["pool_id"], resource_slot_id=role["slot_id"])
    atoms.extend(pending_atoms)
    traps.extend(pending_traps)
    counts = {"patch_count": len(patches), "patch_atom_count": len(atoms) - len(nonpatch),
              "nonpatch_atom_count": len(nonpatch), "total_atom_count": len(atoms),
              "resource_slot_count": len(slots), "atoms_by_role": dict(sorted(role_counts.items()))}
    return deepcopy(inventory), counts
