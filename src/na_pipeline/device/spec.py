"""Versioned engineering device profile; no quantum state or runtime state."""

from __future__ import annotations

import json
import math
from typing import Any

SCHEMA_VERSION = "DeviceSpec/0.2.0-draft"
DEVICE_VERSION = "0.1.0"
_NATIVE_1Q = ["H", "X", "Y", "Z", "S", "SDG", "T", "TDG", "RX", "RY", "RZ"]


def default_device() -> dict:
    """Return a new JSON tree. All operative numbers are project assumptions."""
    device = {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": "device:engineering-reference-v1",
        "device_id": "neutral-atom-engineering-reference",
        "device_version": DEVICE_VERSION,
        "producer_version": "na_pipeline.device/0.1.0",
        "provenance": {
            "owner": "R1", "kb_revision": "kb-0003",
            "interface_version": "IF-MVP-001/0.2.0-draft",
            "source_refs": ["ADR-0003@1.0.0", "R8-PLATFORM-001@0.8.0"],
            "evidence_boundary": "Engineering model, not calibrated hardware or quantum sampling.",
        },
        "execution_kind": "compile_plan",
        "quantum_state_simulated": False,
        "hardware_executed": False,
        "loss_enabled": False,
        "units": {"time": "us", "length": "um", "angle": "rad"},
        "timings_us": {
            "gate_1q": 1.0, "cz": 1.0, "pickup": 200.0, "drop": 200.0,
            "measure": 100.0, "reset": 10.0, "result_latency": 5.0,
            "classical": 1.0, "feedback_latency": 1.0,
        },
        "movement": {
            "model": "parallel_axes_linear", "speed_um_per_us": 1.0,
            "acceleration_model": "ignored", "identity_preserved": True,
        },
        "geometry": {
            "initial_spacing_um": 10.0, "gate_pair_distance_um": 2.0,
            "distance_tolerance_um": 1e-6, "pair_metric": "euclidean",
            "pair_rule": "distance_equal_with_tolerance",
            "atom_model": "point", "extra_pair_center_exclusion": False,
        },
        "zones": {
            "storage_entanglement": {
                "x_range_um": [None, None], "y_range_um": [0.0, 1000.0],
                "boundary": "closed",
            },
            "measurement": {
                "x_range_um": [None, None], "y_range_um": [1020.0, 1040.0],
                "boundary": "closed",
            },
        },
        "broadcast": {
            "zone_id": "storage_entanglement", "resource_id": "rydberg:global",
            "gate": "CZ", "all_geometric_pairs": True,
            "spectator_response": "unevaluated", "geometry_stationary_during_pulse": True,
        },
        "aod_groups": {
            name: {
                "resource_id": f"aod:{name}", "max_rows": None, "max_columns": None,
                "shared_rows": True, "shared_columns": True, "non_crossing": True,
            } for name in ("data", "magic")
        },
        "slm": {"resource_id": "slm:static", "static_traps": True},
        "operations": {
            "native_1q_gates": list(_NATIVE_1Q), "native_2q_gates": ["CZ"],
            "measurement_bases": ["Z"], "reset_target": 0,
            "action_kinds": ["pickup", "move", "drop", "gate", "measure", "reset", "wait", "classical"],
            "parameter_units": "rad",
        },
        "concurrency": {
            "atom_exclusive": True, "trap_exclusive": True,
            "aod_lock_scope": "affected_rows_and_columns",
            "independent_aod_parallel": True, "independent_1q_parallel": True,
            "independent_measure_parallel": True, "independent_reset_parallel": True,
            "independent_transfer_parallel": True,
            "global_motion_lock": False, "global_measure_lock": False,
            "global_1q_lock": False,
        },
        "measurement": {
            "zone_id": "measurement", "basis": "Z", "preserves_atom": True,
            "result_ready_rule": "end_plus_result_latency",
        },
        "reset": {
            "target": 0, "preserves_atom": True, "requires_present_atom": True,
            "allowed_zone_ids": ["storage_entanglement", "measurement"],
        },
        "illumination": {
            "unit": "one_per_broadcast", "scope": "all_atoms_in_broadcast_zone",
            "include_spectators": True, "required_output": "per_atom_cumulative_count",
            "per_event_log_required": False, "noise_model_ref": None,
            "fidelity_status": "unevaluated",
        },
        "physics": {
            "species": "Rb87", "storage_encoding": "hyperfine_ground_state",
            "coherence_reference": {
                "effective_time_range_us": [1_000_000.0, 2_000_000.0],
                "kind": "literature_reference", "source_ref": "R8-FACT-008@0.1.0",
                "conditions": "S7 Rb87 hyperfine clock states, echo/decoupling and motion sequence.",
                "used_for_noise": False, "calibrated": False,
            },
            "t2star_us": None, "gate_error_rate": None, "loss_rate": None,
            "unknown_parameter_status": "unknown", "noise_evaluation": "unevaluated",
        },
        "parameter_provenance": {},
    }
    refs = {
        "/movement": ["R8-PLATFORM-001@0.8.0:UA-02/03/04", "R1-IF-01@0.1.0"],
        "/geometry": ["R8-PLATFORM-001@0.8.0:UA-05/09", "R1-IF-01@0.1.0"],
        "/zones": ["R8-PLATFORM-001@0.8.0:UA-07/19", "R1-IF-01@0.1.0"],
        "/broadcast": ["R8-PLATFORM-001@0.8.0:UA-07/11"],
        "/slm": ["R8-PLATFORM-001@0.8.0:UA-02"],
        "/operations": ["R8-PLATFORM-001@0.8.0:UA-06/10/22", "R1-IF-01@0.1.0"],
        "/concurrency": ["R8-PLATFORM-001@0.8.0:UA-03/10/19"],
        "/measurement": ["R8-PLATFORM-001@0.8.0:UA-06/19/22", "R1-IF-01@0.1.0"],
        "/reset": ["R8-PLATFORM-001@0.8.0:UA-06/19", "R1-IF-01@0.1.0"],
        "/illumination": ["R8-PLATFORM-001@0.8.0:UA-11/12"],
        "/physics/species": ["R8-PLATFORM-001@0.8.0:UA-08", "R1-IF-01@0.1.0"],
        "/physics/storage_encoding": ["R8-FACT-001@0.1.0", "R1-IF-01@0.1.0"],
    }
    refs.update({f"/timings_us/{key}": ["R1-IF-01@0.1.0", "R1-PARAM-001@0.1.0"]
                 for key in device["timings_us"]})
    refs.update({f"/aod_groups/{name}": ["R8-PLATFORM-001@0.8.0:UA-03"]
                 for name in device["aod_groups"]})
    for path, sources in refs.items():
        device["parameter_provenance"][path] = {
            "kind": "project_assumption", "source_refs": sources,
            "scope": "First loss-free fake compile/schedule profile; not calibrated hardware.",
            "calibrated": False,
        }
    for path, kind, sources in [
        ("/physics/coherence_reference", "literature_reference", ["R8-FACT-008@0.1.0"]),
        ("/physics/t2star_us", "unknown", ["R1-PARAM-001@0.1.0"]),
        ("/physics/gate_error_rate", "unknown", ["R1-PARAM-001@0.1.0"]),
        ("/physics/loss_rate", "unknown", ["R1-PARAM-001@0.1.0"]),
    ]:
        device["parameter_provenance"][path] = {
            "kind": kind, "source_refs": sources, "calibrated": False,
            "scope": "Conditional reference only; no noise, fidelity or hardware claim.",
        }
    return device


