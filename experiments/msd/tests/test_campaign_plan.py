"""Stable factor-grid task expansion and explicit budget exclusions."""

from copy import deepcopy

import pytest
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd.campaign_plan import (
    expand_single_level,
    expand_two_level,
    select_two_level_candidates,
)
from experiments.msd.standard import ExperimentSpec, add_buffer_sites, build_world
from modules.logical_compiler.src.placement import PlacementPlan


def configuration():
    return {
        "standard": "nadit.msd.standard/2",
        "aod_count": 1,
        "distances": [3, 5, 7],
        "factory_counts": [1, 2, 4, 8],
        "production_seeds": list(range(16)),
        "budget": {"max_atoms": 5000, "max_footprint_um2": None},
    }


def test_basic_campaign_has_thirty_unique_layouts_and_480_unique_tasks():
    doc = configuration()
    result = expand_single_level(doc, source_identity={"test_fixture": "version1"})
    assert len(result["layouts"]) == 30
    assert len({row["layout_id"] for row in result["layouts"]}) == 30
    assert len(result["tasks"]) == 480
    assert len({row["task_id"] for row in result["tasks"]}) == 480
    assert {row["status"] for row in result["tasks"]} == {"pending_pilot"}
    for row in result["layouts"]:
        plan = PlacementPlan.from_dict(row["placement"])
        assert plan.occupied_bounds.y_max <= 0
        assert row["rows"] * row["columns"] == row["factory_count"]
    assert result == expand_single_level(
        doc, source_identity={"test_fixture": "version1"}
    )


def test_budget_exclusion_is_visible_and_changes_task_identity():
    config = configuration()
    baseline = expand_single_level(config, source_identity={"test_fixture": "v1"})
    config["budget"]["max_atoms"] = 100
    excluded = expand_single_level(config, source_identity={"test_fixture": "v1"})
    assert len(excluded["tasks"]) == 480
    assert all(task["status"] == "budget_excluded" for task in excluded["tasks"])
    assert {t["task_id"] for t in baseline["tasks"]}.isdisjoint(
        t["task_id"] for t in excluded["tasks"]
    )


@pytest.mark.parametrize(
    "field,value", (("aod_count", 2), ("budget", None), ("distances", [4]))
)
def test_invalid_semantics_fail_before_execution(field, value):
    config = deepcopy(configuration())
    config[field] = value
    with pytest.raises(ValueError):
        expand_single_level(config, source_identity={"test_fixture": "v1"})


def arrival_evidence(counts=(32, 31), *, factories=2, distance=3):
    """Frozen synthetic arrival observations, not a singleton throughput model."""
    source = {"scope": "synthetic_arrival_fixture", "source_hash": "a" * 64}
    source_sha = canonical_hash(source)
    layout_id = canonical_hash({"distance": distance, "N1": factories})
    rows = []
    for seed, count in enumerate(counts):
        rows.append(
            {
                "trajectory_id": canonical_hash({"layout": layout_id, "seed": seed}),
                "layout_id": layout_id,
                "distance": distance,
                "factory_count": factories,
                "seed": seed,
                "window_us": [10, 100],
                "duration_us": 105,
                "status": "complete",
                "window_complete": True,
                "source_sha256": source_sha,
                "result_sha256": canonical_hash(
                    {"synthetic_result": seed, "count": count}
                ),
                "arrivals": [
                    {
                        "token_id": f"factory{i % factories}/cycle[{i}]/output",
                        "ready_at_us": 10 + i,
                        "deliverable_at_us": 11 + i,
                    }
                    for i in range(count)
                ],
            }
        )
    return {
        "schema": "nadit.msd.arrival_evidence/1",
        "standard": "nadit.msd.standard/2",
        "source_identity": source,
        "source_sha256": source_sha,
        "trajectories": rows,
    }


def two_level_configuration(evidence):
    return {
        "schema": "nadit.msd.two_level_campaign/1",
        "standard": "nadit.msd.standard/2",
        "aod_count": 1,
        "distance_pairs": [[3, 3]],
        "level2_counts": [1, 2],
        "buffer_capacities": [1, 2],
        "grid_columns": [1, 2],
        "layout_families": ["centralized", "boundary", "local_groups"],
        "production_seeds": [11, 12],
        "minimum_arrival_seeds": 2,
        "parking_gap_um": 40,
        "arrival_evidence_sha256": canonical_hash(evidence),
        "arrival_source_sha256": evidence["source_sha256"],
        "budget": {"max_atoms": 10000, "max_footprint_um2": 10000000},
    }


