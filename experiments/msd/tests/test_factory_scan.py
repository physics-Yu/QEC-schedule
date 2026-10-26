"""The saved schedule must contain actual kernel times and resource leases."""

import csv
import json

from experiments.msd.generic_factory import scan
from modules.codes.rotated_surface.tests.test_generic_fast_factory import (
    fixture_profile,
)


def test_scan_exports_execution_schedule_and_hardware_control(tmp_path):
    document = fixture_profile(3, 1).to_dict()
    document.update(
        standard="nadit.msd.standard/2",
        timing={
            "load_us": 10,
            "store_us": 10,
            "measure_us": 100,
            "result_processing_us": 0,
        },
    )
    profiles = tmp_path / "profiles"
    cell = profiles / "d3-n1"
    cell.mkdir(parents=True)
    (cell / "profile.json").write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "results"
    report = scan(
        profiles,
        output,
        {
            "standard": "nadit.msd.standard/2",
            "distances": [3],
            "factory_counts": [1],
            "seeds": [0],
            "witness_seed": 0,
            "input_z_error": 0,
            "limits": {"raw_attempts": 2, "batches": 1},
        },
    )
    assert len(report["results"]) == 2
    for row in report["results"]:
        case = json.loads((output / row["witness"]).read_text(encoding="utf-8"))
        calls = case["execution"]["calls"]
        path = output / row["witness"].replace(".case.json", ".schedule.csv")
        with path.open(encoding="utf-8", newline="") as stream:
            records = list(csv.DictReader(stream))
        assert len(records) == len(calls)
        assert len({record["invocation"] for record in records}) == len(records)
        assert any(record["reserved_resources"] for record in records)
        assert row["outputs"] == 1
        for record, call in zip(records, calls, strict=True):
            assert float(record["start_us"]) == call["start_us"]
            assert float(record["action_end_us"]) == call["action_end_us"]
            assert record["blocks"].split(";") == call["participant_blocks"]


def test_existing_scan_dispatches_joint_profiles_to_single_shared_aod(tmp_path):
    from modules.codes.rotated_surface.tests.test_joint_factory_profile import (
        SyntheticJointProfile,
        joint_fixture,
    )
    from modules.logical_compiler.examples.surface_factory_fast import (
        run_surface_factory,
    )

    profile = SyntheticJointProfile(joint_fixture(1))
    run_surface_factory(profile, seed=0, input_z_error=0)
    document = profile.to_dict()
    document.update(
        standard="nadit.msd.standard/2",
        timing={
            "load_us": 10,
            "store_us": 10,
            "measure_us": 100,
            "result_processing_us": 0,
        },
    )
    path = tmp_path / "profiles" / "d5-n1"
    path.mkdir(parents=True)
    (path / "profile.json").write_text(json.dumps(document), encoding="utf-8")
    report = scan(
        path.parent,
        tmp_path / "results",
        {
            "standard": "nadit.msd.standard/2",
            "distances": [5],
            "factory_counts": [1],
            "seeds": [0],
            "witness_seed": 0,
            "input_z_error": 0,
            "limits": {"raw_attempts": 8, "batches": 1},
        },
    )
    assert len(report["results"]) == 1
    assert report["results"][0]["hardware"] == "shared_aod"
    case = json.loads(
        (tmp_path / "results" / report["results"][0]["witness"]).read_text()
    )
    assert all(
        c["parallel_mode"] == "shared_aod_lockstep" for c in case["execution"]["calls"]
    )
    assert "joint" in report["shared_hardware_policy"]


def test_fast_entry_counts_multiple_outputs_and_keeps_all_final_decisions():
    from modules.codes.rotated_surface.tests.test_joint_factory_profile import (
        SyntheticJointProfile,
        joint_fixture,
    )
    from modules.logical_compiler.examples.surface_factory_fast import (
        run_surface_factory,
    )
    from modules.logical_compiler.src.protocols.production import (
        OutputDelivery,
        ProductionPolicy,
    )
    from modules.logical_compiler.src.protocols.protocol_intents import WaitIntent

    def fixture_sink(process, token):
        consumer = token.token_id + "/fixture_consumer"
        now = process.execution.clock_us
        process.ledger.reserve(
            token.token_id,
            consumer=consumer,
            at_us=now,
            expected_code=process.code,
            expected_distance=process.distance,
            expected_kind=process.recipe.output_resource_kind,
            expected_canonicalization="canonical",
        )
        yield WaitIntent(now + 2, "fixture_delivery")
        delivered = process.execution.clock_us
        process.ledger.consume(
            token.token_id,
            consumer=consumer,
            at_us=delivered,
            safe_exit_at_us=delivered,
        )
        process.ledger.complete_use(token.carrier_id, owner=consumer, at_us=delivered)
        return OutputDelivery(
            token.token_id,
            token.carrier_id,
            consumer,
            delivered,
            delivered,
            delivered,
            {"kind": "test_fixture", "physical_delivery": False},
        )

    result = run_surface_factory(
        SyntheticJointProfile(joint_fixture(1)),
        seed=0,
        input_z_error=0,
        production_policy=ProductionPolicy(2),
        output_sink=fixture_sink,
    )
    assert result["summary"]["status"] == "complete"
    assert result["summary"]["outputs"] == 2
    assert result["summary"]["delivered_outputs"] == 2
    line = result["ledger"]["lines"]["factory0"]
    assert len(line["factory_check_events"]) == 2
    assert len(line["outputs"]) == 2
    assert line["outputs"][1]["ready_at_us"] > line["outputs"][0]["released_at_us"]
    assert result["summary"]["raw_attempts"] == 30


def test_continuous_call_budget_is_explicit_and_failure_retains_the_case():
    from modules.codes.rotated_surface.tests.test_joint_factory_profile import (
        SyntheticJointProfile,
        joint_fixture,
    )
    from modules.logical_compiler.examples.surface_factory_fast import (
        run_surface_factory,
    )
    from modules.logical_compiler.src.protocols.production import ProductionPolicy

    def unreachable_sink(process, token):
        raise AssertionError("budget should stop before any output")

    result = run_surface_factory(
        SyntheticJointProfile(joint_fixture(1)),
        seed=0,
        input_z_error=0,
        production_policy=ProductionPolicy(2),
        output_sink=unreachable_sink,
        max_component_calls=1,
    )
    assert result["summary"]["status"] == "partial_failure"
    assert result["summary"]["outputs"] == 0
    assert result["summary"]["limits"]["max_component_calls"] == 1
    assert (
        result["case"]["factories"]["factory0"]["status"]
        == "expansion_budget_exhausted"
    )
