"""Real six-patch factory actions with finite protocol/resource scenarios."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import make_factory_world
from modules.logical_compiler.examples.factory_to_t import run_example
from modules.logical_compiler.src.protocols.resources import ResourceError


@pytest.fixture(scope="module")
def reference_backend():
    world = make_factory_world()
    return world, SurfaceFactoryBackend(world.device)


@pytest.fixture(scope="module")
def artifact_root(tmp_path_factory):
    """Optionally retain all verified examples outside pytest's temporary tree."""
    configured = os.environ.get("NADIT_FACTORY_INTEGRATION_OUTPUT")
    return Path(configured) if configured else tmp_path_factory.mktemp("factory-to-t")


def _calls(document, component, roles=None):
    return [
        call
        for call in document["calls"]
        if call["component_id"] == component
        and (roles is None or call["participant_roles"] == list(roles))
    ]


def _carriers(document):
    return {
        item["carrier_id"].rsplit("/", 1)[-1]: item
        for item in document["resources"]["carriers"]
    }


def _final_events(document):
    return [
        event
        for event in document["events"]
        if event["occurrence"]["invocation_id"].endswith("/final/event")
    ]


def _assert_data_reset_boundaries(physical):
    parts = {part["invocation_id"]: part for part in physical["parts"]}
    for step in physical["program"]["steps"]:
        for action in step["actions"]:
            if action["kind"] != "Reset":
                continue
            part_ids = {
                physical["source_id_map"][str(source)]["invocation_id"]
                for source in action["source_ids"]
            }
            assert len(part_ids) == 1
            part = parts[part_ids.pop()]
            if set(action["atoms"]) & set(part["wire_atoms"][:9]):
                assert part["description"]["component_id"] in (
                    "initialize_plus",
                    "initialize_0",
                    "raw_t",
                )


def _assert_physical_and_events(run):
    document = run.case.to_dict()
    physical = document["physical"]
    assert physical is not None and run.case.physical is not None
    assert physical["validation"]["ok"] is True
    assert physical["validation"]["scope"] == "selected_actions_unobserved_measurements"
    assert physical["physical_execution"] is False
    _assert_data_reset_boundaries(physical)
    assert document["full_quantum_simulation"] is False
    assert document["supply_mode"] == "on_demand"
    assert document["inventory_maintenance"] == "not_implemented"
    assert len(run.case.physical.world.atoms) == 102
    assert len(run.case.physical.entry_world.atoms) == 102
    pending = physical["pending_measurements"]
    assert all(item["value"] is None for item in pending)
    results = {item["result"]["measurement_id"]: item for item in pending}
    assert sorted(results) == list(range(len(pending)))
    assert run.executor.physical.next_result_id == len(pending)
    assert [node.id for node in run.case.physical.dag.nodes] == list(
        range(len(run.case.physical.dag.nodes))
    )
    assert len(physical["source_id_map"]) == len(run.case.physical.dag.nodes)
    events = {}
    for event in document["events"]:
        occurrence = event["occurrence"]
        identity = tuple(
            occurrence[key]
            for key in ("case_id", "invocation_id", "attempt", "port_id")
        )
        assert identity not in events
        events[identity] = event
        assert event["port_sha256"] in document["probability_models"]
        assert event["evidence_kind"] == "coarse_probability"
        assert event["released_at_us"] >= event["available_at_us"]
        for dependency in event["dependencies"]:
            assert event["released_at_us"] >= dependency["exit_at_us"]
            assert dependency["results"]
            for result in dependency["results"]:
                physical_result = results[result["result_id"]]
                assert physical_result["invocation_id"] == dependency["invocation_id"]
                assert result["available_at_us"] == physical_result["available_at_us"]
                assert event["released_at_us"] >= result["available_at_us"]
    # Logical prerequisites follow shared patches, even for a serial policy.
    # A global previous-call edge would incorrectly forbid the new frontier.
    previous_on_patch = {}
    by_call = {call["invocation_id"]: call for call in document["calls"]}
    for index, call in enumerate(document["calls"]):
        expected = {
            previous_on_patch[role]
            for role in call["participant_roles"]
            if role in previous_on_patch
        }
        assert set(call["after_calls"]) == expected
        for dependency in expected:
            assert call["start_us"] >= by_call[dependency]["end_us"]
        previous_on_patch.update(
            (role, call["invocation_id"]) for role in call["participant_roles"]
        )
        if index:
            assert call["start_us"] >= document["calls"][index - 1]["end_us"]
        for occurrence in call["event_dependencies"]:
            identity = tuple(
                occurrence[key]
                for key in ("case_id", "invocation_id", "attempt", "port_id")
            )
            assert call["start_us"] >= events[identity]["released_at_us"]
    for part in physical["parts"]:
        if part["description"]["component_id"] in ("logical_mz", "logical_mx"):
            assert (
                sum(item["invocation_id"] == part["invocation_id"] for item in pending)
                == 9
            )
    counts = run.manifest["counts"]
    assert counts["protocol_calls"] == len(document["calls"])
    assert counts["primitive_component_parts"] == len(physical["parts"])
    assert counts["atom_steps"] == len(run.case.physical.program.steps)
    assert counts["atom_actions"] == sum(
        len(step.actions) for step in run.case.physical.program.steps
    )
    assert (
        counts["primitive_component_parts"]
        == counts["protocol_calls"] + counts["raw_preparation_attempts"]
    )
    assert document["duration_us"] == pytest.approx(
        run.case.physical.program.duration_us
    )
    return document