def expand_fixture(config, evidence):
    return expand_two_level(
        config, evidence, source_identity={"planner_fixture": "current"}
    )


def test_two_level_plan_uses_actual_parallel_arrivals_and_preserves_provenance():
    evidence = arrival_evidence()
    config = two_level_configuration(evidence)
    original = deepcopy((config, evidence))
    result = expand_fixture(config, evidence)
    assert result == expand_fixture(config, evidence)
    assert (config, evidence) == original
    assert result["arrival_evidence"] == evidence
    assert result["source_identity"] != evidence["source_identity"]
    assert result["layouts"] and result["tasks"]
    assert {row["level1_count"] for row in result["layouts"]} == {2}
    assert {row["distance"] for row in result["layouts"]} == {3}
    assert len({row["task_id"] for row in result["tasks"]}) == len(result["tasks"])
    assert {row["status"] for row in result["tasks"]} == {"pending_execution"}
    assert result["supply_policy"]["dispatch"] == "global_fifo"
    assert result["resolution"] == "geometry_and_observed_arrival_coverage_only"
    assert result["runnable"] is False
    for layout in result["layouts"]:
        if "boundary" not in layout["layout_families"]:
            continue
        plan = PlacementPlan.from_dict(layout["placement"])
        n1, n2 = layout["level1_count"], layout["level2_count"]
        role = next(iter(plan.placements)).split("/")[1]
        origins = [
            plan.placements[f"factory{i}/{role}"].origin.y for i in range(n1 + n2)
        ]
        assert min(origins[n1:]) >= max(origins[:n1])


def test_supply_coverage_does_not_multiply_singleton_or_sum_seeds():
    evidence = arrival_evidence((14, 14), factories=2)
    result = expand_fixture(two_level_configuration(evidence), evidence)
    assert {task["status"] for task in result["tasks"]} == {"supply_excluded"}
    for layout in result["layouts"]:
        assert [
            row["observed_arrivals"]
            for row in layout["supply_coverage"]["trajectories"]
        ] == [14, 14]
        assert "arrival_count_below_15N2" in layout["supply_exclusions"]


def test_arrival_window_is_half_open_and_minimum_seed_coverage_is_explicit():
    evidence = arrival_evidence((15,))
    evidence["trajectories"][0]["arrivals"].append(
        {"token_id": "late", "ready_at_us": 99, "deliverable_at_us": 100}
    )
    result = expand_fixture(two_level_configuration(evidence), evidence)
    for layout in result["layouts"]:
        assert layout["supply_coverage"]["trajectories"][0]["observed_arrivals"] == 15
        assert "minimum_arrival_seeds" in layout["supply_exclusions"]


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_token",
        "partial_window",
        "source_drift",
        "result_reuse",
        "window_after_end",
    ],
)
def test_two_level_rejects_incomplete_or_conflicting_frozen_arrivals(fault):
    evidence = arrival_evidence()
    if fault == "duplicate_token":
        evidence["trajectories"][0]["arrivals"].append(
            deepcopy(evidence["trajectories"][0]["arrivals"][0])
        )
    elif fault == "partial_window":
        evidence["trajectories"][0]["window_complete"] = False
    elif fault == "source_drift":
        evidence["trajectories"][0]["source_sha256"] = "f" * 64
    elif fault == "result_reuse":
        evidence["trajectories"][1]["result_sha256"] = evidence["trajectories"][0][
            "result_sha256"
        ]
    else:
        evidence["trajectories"][0]["duration_us"] = 99
    with pytest.raises(ValueError):
        expand_fixture(two_level_configuration(evidence), evidence)


def test_frozen_arrival_pin_detects_changes_even_with_other_valid_metadata():
    evidence = arrival_evidence()
    config = two_level_configuration(evidence)
    evidence["trajectories"][0]["arrivals"][0]["deliverable_at_us"] += 1
    with pytest.raises(ValueError, match="PIN"):
        expand_fixture(config, evidence)


def test_full_slm_area_includes_empty_parking_and_uses_common_budget():
    evidence = arrival_evidence()
    config = two_level_configuration(evidence)
    config.update(level2_counts=[1], grid_columns=[1], layout_families=["centralized"])
    layout = expand_fixture(config, evidence)["layouts"][0]
    plan = PlacementPlan.from_dict(layout["placement"])
    world = build_world(ExperimentSpec(3, 3), placement_plan=plan)
    world, _ = add_buffer_sites(
        world, {"exchange_parking": Position(**layout["parking_origin"])}
    )
    xs, ys = (
        [s.position.x for s in world.device.slm_sites],
        [s.position.y for s in world.device.slm_sites],
    )
    area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    assert layout["total_slm_bounding_area_um2"] == area
    assert area > layout["home_occupied_bounding_area_um2"]
    assert layout["configured_atoms"] == len(world.state.atoms) == 306
    config["budget"]["max_footprint_um2"] = (
        area + layout["home_occupied_bounding_area_um2"]
    ) / 2
    result = expand_fixture(config, evidence)
    assert {t["status"] for t in result["tasks"]} == {"budget_excluded"}
    assert result["layouts"][0]["budget_exclusions"] == ["max_footprint_um2"]


