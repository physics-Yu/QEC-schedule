"""Applicability metadata for fixed d3 component cost models and placed returns.

This bridge describes already calibrated interfaces. It neither builds Atom IR
nor resolves a readout destination. The provider domain is a complete registered
world of d3 return footprints, plus each component's declared influence spaces.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from math import isclose
from typing import Any

from nadit_physical_compiler.device import Position, Region

from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.geometry import geometry
from modules.logical_compiler.src.estimation.calibration import (
    CalibrationContext,
    CalibrationRecord,
    calibration_context,
)
from modules.logical_compiler.src.placement import (
    BlockPlacement,
    BlockSpec,
    ExplicitPlacement,
    PlacementPlan,
    PlacementRequest,
    block_bounds,
    place,
)

CODE_ID = "rotated_surface_d3"
APPLICABILITY_SCHEMA = "nadit.fast_surface_applicability/1"
_SCOPE_VERSION = "registered-return-footprints-and-declared-spaces/1"


def _hash(document: Any) -> str:
    return sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _region(value: Any, label: str) -> Region:
    if isinstance(value, Mapping):
        try:
            value = [value[key] for key in ("x_min", "y_min", "x_max", "y_max")]
        except KeyError as error:
            raise ValueError(f"MISSING_CALIBRATION_DEVICE_REGION: {label}") from error
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(v) not in (int, float) for v in value)
    ):
        raise ValueError(f"MISSING_CALIBRATION_DEVICE_REGION: {label}")
    return Region(*value)


def _intersection(
    region: Region, influence: Region, anchor: Position, label: str
) -> list[float]:
    x0, y0 = max(region.x_min, influence.x_min), max(region.y_min, influence.y_min)
    x1, y1 = min(region.x_max, influence.x_max), min(region.y_max, influence.y_max)
    if x0 > x1 or y0 > y1:
        raise ValueError(f"UNCOVERED_CALIBRATION_DEVICE_REGION: {label}")
    return [
        float(x0 - anchor.x),
        float(y0 - anchor.y),
        float(x1 - anchor.x),
        float(y1 - anchor.y),
    ]


def _source_hashes(profile_document: Mapping[str, Any]) -> Mapping[str, str]:
    provenance = profile_document.get("provenance", {})
    hashes = provenance.get("source_hashes", {})
    if (
        not isinstance(hashes, Mapping)
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
            or not value
            for name, value in hashes.items()
        )
        or (not hashes and provenance.get("kind") != "test_fixture")
    ):
        raise ValueError("MISSING_CALIBRATION_SOURCE_FINGERPRINTS")
    return hashes


def _influence(
    plan: PlacementPlan, participants: tuple[str, ...], entry: Mapping[str, Any]
) -> Region:
    by_id = {block.block_id: block for block in plan.blocks}
    if (
        not participants
        or len(set(participants)) != len(participants)
        or not set(participants) <= by_id.keys()
    ):
        raise ValueError("INVALID_CALIBRATION_PARTICIPANTS")
    if any(
        by_id[identity].code != CODE_ID or by_id[identity].distance != 3
        for identity in participants
    ):
        raise ValueError("UNCALIBRATED_CODE_GEOMETRY")
    expected_count = 2 if entry["component_id"] == "transversal_cnot" else 1
    if len(participants) != expected_count:
        raise ValueError("INVALID_CALIBRATION_PARTICIPANTS")
    anchor = plan.placements[participants[0]].origin
    expected_geometry = []
    if expected_count == 2:
        target = plan.placements[participants[1]].origin
        expected_geometry = [float(target.x - anchor.x), float(target.y - anchor.y)]
    if list(entry["geometry"]) != expected_geometry:
        raise ValueError("CALIBRATION_COMPONENT_GEOMETRY_MISMATCH")
    boxes = [
        block_bounds(plan.geometries[by_id[identity].code], plan.placements[identity])
        for identity in participants
    ]
    for space in entry["claim"]["spaces"]:
        if not isinstance(space, (list, tuple)) or len(space) != 5:
            raise ValueError("INVALID_CALIBRATION_COMPONENT_SPACE")
        local = _region(space[:4], "component space")
        boxes.append(
            Region(
                local.x_min + anchor.x,
                local.y_min + anchor.y,
                local.x_max + anchor.x,
                local.y_max + anchor.y,
            )
        )
    return Region(
        min(b.x_min for b in boxes),
        min(b.y_min for b in boxes),
        max(b.x_max for b in boxes),
        max(b.y_max for b in boxes),
    )


def component_context(
    profile_document: Mapping[str, Any],
    plan: PlacementPlan,
    participants: tuple[str, ...],
    entry_document: Mapping[str, Any],
    budget: Mapping[str, Any],
) -> CalibrationContext:
    """Describe one placed lookup using real provider-declared region metadata.

    The caller validates the complete PlacementPlan and device home constraints
    once before repeated lookups. Shared/readout/workspace intersections retain
    only locally relevant geometry, allowing remote window enlargement. Missing
    required regions fail; no fixed y-offset or inferred workspace is substituted.
    Capacity is checked by the scheduler and does not change single-member timing.
    """
    if (
        profile_document.get("code_id") != CODE_ID
        or profile_document.get("distance") != 3
    ):
        raise ValueError("UNCALIBRATED_CODE_GEOMETRY")
    influence = _influence(plan, participants, entry_document)
    anchor = plan.placements[participants[0]].origin
    coordinates = definition(3).reference_coordinates
    for activity in entry_document.get("busy", ()):
        if not isinstance(activity, (tuple, list)) or len(activity) != 6:
            raise ValueError("INVALID_CALIBRATION_ACTIVITY_ROLE")
        slot, role = activity[:2]
        if (
            type(slot) is not int
            or type(role) is not int
            or not 0 <= role < len(coordinates)
        ):
            raise ValueError("INVALID_CALIBRATION_ACTIVITY_ROLE")
        x, y = coordinates[role]
        home = Position(anchor.x + 100 * slot + 10 * x, anchor.y + 10 * y)
        if not influence.contains(home):
            raise ValueError("UNCOVERED_CALIBRATION_ACTIVITY_SCOPE")
    claim = entry_document["claim"]
    source_hashes = _source_hashes(profile_document)
    mode = claim["parallel_mode"]
    transport = None
    if mode != "local_parallel":
        transport = {
            "shared_region": _intersection(
                _region(budget.get("shared_bounds_um"), "shared"),
                influence,
                anchor,
                "shared",
            ),
            "workspace": _intersection(
                _region(budget.get("aod_workspace_bounds_um"), "aod workspace"),
                influence,
                anchor,
                "aod workspace",
            ),
        }
    readout = None
    if claim["result_count"]:
        readout = {
            "region": _intersection(
                _region(budget.get("readout_bounds_um"), "readout"),
                influence,
                anchor,
                "readout",
            ),
        }
    component = entry_document["component_id"]
    parameters = {"geometry": entry_document["geometry"]}
    if component.startswith("raw_t_postselection"):
        if not isinstance(profile_document.get("raw_t_protocol"), Mapping):
            raise ValueError("MISSING_CALIBRATION_RAW_T_POLICY")
        parameters["raw_t_protocol"] = profile_document["raw_t_protocol"]
    return calibration_context(
        plan,
        participants,
        component_id=component,
        component_version=entry_document["waveform_key"],
        component_fingerprint=_hash(
            {
                "schema": profile_document["schema"],
                "model_scope": profile_document.get("provenance", {}).get(
                    "kind", "offline_physical_calibration"
                ),
                "source_hashes": dict(source_hashes),
                "entry": dict(entry_document),
            }
        ),
        device_context={
            "control": {
                "control": profile_document["control"],
                "noise": profile_document["noise_params"],
            },
            "transport": transport,
            "readout": readout,
        },
        parameters=parameters,
        selection={"class": entry_document["selection_class"]},
        scope="local",
        influence_bounds=influence,
        scope_evidence={
            "provider": "rotated_surface_d3.fast_context",
            "version": _SCOPE_VERSION,
            "domain": "complete registered d3 return footprints and declared component spaces",
            "operation_scope": "bound component; no global unregistered illumination",
            "is_physical_validation": False,
        },
    )


def _source_plan(physical: Mapping[str, Any]) -> PlacementPlan:
    if physical.get("validation", {}).get("ok") is not True:
        raise ValueError("CALIBRATION_REQUIRES_VALIDATED_SOURCE")
    try:
        atoms = physical["entry_state"]["atoms"]
        bindings = physical["bindings"]
    except KeyError as error:
        raise ValueError("CALIBRATION_REQUIRES_COMPLETE_RETURN_WORLD") from error
    atom_map = {atom["id"]: atom for atom in atoms}
    registered = [atom for binding in bindings for atom in binding["atom_ids"]]
    if (
        len(atom_map) != len(atoms)
        or len(set(registered)) != len(registered)
        or set(registered) != atom_map.keys()
    ):
        raise ValueError("CALIBRATION_UNREGISTERED_OR_MISSING_SPECTATORS")
    coordinates = definition(3).reference_coordinates
    blocks, placements = [], {}
    for binding in bindings:
        identity = binding["block_id"]
        if identity in placements or len(binding["atom_ids"]) != len(coordinates):
            raise ValueError("INVALID_CALIBRATION_BLOCK_BINDING")
        origin = Position(**binding["origin"])
        names = identity.rsplit("/", 1) if "/" in identity else (None, None)
        blocks.append(BlockSpec(identity, CODE_ID, 3, *names))
        placements[identity] = BlockPlacement(origin)
        for atom_id, (x, y) in zip(binding["atom_ids"], coordinates, strict=True):
            atom = atom_map[atom_id]
            if atom.get("holder", {}).get("kind") != "slm" or not (
                isclose(
                    atom["position"]["x"], origin.x + 10 * x, rel_tol=0, abs_tol=1e-8
                )
                and isclose(
                    atom["position"]["y"], origin.y + 10 * y, rel_tol=0, abs_tol=1e-8
                )
            ):
                raise ValueError("CALIBRATION_REQUIRES_REGISTERED_RETURN_FOOTPRINTS")
    return place(
        PlacementRequest(
            tuple(blocks), {CODE_ID: geometry(CODE_ID, 3)}, positions=placements
        ),
        ExplicitPlacement(),
    )


def _source_budget(physical: Mapping[str, Any]) -> dict[str, Any]:
    device = physical["device"]
    regions = {}
    for label, operation in (
        ("shared_bounds_um", "rotate"),
        ("readout_bounds_um", "measure"),
    ):
        zones = [zone for zone in device["zones"] if operation in zone["operations"]]
        if len(zones) != 1:
            raise ValueError("UNCALIBRATED_DEVICE_REGION_TOPOLOGY")
        regions[label] = zones[0]["bounds"]
    aods = device.get("aods", ())
    if len(aods) != 1 or "workspace" not in aods[0]:
        raise ValueError("MISSING_CALIBRATION_DEVICE_REGION: aod workspace")
    regions["aod_workspace_bounds_um"] = aods[0]["workspace"]
    return regions


def capture_applicability(
    case: Mapping[str, Any],
    entries: Mapping[str, Mapping[str, Any]],
    evidence: Mapping[str, Mapping[str, Any]],
    control: Mapping[str, Any],
    source_hashes: Mapping[str, str],
    noise_params: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture every distinct source context without compiling or sampling.

    Every real initial atom must belong to one registered d3 return footprint.
    Source invocations select ordered participants from component declarations.
    Finite canonicalization supplements use the already checked initial world
    and a single-patch anchor; their footprint declaration is not a routing plan.
    """
    from .fast_profile import SCHEMA, raw_t_protocol_identity

    physical = case["physical"]
    plan = _source_plan(physical)
    budget = _source_budget(physical)
    profile_document = {
        "schema": SCHEMA,
        "code_id": CODE_ID,
        "distance": 3,
        "raw_t_protocol": raw_t_protocol_identity(),
        "control": dict(control),
        "noise_params": dict(noise_params),
        "provenance": {
            "kind": "offline_physical_calibration",
            "source_hashes": dict(source_hashes),
        },
    }
    specs = {node["id"]: node["spec"] for node in case["component_schedule"]["nodes"]}
    records: dict[str, dict[str, Any]] = {}
    for variant, entry in entries.items():
        proof = evidence.get(variant, {})
        sources = proof.get("source_invocations", ())
        contexts = []
        for identity in sources:
            if identity not in specs:
                raise ValueError(
                    f"MISSING_CALIBRATION_COMPONENT_DECLARATION: {identity}"
                )
            contexts.append((identity, tuple(specs[identity]["participant_blocks"])))
        if not contexts:
            if (
                not entry["component_id"].endswith("/canonicalize")
                or proof.get("kind") != "offline_finite_class_supplement"
            ):
                raise ValueError(f"MISSING_CALIBRATION_SOURCE_INVOCATIONS: {variant}")
            contexts.append((None, (plan.blocks[0].block_id,)))
        for identity, participants in contexts:
            context = component_context(
                profile_document, plan, participants, entry, budget
            )
            record = CalibrationRecord(
                context,
                entry,
                {
                    "variant_key": variant,
                    "source_invocation": identity,
                    "source_kind": "offline_finite_class_supplement"
                    if identity is None
                    else "validated_component_invocation",
                    "complete_registered_return_geometry": True,
                    "scope_provider": _SCOPE_VERSION,
                },
            )
            previous = records.get(context.key.fingerprint)
            if previous is not None and previous["payload"] != record.payload:
                raise ValueError("CONFLICTING_CALIBRATION_APPLICABILITY")
            records.setdefault(context.key.fingerprint, record.to_dict())
    return {
        "schema": APPLICABILITY_SCHEMA,
        "records": [records[key] for key in sorted(records)],
    }
