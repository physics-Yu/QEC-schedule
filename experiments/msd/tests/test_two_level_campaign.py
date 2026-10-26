"""Synthetic orchestration proofs only: no physical compilation or sampling."""

from copy import deepcopy

import pytest
from nadit_physical_compiler.experiments.journal import (
    append,
    directory_lock,
    write_json,
)
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd import campaign_arrivals, campaign_driver
from experiments.msd import two_level_campaign as driver
from experiments.msd.campaign_driver import _task
from experiments.msd.campaign_worker import _policy_artifacts


def fixture(tmp_path, monkeypatch, *, arrivals=16):
    source = {"synthetic_fixture": "source"}
    evidence = {
        "schema": "nadit.msd.arrival_evidence/1",
        "standard": "nadit.msd.standard/2",
        "source_identity": source,
        "source_sha256": canonical_hash(source),
        "coverage": {"complete": 1, "software_error": 1},
        "excluded_trajectories": [{"status": "software_error", "reason": "fixture"}],
        "trajectories": [
            {
                "trajectory_id": "a" * 64,
                "layout_id": "b" * 64,
                "result_sha256": "c" * 64,
                "source_sha256": canonical_hash(source),
                "distance": 3,
                "factory_count": 1,
                "seed": 0,
                "window_us": [0, 100],
                "duration_us": 100,
                "status": "complete",
                "window_complete": True,
                "arrivals": [
                    {
                        "token_id": f"fixture/{i}",
                        "ready_at_us": i,
                        "deliverable_at_us": i + 1,
                    }
                    for i in range(arrivals)
                ],
            }
        ],
    }
    proof = tmp_path / "synthetic-source-proof.json"
    write_json(proof, evidence)
    calls = []

    def freeze(plan, directory):
        calls.append((deepcopy(plan), directory))
        return driver._read(proof)

    monkeypatch.setattr(
        campaign_arrivals, "freeze_arrival_evidence", freeze, raising=False
    )
    candidate = {
        "schema": "nadit.msd.two_level_campaign/1",
        "standard": "nadit.msd.standard/2",
        "aod_count": 1,
        "distance_pairs": [[3, 3], [3, 5]],
        "level2_counts": [1],
        "buffer_capacities": [1, 2],
        "grid_columns": [1],
        "layout_families": ["centralized"],
        "production_seeds": [1, 2],
        "minimum_arrival_seeds": 1,
        "parking_gap_um": 40,
        "budget": {"max_atoms": 1000, "max_footprint_um2": 10000000},
    }
    config = {
        "budget": {
            "export_timeout_s": 30,
            "pilot_timeout_s": 30,
            "production_timeout_s": 30,
            "software_max_attempts": 1,
            "memory_bytes": 100000000,
            "calibration_timeout_s": 60,
        },
        "sink": {"kind": "ideal_external", "acknowledge_excluded_costs": True},
        "noise_params": {},
        "sampling": {"shots": 16, "seed": 0},
        "input_z_error": 0.01,
        "two_level": {
            "candidate_rule": candidate,
            "worker_seconds_fraction": 0.25,
            "pilot_seed": 99,
            "acknowledge_theory_transport_exclusions": True,
            "limits": {
                "raw_attempts": 8,
                "max_component_calls": 10000,
                "producer_max_cycles": 40,
                "consumer_max_cycles": 2,
                "level1_batches": 4,
                "level2_batches": 1,
            },
            "observation_rule": {
                "pilot_cycles": 2,
                "warmup_cycles": 0,
                "target_observation_cycles": 2,
                "minimum_observation_cycles": 1,
                "max_total_simulated_us": 10000,
                "software_safety_factor": 2,
            },
        },
    }
    payload = {
        "campaign_directory": str(tmp_path),
        "single_level_plan": {"synthetic_fixture": "single-level"},
        "configuration": config,
        "source_identity": source,
        "dependencies": {
            "actions": {"fixture": "a"},
            "probabilities": {"fixture": "p"},
        },
        "allocation": {"stage_worker_seconds": 100},
    }
    task = _task(
        "msd.two_level_driver",
        payload,
        config["budget"],
        "export_timeout_s",
        terminal=True,
    )
    return task, evidence, proof, calls


