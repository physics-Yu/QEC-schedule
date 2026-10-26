"""Deterministic factory layout plans; no compilation, sampling or forecasting."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import zip_longest
from math import ceil, hypot, isfinite
from typing import Any

from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.rotated_surface import definition
from modules.logical_compiler.src.placement import (
    ExplicitPlacement,
    GridFactoryPlacement,
    PlacementPlan,
    place,
)

from .standard import (
    FACTORY_ROLES,
    SITE_PITCH_UM,
    STANDARD_ID,
    ExperimentSpec,
    add_buffer_sites,
    build_world,
    placement_request,
)


def _integers(document: Mapping[str, Any], field: str, minimum: int) -> tuple[int, ...]:
    values = document[field]
    if (
        not isinstance(values, list)
        or not values
        or any(type(value) is not int or value < minimum for value in values)
    ):
        raise ValueError(f"INVALID_CAMPAIGN_AXIS: {field}")
    return tuple(sorted(set(values)))


def expand_single_level(
    document: Mapping[str, Any], *, source_identity: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve unique factor-grid layouts and seeded production task identities.

    Inputs include explicit atom/footprint budgets and a separately frozen source
    identity. Oversized layouts remain visible with a budget-excluded status.
    This resolves geometry only: the pilot must still resolve observation windows
    and the runner must validate calibration/physical execution before production.
    Raises ValueError for changed experiment semantics or missing budgets.
    """
    if document.get("standard") != STANDARD_ID or document.get("aod_count") != 1:
        raise ValueError("CAMPAIGN_REQUIRES_CURRENT_SINGLE_AOD_STANDARD")
    if not source_identity:
        raise ValueError("CAMPAIGN_SOURCE_IDENTITY_REQUIRED")
    distances = _integers(document, "distances", 3)
    counts = _integers(document, "factory_counts", 1)
    seeds = _integers(document, "production_seeds", 0)
    budget = document.get("budget")
    if not isinstance(budget, Mapping) or type(budget.get("max_atoms")) is not int:
        raise ValueError("CAMPAIGN_ATOM_BUDGET_REQUIRED")
    if budget["max_atoms"] < 1:
        raise ValueError("INVALID_CAMPAIGN_ATOM_BUDGET")
    area_limit = budget.get("max_footprint_um2")
    if area_limit is not None and (
        type(area_limit) not in (int, float)
        or not isfinite(area_limit)
        or area_limit <= 0
    ):
        raise ValueError("INVALID_CAMPAIGN_FOOTPRINT_BUDGET")
    spec_identity = canonical_hash(document)
    source_hash = canonical_hash(source_identity)
    layouts, tasks, seen = [], [], set()
    for distance in distances:
        for count in counts:
            spec = ExperimentSpec(distance, count)
            for columns in range(1, count + 1):
                if count % columns:
                    continue
                plan = place(
                    placement_request(spec),
                    GridFactoryPlacement(
                        FACTORY_ROLES,
                        columns=columns,
                        patch_gap_um=spec.patch_gap_um,
                        factory_gap_x_um=spec.factory_gap_um,
                        factory_gap_y_um=spec.factory_gap_um,
                    ),
                )
                if plan.geometry_fingerprint in seen:
                    continue
                seen.add(plan.geometry_fingerprint)
                atoms = count * len(FACTORY_ROLES) * definition(distance).atom_count
                bounds = plan.occupied_bounds
                footprint = (bounds.x_max - bounds.x_min) * (
                    bounds.y_max - bounds.y_min
                )
                excluded = []
                if atoms > budget["max_atoms"]:
                    excluded.append("max_atoms")
                if area_limit is not None and footprint > area_limit:
                    excluded.append("max_footprint_um2")
                layout_id = canonical_hash(
                    {"placement": plan.to_dict(), "standard": STANDARD_ID}
                )
                layouts.append(
                    {
                        "layout_id": layout_id,
                        "distance": distance,
                        "factory_count": count,
                        "columns": columns,
                        "rows": count // columns,
                        "placement": plan.to_dict(),
                        "configured_atoms": atoms,
                        "occupied_bounding_area_um2": footprint,
                        "budget_exclusions": excluded,
                    }
                )
                for seed in seeds:
                    identity = {
                        "phase": "single_level",
                        "layout_id": layout_id,
                        "seed": seed,
                        "config_sha256": spec_identity,
                        "source_sha256": source_hash,
                    }
                    tasks.append(
                        {
                            **identity,
                            "task_id": canonical_hash(identity),
                            "status": "budget_excluded"
                            if excluded
                            else "pending_pilot",
                            "budget_exclusions": list(excluded),
                        }
                    )
    return {
        "schema": "nadit.msd.single_level_plan/1",
        "resolution": "geometry_and_task_identity_only",
        "configuration": deepcopy(dict(document)),
        "source_identity": deepcopy(dict(source_identity)),
        "layouts": layouts,
        "tasks": tasks,
    }


