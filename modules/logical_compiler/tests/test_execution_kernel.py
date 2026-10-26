"""Physical adaptation retains native source, timing and resource evidence."""

import json
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.device import Region
from test_factory_process import _run
from test_protocol_physical import _part
from test_protocol_physical import setup_world as setup_world  # noqa: PLC0414

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim
from modules.logical_compiler.src.protocols.execution_kernel import (
    ExecutionRequest,
    PhysicalExecutionKernel,
)
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler


def _scenario(scenario):
    if scenario == "retry_s":
        return _run(({"prep:W1": ("rejected", "accepted"), "t:rotation": ("m1",)}, {}))
    if scenario == "failure":
        return _run(
            ({"prep:W1": ("rejected",)}, {}), limits=FactoryLimits(raw_attempts=1)
        )
    return _run(algorithm=scenario == "algorithm")


def _check_native_calls_and_events(case, physical):
    """Compare exported receipts directly with the fixture's committed sources."""
    calls = {call["invocation_id"]: call for call in case["calls"]}
    assert len(calls) == len(case["calls"]) == len(physical.committed)
    assert list(calls) == [identity for _, _, identity in physical.committed]
    schedule = case["component_schedule"]
    assert set(schedule["completed"]) == set(calls)
    assert not schedule["running"]
    admissions = {item["batch_id"]: item for item in schedule["admissions"]}
    parts = {}
    result_ids = []
    for native_component, participants, identity in physical.committed:
        call = calls[identity]
        source = physical.source(identity)
        native_parts = (
            (source.expansion,) if hasattr(source, "expansion") else source.parts
        )
        expected_component = (
            "toy.canonicalize"
            if call["component_id"] == "toy.correction/canonicalize"
            else call["component_id"]
        )
        assert native_component == expected_component
        assert participants == tuple(
            f"{call['factory_id']}/{role}" for role in call["participant_roles"]
        )
        assert call["part_invocations"] == [part.invocation_id for part in native_parts]
        assert call["start_us"] == native_parts[0].start_us
        assert call["end_us"] == max(part.action_end_us for part in native_parts)
        assert schedule["completed"][identity] == call["end_us"]
        admission = admissions[call["batch_id"]]
        assert admission["start_us"] == call["start_us"]
        assert identity in {node["id"] for node in admission["nodes"]}
        assert all(
            calls[key]["end_us"] <= call["start_us"] for key in call["after_calls"]
        )
        for part in native_parts:
            parts[part.invocation_id] = part
            assert part.description.component_id == native_component
            assert (
                tuple(binding.block_id for binding in part.participant_bindings)
                == participants
            )
            assert part.action_end_us - part.start_us == (
                2 if native_component == "toy.canonicalize" else 5
            )
            for result in part.measurements:
                assert result.value is None
                result_ids.append(result.result.measurement_id)
    assert len(result_ids) == len(set(result_ids))
    assert case["duration_us"] == physical.clock_us
    assert case["physical"]["invocation_count"] == len(physical.committed)
    for admission in admissions.values():
        members = [calls[node["id"]] for node in admission["nodes"]]
        assert {member["start_us"] for member in members} == {admission["start_us"]}
    events = {}
    for event in case["events"]:
        events[json.dumps(event["occurrence"], sort_keys=True)] = event
        ready = []
        for dependency in event["dependencies"]:
            part = parts[dependency["invocation_id"]]
            assert dependency["exit_at_us"] == part.action_end_us
            assert dependency["results"] == [
                {
                    "result_id": result.result.measurement_id,
                    "available_at_us": result.available_at_us,
                }
                for result in part.measurements
            ]
            ready.append(part.results_ready_us)
        assert ready and event["released_at_us"] >= max(ready)
    for call in calls.values():
        for dependency in call["event_dependencies"]:
            event = events[json.dumps(dependency, sort_keys=True)]
            assert call["start_us"] >= event["released_at_us"]