def test_identical_geometries_keep_family_aliases_without_duplicate_tasks():
    evidence = arrival_evidence(factories=1)
    config = two_level_configuration(evidence)
    config.update(level2_counts=[1], buffer_capacities=[1], grid_columns=[1])
    result = expand_fixture(config, evidence)
    assert any(len(row["layout_families"]) > 1 for row in result["layouts"])
    assert len(result["tasks"]) == len(result["layouts"]) * len(
        config["production_seeds"]
    )


def test_capacity_policies_have_distinct_layout_ids_with_shared_geometry():
    evidence = arrival_evidence()
    config = two_level_configuration(evidence)
    config.update(level2_counts=[1], grid_columns=[1], layout_families=["centralized"])
    result = expand_fixture(config, evidence)
    layouts = result["layouts"]
    assert len(layouts) == 2
    assert len({row["layout_id"] for row in layouts}) == 2
    assert len({row["geometry_layout_id"] for row in layouts}) == 1
    assert layouts[0]["placement"] == layouts[1]["placement"]
    assert {row["buffer_capacity"] for row in layouts} == {1, 2}
    by_id = {row["layout_id"]: row for row in layouts}
    assert all(
        task["buffer_capacity"] == by_id[task["layout_id"]]["buffer_capacity"]
        for task in result["tasks"]
    )


def two_source_evidence(first_counts=(32, 31), second_counts=(32, 31)):
    evidence = arrival_evidence(first_counts, factories=2)
    second = arrival_evidence(second_counts, factories=2)["trajectories"]
    for row in second:
        row["layout_id"] = canonical_hash({"synthetic_source_layout": "second"})
        row["trajectory_id"] = canonical_hash(
            {"layout_id": row["layout_id"], "seed": row["seed"]}
        )
        row["result_sha256"] = canonical_hash(
            {"synthetic_result_group": "second", "seed": row["seed"]}
        )
    evidence["trajectories"].extend(second)
    return evidence


def one_execution_configuration(evidence):
    config = two_level_configuration(evidence)
    config.update(
        level2_counts=[1],
        buffer_capacities=[1],
        grid_columns=[1],
        layout_families=["centralized"],
        production_seeds=[7],
    )
    return config


def test_distinct_arrival_sources_share_one_execution_and_retain_scoped_seeds():
    evidence = two_source_evidence()
    result = expand_fixture(one_execution_configuration(evidence), evidence)
    assert len(result["layouts"]) == len(result["tasks"]) == 1
    layout = result["layouts"][0]
    groups = layout["arrival_groups"]
    assert len(groups) == 2 and all(g["independently_eligible"] for g in groups)
    assert [g["arrival_group_id"] for g in groups] == sorted(
        g["arrival_group_id"] for g in groups
    )
    assert all([t["seed"] for t in g["trajectories"]] == [0, 1] for g in groups)
    assert {t["trajectory_id"] for g in groups for t in g["trajectories"]} == {
        t["trajectory_id"] for t in evidence["trajectories"]
    }
    assert (
        evidence["trajectories"][0]["arrivals"][0]["token_id"]
        == evidence["trajectories"][2]["arrivals"][0]["token_id"]
    )
    assert layout["arrival_group_id"] == groups[0]["arrival_group_id"]
    assert layout["source_layout_id"] == groups[0]["source_layout_id"]
    assert layout["supply_coverage"]["trajectories"] == groups[0]["trajectories"]
    single = arrival_evidence(factories=2)
    single_layout = expand_fixture(one_execution_configuration(single), single)[
        "layouts"
    ][0]
    assert layout["geometry_layout_id"] == single_layout["geometry_layout_id"]
    assert layout["layout_id"] == single_layout["layout_id"]
    assert result["arrival_evidence"] == evidence