def test_freeze_admits_unique_capacity_cells_and_native_worker_payload(
    tmp_path, monkeypatch
):
    task, evidence, _, calls = fixture(tmp_path, monkeypatch)
    reply = driver.advance_two_level(task, tmp_path)
    assert reply["status"] == "needs_dependencies"
    children = reply["dependency_requests"]
    assert len(children) == 2 and len({row["task_id"] for row in children}) == 2
    assert len(calls) == 1
    assert len(reply["artifacts"]) == 4
    for child in children:
        assert child["kind"] == "msd.two_level_layout_driver"
        payload = child["payload"]
        assert payload["phase"] == "two_level"
        assert payload["allocation"]["layout_worker_seconds"] == 50
        assert payload["pilot_seed"] == 99
        assert payload["limits"] == {
            "raw_attempts": 8,
            "max_component_calls": 10000,
            "max_cycles": 2,
        }
        common = payload["common"]
        assert common["spec"]["pipelines"] == 2
        assert (
            common["two_level"]["level1_count"]
            == common["two_level"]["level2_count"]
            == 1
        )
        assert common["two_level"]["buffer_capacity"] == common["buffer_capacity"]
        assert common["arrival_evidence_sha256"] == canonical_hash(evidence)
        assert {row["seed"] for row in payload["trajectories"]} == {1, 2}
        assert all(
            trajectory[key] == payload[key]
            for trajectory in payload["trajectories"]
            for key in ("config_sha256", "source_sha256")
        )
    plan = driver._read(tmp_path / "two-level/candidate-plan.json")
    assert plan["protocol_dependencies"][0]["status"] == "unsupported_protocol"
    assert (
        plan["arrival_evidence"]["excluded_trajectories"]
        == evidence["excluded_trajectories"]
    )


def test_candidate_cap_allocates_only_selected_cells_without_losing_coverage(
    tmp_path, monkeypatch
):
    original, _, _, _ = fixture(tmp_path, monkeypatch)
    payload = original["payload"]
    payload["configuration"]["two_level"]["candidate_rule"]["max_candidate_layouts"] = 1
    task = _task(
        "msd.two_level_driver",
        payload,
        payload["configuration"]["budget"],
        "export_timeout_s",
        terminal=True,
    )
    reply = driver.advance_two_level(task, tmp_path)
    children = reply["dependency_requests"]
    assert len(children) == 1
    assert children[0]["payload"]["allocation"]["layout_worker_seconds"] == 100
    plan = reply["result"]["two_level_plan"]
    assert len(plan["layouts"]) == 2 and len(plan["tasks"]) == 4
    assert sum(row["status"] == "selection_excluded" for row in plan["tasks"]) == 2
    assert [children[0]["payload"]["layout_id"]] == plan["candidate_selection"][
        "selected_layout_ids"
    ]


def test_generated_policy_is_accepted_by_actual_worker_artifact_guard(
    tmp_path, monkeypatch
):
    task, _, _, _ = fixture(tmp_path, monkeypatch)
    child = driver.advance_two_level(task, tmp_path)["dependency_requests"][0]
    pilot = campaign_driver._drive(child, tmp_path)["dependency_requests"][0]
    result = {
        "level2_factories": ["factory1"],
        "case": {
            "status": "complete",
            "failure": None,
            "factories": {
                "factory0": {"status": "complete", "outputs": [{"handoff_at_us": 10}]},
                "factory1": {
                    "status": "complete",
                    "outputs": [
                        {
                            "cycle": i,
                            "token_id": f"synthetic/{i}",
                            "ready_at_us": end - 2,
                            "deliverable_at_us": end - 1,
                            "consumed_at_us": end - 1,
                            "released_at_us": end,
                            "delivery": {"synthetic_fixture": True},
                        }
                        for i, end in enumerate((100, 200))
                    ],
                },
            },
        },
    }
    relative = f"results/{pilot['task_id']}.json"
    write_json(tmp_path / "task_definitions" / f"{pilot['task_id']}.json", pilot)
    write_json(tmp_path / relative, result)
    write_json(
        tmp_path / "task_completions" / f"{pilot['task_id']}.json",
        {
            "task_id": pilot["task_id"],
            "status": "ok",
            "result_path": relative,
            "result_sha256": canonical_hash(result),
        },
    )
    append(
        tmp_path / "task_attempts.jsonl",
        {
            "task_id": pilot["task_id"],
            "kind": pilot["kind"],
            "run_id": "synthetic-pilot",
            "attempt": 1,
            "process_wall_s": 2,
        },
    )
    producers = campaign_driver._drive(child, tmp_path)["dependency_requests"]
    assert {row["kind"] for row in producers} == {"msd.two_level_produce"}
    for producer in producers:
        adapted = {**producer, "kind": "msd.produce"}
        assert _policy_artifacts(adapted) == [
            producer["payload"]["observation_policy_artifact"]
        ]