@pytest.mark.parametrize("scenario", ["complete", "retry_s", "failure", "algorithm"])
def test_physical_wrapper_preserves_native_evidence_and_complete_case_replay(scenario):
    case, physical = _scenario(scenario)
    replay, replay_physical = _scenario(scenario)
    assert case == replay
    assert physical.committed == replay_physical.committed
    _check_native_calls_and_events(case, physical)
    assert case["status"] == (
        "partial_failure" if scenario == "failure" else "complete"
    )
    assert case["factories"]["line-1"]["status"] == "complete"
    assert case["factories"]["line-0"]["status"] == (
        "input_supply_exhausted" if scenario == "failure" else "complete"
    )
    assert (
        len(case["events"])
        == {"complete": 10, "retry_s": 11, "failure": 6, "algorithm": 14}[scenario]
    )
    for event in case["events"]:
        occurrence = event["occurrence"]
        line_zero = occurrence["invocation_id"].startswith("line-0/")
        port = occurrence["port_id"]
        if port.startswith("test_fixture.t:"):
            expected = (
                "m1"
                if scenario == "retry_s"
                and line_zero
                and port == "test_fixture.t:rotation"
                else "m0"
            )
        else:
            expected = (
                "rejected"
                if scenario in ("retry_s", "failure")
                and line_zero
                and port == "test_fixture.prep:W1"
                and occurrence["attempt"] == 0
                else "accepted"
            )
        assert event["outcome_key"] == expected
    s_calls = [call for call in case["calls"] if call["component_id"] == "toy.s"]
    assert len(s_calls) == int(scenario == "retry_s")
    if s_calls:
        assert s_calls[0]["factory_id"] == "line-0"
        uncompute = next(
            call
            for call in case["calls"]
            if call["factory_id"] == "line-0"
            and call["component_id"] == "toy.uncompute"
        )
        assert s_calls[0]["end_us"] <= uncompute["start_us"]
    tokens = {token["token_id"]: token for token in case["resources"]["tokens"]}
    consumes = Counter(
        item["token_id"]
        for item in case["resources"]["audit"]
        if item["action"] == "consume"
    )
    assert all(count == 1 for count in consumes.values())
    for token in tokens.values():
        assert consumes[token["token_id"]] == int(token["status"] == "consumed")
        if token["status"] == "consumed":
            assert token["consumed_at_us"] >= max(
                token["ready_at_us"], token["exit_at_us"]
            )
    for line, record in case["factories"].items():
        output = record["output_token_id"]
        if scenario == "failure" and line == "line-0":
            assert output is None
            assert all(
                carrier["owner"] is None
                for carrier in case["resources"]["carriers"]
                if carrier["carrier_id"].startswith(line + "/")
            )
        else:
            assert tokens[output]["status"] == (
                "consumed" if scenario == "algorithm" else "offered"
            )
            assert record["algorithm_consumed_token_id"] == (
                output if scenario == "algorithm" else None
            )


def test_native_source_without_optional_exit_binding_normalizes_after_commit(
    setup_world,
):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)
    kernel = PhysicalExecutionKernel(context)
    call = ComponentCall("rotate", "rotation", ("A",))

    class Backend:
        def describe_execution(self, component, participants, parameters):
            binding = participants[0]
            return ComponentExecutionSpec(
                "test",
                component,
                "local/fixture",
                (binding.block_id,),
                (
                    SpaceClaim(
                        Region(binding.origin.x - 1, -1, binding.origin.x + 1, 1),
                        "fixture",
                    ),
                ),
                (),
                "local_parallel",
                0,
            )

        def bind_call(self, component, participants, parameters):
            return SimpleNamespace(
                result_count=0,
                expand=lambda invocation: replace(
                    _part(invocation, participants[0], "rotation"), exit_binding=None
                ),
            )

    backend = Backend()
    scheduler = ComponentScheduler()
    scheduler.add(ComponentNode("native", kernel.describe(backend, call, ("A",))))
    admission = scheduler.admit(0, snapshot_id=kernel.snapshot_id)
    receipts = kernel.execute(
        admission, (ExecutionRequest("native", backend, call, ("A",)),)
    )["native"]
    assert receipts[0].participant_blocks == ("A",)
    assert receipts[0].representation == "physical"
    source = kernel.source("native")
    assert source is context.source("native") and source.exit_binding is None
    assert kernel.event_parts(receipts) == (source,)
    assert context.finalize().validation["ok"] is True