@pytest.mark.parametrize(
    "counts,reason",
    [
        ((8, 8), "arrival_count_below_15N2"),
        ((16,), "minimum_arrival_seeds"),
    ],
)
def test_ineligible_source_groups_cannot_pool_counts_or_seed_coverage(counts, reason):
    evidence = two_source_evidence(counts, counts)
    result = expand_fixture(one_execution_configuration(evidence), evidence)
    assert len(result["layouts"]) == len(result["tasks"]) == 1
    layout = result["layouts"][0]
    assert result["tasks"][0]["status"] == "supply_excluded"
    assert all(
        not g["independently_eligible"] and reason in g["supply_exclusions"]
        for g in layout["arrival_groups"]
    )
    assert layout["arrival_group_id"] == min(
        g["arrival_group_id"] for g in layout["arrival_groups"]
    )
    assert (
        layout["supply_exclusions"] == layout["arrival_groups"][0]["supply_exclusions"]
    )


def test_one_independently_eligible_group_admits_cell_without_dropping_failed_group():
    evidence = two_source_evidence((32, 31), (8, 8))
    result = expand_fixture(one_execution_configuration(evidence), evidence)
    assert len(result["layouts"]) == len(result["tasks"]) == 1
    layout = result["layouts"][0]
    groups = layout["arrival_groups"]
    assert len(groups) == 2
    eligible = [g for g in groups if g["independently_eligible"]]
    assert len(eligible) == 1
    assert layout["arrival_group_id"] == eligible[0]["arrival_group_id"]
    assert layout["supply_exclusions"] == []
    assert result["tasks"][0]["status"] == "pending_execution"
    evidence["trajectories"].reverse()
    assert (
        expand_fixture(one_execution_configuration(evidence), evidence)["layouts"]
        == result["layouts"]
    )


def test_mixed_distance_is_only_an_explicit_protocol_dependency():
    evidence = arrival_evidence()
    config = two_level_configuration(evidence)
    config["distance_pairs"] = [[3, 5], [7, 7]]
    result = expand_fixture(config, evidence)
    assert result["layouts"] == result["tasks"] == []
    assert result["protocol_dependencies"][0]["distance_pair"] == [3, 5]
    assert result["protocol_dependencies"][0]["status"] == "unsupported_protocol"
    assert result["unavailable_sources"] == [
        {"distance": 7, "reason": "no_frozen_arrival_trajectories"}
    ]


@pytest.mark.parametrize(
    "fault", ["missing_area", "unbounded_area", "second_aod", "changed_gap"]
)
def test_two_level_requires_finite_explicit_common_budgets_and_existing_standard(fault):
    evidence = arrival_evidence()
    config = two_level_configuration(evidence)
    if fault == "missing_area":
        del config["budget"]["max_footprint_um2"]
    elif fault == "unbounded_area":
        config["budget"]["max_footprint_um2"] = None
    elif fault == "second_aod":
        config["aod_count"] = 2
    else:
        config["parking_gap_um"] = 80
    with pytest.raises(ValueError):
        expand_fixture(config, evidence)


def priority_group(name, counts, *, eligible=True):
    return {
        "arrival_group_id": name,
        "source_layout_id": f"source/{name}",
        "independently_eligible": eligible,
        "supply_exclusions": [] if eligible else ["minimum_arrival_seeds"],
        "trajectories": [
            {
                "trajectory_id": f"{name}/{seed}",
                "seed": seed,
                "observed_arrivals": count,
                "window_us": [0, 100],
                "source_sha256": "a" * 64,
                "result_sha256": canonical_hash({"name": name, "seed": seed}),
            }
            for seed, count in enumerate(counts)
        ],
    }


def priority_cell(
    name,
    *,
    distance=3,
    n1=2,
    n2=1,
    columns=1,
    family="boundary",
    capacity=1,
    groups=None,
):
    return {
        "layout_id": name,
        "geometry_layout_id": f"geometry/{distance}/{n1}/{n2}/{columns}/{family}",
        "distance": distance,
        "level1_count": n1,
        "level2_count": n2,
        "configured_atoms": (n1 + n2) * 6 * (2 * distance**2 - 1),
        "columns": columns,
        "layout_families": [family],
        "buffer_capacity": capacity,
        "budget_exclusions": [],
        "supply_exclusions": [],
        "arrival_groups": groups or [priority_group(f"{distance}/good", [30, 40])],
    }