_TWO_LEVEL_FAMILIES = ("centralized", "boundary", "local_groups")


def _digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"INVALID_TWO_LEVEL_SHA256: {field}")
    return value


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if (
        type(value) not in (int, float)
        or not isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError(f"INVALID_TWO_LEVEL_NUMBER: {field}")
    return float(value)


def _arrival_groups(
    document: Mapping[str, Any], evidence: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if (
        evidence.get("schema") != "nadit.msd.arrival_evidence/1"
        or evidence.get("standard") != STANDARD_ID
    ):
        raise ValueError("INVALID_FROZEN_ARRIVAL_SCHEMA")
    if canonical_hash(evidence) != _digest(
        document.get("arrival_evidence_sha256"), "arrival_evidence_sha256"
    ):
        raise ValueError("FROZEN_ARRIVAL_PIN_MISMATCH")
    source = evidence.get("source_identity")
    if not isinstance(source, Mapping) or not source:
        raise ValueError("ARRIVAL_SOURCE_IDENTITY_REQUIRED")
    source_hash = canonical_hash(source)
    if source_hash != evidence.get("source_sha256") or source_hash != _digest(
        document.get("arrival_source_sha256"), "arrival_source_sha256"
    ):
        raise ValueError("ARRIVAL_SOURCE_PIN_MISMATCH")
    trajectories = evidence.get("trajectories")
    if not isinstance(trajectories, list):
        raise TypeError("ARRIVAL_TRAJECTORIES_REQUIRED")
    ids, results, seeded = set(), set(), set()
    groups: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    for row in trajectories:
        if not isinstance(row, Mapping):
            raise TypeError("INVALID_ARRIVAL_TRAJECTORY")
        identity = _digest(row.get("trajectory_id"), "trajectory_id")
        result_hash = _digest(row.get("result_sha256"), "result_sha256")
        layout = _digest(row.get("layout_id"), "layout_id")
        if identity in ids or result_hash in results:
            raise ValueError("DUPLICATE_ARRIVAL_TRAJECTORY_OR_RESULT")
        ids.add(identity)
        results.add(result_hash)
        distance, count, seed = (
            row.get("distance"),
            row.get("factory_count"),
            row.get("seed"),
        )
        if (
            type(distance) is not int
            or distance < 3
            or distance % 2 != 1
            or type(count) is not int
            or count < 1
            or type(seed) is not int
            or seed < 0
        ):
            raise ValueError("INVALID_PARALLEL_ARRIVAL_IDENTITY")
        key = distance, count, layout
        if (*key, seed) in seeded:
            raise ValueError("DUPLICATE_COMPLETE_ARRIVAL_SEED")
        seeded.add((*key, seed))
        window = row.get("window_us")
        if (
            row.get("status") != "complete"
            or row.get("window_complete") is not True
            or row.get("source_sha256") != source_hash
            or not isinstance(window, list)
            or len(window) != 2
        ):
            raise ValueError("INCOMPLETE_OR_DRIFTED_ARRIVAL_EVIDENCE")
        start, stop = (_number(t, "window_us") for t in window)
        duration = _number(row.get("duration_us"), "duration_us")
        if not start < stop <= duration:
            raise ValueError("INCOMPLETE_ARRIVAL_OBSERVATION_WINDOW")
        arrivals = row.get("arrivals")
        if not isinstance(arrivals, list):
            raise TypeError("EXPLICIT_ARRIVAL_RECORDS_REQUIRED")
        tokens, observed = set(), 0
        for arrival in arrivals:
            if not isinstance(arrival, Mapping):
                raise TypeError("INVALID_ARRIVAL_RECORD")
            token = arrival.get("token_id")
            if not isinstance(token, str) or not token.strip() or token in tokens:
                raise ValueError("DUPLICATE_OR_INVALID_TRAJECTORY_TOKEN")
            tokens.add(token)
            ready = _number(arrival.get("ready_at_us"), "ready_at_us")
            delivered = _number(arrival.get("deliverable_at_us"), "deliverable_at_us")
            if not ready <= delivered <= duration:
                raise ValueError("INVALID_ARRIVAL_TIMES")
            observed += int(start <= delivered < stop)
        groups.setdefault(key, []).append(
            {
                "trajectory_id": identity,
                "seed": seed,
                "window_us": [start, stop],
                "observed_arrivals": observed,
                "source_sha256": source_hash,
                "result_sha256": result_hash,
            }
        )
    return [
        {
            "distance": key[0],
            "level1_count": key[1],
            "source_layout_id": key[2],
            "trajectories": sorted(rows, key=lambda row: row["seed"]),
            "arrival_group_id": canonical_hash(
                {
                    "distance": key[0],
                    "level1_count": key[1],
                    "source_layout_id": key[2],
                    "trajectory_ids": sorted(r["trajectory_id"] for r in rows),
                }
            ),
        }
        for key, rows in sorted(groups.items())
    ]


def _two_level_geometry(
    distance: int, n1: int, n2: int, columns: int, family: str
) -> PlacementPlan:
    """Permute whole factory slots; preserve every factory's six-role geometry."""
    spec = ExperimentSpec(distance, n1 + n2)
    request = placement_request(spec)
    base = place(
        request,
        GridFactoryPlacement(
            FACTORY_ROLES,
            columns=columns,
            patch_gap_um=spec.patch_gap_um,
            factory_gap_x_um=spec.factory_gap_um,
            factory_gap_y_um=spec.factory_gap_um,
        ),
    )
    origins = [
        base.placements[f"factory{i}/{FACTORY_ROLES[0]}"].origin for i in range(n1 + n2)
    ]
    if family == "centralized":
        x, y = (
            sum(p.x for p in origins) / len(origins),
            sum(p.y for p in origins) / len(origins),
        )
        receivers = sorted(
            range(len(origins)),
            key=lambda i: (hypot(origins[i].x - x, origins[i].y - y), i),
        )[:n2]
    elif family == "boundary":
        receivers = sorted(
            range(len(origins)), key=lambda i: (-origins[i].y, origins[i].x, i)
        )[:n2]
    else:
        receivers = [(2 * i + 1) * len(origins) // (2 * n2) for i in range(n2)]
    producers = [i for i in range(len(origins)) if i not in receivers]
    if family == "local_groups":

        def local_key(slot: int) -> tuple[int, float, int]:
            choices = [
                (
                    hypot(
                        origins[slot].x - origins[r].x, origins[slot].y - origins[r].y
                    ),
                    i,
                )
                for i, r in enumerate(receivers)
            ]
            distance_to_receiver, receiver = min(choices)
            return receiver, distance_to_receiver, slot

        producers.sort(key=local_key)
    order = producers + receivers
    positions = {
        f"factory{i}/{role}": base.placements[f"factory{slot}/{role}"]
        for i, slot in enumerate(order)
        for role in FACTORY_ROLES
    }
    return place(replace(request, positions=positions), ExplicitPlacement())


def _two_level_resources(spec: ExperimentSpec, plan: PlacementPlan) -> dict[str, Any]:
    """Count actual declared SLM sites, including the empty global parking grid."""
    world = build_world(spec, placement_plan=plan)
    parking = Position(
        min(s.position.x for s in world.device.slm_sites),
        min(s.position.y for s in world.device.slm_sites)
        - spec.factory_gap_um
        - 2 * spec.distance * SITE_PITCH_UM,
    )
    old_sites = len(world.device.slm_sites)
    world, _ = add_buffer_sites(world, {"exchange_parking": parking})
    xs = [s.position.x for s in world.device.slm_sites]
    ys = [s.position.y for s in world.device.slm_sites]
    home = plan.occupied_bounds
    return {
        "spec": spec.to_dict(),
        "placement": plan.to_dict(),
        "parking_slot": "exchange_parking",
        "parking_origin": asdict(parking),
        "configured_atoms": len(world.state.atoms),
        "home_occupied_bounding_area_um2": (home.x_max - home.x_min)
        * (home.y_max - home.y_min),
        "total_slm_bounding_area_um2": (max(xs) - min(xs)) * (max(ys) - min(ys)),
        "slm_bounding_box_um": [min(xs), min(ys), max(xs), max(ys)],
        "slm_site_count": len(world.device.slm_sites),
        "parking_site_count": len(world.device.slm_sites) - old_sites,
        "parking_atom_count": 0,
    }


def _candidate_limit(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("INVALID_CANDIDATE_LAYOUT_LIMIT")
    return value


def _arrival_priority(group: Mapping[str, Any]) -> dict[str, Any]:
    """Keep independent seed rates explicit; never sum observations across seeds."""
    seeds = []
    for row in group["trajectories"]:
        start, stop = (_number(t, "candidate_window") for t in row["window_us"])
        count = row["observed_arrivals"]
        if stop <= start or type(count) is not int or count < 0:
            raise ValueError("INVALID_CANDIDATE_ARRIVAL_OBSERVATION")
        seeds.append(
            {**deepcopy(row), "observed_arrivals_per_us": count / (stop - start)}
        )
    if not seeds or group["supply_exclusions"]:
        raise ValueError("INVALID_CANDIDATE_ELIGIBLE_GROUP")
    return {
        "arrival_group_id": group["arrival_group_id"],
        "source_layout_id": group["source_layout_id"],
        "minimum_arrivals_per_us": min(
            row["observed_arrivals_per_us"] for row in seeds
        ),
        "seed_rates": sorted(
            seeds, key=lambda row: (row["seed"], row["trajectory_id"])
        ),
    }


def select_two_level_candidates(
    layouts: Sequence[Mapping[str, Any]], *, max_candidate_layouts: int
) -> dict[str, Any]:
    """Prioritize validated plan metadata within an explicit candidate count cap.

    Only atom/area/supply-admitted cells enter the ranking. Each source group keeps
    its own complete seeds: its rate is the minimum observed arrivals/window over
    those seeds. A pair's score is the highest independently eligible group rate
    divided by 15*N2. This is a preset budget priority, not predicted throughput,
    optimization, or an assertion that another seed will have the same arrivals.
    Distances round-robin in ascending order. Within a distance, pairs sort by
    descending score, fewer atoms, N1, N2; a pair's cells then sort by columns,
    family aliases, geometry ID and capacity. No world, file or compiler is used.
    """
    limit = _candidate_limit(max_candidate_layouts)
    if len({row["layout_id"] for row in layouts}) != len(layouts):
        raise ValueError("DUPLICATE_CANDIDATE_LAYOUT_ID")
    eligible = [
        row
        for row in layouts
        if not row["budget_exclusions"] and not row["supply_exclusions"]
    ]
    pairs: dict[tuple[int, int, int], list[Mapping[str, Any]]] = {}
    for row in eligible:
        pairs.setdefault(
            (row["distance"], row["level1_count"], row["level2_count"]), []
        ).append(row)
    priorities = {}
    for key, cells in sorted(pairs.items()):
        groups: dict[str, Mapping[str, Any]] = {}
        for cell in cells:
            for group in cell["arrival_groups"]:
                if not group["independently_eligible"]:
                    continue
                identity = group["arrival_group_id"]
                if identity in groups and groups[identity] != group:
                    raise ValueError("CONFLICTING_CANDIDATE_SOURCE_GROUP")
                groups[identity] = group
        scored = [_arrival_priority(groups[identity]) for identity in sorted(groups)]
        if not scored:
            raise ValueError("CANDIDATE_REQUIRES_INDEPENDENTLY_ELIGIBLE_GROUP")
        best = min(
            scored,
            key=lambda row: (-row["minimum_arrivals_per_us"], row["arrival_group_id"]),
        )
        priorities[key] = {
            "distance": key[0],
            "level1_count": key[1],
            "level2_count": key[2],
            "configured_atoms": min(row["configured_atoms"] for row in cells),
            "priority_arrival_group_id": best["arrival_group_id"],
            "minimum_arrivals_per_us": best["minimum_arrivals_per_us"],
            "score": best["minimum_arrivals_per_us"] / (15 * key[2]),
            "source_group_scores": scored,
        }

    def order(row: Mapping[str, Any]) -> tuple[Any, ...]:
        priority = priorities[row["distance"], row["level1_count"], row["level2_count"]]
        return (
            -priority["score"],
            priority["configured_atoms"],
            row["level1_count"],
            row["level2_count"],
            row["columns"],
            tuple(sorted(row["layout_families"])),
            row["geometry_layout_id"],
            row["buffer_capacity"],
            row["layout_id"],
        )

    by_distance: dict[int, list[Mapping[str, Any]]] = {}
    for row in eligible:
        by_distance.setdefault(row["distance"], []).append(row)
    queues = [
        sorted(by_distance[distance], key=order) for distance in sorted(by_distance)
    ]
    ranked = [row for turn in zip_longest(*queues) for row in turn if row is not None]
    ranks = {row["layout_id"]: index + 1 for index, row in enumerate(ranked)}
    selected = [row["layout_id"] for row in ranked[:limit]]
    selected_set = set(selected)
    candidates = []
    for row in sorted(layouts, key=lambda row: row["layout_id"]):
        priority = priorities.get(
            (row["distance"], row["level1_count"], row["level2_count"])
        )
        admitted = row["layout_id"] in ranks
        candidates.append(
            {
                "layout_id": row["layout_id"],
                "distance": row["distance"],
                "level1_count": row["level1_count"],
                "level2_count": row["level2_count"],
                "eligible": admitted,
                "selected": row["layout_id"] in selected_set,
                "selection_rank": ranks.get(row["layout_id"]),
                "score": priority["score"]
                if admitted and priority is not None
                else None,
                "budget_exclusions": list(row["budget_exclusions"]),
                "supply_exclusions": list(row["supply_exclusions"]),
            }
        )
    return {
        "schema": "nadit.msd.two_level_candidate_selection/1",
        "max_candidate_layouts": limit,
        "selected_layout_ids": selected,
        "rule": "ascending-distance round-robin; pairs by descending max independent-group min seed rate/(15*N2), atoms, N1, N2; cells by columns, family aliases, geometry ID, capacity",
        "scope": "preset budget candidate priority only; not optimality or throughput prediction",
        "pair_priorities": [priorities[key] for key in sorted(priorities)],
        "candidates": candidates,
        "distance_coverage": [
            {
                "distance": distance,
                "eligible_cells": len(rows),
                "selected_cells": sum(row["layout_id"] in selected_set for row in rows),
            }
            for distance, rows in sorted(by_distance.items())
        ],
    }


def expand_two_level(
    document: Mapping[str, Any],
    arrival_evidence: Mapping[str, Any],
    *,
    source_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Expand same-distance candidates from pinned parallel L1 observations.

    Evidence schema nadit.msd.arrival_evidence/1 retains complete per-seed windows,
    token IDs/times and source/result SHA256 references. document pins the entire
    artifact and its historical source separately from this plan's source_identity.
    The caller/driver verifies original result files: this pure function checks
    frozen-document consistency only, never independently certifies those results.

    Coverage requires each supplied complete seed to observe at least 15*N2 actual
    arrivals in its half-open window and at least minimum_arrival_seeds seeds per
    original layout/d/N1 group. It neither multiplies singleton counts nor predicts
    throughput, retries or sufficiency for a later two-level observation window.
    Explicit finite atom and full-SLM-area budgets include one vacant parking grid.
    Geometry is constructed once per fingerprint outside capacity/seed expansion.
    Within this frozen plan, identical execution geometry/capacity/seed is emitted
    once even when several L1 source layouts support it. Source groups are tested
    independently, never pooling seeds or counts. At least one eligible group is
    required; the lexicographically first eligible group supplies legacy aliases
    (first of all groups if none qualifies). Every group's evidence is retained.
    Noise, limits and source belong to the shared frozen stage; this function does
    not deduplicate executions across campaigns or independently frozen stages.
    Mixed distances remain protocol dependencies; no runner or physics is invoked.
    """
    if (
        document.get("schema") != "nadit.msd.two_level_campaign/1"
        or document.get("standard") != STANDARD_ID
        or document.get("aod_count") != 1
    ):
        raise ValueError("TWO_LEVEL_REQUIRES_CURRENT_SINGLE_AOD_STANDARD")
    if not source_identity:
        raise ValueError("CAMPAIGN_SOURCE_IDENTITY_REQUIRED")
    n2_values = _integers(document, "level2_counts", 1)
    if "max_candidate_layouts" in document:
        _candidate_limit(document["max_candidate_layouts"])
    capacities = _integers(document, "buffer_capacities", 1)
    columns_values = _integers(document, "grid_columns", 1)
    seeds = _integers(document, "production_seeds", 0)
    minimum = document.get("minimum_arrival_seeds")
    if type(minimum) is not int or minimum < 1:
        raise ValueError("EXPLICIT_MINIMUM_ARRIVAL_SEEDS_REQUIRED")
    if document.get("parking_gap_um") != ExperimentSpec().factory_gap_um:
        raise ValueError("TWO_LEVEL_REQUIRES_EXISTING_PARKING_GAP")
    budget = document.get("budget")
    if (
        not isinstance(budget, Mapping)
        or type(budget.get("max_atoms")) is not int
        or budget["max_atoms"] < 1
    ):
        raise ValueError("EXPLICIT_TWO_LEVEL_ATOM_BUDGET_REQUIRED")
    area_limit = _number(
        budget.get("max_footprint_um2"), "max_footprint_um2", positive=True
    )
    families = document.get("layout_families")
    if (
        not isinstance(families, list)
        or not families
        or any(f not in _TWO_LEVEL_FAMILIES for f in families)
    ):
        raise ValueError("EXPLICIT_TWO_LEVEL_LAYOUT_FAMILIES_REQUIRED")
    pairs = document.get("distance_pairs")
    if (
        not isinstance(pairs, list)
        or not pairs
        or any(
            not isinstance(pair, list)
            or len(pair) != 2
            or any(type(d) is not int or d < 3 or d % 2 != 1 for d in pair)
            for pair in pairs
        )
    ):
        raise ValueError("INVALID_TWO_LEVEL_DISTANCE_PAIRS")
    groups = _arrival_groups(document, arrival_evidence)
    config_hash, source_hash = canonical_hash(document), canonical_hash(source_identity)
    resources_cache: dict[str, dict[str, Any]] = {}
    layouts_by_key: dict[tuple[int, int, int, str], dict[str, Any]] = {}
    sources_by_key: dict[tuple[int, int, int, str], dict[str, dict[str, Any]]] = {}
    dependencies, unavailable = [], []
    for d1, d2 in sorted({tuple(pair) for pair in pairs}):
        selected = [group for group in groups if group["distance"] == d1]
        if not selected:
            missing = {"distance": d1, "reason": "no_frozen_arrival_trajectories"}
            if missing not in unavailable:
                unavailable.append(missing)
        for group in selected:
            if d1 != d2:
                dependencies.append(
                    {
                        "distance_pair": [d1, d2],
                        "arrival_group_id": group["arrival_group_id"],
                        "level1_count": group["level1_count"],
                        "level2_counts": list(n2_values),
                        "status": "unsupported_protocol",
                        "dependency": "cross_distance_state_delivery",
                    }
                )
                continue
            n1 = group["level1_count"]
            for n2 in n2_values:
                supply_excluded = []
                if len(group["trajectories"]) < minimum:
                    supply_excluded.append("minimum_arrival_seeds")
                if any(
                    row["observed_arrivals"] < 15 * n2 for row in group["trajectories"]
                ):
                    supply_excluded.append("arrival_count_below_15N2")
                source_group = {
                    "arrival_group_id": group["arrival_group_id"],
                    "source_layout_id": group["source_layout_id"],
                    "trajectories": deepcopy(group["trajectories"]),
                    "supply_exclusions": supply_excluded,
                    "independently_eligible": not supply_excluded,
                }
                for columns in columns_values:
                    for family in sorted(set(families)):
                        plan = _two_level_geometry(d1, n1, n2, columns, family)
                        geometry = plan.geometry_fingerprint
                        if geometry not in resources_cache:
                            resources_cache[geometry] = _two_level_resources(
                                ExperimentSpec(d1, n1 + n2), plan
                            )
                        resources = resources_cache[geometry]
                        key = d1, n1, n2, geometry
                        sources_by_key.setdefault(key, {})[
                            group["arrival_group_id"]
                        ] = source_group
                        if key in layouts_by_key:
                            previous = layouts_by_key[key]
                            previous["layout_families"] = sorted(
                                set(previous["layout_families"]) | {family}
                            )
                            previous["grid_columns"] = sorted(
                                set(previous["grid_columns"]) | {columns}
                            )
                            continue
                        excluded = []
                        if resources["configured_atoms"] > budget["max_atoms"]:
                            excluded.append("max_atoms")
                        if resources["total_slm_bounding_area_um2"] > area_limit:
                            excluded.append("max_footprint_um2")
                        layout_id = canonical_hash(
                            {
                                "geometry": geometry,
                                "standard": STANDARD_ID,
                                "parking_origin": resources["parking_origin"],
                                "level1_count": n1,
                                "level2_count": n2,
                            }
                        )
                        layouts_by_key[key] = {
                            **deepcopy(resources),
                            "layout_id": layout_id,
                            "geometry_fingerprint": geometry,
                            "distance": d1,
                            "level1_count": n1,
                            "level2_count": n2,
                            "factory_count": n1 + n2,
                            "columns": min(columns, n1 + n2),
                            "rows": ceil((n1 + n2) / min(columns, n1 + n2)),
                            "grid_columns": [columns],
                            "layout_families": [family],
                            "budget_exclusions": excluded,
                        }
    for key, layout in layouts_by_key.items():
        source_groups = sorted(
            sources_by_key[key].values(), key=lambda row: row["arrival_group_id"]
        )
        eligible = [row for row in source_groups if row["independently_eligible"]]
        representative = (eligible or source_groups)[0]
        layout.update(
            arrival_groups=deepcopy(source_groups),
            arrival_group_id=representative["arrival_group_id"],
            source_layout_id=representative["source_layout_id"],
            supply_exclusions=list(representative["supply_exclusions"]),
            supply_coverage={
                "rule": "each_complete_seed_at_least_15N2",
                "required_arrivals_per_seed": 15 * layout["level2_count"],
                "minimum_complete_seeds": minimum,
                "trajectories": deepcopy(representative["trajectories"]),
                "throughput_prediction": False,
            },
        )
    layouts = []
    for geometry_layout in sorted(
        layouts_by_key.values(), key=lambda row: row["layout_id"]
    ):
        for capacity in capacities:
            identity = {
                "geometry_layout_id": geometry_layout["layout_id"],
                "buffer_capacity": capacity,
            }
            layouts.append(
                {
                    **deepcopy(geometry_layout),
                    **identity,
                    "layout_id": canonical_hash(identity),
                }
            )
    tasks = []
    selection = None
    if "max_candidate_layouts" in document:
        selection = select_two_level_candidates(
            layouts, max_candidate_layouts=document["max_candidate_layouts"]
        )
        selected_ids = set(selection["selected_layout_ids"])
        for layout in layouts:
            layout["selection_exclusions"] = (
                ["max_candidate_layouts"]
                if not layout["budget_exclusions"]
                and not layout["supply_exclusions"]
                and layout["layout_id"] not in selected_ids
                else []
            )
    for layout in layouts:
        for seed in seeds:
            identity = {
                "phase": "two_level",
                "layout_id": layout["layout_id"],
                "buffer_capacity": layout["buffer_capacity"],
                "seed": seed,
                "config_sha256": config_hash,
                "source_sha256": source_hash,
                "arrival_evidence_sha256": document["arrival_evidence_sha256"],
            }
            tasks.append(
                {
                    **identity,
                    "task_id": canonical_hash(identity),
                    "status": "budget_excluded"
                    if layout["budget_exclusions"]
                    else "supply_excluded"
                    if layout["supply_exclusions"]
                    else "selection_excluded"
                    if layout.get("selection_exclusions")
                    else "pending_execution",
                    "budget_exclusions": list(layout["budget_exclusions"]),
                    "supply_exclusions": list(layout["supply_exclusions"]),
                    **(
                        {}
                        if selection is None
                        else {
                            "selection_exclusions": list(layout["selection_exclusions"])
                        }
                    ),
                }
            )
    return {
        "schema": "nadit.msd.two_level_plan/1",
        "resolution": "geometry_and_observed_arrival_coverage_only",
        "runnable": False,
        "configuration": deepcopy(dict(document)),
        "source_identity": deepcopy(dict(source_identity)),
        "arrival_evidence": deepcopy(dict(arrival_evidence)),
        **({} if selection is None else {"candidate_selection": selection}),
        "arrival_validation_scope": "frozen document consistency; original result verification belongs to the driver",
        "supply_policy": {
            "dispatch": "global_fifo",
            "storage": "producer_carrier_held",
            "parking_slots": 1,
            "routing": "existing_same_distance_three_hop",
            "capacity_allocates_extra_atoms": False,
            "local_groups_are_geometry_only": True,
            "eligibility": "at_least_one_independently_eligible_arrival_group",
            "representative": "lexicographically_first_eligible_group_id_else_first_group_id",
            "execution_deduplication_scope": "one_frozen_plan_only",
        },
        "layout_family_rules": {
            "centralized": "L2 slots nearest the whole-grid centroid",
            "boundary": "L2 slots on the upper boundary nearest readout first",
            "local_groups": "spread L2 slots along row-major grid and group neighboring L1 identities; dispatch remains global FIFO",
        },
        "layouts": layouts,
        "tasks": tasks,
        "protocol_dependencies": dependencies,
        "unavailable_sources": unavailable,
    }
