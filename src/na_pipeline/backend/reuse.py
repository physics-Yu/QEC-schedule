"""T402 proposed qualification helpers, deliberately not a route/result cache.

These helpers do not compile a window, execute one, or replace independent R6
validation. Existing compile_physical has no new arguments or hidden cache.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re


class ReuseContractError(ValueError):
    pass


def route_template_key(template: dict, device: dict, entry_geometry: dict,
                       *, bindings: dict[str, str], policy_version: str) -> str:
    """Bind the whole conservative entry scene, without runtime result state."""
    if not isinstance(policy_version, str) or not policy_version:
        raise ReuseContractError("POLICY_VERSION_REQUIRED")
    if not isinstance(template, dict) or set(template) != {"template_id", "qubits", "body", "metadata"}:
        raise ReuseContractError("IMMUTABLE_TEMPLATE_REQUIRED")
    if not isinstance(entry_geometry, dict) or set(entry_geometry) != {"atoms", "slm_traps", "aod_rows", "aod_columns"}:
        raise ReuseContractError("GEOMETRY_ONLY: results/frames/tokens/epochs belong to the live snapshot")
    atom_fields = {"atom_id", "qubit_id", "position_um", "carrier", "trap_id", "aod_group", "row_id", "column_id"}
    for atom in entry_geometry["atoms"]:
        if not isinstance(atom, dict) or set(atom) != atom_fields:
            raise ReuseContractError("STATIC_ATOM_FIELDS_REQUIRED: project geometry explicitly from runtime state")
    known_qubits = {atom["qubit_id"] for atom in entry_geometry["atoms"]}
    if (not isinstance(bindings, dict) or set(bindings) != set(template["qubits"])
            or any(not isinstance(q, str) for q in bindings.values())
            or not set(bindings.values()) <= known_qubits or len(set(bindings.values())) != len(bindings)):
        raise ReuseContractError("EXACT_DISTINCT_INSTANCE_BINDINGS_REQUIRED")
    for trap in entry_geometry["slm_traps"]:
        if not isinstance(trap, dict) or set(trap) != {"trap_id", "position_um", "zone_id", "occupant"}:
            raise ReuseContractError("STATIC_TRAP_FIELDS_REQUIRED")
    # Axis records remain complete immutable geometric JSON, including empty
    # active lines when future producers define their exact record shape.
    forbidden = {"results", "result_values", "fake_values", "frames", "tokens", "epochs", "acceptance", "validation_report"}
    def check_no_runtime_records(value):
        if isinstance(value, dict):
            if forbidden & value.keys():
                raise ReuseContractError("RUNTIME_STATE_MUST_NOT_BE_CACHED")
            for item in value.values():
                check_no_runtime_records(item)
        elif isinstance(value, list):
            for item in value:
                check_no_runtime_records(item)
    check_no_runtime_records(template)
    check_no_runtime_records(entry_geometry)
    try:
        encoded = json.dumps({"key_schema": "R4RouteKey/0.1.0-proposed", "template": template,
                              "device": device, "entry_geometry": entry_geometry,
                              "bindings": bindings, "policy_version": policy_version}, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReuseContractError("FINITE_JSON_REQUIRED") from exc
    return sha256(encoded).hexdigest()


def check_frontier(request_frontier: dict, current_frontier: dict) -> dict:
    """Reject stale snapshots; passing never grants execution/geometry approval."""
    required = {"run_id", "epoch", "revision", "time_us", "history_sha256"}
    for frontier in (request_frontier, current_frontier):
        if not isinstance(frontier, dict) or set(frontier) != required:
            raise ReuseContractError("FRONTIER_FIELDS_REQUIRED")
        if not isinstance(frontier["run_id"], str) or not frontier["run_id"]:
            raise ReuseContractError("RUN_ID_REQUIRED")
        if any(type(frontier[k]) is not int or frontier[k] < 0 for k in ("epoch", "revision")):
            raise ReuseContractError("NONNEGATIVE_FRONTIER_COUNTER_REQUIRED")
        t = frontier["time_us"]
        if type(t) not in (int, float) or not math.isfinite(t) or t < 0:
            raise ReuseContractError("FRONTIER_TIME_REQUIRED")
        if not isinstance(frontier["history_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", frontier["history_sha256"]):
            raise ReuseContractError("HISTORY_HASH_REQUIRED")
    changed = sorted(k for k in required if request_frontier[k] != current_frontier[k])
    return {"fresh": not changed, "code": "FRONTIER_UNCHANGED" if not changed else "STALE_FRONTIER",
            "changed_fields": changed, "execution_authorized": False,
            "requires": ["R5 atomic commit and resource checks", "R6 independent window qualification"]}
