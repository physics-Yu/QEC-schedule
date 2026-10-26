"""Stage barriers synchronize production attempts, never accepted-output quotas."""

import json
from functools import lru_cache
from itertools import pairwise

import pytest

from modules.codes.rotated_surface.object_factory import FactoryObjectCatalog
from modules.logical_compiler.examples.factory_objects import run_factory_objects
from modules.logical_compiler.examples.object_cases import forbid_atom_work
from modules.logical_compiler.src.protocols.production import ProductionPolicy


@lru_cache(maxsize=4)
def _run(strategy, seed):
    with forbid_atom_work() as counters:
        result = run_factory_objects(
            FactoryObjectCatalog.load(),
            factories=2,
            seed=seed,
            cycles=2,
            strategy=strategy,
            production_basis="production_rounds",
        )
    assert not any(counters.values())
    return result


def _outcomes(case):
    return {
        json.dumps(e["occurrence"], sort_keys=True): (
            e["outcome_key"],
            e["values"],
            e["port_sha256"],
        )
        for e in case["events"]
    }


def test_successful_raw_waits_without_repreparation_before_next_gate():
    result = _run("synchronous", 0)
    case = result["case"]
    assert result["summary"]["raw_rejections"] > 0
    marks = case["milestones"]
    arrivals = [m for m in marks if m["kind"] == "synchronous_barrier_arrived"]
    releases = [m for m in marks if m["kind"] == "synchronous_barrier_released"]
    positive_wait = False
    for release in releases:
        group = [
            a
            for a in arrivals
            if (a["cycle"], a["batch"], a["stage_key"])
            == (release["cycle"], release["batch"], release["stage_key"])
            and a["factory_id"] in release["peers"]
        ]
        assert release["at_us"] == max(a["at_us"] for a in group)
        if release["stage_key"].endswith("raw_prepared"):
            positive_wait |= any(a["at_us"] < release["at_us"] for a in group)
            for arrival in group:
                assert not any(
                    c["factory_id"] == arrival["factory_id"]
                    and arrival["at_us"] <= c["start_us"] < release["at_us"]
                    for c in case["calls"]
                )
    assert positive_wait


def test_conditional_s_branches_join_and_deterministic_cnot_steps_align():
    case = _run("synchronous", 0)["case"]
    # Actual branch field names are retained by the original probability port.
    consumption = [
        e
        for e in case["events"]
        if e["occurrence"]["port_id"].endswith("t_injection.logical_z")
    ]
    groups = {}
    for e in consumption:
        groups.setdefault(e["occurrence"]["invocation_id"].split("/", 1)[1], []).append(
            e
        )
    mismatched_branches = any(
        len({e["outcome_key"] for e in g}) > 1 for g in groups.values()
    )
    assert mismatched_branches
    for wave in case["execution"]["waves"]:
        ids = wave["invocations"]
        calls = [c for c in case["calls"] if c["invocation_id"] in ids]
        if calls[0]["component_id"] == "transversal_cnot":
            assert len(calls) == 2
            assert (
                calls[0]["invocation_id"].split("/", 1)[1]
                == calls[1]["invocation_id"].split("/", 1)[1]
            )
            assert all(len(s["members"]) == 2 for s in wave["stage_schedule"])
        resources = sorted(
            (p["start_us"], p["end_us"])
            for p in wave["stage_schedule"]
            if "aod:transport" in p["resources"]
        )
        assert all(a[1] <= b[0] for a, b in pairwise(resources))


