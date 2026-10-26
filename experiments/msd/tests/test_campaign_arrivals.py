"""Arrival evidence must be backed by distinct completed runner trajectories."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nadit_physical_compiler.experiments.journal import write_json
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd import campaign_arrivals
from experiments.msd.campaign_plan import expand_single_level
from experiments.msd.production_metrics import summarize_production
from experiments.msd.tests.test_production_metrics import fixture as activity_fixture
from modules.logical_compiler.src.protocols.resources import ResourceLedger


def saved_campaign(directory, *, seeds=(0, 1, 2), window=(0, 24)):
    """Synthetic runner files with real ledger transitions; no physics is executed."""
    plan = expand_single_level(
        {
            "standard": "nadit.msd.standard/2",
            "aod_count": 1,
            "distances": [3],
            "factory_counts": [1],
            "production_seeds": list(seeds),
            "budget": {"max_atoms": 1000, "max_footprint_um2": None},
        },
        source_identity={"fixture": "frozen-original-source"},
    )
    policy = {"warmup_us": window[0], "stop_us": window[1], "fixture": "frozen-window"}
    layout = plan["layouts"][0]
    envelope = {
        "schema": "nadit.msd.frozen_observation_policy/1",
        "policy": policy,
        "policy_sha256": canonical_hash(policy),
        "identity": {
            key: plan["tasks"][0][key]
            for key in ("layout_id", "config_sha256", "source_sha256")
        },
    }
    policy_path = directory / "policies" / layout["layout_id"] / "policy.json"
    write_json(policy_path, envelope)
    write_json(
        policy_path.with_name("frozen.json"),
        {"policy_artifact_sha256": canonical_hash(envelope)},
    )
    saved = []
    for row in plan["tasks"]:
        case, world, traces = activity_fixture()
        case["seed"] = row["seed"]
        for call in case["execution"]["calls"]:
            call["results_ready_us"] = call["action_end_us"]
        ledger = ResourceLedger()
        for patch in world.patches:
            ledger.register_logical_carrier(
                patch.binding.block_id, code_id="rotated_surface_d3", distance=3
            )
        for output in case["factories"]["factory0"]["outputs"]:
            cycle = output["cycle"]
            owner, consumer = f"factory0/cycle[{cycle}]", output["delivery"]["consumer"]
            carrier = ledger.begin_preparation(
                output["carrier_id"], owner=owner, at_us=12 * cycle
            )
            ledger.offer(
                output["token_id"],
                carrier_id=carrier.carrier_id,
                epoch=carrier.epoch,
                owner=owner,
                resource_kind="A",
                producer="fixture",
                ready_at_us=output["ready_at_us"],
                exit_at_us=output["ready_at_us"],
                canonicalization="canonical",
                quality=output["quality"],
            )
            ledger.reserve(
                output["token_id"],
                consumer=consumer,
                at_us=output["ready_at_us"],
                expected_code="rotated_surface_d3",
                expected_distance=3,
                expected_kind="A",
                expected_canonicalization="canonical",
            )
            ledger.consume(
                output["token_id"],
                consumer=consumer,
                at_us=output["consumed_at_us"],
                safe_exit_at_us=output["released_at_us"],
            )
            ledger.complete_use(
                carrier.carrier_id, owner=consumer, at_us=output["released_at_us"]
            )
        case["resources"] = ledger.snapshot()
        metrics = summarize_production(
            case, world, traces, warmup_us=window[0], stop_us=window[1]
        )
        identity = {
            key: row[key]
            for key in ("layout_id", "seed", "config_sha256", "source_sha256")
        }
        body = {
            "kind": "msd.produce",
            "dependencies": [],
            "timeout_s": 10,
            "max_attempts": 1,
            "memory_bytes": 1000000,
            "payload": {
                **identity,
                "trajectory_id": row["task_id"],
                "production_seed": row["seed"],
                "placement": layout["placement"],
                "spec": {"distance": 3, "pipelines": 1},
                "observation_policy": policy,
                "observation_policy_artifact": {
                    "path": str(policy_path),
                    "sha256": canonical_hash(envelope),
                    "hash_kind": "canonical_json",
                },
            },
        }
        task = {"task_id": canonical_hash(body), **body}
        result = {
            **identity,
            "trajectory_id": row["task_id"],
            "case": case,
            "case_sha256": canonical_hash(case),
            "metrics": metrics,
            "observation_policy_sha256": canonical_hash(policy),
        }
        completion = {
            "task_id": task["task_id"],
            "kind": task["kind"],
            "status": "ok",
            "result_path": f"results/{task['task_id']}.json",
            "result_sha256": canonical_hash(result),
        }
        write_json(directory / "task_definitions" / f"{task['task_id']}.json", task)
        write_json(directory / completion["result_path"], result)
        write_json(
            directory / "task_completions" / f"{task['task_id']}.json", completion
        )
        saved.append((task, result, completion))
    return plan, saved


def save_result(directory, result, completion):
    completion["result_sha256"] = canonical_hash(result)
    write_json(directory / completion["result_path"], result)
    write_json(
        directory / "task_completions" / f"{completion['task_id']}.json", completion
    )


def test_real_runner_records_are_cross_checked_and_seeds_are_not_merged(tmp_path):
    plan, saved = saved_campaign(tmp_path)
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    evidence = campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)
    assert evidence == campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)
    assert evidence["schema"] == "nadit.msd.arrival_evidence/1"
    assert evidence["source_identity"] == plan["source_identity"]
    assert evidence["source_sha256"] == canonical_hash(plan["source_identity"])
    assert evidence["config_sha256"] == canonical_hash(plan["configuration"])
    assert evidence["coverage"] == {"complete": 3}
    assert evidence["excluded_trajectories"] == []
    assert len(evidence["trajectories"]) == 3
    for row in evidence["trajectories"]:
        assert row["factory_count"] == 1 and row["distance"] == 3
        assert row["window_us"] == [0, 24] and row["duration_us"] == 24
        assert row["window_complete"] is True
        assert [arrival["deliverable_at_us"] for arrival in row["arrivals"]] == [9, 21]
    assert len({row["result_sha256"] for row in evidence["trajectories"]}) == 3
    # Repeated protocol-local token IDs across different seeds remain separate.
    assert (
        evidence["trajectories"][0]["arrivals"]
        == evidence["trajectories"][1]["arrivals"]
    )
    assert {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    } == before
    assert len(saved) == evidence["expected_trajectory_count"] == 3


def test_failed_and_unfinished_sources_stay_visible_but_are_not_arrivals(tmp_path):
    plan, saved = saved_campaign(tmp_path)
    task, _, completion = saved[1]
    completion.update(status="budget_exceeded", reason="fixture limit")
    write_json(tmp_path / "task_completions" / f"{task['task_id']}.json", completion)
    (tmp_path / "task_completions" / f"{saved[2][0]['task_id']}.json").unlink()
    evidence = campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)
    assert evidence["coverage"] == {"budget_exceeded": 1, "complete": 1, "not_run": 1}
    assert (
        len(evidence["trajectories"]) == 1
        and len(evidence["excluded_trajectories"]) == 2
    )


@pytest.mark.parametrize(
    "damage",
    (
        "result_hash",
        "case_hash",
        "result_identity",
        "case_seed",
        "policy",
        "policy_marker",
        "task_hash",
    ),
)
def test_changed_identity_hash_or_frozen_policy_is_rejected(tmp_path, damage):
    plan, saved = saved_campaign(tmp_path, seeds=(0,))
    task, result, completion = saved[0]
    if damage == "result_hash":
        result["unexpected"] = True
        write_json(tmp_path / completion["result_path"], result)
    elif damage == "case_hash":
        result["case"]["duration_us"] += 1
        save_result(tmp_path, result, completion)
    elif damage == "result_identity":
        result["source_sha256"] = "f" * 64
        save_result(tmp_path, result, completion)
    elif damage == "case_seed":
        result["case"]["seed"] += 1
        result["case_sha256"] = canonical_hash(result["case"])
        save_result(tmp_path, result, completion)
    elif damage in ("policy", "policy_marker"):
        path = Path(task["payload"]["observation_policy_artifact"]["path"])
        if damage == "policy_marker":
            write_json(
                path.with_name("frozen.json"), {"policy_artifact_sha256": "f" * 64}
            )
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
            value["policy"]["stop_us"] = 23
            write_json(path, value)
    else:
        task["payload"]["seed"] = 7
        write_json(tmp_path / "task_definitions" / f"{task['task_id']}.json", task)
    with pytest.raises(ValueError):
        campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)


@pytest.mark.parametrize(
    "damage",
    (
        "count_only",
        "metric_time",
        "missing_consume",
        "duplicate_output",
        "different_quality",
    ),
)
def test_self_reported_counts_or_forged_output_lifecycle_cannot_become_arrivals(
    tmp_path, damage
):
    plan, saved = saved_campaign(tmp_path, seeds=(0,))
    _, result, completion = saved[0]
    if damage == "count_only":
        result["metrics"]["delivered_outputs"] += 1
        result["metrics"]["delivered_outputs_per_second"] += 1e6 / 24
    elif damage == "metric_time":
        result["metrics"]["outputs"][0]["deliverable_at_us"] += 1
    elif damage == "missing_consume":
        result["case"]["resources"]["audit"] = [
            row
            for row in result["case"]["resources"]["audit"]
            if row["action"] != "consume"
        ]
    elif damage == "duplicate_output":
        result["case"]["factories"]["factory0"]["outputs"].append(
            deepcopy(result["case"]["factories"]["factory0"]["outputs"][0])
        )
    else:
        result["case"]["resources"]["tokens"][0]["quality"] = {"forged": True}
    result["case_sha256"] = canonical_hash(result["case"])
    save_result(tmp_path, result, completion)
    with pytest.raises(ValueError):
        campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)


def test_ok_runner_but_incomplete_window_is_excluded_without_low_rate_inference(
    tmp_path,
):
    plan, saved = saved_campaign(tmp_path, seeds=(0,))
    _, result, completion = saved[0]
    result["metrics"].update(
        requested_window_complete=False,
        window_status="incomplete",
        actual_observation_us=10,
    )
    save_result(tmp_path, result, completion)
    evidence = campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)
    assert evidence["trajectories"] == []
    assert evidence["coverage"] == {"incomplete_window": 1}


def test_one_result_cannot_be_reused_for_a_second_seed(tmp_path):
    plan, saved = saved_campaign(tmp_path, seeds=(0, 1))
    task, _, completion = saved[1]
    completion.update(
        result_path=saved[0][2]["result_path"],
        result_sha256=saved[0][2]["result_sha256"],
    )
    write_json(tmp_path / "task_completions" / f"{task['task_id']}.json", completion)
    with pytest.raises(ValueError):
        campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)


@pytest.mark.parametrize(("window", "observed"), (((9, 21), 1), ((0, 8), 0)))
def test_exact_half_open_window_preserves_records_without_scaling_or_clipping_them(
    tmp_path, window, observed
):
    plan, _ = saved_campaign(tmp_path, seeds=(0,), window=window)
    evidence = campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)
    row = evidence["trajectories"][0]
    assert row["window_us"] == list(window)
    assert len(row["arrivals"]) == 2
    assert (
        sum(window[0] <= a["deliverable_at_us"] < window[1] for a in row["arrivals"])
        == observed
    )
    assert evidence["coverage"] == {"complete": 1}


def test_ok_worker_cannot_promote_a_failed_factory_to_complete_arrival_source(tmp_path):
    plan, saved = saved_campaign(tmp_path, seeds=(0,))
    _, result, completion = saved[0]
    result["case"]["factories"]["factory0"].update(
        status="input_supply_exhausted", failure={"code": "input_supply_exhausted"}
    )
    result["case_sha256"] = canonical_hash(result["case"])
    save_result(tmp_path, result, completion)
    evidence = campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)
    assert evidence["trajectories"] == [] and evidence["coverage"] == {"failed": 1}


def test_duplicate_runner_definitions_for_one_trajectory_fail_closed(tmp_path):
    plan, saved = saved_campaign(tmp_path, seeds=(0,))
    task = deepcopy(saved[0][0])
    task["timeout_s"] += 1
    task["task_id"] = canonical_hash(
        {key: value for key, value in task.items() if key != "task_id"}
    )
    write_json(tmp_path / "task_definitions" / f"{task['task_id']}.json", task)
    with pytest.raises(ValueError, match="DUPLICATE_ARRIVAL_TRAJECTORY"):
        campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)


def test_boolean_seed_is_not_equal_to_integer_seed_for_arrival_identity(tmp_path):
    plan, saved = saved_campaign(tmp_path, seeds=(0,))
    _, result, completion = saved[0]
    result["seed"] = False
    save_result(tmp_path, result, completion)
    with pytest.raises(ValueError, match="SEED_REQUIRES_INTEGER"):
        campaign_arrivals.freeze_arrival_evidence(plan, tmp_path)