def test_resume_rechecks_original_proof_without_reexpanding_plan(tmp_path, monkeypatch):
    task, evidence, proof, calls = fixture(tmp_path, monkeypatch)
    first = driver.advance_two_level(task, tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("A committed plan must not reconstruct worlds on resume")

    monkeypatch.setattr(driver, "expand_two_level", forbidden)
    assert driver.advance_two_level(task, tmp_path) == first
    assert len(calls) == 2
    evidence["trajectories"][0]["arrivals"][0]["deliverable_at_us"] = 0.5
    write_json(proof, evidence)
    with pytest.raises(ValueError, match="ARRIVAL.*CHANGED"):
        driver.advance_two_level(task, tmp_path)


@pytest.mark.parametrize(
    "failed_name", ["arrivals.json", "candidate-plan.json", "frozen.json"]
)
def test_partial_publication_resumes_without_replacing_written_inputs(
    tmp_path, monkeypatch, failed_name
):
    task, _, _, _ = fixture(tmp_path, monkeypatch)
    original = driver.write_json

    def interrupted(path, document):
        if path.name == failed_name:
            raise OSError("synthetic interruption")
        original(path, document)

    monkeypatch.setattr(driver, "write_json", interrupted)
    with pytest.raises(OSError, match="synthetic interruption"):
        driver.advance_two_level(task, tmp_path)
    existing = {p.name: p.read_bytes() for p in (tmp_path / "two-level").glob("*.json")}
    monkeypatch.setattr(driver, "write_json", original)
    reply = driver.advance_two_level(task, tmp_path)
    assert reply["status"] == "needs_dependencies"
    assert all(
        (tmp_path / "two-level" / name).read_bytes() == content
        for name, content in existing.items()
    )


def test_partial_identity_rejects_config_drift_and_committed_missing_file(
    tmp_path, monkeypatch
):
    task, _, _, _ = fixture(tmp_path, monkeypatch)
    driver.advance_two_level(task, tmp_path)
    changed = deepcopy(task["payload"])
    changed["configuration"]["noise_params"] = {"changed": 0.1}
    changed_task = _task(
        "msd.two_level_driver",
        changed,
        changed["configuration"]["budget"],
        "export_timeout_s",
        terminal=True,
    )
    with pytest.raises(ValueError, match="IDENTITY.*CHANGED"):
        driver.advance_two_level(changed_task, tmp_path)
    (tmp_path / "two-level/arrivals.json").unlink()
    with pytest.raises(ValueError, match="FROZEN.*MISSING"):
        driver.advance_two_level(task, tmp_path)


def test_terminal_children_preserve_failures_and_complete_coverage(
    tmp_path, monkeypatch
):
    task, evidence, _, _ = fixture(tmp_path, monkeypatch)
    first = driver.advance_two_level(task, tmp_path)
    for index, child in enumerate(first["dependency_requests"]):
        write_json(
            tmp_path / "task_completions" / f"{child['task_id']}.json",
            {
                "task_id": child["task_id"],
                "status": "ok" if index == 0 else "software_error",
                "reason": {"synthetic_fixture": True},
            },
        )
    final = driver.advance_two_level(task, tmp_path)
    assert final["status"] == "software_error"
    assert len(final["result"]["children"]) == 2
    assert final["result"]["arrival_coverage"] == evidence["coverage"]
    assert len(final["result"]["two_level_plan"]["tasks"]) == 4


def test_supply_exclusions_are_terminal_plan_coverage_not_software_failure(
    tmp_path, monkeypatch
):
    task, _, _, _ = fixture(tmp_path, monkeypatch, arrivals=14)
    reply = driver.advance_two_level(task, tmp_path)
    assert reply["status"] == "ok"
    assert reply["result"]["children"] == []
    assert {row["status"] for row in reply["result"]["two_level_plan"]["tasks"]} == {
        "supply_excluded"
    }


def test_existing_writer_defers_before_reading_source_evidence(tmp_path, monkeypatch):
    task, _, _, calls = fixture(tmp_path, monkeypatch)
    with directory_lock(tmp_path / "two-level"):
        reply = driver.advance_two_level(task, tmp_path)
    assert reply["status"] == "deferred"
    assert calls == []


def test_global_warm_cost_mode_reaches_two_level_layout_drivers(tmp_path, monkeypatch):
    task, _, _, _ = fixture(tmp_path, monkeypatch)
    config = task["payload"]["configuration"]
    config["pilot_cost_model"] = {
        "mode": "cached_replay",
        "future_miss_reserve_fraction": 0.25,
    }
    task = _task(
        "msd.two_level_driver",
        task["payload"],
        config["budget"],
        "export_timeout_s",
        terminal=True,
    )
    reply = driver.advance_two_level(task, tmp_path)
    assert all(
        child["payload"]["pilot_cost_model"] == config["pilot_cost_model"]
        for child in reply["dependency_requests"]
    )
