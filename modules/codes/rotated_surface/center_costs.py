"""Read compact reference costs and replace only declared center-distance legs.

No atom program, device routing, physical frontend or probability sampling is
used. The result is a geometric cost model, not physical admission evidence.
Intrinsic gates, reset, readout, transfers and local SE motion retain the saved
reference durations. Raw acceptance remains an explicitly archived estimate.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from math import dist, isfinite
from pathlib import Path
from typing import Any

REFERENCE_SCHEMA = "nadit.surface_center_references/1"


def reference_digest(document: Mapping[str, Any]) -> str:
    """Hash a finite JSON document independently of its pretty-print layout."""
    return sha256(
        json.dumps(
            dict(document), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def load_center_references(path: Path) -> dict[str, Any]:
    """Read a hash-checked reference bundle without loading any atom artifacts.

    Raises ValueError for wrong schema, modified contents or unsupported records.
    File/JSON errors are retained for the caller to report.
    """
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != REFERENCE_SCHEMA:
        raise ValueError("INVALID_CENTER_REFERENCE_SCHEMA")
    payload = document["payload"]
    if document.get("payload_sha256") != reference_digest(payload):
        raise ValueError("CENTER_REFERENCE_HASH_MISMATCH")
    if set(payload["distances"]) != {"3", "5", "7"}:
        raise ValueError("CENTER_REFERENCES_REQUIRE_D3_D5_D7")
    return document


def _point(value: Sequence[float], label: str) -> tuple[float, float]:
    if len(value) != 2 or any(
        type(item) not in (int, float) or not isfinite(item) for item in value
    ):
        raise ValueError(f"INVALID_CENTER_POINT: {label}")
    return float(value[0]), float(value[1])


def center_component_cost(
    references: Mapping[str, Any],
    *,
    distance: int,
    component_id: str,
    centers: tuple[tuple[float, float], ...],
    readout_center: tuple[float, float],
    movement_us_per_um: float,
    cnot_target_offset_um: tuple[float, float] = (0.0, 0.0),
) -> dict[str, Any]:
    """Return ordered macro phases with only readout/CNOT travel re-estimated.

    ``centers`` follows the component's ordered participants (control first for
    CNOT). Its target offset is a cost-reference point, not a validated docking
    position. Every readout leg uses the owning block center, including embedded
    d3 raw preparation in a larger target patch. All retained readout batches
    still execute. Return travel has the same distance as outward travel.

    Raises ValueError for unsupported components, malformed points or negative
    timing. Reference loading performs content hash validation once, separately.
    """
    if (
        type(distance) is not int
        or str(distance) not in references["payload"]["distances"]
    ):
        raise ValueError("UNSUPPORTED_CENTER_REFERENCE_DISTANCE")
    components = references["payload"]["distances"][str(distance)]["components"]
    if component_id not in components:
        raise ValueError(f"UNSUPPORTED_CENTER_COMPONENT: {component_id}")
    if (
        type(movement_us_per_um) not in (int, float)
        or not isfinite(movement_us_per_um)
        or movement_us_per_um <= 0
    ):
        raise ValueError("CENTER_MOVEMENT_TIMING_MUST_BE_POSITIVE")
    expected = 2 if component_id == "transversal_cnot" else 1
    if len(centers) != expected:
        raise ValueError("CENTER_COMPONENT_PARTICIPANT_ARITY")
    points = tuple(_point(point, "participant") for point in centers)
    readout = _point(readout_center, "readout")
    offset = _point(cnot_target_offset_um, "cnot_target_offset")
    reference = components[component_id]
    segments = deepcopy(reference["segments"])
    clock = 0.0
    primitive_counts: Counter[str] = Counter()
    cost_segments = []
    for segment in segments:
        kind = segment["travel_kind"]
        if kind in ("readout", "cnot"):
            destination = (
                readout
                if kind == "readout"
                else (points[1][0] + offset[0], points[1][1] + offset[1])
            )
            length = dist(points[0], destination)
            segment.update(
                duration_us=length * movement_us_per_um,
                movement_distance_atom_um=length * segment["atom_count"],
                basis="center_distance_estimate",
            )
        elif kind not in ("none", "local"):
            raise ValueError("UNKNOWN_CENTER_REFERENCE_TRAVEL_KIND")
        duration = segment["duration_us"]
        if type(duration) not in (int, float) or not isfinite(duration) or duration < 0:
            raise ValueError("INVALID_CENTER_SEGMENT_DURATION")
        segment["start_offset_us"] = clock
        clock += duration
        segment["end_offset_us"] = clock
        segment["busy_atom_us"] = duration * segment["atom_count"]
        primitive_counts.update(segment["primitive_counts"])
        cost_segments.append(
            {
                "start_offset_us": segment["start_offset_us"],
                "end_offset_us": clock,
                "category": segment["category"],
                "resource": segment["resource"],
            }
        )
    return {
        "component_id": component_id,
        "distance": distance,
        "segments": segments,
        "phase_durations_us": [part["duration_us"] for part in segments],
        "measurement_phases": deepcopy(reference["measurement_phases"]),
        "primitive_counts": dict(primitive_counts),
        "cost_segments": cost_segments,
        "duration_us": clock,
        "busy_atom_us": sum(part["busy_atom_us"] for part in segments),
        "movement_distance_atom_um": sum(
            part["movement_distance_atom_um"] for part in segments
        ),
        "basis": "intrinsic_reference_with_center_distance_readout_and_cnot",
        "reference_payload_sha256": references["payload_sha256"],
        "reference_provenance": deepcopy(reference["provenance"]),
        "atom_exposure_scope": "addressed_atoms_only; illuminated spectators are separate reference metadata",
        "physical_validation_run": False,
    }
