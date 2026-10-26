"""Cooperative recipe control; toy cases make no physical probability claim."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.device import Position
from test_factory_execution import CODE, consumption, preparation, toy_recipe
from test_scheduled_factory import BatchedPhysical, DeclaredBackend

from modules.codes.contracts.component import ComponentBinding
from modules.codes.contracts.factory_recipe import ComponentCall, EventRequest
from modules.codes.contracts.parallel import SharedAODClaim
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import (
    FactoryExecutor,
    FactoryLimits,
)
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.scheduling import ComponentScheduler


def _measurement_case(*, readout=4, lines=1, fail_line=None):
    """Exercise final group admission with synthetic readout capacity and timing."""
    work = tuple(f"W{i}" for i in range(1, 6))
    measured = work[1:]
    roles = (*work, "R")
    calls = tuple(ComponentCall(f"final/mx/{r}", "toy.mx", (r,)) for r in measured)
    recipe = replace(
        toy_recipe(),
        work_roles=work,
        initial_preparations=tuple(preparation(r, working=True) for r in work),
        rotations=(),
        final_measurement_calls=calls,
        final_event=EventRequest(
            "final/event", "final", tuple(call.key for call in calls), measured
        ),
        retry_work_roles=work,
        released_roles=(*measured, "R"),
    )
    physical = BatchedPhysical()
    physical.bindings = {
        f"line-{line}/{role}": ComponentBinding(
            f"line-{line}/{role}",
            Position((line * len(roles) + index) * 10, 0),
            (line * len(roles) + index,),
            "fixture_aod",
        )
        for line in range(lines)
        for index, role in enumerate(roles)
    }
    resolved = []

    class MeasurementBackend(DeclaredBackend):
        def describe_execution(self, component_id, participants, parameters=()):
            spec = super().describe_execution(component_id, participants, parameters)
            if component_id != "toy.mx":
                return spec
            column = participants[0].origin.x
            return replace(
                spec,
                waveform_key="fixture-readout",
                parallel_mode="shared_aod_lockstep",
                shared_aod=SharedAODClaim(
                    "fixture_aod",
                    "fixture-rows",
                    column,
                    column + 1,
                    1,
                    1,
                    None,
                    None,
                    "fixture-camera",
                    1,
                    readout,
                    1,
                ),
            )

        def bind_call(self, component_id, participant_bindings, parameters=()):
            if (
                component_id == "toy.mx"
                and participant_bindings[0].block_id == f"line-{fail_line}/W3"
            ):
                raise ValueError("TEST_MEASUREMENT_BIND_FAILURE")
            return super().bind_call(component_id, participant_bindings, parameters)

        def resolve_event_from_sources(self, selector, parts, parameters, *, event_id):
            assert selector == "final"
            assert len(parts) == 4
            ready = max(part.results_ready_us for part in parts)
            assert physical.clock_us >= ready
            resolved.append((event_id, physical.clock_us, ready))
            return self.resolve_event(selector, parameters)

    processes = tuple(
        FactoryProcess(
            f"line-{line}",
            code=CODE,
            recipe=recipe,
            backend=MeasurementBackend(),
            role_bindings={role: f"line-{line}/{role}" for role in roles},
            distance=1,
        )
        for line in range(lines)
    )
    result = CooperativeFactoryRuntime(
        physical,
        case_id="measurement-group-fixture",
        seed=17,
        scheduler=ComponentScheduler(),
        processes=processes,
    ).run()
    return result.to_dict(), physical, resolved


@pytest.mark.parametrize("readout,widths", [(4, [4]), (2, [2, 2]), (1, [1, 1, 1, 1])])
def test_final_measurements_fill_available_readout_capacity_and_join_results(
    readout, widths
):
    case, physical, resolved = _measurement_case(readout=readout)
    assert case["status"] == "complete", case["factories"]
    measurements = [call for call in case["calls"] if call["component_id"] == "toy.mx"]
    groups = {}
    for call in measurements:
        groups.setdefault(call["batch_id"], []).append(call)
    assert [len(group) for group in groups.values()] == widths
    assert all(
        len({call["start_us"] for call in group}) == 1 for group in groups.values()
    )
    assert len(resolved) == 1
    final_events = [
        event
        for event in case["events"]
        if event["occurrence"]["invocation_id"].endswith("/final/event")
    ]
    assert len(final_events) == 1
    event = final_events[0]
    assert len(event["dependencies"]) == 4
    assert (
        len(
            {
                result["result_id"]
                for dependency in event["dependencies"]
                for result in dependency["results"]
            }
        )
        == 4
    )
    assert event["released_at_us"] == resolved[0][2]
    assert event["released_at_us"] > max(call["end_us"] for call in measurements)
    assert max(time for time, _ in physical.waits) >= resolved[0][2]


def test_final_measurements_batch_with_other_factories_at_one_stage_barrier():
    case, _, resolved = _measurement_case(readout=8, lines=2)
    measurements = [call for call in case["calls"] if call["component_id"] == "toy.mx"]
    assert case["status"] == "complete"
    assert (
        len(measurements) == 8 and len({call["batch_id"] for call in measurements}) == 1
    )
    assert len(resolved) == 2
    barriers = [
        mark
        for mark in case["milestones"]
        if mark["kind"] == "cohort_barrier_released"
        and mark["stage_key"] == "batch[0]/final/measurements_complete"
    ]
    assert len(barriers) == 2
    assert all(mark["peers"] == ["line-0", "line-1"] for mark in barriers)


def test_failed_final_group_cancels_its_pending_children_and_releases_peer():
    case, _, resolved = _measurement_case(readout=8, lines=2, fail_line=0)
    assert case["factories"]["line-0"]["status"] == "physical_failure"
    assert case["factories"]["line-1"]["status"] == "complete"
    assert len(resolved) == 1 and resolved[0][0].startswith("line-1/")
    cancelled = case["component_schedule"]["cancelled"]
    assert set(cancelled) == {f"line-0/batch[0]/final/mx/W{i}" for i in range(2, 6)}
    assert not set(cancelled).intersection(case["component_schedule"]["completed"])
    assert all(
        not call["invocation_id"].startswith("line-0/batch[0]/final/")
        for call in case["calls"]
    )


def _run(
    scripts=({}, {}),
    *,
    limits=None,
    algorithm=False,
    backend_factory=None,
    recipe=None,
):
    physical = BatchedPhysical()
    physical.bindings = {
        f"line-{line}/{role}": ComponentBinding(
            f"line-{line}/{role}",
            Position(line * 10 + index, 0),
            (line * 4 + index,),
            "fixture_aod",
        )
        for line in range(len(scripts))
        for index, role in enumerate(("W1", "W2", "R", "D"))
    }
    processes = tuple(
        FactoryProcess(
            f"line-{line}",
            code=CODE,
            recipe=toy_recipe() if recipe is None else recipe,
            backend=DeclaredBackend(script)
            if backend_factory is None
            else backend_factory(line, script, physical),
            role_bindings={
                role: f"line-{line}/{role}" for role in ("W1", "W2", "R", "D")
            },
            distance=1,
            limits=limits,
            algorithm_preparation=preparation("D", working=True) if algorithm else None,
            algorithm_consumption=consumption(
                "D", "W1", key="algorithm", selector="t:algorithm"
            )
            if algorithm
            else None,
        )
        for line, script in enumerate(scripts)
    )
    runtime = CooperativeFactoryRuntime(
        physical,
        case_id="cooperative-fixture",
        seed=17,
        scheduler=ComponentScheduler(),
        processes=processes,
    )
    return runtime.run().to_dict(), physical


def test_single_factory_adapter_preserves_shared_runtime_events_and_resources():
    recipe = replace(
        toy_recipe(), initial_preparations=toy_recipe().initial_preparations
    )
    old_physical, new_physical = BatchedPhysical(), BatchedPhysical()
    kwargs = {
        "code": CODE,
        "recipe": recipe,
        "role_bindings": {r: r for r in old_physical.bindings},
        "distance": 1,
    }
    old = (
        FactoryExecutor(
            **kwargs,
            backend=DeclaredBackend(),
            physical=old_physical,
            case_id="same-case",
            seed=17,
            scheduler=ComponentScheduler(),
        )
        .run()
        .to_dict()
    )
    process = FactoryProcess("factory", **kwargs, backend=DeclaredBackend())
    new = (
        CooperativeFactoryRuntime(
            new_physical,
            case_id="same-case",
            seed=17,
            scheduler=ComponentScheduler(),
            processes=(process,),
        )
        .run()
        .to_dict()
    )
    assert new["status"] == old["status"] == "complete"
    assert [(c["invocation_id"], c["component_id"]) for c in new["calls"]] == [
        (c["invocation_id"], c["component_id"]) for c in old["calls"]
    ]
    assert [(e["occurrence"], e["outcome_key"]) for e in new["events"]] == [
        (e["occurrence"], e["outcome_key"]) for e in old["events"]
    ]
    assert new["resources"]["tokens"] == old["resources"]["tokens"]


def test_two_factories_share_frontier_and_keep_outputs_held():
    case, _ = _run()
    assert case["status"] == "complete"
    assert len(case["factories"]) == 2
    starts = [
        c
        for c in case["calls"]
        if "/prepare/W" in c["invocation_id"] and c["invocation_id"].endswith("/body")
    ]
    assert len(starts) == 4 and len({c["start_us"] for c in starts}) == 1
    outputs = [
        t for t in case["resources"]["tokens"] if t["token_id"].endswith("/output")
    ]
    assert len(outputs) == 2 and all(t["status"] == "offered" for t in outputs)
    assert all(
        line["algorithm_consumed_token_id"] is None
        for line in case["factories"].values()
    )


def test_retry_and_terminal_failure_are_local_and_other_factory_continues():
    case, _ = _run(
        ({"prep:W1": ("rejected",)}, {}), limits=FactoryLimits(raw_attempts=1)
    )
    assert case["factories"]["line-0"]["status"] == "input_supply_exhausted"
    assert case["factories"]["line-1"]["status"] == "complete"
    assert case["status"] == "partial_failure"
    assert not any(
        c["invocation_id"].startswith("line-0/") and c["component_id"] == "toy.compute"
        for c in case["calls"]
    )
    assert all(
        t["status"] not in ("offered", "reserved")
        for t in case["resources"]["tokens"]
        if t["carrier_id"].startswith("line-0/")
    )


def test_independent_retry_does_not_restart_successful_sibling_patch():
    case, _ = _run(({"prep:W1": ("rejected", "accepted")}, {}))
    assert case["status"] == "complete"

    def count(key):
        return sum(
            key in c["invocation_id"] and c["invocation_id"].endswith("/body")
            for c in case["calls"]
        )

    assert count("line-0/batch[0]/prepare/W1/") == 2
    assert count("line-0/batch[0]/prepare/W2/") == 1
    assert count("line-1/batch[0]/prepare/W1/") == 1
    assert count("line-1/batch[0]/prepare/W2/") == 1


def test_ready_canonicalization_precedes_retry_from_an_older_fairness_round():
    # A separate plus preparation gives the lines different service ordinals.
    # Both raw decisions are ready: finish the accepted source before restarting
    # its rejected peer. This must not depend on which line was served last.
    recipe = replace(
        toy_recipe(),
        initial_preparations=(preparation("W1", working=True), preparation("W2")),
    )
    case, _ = _run(({"prep:W2": ("rejected", "accepted")}, {}), recipe=recipe)
    assert case["status"] == "complete"
    accepted = next(
        call
        for call in case["calls"]
        if call["invocation_id"] == "line-1/batch[0]/prepare/W2/attempt[0]/canonicalize"
    )
    retry = next(
        call
        for call in case["calls"]
        if call["invocation_id"] == "line-0/batch[0]/prepare/W2/attempt[1]/body"
    )
    assert accepted["end_us"] <= retry["start_us"]


def test_optional_algorithm_consumes_each_output_once():
    case, _ = _run(algorithm=True)
    assert case["status"] == "complete"
    outputs = [
        t for t in case["resources"]["tokens"] if t["token_id"].endswith("/output")
    ]
    assert len(outputs) == 2 and all(t["status"] == "consumed" for t in outputs)
    assert all(
        line["algorithm_consumed_token_id"] == line["output_token_id"]
        for line in case["factories"].values()
    )


def test_one_binding_failure_cancels_only_its_line_before_physical_writes():
    class FailingBackend(DeclaredBackend):
        def bind_call(self, component_id, participant_bindings, parameters=()):
            if participant_bindings[0].block_id.startswith("line-0/"):
                raise ValueError("TEST_FIXTURE_BIND_FAILURE")
            return super().bind_call(component_id, participant_bindings, parameters)

    case, _ = _run(
        backend_factory=lambda line, script, physical: FailingBackend(script)
    )
    assert case["factories"]["line-0"]["status"] == "physical_failure"
    assert case["factories"]["line-1"]["status"] == "complete"
    assert all(c["factory_id"] == "line-1" for c in case["calls"])
    cancelled = case["component_schedule"]["cancelled"]
    assert cancelled and all(key.startswith("line-0/") for key in cancelled)
    assert not set(cancelled).intersection(case["component_schedule"]["completed"])


def test_model_resolvers_run_only_after_sources_are_ready():
    seen = []

    def backend_factory(line, script, physical):
        class ReadyBackend(DeclaredBackend):
            def preparation_event(self, preparation, source, parameters):
                ready = max(part.results_ready_us for part in source.parts)
                assert physical.clock_us >= ready
                seen.append((physical.clock_us, ready))
                role = source.parts[0].exit_binding.block_id.rsplit("/", 1)[-1]
                return self.resolve_event("prep:" + role)

            def resolve_event_from_sources(
                self, selector, parts, parameters, *, event_id
            ):
                ready = max(part.results_ready_us for part in parts)
                assert physical.clock_us >= ready
                seen.append((physical.clock_us, ready))
                return self.resolve_event(selector, parameters)

        return ReadyBackend(script)

    case, _ = _run(backend_factory=backend_factory)
    assert case["status"] == "complete" and len(seen) == len(case["events"])
    for event in case["events"]:
        assert event["released_at_us"] >= max(
            result["available_at_us"]
            for source in event["dependencies"]
            for result in source["results"]
        )


def test_real_two_factory_initial_raw_wave_uses_one_shared_aod():
    """Real bodies/validation, deliberately limited before any factory protocol.

    A fixture treats all accepted preparations as work states and exhausts the
    component budget after initial canonicalization. No factory output, noisy
    quality or logical success is asserted by this bounded integration test.
    """
    from modules.codes.rotated_surface_d3.protocols.factory import factory_recipe
    from modules.codes.rotated_surface_d3.protocols.factory_array import (
        make_factory_array,
    )
    from modules.codes.rotated_surface_d3.protocols.factory_backend import (
        SurfaceFactoryBackend,
    )
    from modules.logical_compiler.src.protocols.physical import PhysicalContext

    world = make_factory_array()
    physical = PhysicalContext(world.device, world.world_state, world.bindings.values())
    backend = SurfaceFactoryBackend(world.device)
    original = factory_recipe()
    recipe = replace(
        original,
        protocol_id="test_fixture.initial_real_bodies_only",
        initial_preparations=tuple(
            replace(item, resource_kind=None, ownership="working")
            for item in original.initial_preparations
        ),
    )
    processes = tuple(
        FactoryProcess(
            placement.factory_id,
            code=recipe.code_id,
            recipe=recipe,
            backend=backend,
            role_bindings={
                role: binding.block_id for role, binding in placement.bindings.items()
            },
            distance=3,
            limits=FactoryLimits(max_component_calls=10),
        )
        for placement in world.factories
    )
    result = CooperativeFactoryRuntime(
        physical,
        case_id="test-fixture-real-shared-lines",
        seed=0,
        scheduler=ComponentScheduler(),
        processes=processes,
    ).run()
    case = result.to_dict()
    assert all(
        line["status"] == "expansion_budget_exhausted"
        for line in case["factories"].values()
    ), case["factories"]
    assert result.physical is not None and result.physical.validation["ok"] is True
    assert len(result.physical.world.atoms) == 204
    assert len(world.device.aods) == 1
    initial_raw = [
        c for c in case["calls"] if c["component_id"] == "raw_t_postselection"
    ]
    assert len(initial_raw) == 8
    assert len({c["start_us"] for c in initial_raw}) == 1
    assert len({c["batch_id"] for c in initial_raw}) == 1
    assert all(m.value is None for m in result.physical.pending_measurements)
    batch = physical.batch_for(initial_raw[0]["invocation_id"])
    assert batch is not None and len(batch.member_parts) == 8
    assert batch.to_dict()["mode"] == "shared_aod_lockstep"
    assert all(line["output_token_id"] is None for line in case["factories"].values())
