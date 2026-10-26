"""Cooperative recipe control; toy cases make no physical probability claim."""

from dataclasses import replace

from nadit_physical_compiler.device import Position
from test_factory_execution import CODE, consumption, preparation, toy_recipe
from test_scheduled_factory import BatchedPhysical, DeclaredBackend

from modules.codes.contracts.component import ComponentBinding
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import (
    FactoryExecutor,
    FactoryLimits,
)
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.scheduling import ComponentScheduler


def _run(
    scripts=({}, {}),
    *,
    limits=None,
    algorithm=False,
    mode="parallel",
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
        scheduler=ComponentScheduler(mode=mode),
        processes=processes,
    )
    return runtime.run().to_dict(), physical


def test_one_factory_preserves_legacy_events_and_resource_protocol():
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
