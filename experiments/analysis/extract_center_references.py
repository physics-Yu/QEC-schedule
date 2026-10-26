"""Extract compact macro costs by reading historical saved JSON, never replaying.

This one-time preparation reads existing singleton profiles and matching saved
joint trace dictionaries to count addressed atoms. It does not decode Atom IR,
update atom state, call any compiler, or sample probabilities. Runtime consumers
only need the resulting compact bundle, not these historical artifact folders.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from math import isclose
from pathlib import Path
from typing import Any

from modules.codes.rotated_surface.center_costs import (
    REFERENCE_SCHEMA,
    reference_digest,
)

_CATEGORY = {
    "Reset": ("reset", "local"),
    "Rotation": ("gate", "local"),
    "CZPulse": ("gate", "rydberg"),
    "Load": ("transfer", "aod"),
    "Store": ("transfer", "aod"),
    "Move": ("movement", "aod"),
    "Measure": ("measurement", "camera"),
}


def _read(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    return json.loads(data), sha256(data).hexdigest()


def _near(a: float, b: float) -> bool:
    return isclose(a, b, rel_tol=1e-10, abs_tol=1e-7)


def _mark_travel(segments: list[dict[str, Any]], component: str) -> None:
    if component == "transversal_cnot":
        movement = [s for s in segments if s["category"] == "movement"]
        if len(movement) != 2:
            raise ValueError("CNOT_REFERENCE_REQUIRES_TWO_MOVEMENT_LEGS")
        for segment in movement:
            segment["travel_kind"] = "cnot"
        return
    for index, segment in enumerate(segments):
        if segment["category"] != "measurement":
            continue
        group = segments[index - 2 : index + 3]
        if index < 2 or [s["category"] for s in group] != [
            "transfer",
            "movement",
            "measurement",
            "movement",
            "transfer",
        ]:
            raise ValueError("AMBIGUOUS_READOUT_REFERENCE_LEGS")
        if any(s["atom_count"] != segment["atom_count"] for s in group):
            raise ValueError("READOUT_REFERENCE_CARRIER_COUNTS_DIFFER")
        segments[index - 1]["travel_kind"] = "readout"
        segments[index + 1]["travel_kind"] = "readout"


def _extract_trace(
    group: dict[str, Any], trace: dict[str, Any], entry: dict[str, Any], component: str
) -> dict[str, Any]:
    if trace["validation"]["ok"] is not True or group["validation_ok"] is not True:
        raise ValueError("REFERENCE_PHYSICAL_VALIDATION_MISSING")
    if reference_digest(trace) != group["trace_sha256"]:
        raise ValueError("REFERENCE_TRACE_HASH_MISMATCH")
    phases = entry["phase_durations_us"]
    steps = trace["program"]["steps"]
    if len(steps) != len(phases):
        raise ValueError("REFERENCE_STEP_PHASE_COUNT_MISMATCH")
    nodes = {n["id"]: n for n in trace["dag"]["nodes"]}
    wire_atoms = trace["entry_state"]["qubit_to_atom"]
    moves = [
        move for b in group["schedule"]["transport_batches"] for move in b["moves"]
    ]
    pulses = group["schedule"]["cz_pulses"]
    segments = []
    clock = 0.0
    for phase, step in zip(phases, steps, strict=True):
        actions = step["actions"]
        kinds = {action["kind"] for action in actions}
        if len(kinds) != 1:
            raise ValueError("REFERENCE_PHASE_HAS_MIXED_ACTION_KINDS")
        kind = next(iter(kinds))
        category, resource = _CATEGORY[kind]
        if any(not _near(action["duration_us"], phase) for action in actions):
            raise ValueError("REFERENCE_PHASE_DURATION_MISMATCH")
        atoms: set[int] = set()
        source_ids: set[int] = set()
        for action in actions:
            source_ids.update(action["source_ids"])
            if kind in ("Reset", "Rotation"):
                atoms.update(action["atoms"])
            elif kind in ("Load", "Store"):
                atoms.update(binding[0] for binding in action["bindings"])
            elif kind == "Move":
                atoms.update(target[0] for target in action["targets"])
            elif kind == "Measure":
                atoms.update(result[0] for result in action["results"])
            elif kind == "CZPulse":
                atoms.update(
                    wire_atoms[q]
                    for identity in action["source_ids"]
                    for q in nodes[identity]["qubits"]
                )
        counts = Counter(nodes[identity]["name"] for identity in source_ids)
        distance = 0.0
        if kind == "Move":
            selected = [
                m
                for m in moves
                if _near(m["start_us"], clock) and _near(m["end_us"], clock + phase)
            ]
            if len(selected) != 1:
                raise ValueError("REFERENCE_MOVEMENT_SUMMARY_AMBIGUOUS")
            distance = selected[0]["total_atom_distance_um"]
        illuminated = None
        if kind == "CZPulse":
            selected = [
                p
                for p in pulses
                if _near(p["start_us"], clock) and _near(p["end_us"], clock + phase)
            ]
            if len(selected) != 1:
                raise ValueError("REFERENCE_CZ_SUMMARY_AMBIGUOUS")
            illuminated = selected[0]["illuminated_atom_count"]
        segments.append(
            {
                "duration_us": phase,
                "category": category,
                "resource": resource,
                "operation_type": kind,
                "atom_count": len(atoms),
                "action_count": len(actions),
                "movement_distance_atom_um": distance,
                "primitive_counts": dict(counts),
                "travel_kind": "local" if kind == "Move" else "none",
                "reference_illuminated_atom_count": illuminated,
                "basis": "saved_intrinsic_reference",
            }
        )
        clock += phase
    _mark_travel(segments, component)
    aggregate: Counter[str] = Counter()
    for segment in segments:
        aggregate.update(segment["primitive_counts"])
    if dict(aggregate) != entry["primitive_counts"]:
        raise ValueError("REFERENCE_PRIMITIVE_COUNTS_MISMATCH")
    if not _near(
        sum(s["movement_distance_atom_um"] for s in segments),
        entry["movement_distance_atom_um"],
    ):
        raise ValueError("REFERENCE_MOVEMENT_DISTANCE_MISMATCH")
    return {"segments": segments, "measurement_phases": entry["measurement_phases"]}


def _slice_round(reference: dict[str, Any], distance: int) -> dict[str, Any]:
    segments = reference["segments"]
    measurements = [i for i, s in enumerate(segments) if s["category"] == "measurement"]
    if len(measurements) < 2:
        raise ValueError("SE_REFERENCE_REQUIRES_REPEATED_ROUNDS")
    start, stop = measurements[0] + 3, measurements[1] + 3
    selected = deepcopy(segments[start:stop])
    phases = [
        [i - start, latency]
        for i, latency in reference["measurement_phases"]
        if start <= i < stop
    ]
    if (
        len(phases) != distance * distance - 1
        or selected[0]["operation_type"] != "Reset"
    ):
        raise ValueError("SE_ROUND_REFERENCE_MEASUREMENTS_MISMATCH")
    return {
        "segments": selected,
        "measurement_phases": phases,
        "provenance": {
            **reference["provenance"],
            "derivation": "second complete ordinary SE round",
            "phase_slice": [start, stop],
        },
    }


def _initialization(
    entry: dict[str, Any], se: dict[str, Any], distance: int
) -> dict[str, Any]:
    segments = []
    for index, kind in enumerate(("Reset", "Rotation", "Rotation")):
        old = entry["cost_segments"][index]
        segments.append(
            {
                "duration_us": entry["phase_durations_us"][index],
                "category": old["category"],
                "resource": old["resource"],
                "operation_type": kind,
                "atom_count": distance * distance,
                "action_count": distance * distance,
                "movement_distance_atom_um": 0.0,
                "primitive_counts": {("reset", "ry", "rx")[index]: distance * distance},
                "travel_kind": "none",
                "reference_illuminated_atom_count": None,
                "basis": "saved_intrinsic_reference",
            }
        )
    segments.extend(deepcopy(se["segments"]))
    if len(segments) != len(entry["phase_durations_us"]) or any(
        not _near(s["duration_us"], duration)
        for s, duration in zip(segments, entry["phase_durations_us"], strict=True)
    ):
        raise ValueError("INITIALIZATION_SE_DECOMPOSITION_MISMATCH")
    counts: Counter[str] = Counter()
    for segment in segments:
        counts.update(segment["primitive_counts"])
    if dict(counts) != entry["primitive_counts"]:
        raise ValueError("INITIALIZATION_PRIMITIVE_DECOMPOSITION_MISMATCH")
    return {
        "segments": segments,
        "measurement_phases": entry["measurement_phases"],
        "provenance": {
            **se["provenance"],
            "derivation": "saved initialize_plus data reset and H prefix plus verified SE suffix",
        },
    }


def extract_references(artifact_root: Path) -> dict[str, Any]:
    """Build d3/5/7 macro records from existing matching singleton artifacts."""
    distances = {}
    source_files = {}
    noise_params = None
    components = (
        "raw_t_postselection",
        "raw_t_postselection/canonicalize",
        "logical_mz",
        "logical_mx",
        "logical_x",
        "logical_s",
        "transversal_cnot",
    )
    for distance in (3, 5, 7):
        singleton_path = (
            artifact_root
            / f"generic-factory-20261024/profiles/d{distance}-n1/profile.json"
        )
        singleton, singleton_hash = _read(singleton_path)
        root = artifact_root / f"joint-factory-cohort-20261024/d{distance}-n1"
        profile, profile_hash = _read(root / "profile.json")
        source_files[str(singleton_path.relative_to(artifact_root))] = singleton_hash
        source_files[str((root / "profile.json").relative_to(artifact_root))] = (
            profile_hash
        )
        if singleton["standard"] != "nadit.msd.standard/2":
            raise ValueError("CENTER_REFERENCE_REQUIRES_STANDARD_2")
        if noise_params is None:
            noise_params = singleton["noise_params"]
        elif noise_params != singleton["noise_params"]:
            raise ValueError("REFERENCE_NOISE_PARAMETERS_DIFFER")
        records = {}
        for component in components:
            key, group = next(
                (key, g)
                for key, g in profile["joint_groups"].items()
                if len(g["members"]) == 1
                and next(iter(g["members"])).startswith(component + ":")
            )
            member = next(iter(group["members"]))
            trace_path = root / "groups" / f"{key}.trace.json"
            trace, trace_hash = _read(trace_path)
            source_files[str(trace_path.relative_to(artifact_root))] = trace_hash
            record = _extract_trace(
                group, trace, singleton["entries"][member], component
            )
            record["provenance"] = {
                "member": member,
                "source_tree_sha256": singleton["source_tree_sha256"],
                "singleton_profile_bytes_sha256": singleton_hash,
                "joint_profile_bytes_sha256": profile_hash,
                "trace_bytes_sha256": trace_hash,
                "trace_sha256": group["trace_sha256"],
                "reference_validation_ok": True,
            }
            records[component] = record
        se_source = (
            records["raw_t_postselection"]
            if distance == 3
            else records["raw_t_postselection/canonicalize"]
        )
        records["se_round"] = _slice_round(se_source, distance)
        records["initialize_plus"] = _initialization(
            singleton["entries"]["initialize_plus:factory0/W1"],
            records["se_round"],
            distance,
        )
        canonical = singleton["entries"]["initialize_plus/canonicalize:factory0/W1"]
        if canonical["phase_durations_us"] != [1] or canonical["primitive_counts"] != {
            "ry": distance * distance
        }:
            raise ValueError("INITIALIZATION_CORRECTION_REFERENCE_MISMATCH")
        correction = deepcopy(records["logical_x"])
        correction["segments"][0].update(
            atom_count=distance * distance,
            action_count=distance * distance,
            primitive_counts={"ry": distance * distance},
        )
        correction["provenance"] = {
            "singleton_profile_bytes_sha256": singleton_hash,
            "member": "initialize_plus/canonicalize:factory0/W1",
            "derivation": "saved one-layer Y correction cost envelope, not sampled frame",
        }
        records["initialize_plus/canonicalize"] = correction
        raw_ports = {}
        for role in ("W2", "W3", "W4", "W5", "R"):
            port = singleton["raw_ports"][f"factory0/{role}"]
            raw_ports[role] = {
                "probability": sum(
                    o["probability"]
                    for o in port["outcomes"]
                    if o["values"].get("accepted") is True
                ),
                "port_sha256": reference_digest(port),
                "model": port["model"],
                "singleton_profile_bytes_sha256": singleton_hash,
            }
        distances[str(distance)] = {"components": records, "raw_acceptance": raw_ports}
    payload = {
        "standard": "nadit.msd.standard/2",
        "distances": distances,
        "noise_params": noise_params,
        "source_files": source_files,
        "extraction": "Read stored JSON only; no physical compilation, Atom IR decoding, replay, state update or probability sampling",
        "exposure": "Addressed atom counts; reference CZ illuminated count retained separately, not a new geometry spectator estimate",
    }
    return {
        "schema": REFERENCE_SCHEMA,
        "payload": payload,
        "payload_sha256": reference_digest(payload),
    }


def main() -> None:
    """Write a new compact reference bundle from explicitly supplied old artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = extract_references(arguments.artifact_root)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "payload_sha256": result["payload_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
