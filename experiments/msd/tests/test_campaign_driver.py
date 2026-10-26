"""Pure dependency orchestration with synthetic pilot evidence; no physics runs."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nadit_physical_compiler.experiments.journal import append, write_json
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd import campaign_driver as driver


def configuration():
    return {
        "schema": "nadit.msd.campaign/1",
        "standard": "nadit.msd.standard/2",
        "aod_count": 1,
        "distances": [3, 5, 7],
        "factory_counts": [1, 2, 4, 8],
        "production_seeds": list(range(16)),
        "budget": {
            "workers": 4,
            "max_atoms": 10000,
            "memory_bytes": 100000000,
            "calibration_timeout_s": 60,
            "production_timeout_s": 100,
            "pilot_timeout_s": 60,
            "export_timeout_s": 30,
            "export_reserve_s": 30,
            "export_reserve_bytes": 1000000,
            "campaign_timeout_s": 10000,
            "max_storage_bytes": 1000000000,
            "software_max_attempts": 1,
            "max_artifact_refreshes": 1,
        },
        "sink": {"kind": "ideal_external", "acknowledge_excluded_costs": True},
        "noise_params": {},
        "sampling": {"shots": 16, "seed": 11},
        "pilot_seed": 99,
        "input_z_error": 0.01,
        "limits": {
            "raw_attempts": 8,
            "batches": 4,
            "max_component_calls": 10000,
            "max_cycles": 20,
        },
        "observation_rule": {
            "pilot_cycles": 2,
            "warmup_cycles": 1,
            "target_observation_cycles": 3,
            "minimum_observation_cycles": 2,
            "max_total_simulated_us": 10000,
            "software_safety_factor": 2,
        },
    }


def resolve(config, directory, evidence=None):
    return driver.resolve_campaign(
        config,
        source_identity={"test_fixture": "source"},
        action_dependencies={"fixture": "actions"},
        probability_dependencies={"fixture": "probabilities"},
        campaign_directory=directory,
        acceptance_evidence=evidence,
    )


def multistage_configuration():
    from experiments.msd.tests.test_campaign_plan import (
        arrival_evidence,
        two_level_configuration,
    )

    config = configuration()
    rule = two_level_configuration(arrival_evidence())
    del rule["arrival_evidence_sha256"], rule["arrival_source_sha256"]
    config["two_level"] = {
        "candidate_rule": rule,
        "worker_seconds_fraction": 0.4,
        "pilot_seed": 42,
        "limits": {
            "raw_attempts": 8,
            "max_component_calls": 20000,
            "producer_max_cycles": 100,
            "consumer_max_cycles": 4,
            "level1_batches": 4,
            "level2_batches": 2,
        },
        "observation_rule": config["observation_rule"],
        "acknowledge_theory_transport_exclusions": True,
    }
    return config


def interface_evidence(tmp_path, kind):
    evidence = {
        "evidence_kind": kind,
        "passed": True,
        "source_identity": {"test_fixture": "source"},
        "checks": ["synthetic interface control only"],
    }
    path = tmp_path / f"{kind}.json"
    write_json(path, evidence)
    return {
        "path": str(path),
        "sha256": canonical_hash(evidence),
        "hash_kind": "canonical_json",
    }


def test_multistage_reserves_worker_budget_and_requires_both_acceptance_gates(tmp_path):
    config = multistage_configuration()
    kwargs = {
        "source_identity": {"test_fixture": "source"},
        "action_dependencies": {"fixture": "actions"},
        "probability_dependencies": {"fixture": "probabilities"},
        "campaign_directory": tmp_path,
        "acceptance_evidence": interface_evidence(
            tmp_path, "physical_interface_acceptance"
        ),
    }
    gated = driver.resolve_campaign(config, **kwargs)
    assert gated["campaign"]["runnable"] is False
    plan = driver.resolve_campaign(
        config,
        **kwargs,
        two_level_evidence=interface_evidence(tmp_path, "physical_two_level_delivery"),
    )
    assert plan["campaign"]["runnable"] and plan["campaign"]["two_level_ready"]
    l1 = [task for task in plan["tasks"] if task["kind"] == "msd.layout_driver"]
    l2 = next(task for task in plan["tasks"] if task["kind"] == "msd.two_level_driver")
    summary = next(task for task in plan["tasks"] if task["kind"] == "msd.summarize")
    assert set(l2["dependencies"]) == {task["task_id"] for task in l1}
    assert l2["dependency_mode"] == "terminal"
    assert set(summary["dependencies"]) == {task["task_id"] for task in [*l1, l2]}
    allocation = plan["campaign"]["allocation_policy"]
    available = (10000 - 30) * 4
    assert allocation["available_worker_seconds"] == available * 0.6
    assert l2["payload"]["allocation"]["stage_worker_seconds"] == available * 0.4
    assert allocation["layout_worker_seconds"] * len(l1) + l2["payload"]["allocation"][
        "stage_worker_seconds"
    ] == pytest.approx(available)
    assert plan["budget"]["campaign_timeout_s"] == 10000


@pytest.mark.parametrize("damage", ("fraction", "unresolved", "atoms", "ack", "pins"))
def test_multistage_unresolved_or_expanded_budget_is_rejected(tmp_path, damage):
    config = multistage_configuration()
    stage = config["two_level"]
    if damage == "fraction":
        stage["worker_seconds_fraction"] = 1
    elif damage == "unresolved":
        del stage["limits"]["producer_max_cycles"]
    elif damage == "atoms":
        stage["candidate_rule"]["budget"]["max_atoms"] = (
            config["budget"]["max_atoms"] + 1
        )
    elif damage == "ack":
        stage["acknowledge_theory_transport_exclusions"] = False
    else:
        stage["candidate_rule"]["arrival_evidence_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        resolve(config, tmp_path)


def complete(directory, task, result, *, attempt=1):
    identity = task["task_id"]
    relative = f"results/{identity}.json"
    write_json(directory / "task_definitions" / f"{identity}.json", task)
    write_json(directory / relative, result)
    write_json(
        directory / "task_completions" / f"{identity}.json",
        {
            "task_id": identity,
            "kind": task["kind"],
            "status": "ok",
            "attempts": attempt,
            "result_path": relative,
            "result_sha256": canonical_hash(result),
        },
    )


def prepared_driver(tmp_path, config=None):
    config = configuration() if config is None else config
    config.update(distances=[3], factory_counts=[1], production_seeds=[0, 1])
    resolved = resolve(config, tmp_path)
    task = next(row for row in resolved["tasks"] if row["kind"] == "msd.layout_driver")
    initial = driver.execute_task(task)
    assert initial["status"] == "needs_dependencies"
    pilot = initial["dependency_requests"][0]
    outputs = [
        {
            "cycle": index,
            "token_id": f"fixture/{index}",
            "ready_at_us": end - 2,
            "deliverable_at_us": end - 1,
            "consumed_at_us": end - 1,
            "released_at_us": end,
            "delivery": {"test_fixture": True},
        }
        for index, end in enumerate((120, 220))
    ]
    complete(
        tmp_path,
        pilot,
        {
            "case": {
                "status": "complete",
                "factories": {"factory0": {"status": "complete", "outputs": outputs}},
            }
        },
        attempt=2,
    )
    child_body = {
        "kind": "msd.calibrate",
        "payload": {"fixture": True},
        "dependencies": [],
        "timeout_s": 1,
        "max_attempts": 1,
        "memory_bytes": 100000,
    }
    child = {"task_id": canonical_hash(child_body), **child_body}
    complete(tmp_path, child, {"test_fixture": True})
    for _ in range(2):
        append(
            tmp_path / "task_edges.jsonl",
            {"task_id": pilot["task_id"], "add": [child["task_id"]]},
        )
    for work, attempt, seconds in ((pilot, 1, 1), (child, 1, 3), (pilot, 2, 2)):
        append(
            tmp_path / "task_attempts.jsonl",
            {
                "task_id": work["task_id"],
                "kind": work["kind"],
                "run_id": f"{work['task_id']}.a{attempt}",
                "attempt": attempt,
                "worker_wall_s": seconds,
            },
        )
    return task, pilot, resolved


def prepared_two_level_driver(tmp_path):
    original, old_pilot, _ = prepared_driver(tmp_path)
    task = json.loads(json.dumps(original))
    task.pop("task_id")
    task["kind"] = "msd.two_level_layout_driver"
    payload = task["payload"]
    payload["phase"] = "two_level"
    payload["common"].update(
        geometry_layout_id="1" * 64,
        buffer_capacity=1,
        arrival_evidence_sha256="2" * 64,
        two_level={
            "level1_count": 1,
            "level2_count": 1,
            "buffer_capacity": 1,
            "producer_max_cycles": 100,
            "consumer_max_cycles": 4,
            "level1_batches": 4,
            "level2_batches": 2,
            "parking_origin": {"x": -100, "y": -60},
            "output_sink": payload["common"]["output_sink"],
            "acknowledge_theory_transport_exclusions": True,
        },
    )
    payload["limits"] = {
        "raw_attempts": 8,
        "max_component_calls": 20000,
        "max_cycles": 4,
    }
    task["task_id"] = canonical_hash(task)
    initial = driver.execute_task(task)
    pilot = initial["dependency_requests"][0]
    assert pilot["kind"] == "msd.two_level_pilot"
    old = json.loads(
        (tmp_path / "results" / f"{old_pilot['task_id']}.json").read_text()
    )
    l2 = old["case"]["factories"]["factory0"]
    result = {
        "level2_factories": ["factory1"],
        "case": {
            "status": "complete",
            "failure": None,
            "factories": {
                "factory0": {"status": "complete", "outputs": [{"handoff_at_us": 10}]},
                "factory1": l2,
            },
        },
    }
    complete(tmp_path, pilot, result)
    append(
        tmp_path / "task_attempts.jsonl",
        {
            "task_id": pilot["task_id"],
            "kind": pilot["kind"],
            "run_id": f"{pilot['task_id']}.a1",
            "attempt": 1,
            "process_wall_s": 30,
        },
    )
    return task, pilot, result


def test_two_level_driver_uses_l2_policy_and_whole_run_cost(tmp_path):
    task, pilot, _ = prepared_two_level_driver(tmp_path)
    reply = driver.execute_task(task)
    producers = reply["dependency_requests"]
    assert len(producers) == 2
    assert {row["kind"] for row in producers} == {"msd.two_level_produce"}
    for row in producers:
        payload = row["payload"]
        assert payload["observation_policy"]["output_factory_ids"] == ["factory1"]
        assert payload["observation_policy"]["pilot_worker_seconds"] == 30
        assert (
            payload["geometry_layout_id"] == "1" * 64
            and payload["buffer_capacity"] == 1
        )
        assert payload["limits"] == task["payload"]["limits"]
        assert row["dependencies"] == [pilot["task_id"]]
    assert driver.execute_task(task)["dependency_requests"] == producers


def test_two_level_policy_rejects_pilot_with_wrong_output_layer(tmp_path):
    task, pilot, result = prepared_two_level_driver(tmp_path)
    result["level2_factories"] = ["factory0"]
    complete(tmp_path, pilot, result)
    with pytest.raises(ValueError, match="TWO_LEVEL_PILOT_OUTPUT_FACTORIES_MISMATCH"):
        driver.execute_task(task)


def test_resolution_has_thirty_independent_drivers_and_terminal_summary():
    config = configuration()
    result = resolve(config, "/home/yyq/msd-study")
    drivers = [row for row in result["tasks"] if row["kind"] == "msd.layout_driver"]
    summary = next(row for row in result["tasks"] if row["kind"] == "msd.summarize")
    assert len(drivers) == 30
    assert sum(len(row["payload"]["trajectories"]) for row in drivers) == 480
    assert all(row["dependencies"] == [] for row in drivers)
    assert all(row["dependency_mode"] == "terminal" for row in drivers)
    assert set(summary["dependencies"]) == {row["task_id"] for row in drivers}
    assert summary["dependency_mode"] == "terminal"
    assert result["finalization"] == {
        "task_ids": [summary["task_id"]],
        "reserve_seconds": 30,
        "reserve_bytes": 1000000,
    }
    allocation = result["campaign"]["allocation_policy"]
    assert allocation["configured_worker_seconds"] == 40000
    assert allocation["reserved_worker_seconds"] == 120
    assert allocation["available_worker_seconds"] == 39880
    assert allocation["layout_worker_seconds"] == 39880 / 30
    assert all(row["payload"]["allocation"] == allocation for row in drivers)
    assert result["campaign"]["campaign_directory"] == "/home/yyq/msd-study"
    assert all(
        row["payload"]["common"]["cache_root"] == "/home/yyq/msd-study/cache"
        for row in drivers
    )
    assert (
        result["campaign"]["runnable"] is False
        and result["campaign"]["two_level_ready"] is False
    )
    assert result == resolve(config, "/home/yyq/msd-study")


@pytest.mark.parametrize("field", ("sink", "budget", "observation_rule"))
def test_missing_configuration_is_not_filled_with_defaults(tmp_path, field):
    config = configuration()
    del config[field]
    with pytest.raises(ValueError, match="INCOMPLETE_MSD_CAMPAIGN"):
        resolve(config, tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("export_reserve_s", None),
        ("export_reserve_bytes", None),
        ("export_reserve_s", 0),
        ("export_reserve_s", 10000),
        ("export_reserve_bytes", 0.5),
        ("export_reserve_bytes", 1000000000),
    ),
)
def test_export_reserves_must_be_explicit_and_inside_campaign_caps(
    tmp_path, field, value
):
    config = configuration()
    if value is None:
        del config["budget"][field]
    else:
        config["budget"][field] = value
    with pytest.raises(ValueError, match="UNRESOLVED_CAMPAIGN_INPUT|EXPORT_RESERVE"):
        resolve(config, tmp_path)


def test_reserved_export_time_reduces_frozen_observation_window(tmp_path):
    config = configuration()
    config["budget"]["campaign_timeout_s"] = 41
    task, _pilot, _resolved = prepared_driver(tmp_path, config)
    result = driver.execute_task(task)
    frozen = json.loads(Path(result["artifacts"][0]["path"]).read_text())
    assert frozen["identity"]["allocation"]["layout_worker_seconds"] == 44
    assert frozen["policy"]["observation_cycles"] == 2


def test_only_source_matched_interface_evidence_enables_single_level(tmp_path):
    config = configuration()
    config["two_level_ready"] = True
    evidence = {
        "passed": True,
        "evidence_kind": "physical_interface_acceptance",
        "source_identity": {"test_fixture": "source"},
        "checks": ["fixture only"],
    }
    path = tmp_path / "evidence.json"
    write_json(path, evidence)
    descriptor = {
        "path": str(path),
        "sha256": canonical_hash(evidence),
        "hash_kind": "canonical_json",
    }
    resolved = resolve(config, tmp_path / "runtime", descriptor)
    assert resolved["campaign"]["runnable"] is True
    assert resolved["campaign"]["two_level_ready"] is False
    evidence["source_identity"] = {"test_fixture": "changed"}
    write_json(path, evidence)
    descriptor["sha256"] = canonical_hash(evidence)
    with pytest.raises(ValueError, match="ACCEPTANCE_EVIDENCE_MISMATCH"):
        resolve(config, tmp_path / "runtime", descriptor)


def test_policy_freezes_unique_pilot_cost_before_production_and_survives_extra_work(
    tmp_path,
):
    task, pilot, _ = prepared_driver(tmp_path)
    result = driver.execute_task(task)
    assert result["status"] == "needs_dependencies"
    producers = result["dependency_requests"]
    assert len(producers) == 2 and all(
        row["kind"] == "msd.produce" for row in producers
    )
    artifact = producers[0]["payload"]["observation_policy_artifact"]
    frozen = json.loads(Path(artifact["path"]).read_text())
    assert canonical_hash(frozen) == artifact["sha256"]
    assert frozen["policy"]["pilot_worker_seconds"] == 6
    assert len(frozen["cost_ledger"]) == 3
    assert frozen["pilot_evidence"]["task_id"] == pilot["task_id"]
    assert all(
        row["payload"]["observation_policy"] == frozen["policy"] for row in producers
    )
    append(
        tmp_path / "task_attempts.jsonl",
        {
            "task_id": "unrelated",
            "kind": "msd.produce",
            "run_id": "unrelated.a1",
            "attempt": 1,
            "worker_wall_s": 100000,
        },
    )
    replay = driver.execute_task(task)
    assert replay["dependency_requests"] == producers
    for producer in producers:
        complete(tmp_path, producer, {"test_fixture": "production"})
    finished = driver.execute_task(task)
    assert finished["status"] == "ok"
    assert finished["result"]["production_task_ids"] == [
        row["task_id"] for row in producers
    ]


@pytest.mark.parametrize("damage", ("changed", "missing"))
def test_frozen_policy_corruption_never_silently_resolves_a_new_window(
    tmp_path, damage
):
    task, _, _ = prepared_driver(tmp_path)
    result = driver.execute_task(task)
    path = Path(result["artifacts"][0]["path"])
    if damage == "missing":
        path.unlink()
    else:
        frozen = json.loads(path.read_text())
        frozen["policy"]["stop_us"] += 1
        write_json(path, frozen)
    with pytest.raises(ValueError, match="FROZEN_OBSERVATION_POLICY"):
        driver.execute_task(task)


def test_summary_reuses_saved_campaign_export_with_failed_layouts_visible(
    tmp_path, monkeypatch
):
    from experiments.msd import campaign

    resolved = resolve(configuration(), tmp_path)
    write_json(tmp_path / "task_plan.json", resolved)
    summary = next(row for row in resolved["tasks"] if row["kind"] == "msd.summarize")
    seen = []

    def export(plan, directory, *, plots):
        seen.append((plan, directory, plots))
        result = {"fixture": True, "status": "incomplete", "failed_layouts": 1}
        write_json(directory / "report/summary.json", result)
        return result

    monkeypatch.setattr(campaign, "summarize_saved", export)
    result = driver.execute_task(summary)
    assert result["status"] == "ok" and result["result"]["status"] == "incomplete"
    assert seen == [(resolved, tmp_path, True)]
    assert result["artifacts"][0]["path"] == str(tmp_path / "report/summary.json")


def test_failed_seed_cannot_release_driver_or_summary_while_peer_is_pending(tmp_path):
    from nadit_physical_compiler.experiments.task_plan import (
        TaskPlanState,
        validate_plan,
    )

    task, _pilot, resolved = prepared_driver(tmp_path / "fixture")
    producers = driver.execute_task(task)["dependency_requests"]
    waiting = {key: value for key, value in task.items() if key != "task_id"}
    waiting["dependencies"] = [row["task_id"] for row in producers]
    waiting = {"task_id": canonical_hash(waiting), **waiting}
    summary = {
        key: value for key, value in resolved["tasks"][-1].items() if key != "task_id"
    }
    summary["dependencies"] = [waiting["task_id"]]
    summary = {"task_id": canonical_hash(summary), **summary}
    for producer in producers:
        producer["dependencies"] = []
        producer["task_id"] = canonical_hash(
            {key: value for key, value in producer.items() if key != "task_id"}
        )
    waiting["dependencies"] = [row["task_id"] for row in producers]
    waiting["task_id"] = canonical_hash(
        {key: value for key, value in waiting.items() if key != "task_id"}
    )
    summary["dependencies"] = [waiting["task_id"]]
    summary["task_id"] = canonical_hash(
        {key: value for key, value in summary.items() if key != "task_id"}
    )
    state = TaskPlanState(
        validate_plan(
            {
                "schema": "nadit.task_plan/1",
                "tasks": [*producers, waiting, summary],
                "budget": {"campaign_timeout_s": 10, "max_storage_bytes": 10000000},
            }
        ),
        tmp_path / "state",
        {"fixture": True},
        1,
        "fixture:execute",
        lambda: None,
    )
    state.completed[producers[0]["task_id"]] = {"status": "software_error"}
    assert {row["task_id"] for row in state.ready_runs()} == {producers[1]["task_id"]}
    state.completed[producers[1]["task_id"]] = {"status": "ok"}
    assert {row["task_id"] for row in state.ready_runs()} == {waiting["task_id"]}
    state.completed[waiting["task_id"]] = {"status": "software_error"}
    assert {row["task_id"] for row in state.ready_runs()} == {summary["task_id"]}


def test_software_accounting_deduplicates_attempts_and_keeps_missing_stages(tmp_path):
    rows = [
        {
            "run_id": "calib.a1",
            "task_id": "calib",
            "attempt": 1,
            "kind": "msd.calibrate",
            "worker_wall_s": 8,
            "process_wall_s": 10,
            "software_seconds": {
                "cold_calibration": 5,
                "action_calibration": 4,
                "probability_calibration": 1,
                "validation": 1,
                "cache_load": 2,
            },
            "runner_software_seconds": {"artifact_validation": 0.2},
        },
        {
            "run_id": "pilot.a1",
            "task_id": "pilot",
            "attempt": 1,
            "kind": "msd.pilot",
            "worker_wall_s": 3,
            "software_seconds": {"fast_execution": 2, "cache_load": 0.5},
        },
        {
            "run_id": "produce.a1",
            "task_id": "produce",
            "attempt": 1,
            "kind": "msd.produce",
            "worker_wall_s": 1,
        },
    ]
    for row in [*rows, rows[0]]:
        append(tmp_path / "task_attempts.jsonl", row)
    result = driver.software_accounting(tmp_path, current_task_id="summary")
    assert result["unique_attempts"] == 3 and result["duplicate_rows_ignored"] == 1
    assert result["stages"]["cold_calibration"] == {
        "sum_seconds": 5,
        "n_reported": 1,
        "n_missing": 2,
    }
    assert result["stages"]["export"] == {
        "sum_seconds": None,
        "n_reported": 0,
        "n_missing": 3,
    }
    assert result["runner_artifact_validation"]["sum_seconds"] == 0.2
    assert result["process_wall_by_kind"]["msd.calibrate"]["sum_seconds"] == 10
    assert result["worker_wall_by_kind"]["msd.calibrate"]["sum_seconds"] == 8
    assert result["stage_timers_not_additive_to_worker_wall"]


def test_pilot_budget_uses_process_clock_including_startup(tmp_path):
    task, _pilot, _ = prepared_driver(tmp_path)
    path = tmp_path / "task_attempts.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["process_wall_s"] = row["worker_wall_s"] + 1
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    reply = driver.execute_task(task)
    assert reply["status"] == "needs_dependencies"
    frozen = json.loads(
        (
            tmp_path / "policies" / task["payload"]["layout_id"] / "policy.json"
        ).read_text()
    )
    assert frozen["policy"]["pilot_worker_seconds"] == 9
    assert {row["timing_basis"] for row in frozen["cost_ledger"]} == {"process_wall_s"}


def test_incomplete_physical_pilot_is_budget_excluded_without_production(tmp_path):
    task, pilot, _ = prepared_driver(tmp_path)
    complete(
        tmp_path,
        pilot,
        {
            "case": {
                "status": "partial_failure",
                "factories": {
                    "factory0": {"status": "input_supply_exhausted", "outputs": []}
                },
            }
        },
        attempt=2,
    )
    result = driver.execute_task(task)
    assert result["status"] == "budget_exceeded"
    assert result["reason"] == "PILOT_INCOMPLETE"
    assert "dependency_requests" not in result


def prepared_warm_driver(tmp_path, *, reserve=0.25):
    """Synthetic cold/warm dependency attempts, including a new warm-prefix miss."""
    config = configuration()
    config["budget"].update(campaign_timeout_s=1000, production_timeout_s=10000)
    config["pilot_cost_model"] = {
        "mode": "cached_replay",
        "future_miss_reserve_fraction": reserve,
    }
    task, cold, _ = prepared_driver(tmp_path, config)
    cold_path = tmp_path / "results" / f"{cold['task_id']}.json"
    result = json.loads(cold_path.read_text())
    result["case"].update(
        seed=task["payload"]["pilot_seed"], case_id="synthetic_protocol"
    )
    result["case_sha256"] = canonical_hash(result["case"])
    result["software_seconds"] = {"setup": 999}
    complete(tmp_path, cold, result, attempt=2)
    attempts_path = tmp_path / "task_attempts.jsonl"
    rows = [json.loads(line) for line in attempts_path.read_text().splitlines()]
    for row, seconds, validation, status in zip(
        rows,
        [1, 2000, 5],
        [None, 3, 1],
        ["needs_dependencies", "ok", "ok"],
        strict=True,
    ):
        row.update(process_wall_s=seconds, status=status)
        if validation is not None:
            row["runner_software_seconds"] = {"artifact_validation": validation}
    attempts_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    request = driver.execute_task(task)
    assert request["status"] == "needs_dependencies"
    warm = request["dependency_requests"][0]
    assert warm["kind"] == cold["kind"] and warm["task_id"] != cold["task_id"]
    assert warm["payload"]["pilot_role"] == "warm_replay"
    assert warm["payload"]["replay_of"] == cold["task_id"]
    assert warm["dependencies"] == [cold["task_id"]]
    assert {
        key: value
        for key, value in warm["payload"].items()
        if key not in {"pilot_role", "replay_of"}
    } == cold["payload"]
    warm_result = deepcopy(result)
    warm_result["software_seconds"] = {"setup": 0.1}
    complete(tmp_path, warm, warm_result, attempt=2)
    completion_path = tmp_path / "task_completions" / f"{warm['task_id']}.json"
    completion = json.loads(completion_path.read_text())
    completion["run_id"] = f"{warm['task_id']}.a2"
    write_json(completion_path, completion)
    calibration = driver._task(
        "msd.calibrate",
        {"synthetic_fixture": "warm-prefix-miss"},
        config["budget"],
        "calibration_timeout_s",
    )
    complete(tmp_path, calibration, {"synthetic_fixture": True})
    append(
        tmp_path / "task_edges.jsonl",
        {"task_id": warm["task_id"], "add": [calibration["task_id"]]},
    )
    for item, attempt, seconds, validation, status in (
        (warm, 1, 10, None, "needs_dependencies"),
        (calibration, 1, 100, 2, "ok"),
        (warm, 2, 20, 2, "ok"),
    ):
        record = {
            "task_id": item["task_id"],
            "kind": item["kind"],
            "run_id": f"{item['task_id']}.a{attempt}",
            "attempt": attempt,
            "process_wall_s": seconds,
            "status": status,
        }
        if validation is not None:
            record["runner_software_seconds"] = {"artifact_validation": validation}
        append(attempts_path, record)
    return task, cold, warm, warm_result


def test_cached_replay_keeps_cold_and_prefix_cost_once_and_admits_measured_warm_window(
    tmp_path,
):
    task, cold, warm, _ = prepared_warm_driver(tmp_path)
    reply = driver.execute_task(task)
    assert reply["status"] == "needs_dependencies"
    assert {row["kind"] for row in reply["dependency_requests"]} == {"msd.produce"}
    envelope = json.loads(Path(reply["artifacts"][0]["path"]).read_text())
    assert (
        len(envelope["cost_ledger"])
        == len({row["run_id"] for row in envelope["cost_ledger"]})
        == 6
    )
    assert envelope["policy"]["pilot_worker_seconds"] == 2144
    assert envelope["policy"]["observation_cycles"] == 3
    cost = envelope["pilot_cost_model"]
    assert cost["cold_worker_seconds"] == 2010
    assert cost["warm_incremental_worker_seconds"] == 134
    assert cost["warm_replay_worker_seconds"] == 22
    assert cost["future_miss_reserved_worker_seconds"] == 434
    assert cost["available_worker_seconds_per_seed"] == 651
    assert cost["reserve_is_hard_quota"] is False
    assert envelope["pilot_evidence"]["task_id"] == cold["task_id"]
    assert envelope["warm_pilot_evidence"]["task_id"] == warm["task_id"]
    assert (
        driver.execute_task(task)["dependency_requests"] == reply["dependency_requests"]
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing_process",
        "missing_validation",
        "case_changed",
        "case_hash_missing",
        "wrong_seed",
    ],
)
def test_warm_replay_requires_measured_cost_and_identical_verified_case(
    tmp_path, damage
):
    task, _, warm, result = prepared_warm_driver(tmp_path)
    if damage.startswith("missing_"):
        path = tmp_path / "task_attempts.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        target = next(row for row in rows if row["run_id"] == f"{warm['task_id']}.a2")
        del target[
            "process_wall_s"
            if damage == "missing_process"
            else "runner_software_seconds"
        ]
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    else:
        if damage == "case_hash_missing":
            del result["case_sha256"]
        else:
            result["case"]["seed" if damage == "wrong_seed" else "case_id"] = "changed"
            result["case_sha256"] = canonical_hash(result["case"])
        path = tmp_path / "results" / f"{warm['task_id']}.json"
        write_json(path, result)
        completion_path = tmp_path / "task_completions" / f"{warm['task_id']}.json"
        completion = json.loads(completion_path.read_text())
        completion["result_sha256"] = canonical_hash(result)
        write_json(completion_path, completion)
    with pytest.raises(ValueError, match="WARM_"):
        driver.execute_task(task)


def test_fixed_future_miss_reserve_strictly_reduces_per_seed_budget(tmp_path):
    budgets = []
    for name, reserve in (("none", 0), ("half", 0.5)):
        folder = tmp_path / name
        task, _, _, _ = prepared_warm_driver(folder, reserve=reserve)
        reply = driver.execute_task(task)
        envelope = json.loads(Path(reply["artifacts"][0]["path"]).read_text())
        budgets.append(
            envelope["pilot_cost_model"]["available_worker_seconds_per_seed"]
        )
    assert budgets == [868, 434]


@pytest.mark.parametrize("reserve", [-0.1, 1, True, float("nan")])
def test_invalid_warm_cost_reserve_is_rejected_before_task_resolution(
    tmp_path, reserve
):
    config = configuration()
    config["pilot_cost_model"] = {
        "mode": "cached_replay",
        "future_miss_reserve_fraction": reserve,
    }
    with pytest.raises(ValueError, match="PILOT_COST|future_miss_reserve_fraction"):
        resolve(config, tmp_path)