def _assert_single_consumption(document, *, completed=True):
    output_id = document["output_token_id"]
    assert (
        output_id is not None and document["algorithm_consumed_token_id"] == output_id
    )
    output = next(
        token
        for token in document["resources"]["tokens"]
        if token["token_id"] == output_id
    )
    assert output["status"] == "consumed" and output["consumer"] == "algorithm"
    consumes = [
        event
        for event in document["resources"]["audit"]
        if event["action"] == "consume" and event["token_id"] == output_id
    ]
    assert len(consumes) == 1
    assert consumes[0]["usage_kind"] == "consume"
    carriers = _carriers(document)
    assert carriers["W2"]["owner"] == "algorithm"
    assert (
        carriers["W1"]["owner"] is None
        if completed
        else carriers["W1"]["owner"] == "algorithm"
    )


def test_real_ideal_factory_to_t_and_export(reference_backend, artifact_root):
    world, backend = reference_backend
    output = artifact_root / "ideal"
    run = run_example("ideal", world=world, backend=backend, output=output)
    document = _assert_physical_and_events(run)
    assert document["status"] == "complete"
    assert len(document["calls"]) == 118
    assert document["duration_us"] == pytest.approx(80928.19947143435)
    assert run.manifest["counts"]["factory_cnot_calls"] == 59
    assert run.manifest["counts"]["algorithm_cnot_calls"] == 1
    assert run.manifest["counts"]["raw_resource_tokens"] == 15
    _assert_single_consumption(document)
    assert _carriers(document)["W2"]["epoch"] == 2
    assert _carriers(document)["R"]["epoch"] == 11
    assert document["physical"]["validation"]["ok"] is True
    assert all(m["value"] is None for m in document["physical"]["pending_measurements"])
    assert json.loads((output / "case.json").read_text("utf-8")) == document
    for name, digest in run.manifest["files_sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    trace = json.loads((output / "trace.json").read_text("utf-8"))
    assert trace["measurements"] == []
    assert all(item["value"] is None for item in trace["pending_measurements"])
    assert (output / "index.html").stat().st_size > 1000
    with pytest.raises(FileExistsError):
        run_example("ideal", world=world, backend=backend, output=output)


@pytest.mark.parametrize(
    "scenario",
    [
        "startup-retry",
        "rotation-retry",
        "supply-exhaustion",
        "batch-retry",
        "batch-exhaustion",
        "consumption-failure",
        "output-hold",
    ],
)
def test_real_factory_scenarios(reference_backend, artifact_root, scenario):
    world, backend = reference_backend
    run = run_example(
        scenario, world=world, backend=backend, output=artifact_root / scenario
    )
    document = _assert_physical_and_events(run)
    counts = run.manifest["counts"]
    carriers = _carriers(document)
    if scenario in ("startup-retry", "rotation-retry"):
        assert document["status"] == "complete"
        _assert_single_consumption(document)
        assert counts["raw_preparation_attempts"] == 16
        assert counts["raw_resource_tokens"] == 15
        assert counts["factory_cnot_calls"] == 59
        assert counts["algorithm_cnot_calls"] == 1
        assert (
            sum(mark["kind"] == "rotation_complete" for mark in document["milestones"])
            == 11
        )
        if scenario == "startup-retry":
            assert len(_calls(document, "raw_t_postselection", ("W3",))) == 2
            assert carriers["W3"]["epoch"] == 2
            assert carriers["R"]["epoch"] == 11
        else:
            assert len(_calls(document, "raw_t_postselection", ("R",))) == 12
            assert carriers["R"]["epoch"] == 12
            for role in ("W2", "W3", "W4", "W5"):
                assert len(_calls(document, "raw_t_postselection", (role,))) == 1
        fixture_ports = [
            port
            for port in document["probability_models"].values()
            if port["model"]["kind"] == "test_fixture"
        ]
        assert len(fixture_ports) == 1
        assert len(fixture_ports[0]["outcomes"]) == 17
        assert (
            sum(
                outcome["probability"]
                for outcome in fixture_ports[0]["outcomes"]
                if outcome["values"]["accepted"]
            )
            == 0
        )
    elif scenario == "supply-exhaustion":
        assert document["status"] == "input_supply_exhausted"
        assert document["output_token_id"] is None
        assert counts["raw_preparation_attempts"] == 7
        assert counts["raw_resource_tokens"] == 5
        assert counts["factory_cnot_calls"] == 5
        assert counts["algorithm_cnot_calls"] == 0
        assert carriers["R"]["epoch"] == 3
        assert all(carrier["owner"] is not None for carrier in carriers.values())
        assert not _final_events(document)
        assert (
            sum(mark["kind"] == "rotation_complete" for mark in document["milestones"])
            == 1
        )
        assert not any(
            "rotation[1]/compute" in call["invocation_id"] for call in document["calls"]
        )
    elif scenario == "batch-retry":
        assert document["status"] == "complete"
        assert [event["outcome_key"] for event in _final_events(document)] == [
            "mx_0101",
            "mx_0000",
        ]
        assert counts["batches_started"] == 2
        assert counts["raw_resource_tokens"] == counts["raw_preparation_attempts"] == 30
        assert counts["factory_cnot_calls"] == 118
        assert counts["algorithm_cnot_calls"] == 1
        assert len(_calls(document, "logical_mx")) == 8
        assert len(_calls(document, "logical_x", ("W1",))) == 1
        assert carriers["W2"]["epoch"] == 3
        assert carriers["R"]["epoch"] == 22
        assert all(carriers[role]["epoch"] == 2 for role in ("W1", "W3", "W4", "W5"))
        _assert_single_consumption(document)
    elif scenario == "batch-exhaustion":
        assert document["status"] == "distillation_rejected"
        assert [event["outcome_key"] for event in _final_events(document)] == [
            "mx_0100"
        ]
        assert document["output_token_id"] is None
        assert counts["factory_cnot_calls"] == 59
        assert counts["algorithm_cnot_calls"] == 0
        assert counts["raw_resource_tokens"] == 15
        assert not _calls(document, "logical_x", ("W1",))
        assert all(
            carriers[role]["owner"] is not None
            for role in ("W1", "W2", "W3", "W4", "W5")
        )
    elif scenario == "consumption-failure":
        assert document["status"] == "physical_failure"
        assert "TEST_FIXTURE_CONSUMPTION_FAILURE" in document["failure"]["detail"]
        _assert_single_consumption(document, completed=False)
        assert counts["raw_resource_tokens"] == counts["raw_preparation_attempts"] == 15
        assert (
            counts["factory_cnot_calls"] == 59 and counts["algorithm_cnot_calls"] == 1
        )
        assert document["calls"][-1]["component_id"] == "transversal_cnot"
        assert document["calls"][-1]["participant_roles"] == ["W2", "W1"]
        assert not _calls(document, "logical_mz", ("W1",))
    else:
        assert document["status"] == "complete" and document["goal"] == "factory_output"
        assert document["algorithm_consumed_token_id"] is None
        assert (
            counts["factory_cnot_calls"] == 59 and counts["algorithm_cnot_calls"] == 0
        )
        assert counts["raw_resource_tokens"] == 15
        token = run.executor.ledger.token(document["output_token_id"])
        assert token.status == "offered"
        assert carriers["W1"]["owner"] == "factory/batch[0]"
        before = run.executor.ledger.snapshot()
        with pytest.raises(ResourceError, match="CARRIER_OWNED|ACTIVE_TOKEN"):
            run.executor.ledger.begin_preparation(
                token.carrier_id, owner="test-reset", at_us=document["duration_us"]
            )
        assert run.executor.ledger.snapshot() == before
        assert run.manifest["output_hold_check"]["reset_rejected"] is True
        assert run.manifest["output_hold_check"]["ledger_unchanged"] is True
    if scenario in ("batch-retry", "batch-exhaustion"):
        assert run.manifest["input_z_error"] == 0.01
        assert run.manifest["input_quality_status"] == "assumed_reference"
        assert all(
            token["quality"]["status"] == "assumed_reference"
            for token in document["resources"]["tokens"]
        )


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), True])
def test_invalid_quality_is_rejected_before_any_physical_work(value):
    with pytest.raises(ValueError, match="input_z_error"):
        run_example(input_z_error=value)