@pytest.mark.parametrize("seed", [0, 1])
def test_paired_rounds_preserve_events_without_replacing_rejected_outputs(seed):
    sync, asynchronous = _run("synchronous", seed), _run("asynchronous", seed)
    assert _outcomes(sync["case"]) == _outcomes(asynchronous["case"])
    assert {c["invocation_id"] for c in sync["case"]["calls"]} == {
        c["invocation_id"] for c in asynchronous["case"]["calls"]
    }
    assert sync["summary"]["batches"] == 4
    assert (
        sync["summary"]["accepted_outputs"] == 4 - sync["summary"]["factory_rejections"]
    )
    if seed == 1:
        assert sync["summary"]["factory_rejections"] == 1
    factories = sync["case"]["factories"]
    first_completions = [
        f["production_rounds"][0]["completed_at_us"] for f in factories.values()
    ]
    next_starts = [
        m["at_us"]
        for m in sync["case"]["milestones"]
        if m["kind"] == "production_cycle_started" and m["cycle"] == 1
    ]
    assert next_starts == [max(first_completions)] * 2
    assert all(len(f["production_rounds"]) == 2 for f in factories.values())
    assert not any(
        m.get("stage_key") == "production/epoch_complete"
        for m in sync["case"]["milestones"]
    )
    tokens = [
        p["delivery"]["token_id"]
        for f in factories.values()
        for p in f["production_cycles"]
    ]
    assert len(set(tokens)) == sync["summary"]["accepted_outputs"]


def test_final_rejection_advances_both_factories_to_the_next_round():
    with forbid_atom_work():
        result = run_factory_objects(
            FactoryObjectCatalog.load(),
            factories=2,
            seed=1,
            cycles=2,
            strategy="synchronous",
        )
    case = result["case"]
    decisions = [m for m in case["milestones"] if m["kind"] == "batch_decision"]
    assert any(not m["accepted"] for m in decisions)
    assert len(decisions) == 4
    for factory in case["factories"].values():
        assert [r["round"] for r in factory["production_rounds"]] == [0, 1]
        assert len(factory["production_cycles"]) == sum(
            r["accepted"] for r in factory["production_rounds"]
        )
    assert all("/batch[0]/" in c["invocation_id"] for c in case["calls"])


def test_synchronous_member_failure_cannot_silently_reduce_the_cohort():
    with (
        forbid_atom_work(),
        pytest.raises(RuntimeError, match="SYNCHRONOUS_MEMBER_FAILED"),
    ):
        run_factory_objects(
            FactoryObjectCatalog.load(),
            factories=2,
            seed=0,
            strategy="synchronous",
            raw_attempts=1,
        )


def test_synchronous_zero_budget_returns_timeout_reason():
    with pytest.raises(TimeoutError, match="factory_runtime budget=0"):
        run_factory_objects(
            FactoryObjectCatalog.load(),
            factories=2,
            seed=0,
            strategy="synchronous",
            timeout_seconds=0,
        )


def test_production_basis_is_explicit_and_sync_rejects_success_quotas():
    with pytest.raises(ValueError, match="INVALID_PRODUCTION_COMPLETION_BASIS"):
        ProductionPolicy(2, completion_basis="unknown")
    with pytest.raises(ValueError, match="SYNCHRONOUS_REQUIRES"):
        run_factory_objects(
            FactoryObjectCatalog.load(),
            factories=2,
            seed=0,
            strategy="synchronous",
            production_basis="accepted_outputs",
        )


def test_zero_accepted_outputs_complete_rounds_with_null_output_costs():
    # A deliberately poor input is a boundary test, not the acceptance workload.
    with forbid_atom_work():
        result = run_factory_objects(
            FactoryObjectCatalog.load(),
            factories=1,
            seed=0,
            cycles=1,
            strategy="synchronous",
            input_z_error=0.5,
        )
    summary = result["summary"]
    assert summary["accepted_outputs"] == 0
    assert summary["batches"] == summary["factory_rejections"] == 1
    assert summary["finite_batch_rate_per_second"] == 0
    assert summary["startup_latency_us"] is None
    assert summary["atom_us_per_accepted_output"] is None
    assert summary["storage_area_us_per_accepted_output"] is None
    factory = result["case"]["factories"]["factory0"]
    assert factory["production_cycles"] == []
    assert factory["production_rounds"][0]["accepted"] is False