def _finite_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _validate_base_device(device: Any) -> list[dict]:
    """Validate the supported profile, reporting paths without mutating input.

    Structural validity does not validate a schedule, a trajectory or hardware.
    Unsupported model flags fail closed; numerical engineering values may vary.
    """
    errors: list[dict] = []

    def pointer(path: str, key: str) -> str:
        return f"{path}/{key.replace('~', '~0').replace('/', '~1')}"

    def error(code: str, path: str, message: str) -> None:
        errors.append({"code": code, "path": path or "/", "message": message})

    reference = default_device()
    if type(device) is not dict:
        return [{"code": "INVALID_TYPE", "path": "/", "message": "DeviceSpec must be an object."}]
    try:
        json.dumps(device, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return [{"code": "NON_JSON_VALUE", "path": "/", "message": "Finite JSON values are required."}]

    def shape(actual: Any, expected: Any, path: str) -> None:
        if type(expected) is dict:
            if type(actual) is not dict:
                error("INVALID_TYPE", path, "Expected object.")
                return
            for key in expected:
                if key not in actual:
                    error("MISSING_FIELD", pointer(path, key), "Required field is absent.")
            if path not in ("/aod_groups", "/parameter_provenance"):
                for key in actual:
                    if key not in expected:
                        error("UNSUPPORTED_FIELD", pointer(path, str(key)), "Undeclared field is not supported.")
            for key, value in actual.items():
                if type(key) is not str or not key:
                    error("INVALID_KEY", path, "Object keys must be nonempty strings.")
                    continue
                if path == "/aod_groups":
                    if "/" in key or "~" in key:
                        error("INVALID_ID", f"{path}/{key}", "AOD group IDs cannot contain / or ~.")
                    shape(value, reference["aod_groups"]["data"], f"{path}/{key}")
                elif path == "/parameter_provenance":
                    shape(value, reference["parameter_provenance"]["/movement"], pointer(path, key))
                elif key in expected:
                    shape(value, expected[key], f"{path}/{key}")
        elif type(expected) is list:
            if type(actual) is not list:
                error("INVALID_TYPE", path, "Expected array.")
            elif path.endswith(("x_range_um", "y_range_um", "effective_time_range_us")):
                if len(actual) != 2:
                    error("INVALID_RANGE", path, "Range must have two endpoints.")
                else:
                    for i, value in enumerate(actual):
                        if value is None and not path.endswith("effective_time_range_us"):
                            continue
                        if not _finite_number(value):
                            error("INVALID_TYPE", f"{path}/{i}", "Expected finite endpoint or unbounded null.")
            elif not actual or any(type(value) is not str or not value for value in actual):
                error("INVALID_LIST", path, "Expected a nonempty array of nonempty strings.")
            elif len(actual) != len(set(actual)):
                error("DUPLICATE_VALUE", path, "Repeated list values are not allowed.")
        elif type(expected) is bool:
            if type(actual) is not bool:
                error("INVALID_TYPE", path, "Expected boolean.")
            elif actual != expected:
                error("UNSUPPORTED_MODEL", path, "Flag is outside this profile's supported model.")
        elif expected is None:
            if actual is not None:
                error("UNSUPPORTED_MODEL", path, "Must remain null (unbounded or explicitly unevaluated).")
        elif type(expected) in (int, float):
            if not _finite_number(actual):
                error("INVALID_TYPE", path, "Expected finite number; booleans are not numbers.")
        elif type(actual) is not str or not actual.strip():
            error("INVALID_TYPE", path, "Expected nonempty string.")

    shape(device, reference, "")
    # Cross-field checks use a complete well-typed tree only.
    if errors:
        return errors

    def fixed(path: str, actual: Any, expected: Any) -> None:
        if actual != expected:
            error("UNSUPPORTED_MODEL", path, f"Supported value: {expected!r}.")

    fixed("/schema_version", device["schema_version"], SCHEMA_VERSION)
    fixed("/device_version", device["device_version"], DEVICE_VERSION)
    fixed("/execution_kind", device["execution_kind"], "compile_plan")
    for section, keys in {
        "units": ["time", "length", "angle"],
        "movement": ["model", "acceleration_model"],
        "geometry": ["pair_metric", "pair_rule", "atom_model"],
        "broadcast": ["zone_id", "gate", "spectator_response"],
        "operations": ["reset_target", "parameter_units"],
        "concurrency": ["aod_lock_scope"],
        "measurement": ["zone_id", "basis", "result_ready_rule"],
        "reset": ["target"],
        "illumination": ["unit", "scope", "required_output", "fidelity_status"],
        "physics": ["species", "storage_encoding", "unknown_parameter_status", "noise_evaluation"],
    }.items():
        for key in keys:
            fixed(f"/{section}/{key}", device[section][key], reference[section][key])
    fixed("/physics/coherence_reference/kind", device["physics"]["coherence_reference"]["kind"], "literature_reference")
    for key, value in device["timings_us"].items():
        if value <= 0:
            error("NON_POSITIVE_PARAMETER", f"/timings_us/{key}", "Operation durations and latencies must be positive.")
    for path, value in [("/movement/speed_um_per_us", device["movement"]["speed_um_per_us"])] + [
        (f"/geometry/{key}", device["geometry"][key])
        for key in ("initial_spacing_um", "gate_pair_distance_um", "distance_tolerance_um")
    ]:
        if value <= 0:
            error("NON_POSITIVE_PARAMETER", path, "Expected a positive model parameter.")
    if device["geometry"]["distance_tolerance_um"] >= device["geometry"]["gate_pair_distance_um"]:
        error("INVALID_TOLERANCE", "/geometry/distance_tolerance_um", "Tolerance must be smaller than the gate distance.")
    for zone_id, zone in device["zones"].items():
        fixed(f"/zones/{zone_id}/boundary", zone["boundary"], "closed")
        for axis in ("x", "y"):
            lower, upper = zone[f"{axis}_range_um"]
            if lower is not None and upper is not None and lower >= upper:
                error("INVALID_RANGE", f"/zones/{zone_id}/{axis}_range_um", "Finite lower bound must be below upper bound.")
    fixed("/zones/storage_entanglement/x_range_um", device["zones"]["storage_entanglement"]["x_range_um"], [None, None])
    if any(value is None for value in device["zones"]["storage_entanglement"]["y_range_um"]):
        error("INVALID_RANGE", "/zones/storage_entanglement/y_range_um", "Broadcast is a finite-width strip infinite along x.")
    native = device["operations"]["native_1q_gates"]
    if not set(native) <= set(_NATIVE_1Q):
        error("UNSUPPORTED_GATE", "/operations/native_1q_gates", "An undeclared native gate was requested.")
    for key in ("native_2q_gates", "measurement_bases", "action_kinds"):
        if key == "action_kinds" and device["operations"][key] == reference["operations"][key] + ["rebind"]:
            continue
        fixed(f"/operations/{key}", device["operations"][key], reference["operations"][key])
    fixed("/reset/allowed_zone_ids", device["reset"]["allowed_zone_ids"], reference["reset"]["allowed_zone_ids"])

    resource_ids = [device["slm"]["resource_id"], device["broadcast"]["resource_id"]]
    resource_ids.extend(group["resource_id"] for group in device["aod_groups"].values())
    if len(set(resource_ids)) != len(resource_ids):
        error("DUPLICATE_RESOURCE", "/aod_groups", "SLM, broadcast and every AOD group need distinct resource IDs.")
    coherence = device["physics"]["coherence_reference"]["effective_time_range_us"]
    if coherence[0] <= 0 or coherence[0] > coherence[1]:
        error("INVALID_RANGE", "/physics/coherence_reference/effective_time_range_us", "Coherence reference needs positive ordered endpoints.")
    provenance = device["parameter_provenance"]
    for group_id in device["aod_groups"]:
        if f"/aod_groups/{group_id}" not in provenance:
            error("MISSING_PROVENANCE", pointer("/parameter_provenance", f"/aod_groups/{group_id}"), "Additional AOD groups need source metadata.")
    for path, record in provenance.items():
        value: Any = device
        if not path.startswith("/") or path.startswith("/parameter_provenance"):
            error("INVALID_PROVENANCE_PATH", "/parameter_provenance", f"Invalid source pointer: {path}.")
            continue
        try:
            for token in path[1:].split("/"):
                value = value[token.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError, IndexError):
            error("INVALID_PROVENANCE_PATH", "/parameter_provenance", f"Unknown source pointer: {path}.")
            continue
        expected_kind = reference["parameter_provenance"].get(path, {"kind": "project_assumption"})["kind"]
        if record["kind"] != expected_kind:
            error("PROVENANCE_KIND", pointer("/parameter_provenance", path), f"Expected {expected_kind}; this profile does not claim calibration.")
    return errors


def validate_device(device: Any) -> list[dict]:
    """Validate the legacy profile and an explicitly present grouped extension."""
    if type(device) is not dict or "grouped_profile" not in device:
        return _validate_base_device(device)
    base = {key: value for key, value in device.items() if key not in ("grouped_profile", "patch_geometry", "entry_mode", "rigid_readout")}
    errors = _validate_base_device(base)
    if errors:
        return errors
    if 'rigid_readout' in device:
        from .rigid_readout import validate_rigid_readout_profile
        errors=validate_rigid_readout_profile(device)
        if errors:return errors
    from .groups import validate_grouped_profile
    errors = validate_grouped_profile(device)
    if errors:
        return errors
    current = device["grouped_profile"]["schema_version"] == "grouped-device-profile/0.2"
    if current:
        from .initial import _validate_patch_geometry
        return _validate_patch_geometry(device)
    if "entry_mode" in device or "patch_geometry" in device:
        return [{"code": "PROFILE_MISMATCH", "path": "/entry_mode", "message": "Preinitialized entry requires grouped-device-profile/0.2."}]
    return []