def test_candidate_cap_round_robins_distances_and_prioritizes_pair_geometry_capacity(
    monkeypatch,
):
    from experiments.msd import campaign_plan

    def forbidden(*args, **kwargs):
        pytest.fail("Candidate priority is metadata-only")

    monkeypatch.setattr(campaign_plan, "build_world", forbidden)
    cells = []
    for distance in (3, 5, 7):
        for family in ("boundary", "centralized"):
            for capacity in (1, 2):
                cells.append(
                    priority_cell(
                        f"d{distance}/{family}/{capacity}",
                        distance=distance,
                        family=family,
                        capacity=capacity,
                    )
                )
        cells.append(
            priority_cell(f"d{distance}/more-columns", distance=distance, columns=2)
        )
        cells.append(
            priority_cell(
                f"d{distance}/less-supply",
                distance=distance,
                n1=1,
                groups=[priority_group(f"{distance}/less", [20, 20])],
            )
        )
        cells.append(
            priority_cell(
                f"d{distance}/more-receivers",
                distance=distance,
                n2=2,
                groups=[priority_group(f"{distance}/receivers", [40, 40])],
            )
        )
    original = deepcopy(cells)
    result = select_two_level_candidates(cells, max_candidate_layouts=12)
    assert result["selected_layout_ids"] == [
        f"d{d}/{family}/{capacity}"
        for family in ("boundary", "centralized")
        for capacity in (1, 2)
        for d in (3, 5, 7)
    ]
    assert cells == original
    assert result == select_two_level_candidates(
        list(reversed(cells)), max_candidate_layouts=12
    )
    assert {
        row["distance"]: row["selected_cells"] for row in result["distance_coverage"]
    } == {3: 4, 5: 4, 7: 4}
    pair = next(
        row
        for row in result["pair_priorities"]
        if row["distance"] == 3
        and row["level1_count"] == 2
        and row["level2_count"] == 1
    )
    assert pair["score"] == pytest.approx(0.3 / 15)


def test_candidate_priority_uses_best_independent_group_minimum_without_pooling():
    sources = [
        priority_group("uneven", [100, 15]),
        priority_group("steady", [20, 20]),
        priority_group("ineligible", [10000, 10000], eligible=False),
    ]
    pooled_would_win = priority_cell("two-sources", groups=sources)
    better = priority_cell(
        "independently-better", n1=1, groups=[priority_group("better", [25, 25])]
    )
    result = select_two_level_candidates(
        [pooled_would_win, better], max_candidate_layouts=1
    )
    assert result["selected_layout_ids"] == ["independently-better"]
    pair = next(row for row in result["pair_priorities"] if row["level1_count"] == 2)
    assert pair["priority_arrival_group_id"] == "steady"
    assert pair["minimum_arrivals_per_us"] == 0.2
    assert {
        row["arrival_group_id"]: row["minimum_arrivals_per_us"]
        for row in pair["source_group_scores"]
    } == {"steady": 0.2, "uneven": 0.15}


def test_capped_plan_keeps_all_unselected_candidates_visible_and_default_shape():
    evidence = arrival_evidence()
    config = two_level_configuration(evidence)
    original = expand_fixture(config, evidence)
    assert "candidate_selection" not in original
    assert all(
        "selection_exclusions" not in row
        for row in original["layouts"] + original["tasks"]
    )
    config["max_candidate_layouts"] = 1
    capped = expand_fixture(config, evidence)
    assert len(capped["layouts"]) == len(original["layouts"])
    assert len(capped["tasks"]) == len(original["tasks"])
    selected = capped["candidate_selection"]["selected_layout_ids"]
    assert len(selected) == 1
    for row in capped["layouts"]:
        assert row["selection_exclusions"] == (
            [] if row["layout_id"] in selected else ["max_candidate_layouts"]
        )
    for row in capped["tasks"]:
        assert row["status"] == (
            "pending_execution"
            if row["layout_id"] in selected
            else "selection_excluded"
        )
    assert capped["arrival_evidence"] == evidence


def test_candidate_cap_above_eligible_count_and_preexisting_exclusions():
    eligible = priority_cell("eligible")
    budget = {**priority_cell("budget"), "budget_exclusions": ["max_atoms"]}
    supply = {**priority_cell("supply"), "supply_exclusions": ["minimum_arrival_seeds"]}
    result = select_two_level_candidates(
        [budget, eligible, supply], max_candidate_layouts=12
    )
    assert result["selected_layout_ids"] == ["eligible"]
    assert len(result["candidates"]) == 3
    assert (
        select_two_level_candidates([], max_candidate_layouts=1)["selected_layout_ids"]
        == []
    )


@pytest.mark.parametrize("cap", [0, -1, True, 1.5])
def test_candidate_cap_requires_explicit_positive_integer(cap):
    with pytest.raises(ValueError, match="CANDIDATE.*LIMIT"):
        select_two_level_candidates([], max_candidate_layouts=cap)
