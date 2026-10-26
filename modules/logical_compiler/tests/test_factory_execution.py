"""Toy protocol lifecycle tests, explicitly not physical or surface-code evidence."""

import json
from collections import Counter
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.device import Position

from modules.codes.contracts.component import ComponentBinding
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import (
    ComponentCall,
    EventBranch,
    EventRequest,
    FactoryRecipe,
    ResourcePreparation,
    RotationRecipe,
    TConsumptionRecipe,
)
from modules.logical_compiler.src.protocols.factory import (
    FactoryExecutor,
    FactoryLimits,
)

CODE = "test_fixture.toy_code"


def preparation(role, *, working=False):
    return ResourcePreparation(
        f"prepare/{role}",
        role,
        "toy.plus" if working else "toy.raw",
        f"prep:{role}",
        "toy.correction",
        None if working else "A",
        "working" if working else "reserve" if role == "R" else "adopt",
    )


def consumption(data="W1", magic="R", *, key="rotation", selector="t:rotation"):
    cx = ComponentCall(
        f"{key}/cx", "toy.cx", (data, magic), consumes_resource_role=magic
    )
    mz = ComponentCall(f"{key}/mz", "toy.mz", (magic,))
    return TConsumptionRecipe(
        key,
        data,
        magic,
        cx,
        mz,
        EventRequest(f"{key}/event", selector, (cx.key, mz.key), (data, magic)),
        (
            EventBranch("m0", ()),
            EventBranch("m1", (ComponentCall(f"{key}/s", "toy.s", (data,)),)),
        ),
    )


def toy_recipe():
    final_measurement = ComponentCall("final/mx", "toy.mx", ("W2",))
    rotation = RotationRecipe(
        "rotation",
        ("W1", "W2"),
        "W1",
        preparation("R"),
        (ComponentCall("rotation/compute", "toy.compute", ("W1", "W2")),),
        consumption(),
        (ComponentCall("rotation/uncompute", "toy.uncompute", ("W1", "W2")),),
    )
    return FactoryRecipe(
        CODE,
        "test_fixture.two_work_factory",
        "1",
        ("W1", "W2"),
        "R",
        (preparation("W1"), preparation("W2")),
        (rotation,),
        (final_measurement,),
        EventRequest("final/event", "final", (final_measurement.key,), ("W2",)),
        (ComponentCall("output/x", "toy.x", ("W1",)),),
        ("W1", "W2"),
        ("W2", "R"),
        "W1",
        "A",
    )


def fixture_port(selector, outcome_key, index):
    """Use scripted deterministic test probabilities with explicit fixture evidence."""
    if selector.startswith("t:"):
        outcomes = [
            {
                "key": "m0",
                "probability": float(outcome_key == "m0"),
                "values": {"logical_m": 0},
                "branch_id": "no_s",
            },
            {
                "key": "m1",
                "probability": float(outcome_key == "m1"),
                "values": {"logical_m": 1},
                "branch_id": "apply_s",
            },
        ]
        # This metadata must not cause a second expansion of the recipe's S call.
        branches = [
            {"key": "no_s", "transition": "continue", "steps": []},
            {
                "key": "apply_s",
                "transition": "continue",
                "steps": [{"component_id": "toy.s", "participant_roles": ["data"]}],
            },
        ]
    else:
        outcomes = [
            {
                "key": "accepted",
                "probability": float(outcome_key == "accepted"),
                "values": {"accepted": True, "byproduct_class": 0},
                "branch_id": "accept",
            },
            {
                "key": "rejected",
                "probability": float(outcome_key == "rejected"),
                "values": {"accepted": False, "byproduct_class": None},
                "branch_id": "reject",
            },
        ]
        branches = [
            {"key": "accept", "transition": "deliver", "steps": []},
            {"key": "reject", "transition": "retry", "steps": []},
        ]
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": f"test_fixture.{selector}",
            "protocol_id": f"test_fixture.protocol.{selector}",
            "protocol_version": "1",
            "model": {
                "id": "scripted_fixture",
                "kind": "test_fixture",
                "assumptions": [
                    "Synthetic control-flow unit test; no quantum or physical estimate"
                ],
                "parameters": {"selector_call": index},
                "evidence": {},
            },
            "outcomes": outcomes,
            "branches": branches,
        }
    )


@dataclass
class FixtureBound:
    component_id: str
    bindings: tuple
    result_count: int
    correction: bool = False
    early_results: bool = False

    def expand(self, context):
        start = context.start_us
        end = start + (2 if self.correction else 5)
        results = tuple(
            SimpleNamespace(
                invocation_id=context.invocation_id,
                result=SimpleNamespace(measurement_id=context.result_id_base + offset),
                available_at_us=start + 1 if self.early_results else end + 3,
                value=None,
            )
            for offset in range(self.result_count)
        )
        part = SimpleNamespace(
            invocation_id=context.invocation_id,
            description=SimpleNamespace(code_id=CODE, component_id=self.component_id),
            start_us=start,
            action_end_us=end,
            results_ready_us=max((end, *(item.available_at_us for item in results))),
            measurements=results,
            exit_binding=self.bindings[0],
            participant_bindings=self.bindings,
            exit_participant_bindings=self.bindings,
            entry_state=context.world_state,
            exit_state=context.world_state,
        )
        if self.correction:
            return SimpleNamespace(expansion=part)
        return SimpleNamespace(parts=(part,))


class FixtureBackend:
    def __init__(self, scripts=None, *, early_results=False):
        self.scripts = dict(scripts or {})
        self.event_counts = Counter()
        self.t_parameters = []
        self.early_results = early_results
        self.decision_times = []

    def describe_execution(self, component_id, participants, parameters=()):
        from nadit_physical_compiler.device import Region

        from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim

        count = int(component_id in ("toy.raw", "toy.plus", "toy.mz", "toy.mx"))
        batchable = len(participants) == 1
        return ComponentExecutionSpec(
            CODE,
            component_id,
            component_id if batchable else None,
            tuple(p.block_id for p in participants),
            tuple(
                SpaceClaim(
                    Region(p.origin.x - 0.1, -0.1, p.origin.x + 0.1, 0.1), "fixture"
                )
                for p in participants
            ),
            (),
            "independent_aods_lockstep" if batchable else "exclusive",
            count,
        )

    def bind_call(self, component_id, participant_bindings, parameters=()):
        assert parameters == ()
        measured = component_id in ("toy.raw", "toy.plus", "toy.mz", "toy.mx")
        return FixtureBound(
            component_id,
            participant_bindings,
            int(measured),
            early_results=self.early_results,
        )

    def resolve_event(self, selector, parameters=None):
        index = self.event_counts[selector]
        self.event_counts[selector] += 1
        script = self.scripts.get(
            selector, ("m0",) if selector.startswith("t:") else ("accepted",)
        )
        outcome = script[min(index, len(script) - 1)]
        if selector.startswith("t:"):
            self.t_parameters.append((selector, dict(parameters or {})))
        return fixture_port(selector, outcome, index)

    def correction_decision(
        self, source, *, event_id, probability_port, values, available_at_us
    ):
        assert source.parts
        assert probability_port.to_dict()["model"]["kind"] == "test_fixture"
        self.decision_times.append(
            (available_at_us, max(part.results_ready_us for part in source.parts))
        )
        return SimpleNamespace(
            accepted=values["accepted"],
            event_id=event_id,
            available_at_us=available_at_us,
            byproduct_class=values["byproduct_class"],
        )

    def bind_canonicalization(self, preparation, source, decision, probability_port):
        assert decision.accepted
        assert preparation
        assert probability_port.to_dict()["model"]["kind"] == "test_fixture"
        return FixtureBound(
            "toy.canonicalize", (source.parts[-1].exit_binding,), 0, correction=True
        )

    def preparation_quality(self, preparation, parameters=None):
        return {
            "kind": "test_fixture",
            "quality_verified": False,
            "consumption_parameters": {"resource_origin": "raw"},
        }

    def output_quality(self, factory_port):
        return {
            "kind": "test_fixture",
            "quality_verified": False,
            "consumption_parameters": {"resource_origin": "factory_output"},
        }


@dataclass
class FixtureBundle:
    clock_us: float
    invocation_count: int

    def to_dict(self):
        return {
            "artifact_kind": "test_fixture",
            "physical_validation": "not_performed",
            "physical_execution": False,
            "duration_us": self.clock_us,
            "invocation_count": self.invocation_count,
        }


class FixturePhysical:
    """Clock/result-ID harness; deliberately performs no physical validation."""

    def __init__(self, *, fail_on=None):
        self.clock_us = 0.0
        self.bindings = {
            role: ComponentBinding(role, Position(i, 0), (i,), "fixture_aod")
            for i, role in enumerate(("W1", "W2", "R", "D"))
        }
        self.world = SimpleNamespace(artifact_kind="test_fixture")
        self._sources = {}
        self._next_result = 0
        self.fail_on = fail_on
        self.attempted = []
        self.committed = []
        self.waits = []

    @property
    def invocations(self):
        return tuple(self.committed)

    @property
    def snapshot_id(self):
        return f"fixture:{self.clock_us}:{len(self.committed)}"

    def invoke_batch(self, admission, requests, *, not_before_us=0):
        assert admission.snapshot_id == self.snapshot_id
        start, parts, ends = max(self.clock_us, not_before_us), [], []
        for request in requests:
            self.clock_us = start
            value = self.invoke(
                request.bound, request.invocation_id, request.result_count
            )
            parts.append((request.invocation_id, value))
            ends.append(self.clock_us)
        self.clock_us = max(ends)
        return SimpleNamespace(member_parts=tuple(parts), action_end_us=self.clock_us)

    def source(self, invocation_id):
        return self._sources[invocation_id]

    def wait_until(self, time_us, *, reason):
        self.waits.append((time_us, reason))
        self.clock_us = max(self.clock_us, time_us)

    def invoke(self, bound, invocation_id, result_count=None, *, not_before_us=0):
        participants = tuple(binding.block_id for binding in bound.bindings)
        record = (bound.component_id, participants, invocation_id)
        self.attempted.append(record)
        if self.fail_on is not None and self.fail_on(bound.component_id, participants):
            raise ValueError(
                "TEST_FIXTURE_PHYSICAL_FAILURE: injected after irreversible use"
            )
        start = max(self.clock_us, not_before_us)
        source = bound.expand(
            SimpleNamespace(
                invocation_id=invocation_id,
                start_us=start,
                result_id_base=self._next_result,
                world_state=self.world,
            )
        )
        parts = (source.expansion,) if hasattr(source, "expansion") else source.parts
        count = sum(len(part.measurements) for part in parts)
        assert result_count is None or count == result_count
        assert invocation_id not in self._sources
        self._sources[invocation_id] = source
        self._next_result += count
        self.clock_us = parts[-1].action_end_us
        self.committed.append(record)
        return parts

    def finalize(self):
        return FixtureBundle(self.clock_us, len(self.committed))


def executor(
    *,
    scripts=None,
    limits=None,
    recipe=None,
    physical=None,
    role_bindings=None,
    backend=None,
):
    backend = backend or FixtureBackend(scripts)
    physical = physical or FixturePhysical()
    runner = FactoryExecutor(
        code=CODE,
        recipe=recipe or toy_recipe(),
        backend=backend,
        physical=physical,
        role_bindings=role_bindings or {role: role for role in physical.bindings},
        distance=1,
        case_id="test-fixture-factory",
        seed=17,
        limits=limits or FactoryLimits(),
    )
    return runner, backend, physical


def calls(document, component_id, roles=None):
    return [
        call
        for call in document["calls"]
        if call["component_id"] == component_id
        and (roles is None or tuple(call["participant_roles"]) == tuple(roles))
    ]


def carrier(document, carrier_id):
    return next(
        item
        for item in document["resources"]["carriers"]
        if item["carrier_id"] == carrier_id
    )


def test_startup_rejection_retries_only_the_failed_work_role():
    runner, _, _ = executor(scripts={"prep:W2": ("rejected", "accepted")})
    document = runner.run().to_dict()
    assert document["status"] == "complete"
    assert len(calls(document, "toy.raw", ("W1",))) == 1
    assert len(calls(document, "toy.raw", ("W2",))) == 2
    assert carrier(document, "W1")["epoch"] == 1
    assert carrier(document, "W2")["epoch"] == 2
    assert document["output_token_id"] is not None


def test_resource_slot_rejection_does_not_replay_compute_or_consumption():
    runner, _, _ = executor(scripts={"prep:R": ("rejected", "accepted")})
    document = runner.run().to_dict()
    assert document["status"] == "complete"
    assert len(calls(document, "toy.raw", ("R",))) == 2
    assert len(calls(document, "toy.raw", ("W1",))) == 1
    assert len(calls(document, "toy.raw", ("W2",))) == 1
    for component in ("toy.compute", "toy.cx", "toy.mz", "toy.uncompute"):
        assert len(calls(document, component)) == 1


def test_m1_applies_s_once_after_feedback_and_before_uncompute():
    runner, _, _ = executor(scripts={"t:rotation": ("m1",)})
    document = runner.run().to_dict()
    assert document["status"] == "complete"
    assert len(calls(document, "toy.s")) == 1
    ordered = [call["component_id"] for call in document["calls"]]
    assert (
        ordered.index("toy.mz")
        < ordered.index("toy.s")
        < ordered.index("toy.uncompute")
    )
    event = next(
        event
        for event in document["events"]
        if event["occurrence"]["port_id"] == "test_fixture.t:rotation"
    )
    assert event["values"] == {"logical_m": 1}
    assert calls(document, "toy.s")[0]["start_us"] >= event["released_at_us"]


def test_final_rejection_rebuilds_all_work_epochs_and_preserves_previous_batch():
    runner, _, _ = executor(
        scripts={"final": ("rejected", "accepted")}, limits=FactoryLimits(batches=2)
    )
    document = runner.run().to_dict()
    assert document["status"] == "complete"
    for role in ("W1", "W2"):
        assert len(calls(document, "toy.raw", (role,))) == 2
        assert carrier(document, role)["epoch"] == 2
    assert len(calls(document, "toy.mx")) == 2
    assert len(calls(document, "toy.x")) == 1
    final_events = [
        event
        for event in document["events"]
        if event["occurrence"]["port_id"] == "test_fixture.final"
    ]
    assert [event["values"]["accepted"] for event in final_events] == [False, True]
    assert len({call["invocation_id"] for call in document["calls"]}) == len(
        document["calls"]
    )


def test_raw_supply_exhaustion_cleans_owned_work_and_retains_failure_history():
    runner, _, _ = executor(
        scripts={"prep:R": ("rejected",)},
        limits=FactoryLimits(raw_attempts=2, batches=2),
    )
    document = runner.run().to_dict()
    assert document["status"] == "input_supply_exhausted"
    assert document["output_token_id"] is None
    assert len(calls(document, "toy.raw", ("R",))) == 2
    assert len(calls(document, "toy.raw", ("W1",))) == 1
    assert not calls(document, "toy.mx")
    for role in ("W1", "W2", "R"):
        assert carrier(document, role)["owner"] is None
    assert document["failure"] is not None


def test_final_rejection_exhaustion_has_no_output_and_a_distinct_status():
    runner, _, _ = executor(
        scripts={"final": ("rejected",)}, limits=FactoryLimits(batches=1)
    )
    document = runner.run().to_dict()
    assert document["status"] == "distillation_rejected"
    assert document["output_token_id"] is None
    assert not calls(document, "toy.x")
    assert len(calls(document, "toy.mx")) == 1


def test_output_is_corrected_and_consumed_exactly_once_by_algorithm():
    runner, backend, _ = executor()
    result = runner.run(
        algorithm_preparation=preparation("D", working=True),
        algorithm_consumption=consumption(
            "D", "W1", key="algorithm", selector="t:algorithm"
        ),
    )
    document = result.to_dict()
    assert document["status"] == "complete"
    assert document["goal"] == "factory_output_to_t"
    assert len(calls(document, "toy.x", ("W1",))) == 1
    output_id = document["output_token_id"]
    assert (
        output_id is not None and document["algorithm_consumed_token_id"] == output_id
    )
    output = next(
        token
        for token in document["resources"]["tokens"]
        if token["token_id"] == output_id
    )
    assert output["status"] == "consumed"
    output_consumptions = [
        event
        for event in document["resources"]["audit"]
        if event["action"] == "consume" and event["token_id"] == output_id
    ]
    assert len(output_consumptions) == 1
    assert output_consumptions[0]["usage_kind"] == "consume"
    assert any(
        selector == "t:algorithm"
        and parameters.get("resource_origin") == "factory_output"
        for selector, parameters in backend.t_parameters
    )
    assert result.physical.to_dict()["artifact_kind"] == "test_fixture"
    assert json.loads(result.to_json()) == document
    data = next(c for c in document["resources"]["carriers"] if c["carrier_id"] == "D")
    assert data["phase"] == "work"
    assert data["owner"] == "algorithm"


def test_physical_failure_after_consumption_cannot_trigger_raw_retry():
    physical = FixturePhysical(
        fail_on=lambda component, roles: component == "toy.mz" and roles == ("W1",)
    )
    runner, _, _ = executor(
        physical=physical, limits=FactoryLimits(raw_attempts=3, batches=2)
    )
    document = runner.run(
        algorithm_preparation=preparation("D", working=True),
        algorithm_consumption=consumption(
            "D", "W1", key="algorithm", selector="t:algorithm"
        ),
    ).to_dict()
    assert document["status"] == "physical_failure"
    output_id = document["output_token_id"]
    assert output_id is not None
    assert document["algorithm_consumed_token_id"] == output_id
    assert (
        next(
            token
            for token in document["resources"]["tokens"]
            if token["token_id"] == output_id
        )["status"]
        == "consumed"
    )
    for role in ("W1", "W2", "R"):
        assert len(calls(document, "toy.raw", (role,))) == 1
    assert (
        sum(
            component == "toy.mz" and roles == ("W1",)
            for component, roles, _ in physical.attempted
        )
        == 1
    )


def test_aliasing_work_and_resource_roles_is_rejected_before_execution():
    physical = FixturePhysical()
    with pytest.raises(ValueError):
        executor(
            physical=physical,
            role_bindings={"W1": "W1", "W2": "W2", "R": "W1", "D": "D"},
        )
    assert physical.attempted == []


def test_consuming_cx_requires_the_declared_irreversible_resource_milestone():
    recipe = toy_recipe()
    rotation = recipe.rotations[0]
    invalid_consumption = replace(
        rotation.consumption,
        cx_call=replace(rotation.consumption.cx_call, consumes_resource_role=None),
    )
    invalid_recipe = replace(
        recipe, rotations=(replace(rotation, consumption=invalid_consumption),)
    )
    physical = FixturePhysical()
    with pytest.raises(ValueError):
        executor(recipe=invalid_recipe, physical=physical)
    assert physical.attempted == []


@pytest.mark.parametrize("stop_early", [False, True])
def test_factory_executor_cannot_replay_a_started_case(stop_early):
    limits = FactoryLimits(max_component_calls=1) if stop_early else FactoryLimits()
    runner, _, physical = executor(limits=limits)
    first = runner.run().to_dict()
    assert first["status"] == (
        "expansion_budget_exhausted" if stop_early else "complete"
    )
    committed = tuple(physical.committed)
    with pytest.raises(ValueError):
        runner.run()
    assert tuple(physical.committed) == committed


def test_same_case_seed_and_fixture_inputs_reproduce_the_full_static_case():
    scripts = {"prep:R": ("rejected", "accepted"), "t:rotation": ("m1",)}
    first, _, _ = executor(scripts=scripts)
    second, _, _ = executor(scripts=scripts)
    assert first.run().to_json() == second.run().to_json()


@pytest.mark.parametrize(("call_budget", "committed"), [(1, 0), (2, 2), (7, 7)])
def test_global_call_budget_stops_before_an_indivisible_wave(call_budget, committed):
    runner, _, physical = executor(
        limits=FactoryLimits(max_component_calls=call_budget)
    )
    document = runner.run().to_dict()
    assert document["status"] == "expansion_budget_exhausted"
    assert document["output_token_id"] is None
    assert len(document["calls"]) == committed
    assert len(physical.committed) == committed
    assert len(physical.attempted) == committed
    assert committed <= call_budget
    assert document["failure"] is not None


@pytest.mark.parametrize("field", ["raw_attempts", "batches", "max_component_calls"])
@pytest.mark.parametrize("invalid", [0, True])
def test_factory_limits_require_positive_integer_budgets(field, invalid):
    with pytest.raises(ValueError):
        FactoryLimits(**{field: invalid})


def test_preparation_decision_uses_complete_feedback_release_not_early_result_time():
    backend = FixtureBackend(early_results=True)
    runner, _, _ = executor(backend=backend)
    document = runner.run().to_dict()
    assert document["status"] == "complete"
    assert backend.decision_times
    preparation_events = [
        event
        for event in document["events"]
        if event["occurrence"]["port_id"].startswith("test_fixture.prep:")
    ]
    assert all(
        event["available_at_us"] < event["released_at_us"]
        for event in preparation_events
    )
    for decision_available, complete_source_ready in backend.decision_times:
        assert decision_available >= complete_source_ready


def test_new_executor_rejects_physical_context_with_preexisting_invocations():
    physical = FixturePhysical()
    physical.invoke(
        FixtureBound("toy.raw", (physical.bindings["W1"],), 1), "preexisting"
    )
    before = tuple(physical.committed)
    with pytest.raises(ValueError):
        executor(physical=physical)
    assert tuple(physical.committed) == before


class SourcePreparationBackend(FixtureBackend):
    def __init__(self, *, unsupported=False):
        super().__init__({"prep:W1": ("rejected", "accepted")})
        self.preparation_sources = []
        self.quality_sources = []
        self.unsupported = unsupported

    def preparation_event(self, preparation, source, parameters=None):
        self.preparation_sources.append(source)
        role = source.parts[-1].exit_binding.block_id
        return self.resolve_event(f"prep:{role}", parameters)

    def preparation_quality_from_event(
        self, preparation, source, port, values, parameters=None
    ):
        assert values["accepted"] is True
        self.quality_sources.append(source)
        return {
            "status": "unsupported" if self.unsupported else "test_fixture",
            "reason": "No residual-sector recovery model" if self.unsupported else None,
            "source_port_sha256": port.content_sha256,
            "consumption_parameters": None
            if self.unsupported
            else {"source_bound": True},
        }

    def preparation_quality(self, preparation, parameters=None):
        raise AssertionError("Source-aware quality must not fall back to ideal quality")


def test_source_preparation_hooks_receive_each_actual_retry_and_selected_event():
    backend = SourcePreparationBackend()
    runner, _, physical = executor(backend=backend)
    document = runner.run().to_dict()
    assert document["status"] == "complete"
    assert len(backend.preparation_sources) == 4
    assert len(backend.quality_sources) == 3
    rejected = physical.source("factory/batch[0]/prepare/W1/attempt[0]/body")
    retried = physical.source("factory/batch[0]/prepare/W1/attempt[1]/body")
    peer = physical.source("factory/batch[0]/prepare/W2/attempt[0]/body")
    assert all(
        any(source is expected for source in backend.preparation_sources)
        for expected in (rejected, retried, peer)
    )
    assert all(source is not rejected for source in backend.quality_sources)
    assert all(
        any(source is expected for source in backend.quality_sources)
        for expected in (retried, peer)
    )


def test_unsupported_raw_quality_retains_discarded_resource_evidence_without_consuming():
    backend = SourcePreparationBackend(unsupported=True)
    runner, _, _ = executor(backend=backend)
    document = runner.run().to_dict()
    assert document["status"] == "unsupported_resource_quality"
    assert len(calls(document, "toy.raw")) == 2
    assert len(calls(document, "toy.correction/canonicalize")) == 1
    assert not calls(document, "toy.cx")
    tokens = document["resources"]["tokens"]
    assert len(tokens) == 1 and tokens[0]["status"] == "discarded"
    assert any(
        e["action"] == "discard" and e["token_id"] == tokens[0]["token_id"]
        for e in document["resources"]["audit"]
    )
    assert tokens[0]["quality"]["consumption_parameters"] is None
    assert not any(e["action"] == "consume" for e in document["resources"]["audit"])


def test_unsupported_output_quality_stops_before_irreversible_algorithm_cx():
    class UnsupportedOutput(FixtureBackend):
        def output_quality(self, factory_port):
            return {"status": "unsupported", "consumption_parameters": None}

    runner, _, _ = executor(backend=UnsupportedOutput())
    document = runner.run(
        algorithm_preparation=preparation("D", working=True),
        algorithm_consumption=consumption(
            "D", "W1", key="algorithm", selector="t:algorithm"
        ),
    ).to_dict()
    assert document["status"] == "unsupported_resource_quality"
    assert document["algorithm_consumed_token_id"] is None
    assert not calls(document, "toy.cx", ("D", "W1"))
    output = next(
        t
        for t in document["resources"]["tokens"]
        if t["token_id"] == document["output_token_id"]
    )
    assert output["status"] == "discarded"
    assert any(
        e["action"] == "reserve" and e["token_id"] == output["token_id"]
        for e in document["resources"]["audit"]
    )


@pytest.mark.parametrize("quality", [{}, {"status": "unknown"}])
def test_missing_consumption_model_cannot_fall_back_to_ideal(quality):
    class MissingQuality(FixtureBackend):
        def preparation_quality(self, preparation, parameters=None):
            return quality

    runner, _, _ = executor(backend=MissingQuality())
    document = runner.run().to_dict()
    assert document["status"] == "unsupported_resource_quality"
    assert len(document["resources"]["tokens"]) == 1
    assert not any(e["action"] == "consume" for e in document["resources"]["audit"])


def test_source_event_model_is_built_only_after_actual_feedback_sources_are_ready():
    physical = FixturePhysical()

    class ContextEvents(FixtureBackend):
        def __init__(self):
            super().__init__()
            self.source_events = []

        def resolve_event_from_sources(self, selector, parts, parameters, *, event_id):
            assert physical.clock_us >= max(part.results_ready_us for part in parts)
            self.source_events.append((selector, event_id, parts))
            return self.resolve_event(selector, parameters)

    backend = ContextEvents()
    runner, _, _ = executor(backend=backend, physical=physical)
    document = runner.run().to_dict()
    assert document["status"] == "complete"
    assert [event[0] for event in backend.source_events] == ["t:rotation", "final"]
    assert backend.source_events[-1][1] == "factory/batch[0]/final/event"
    assert (
        backend.source_events[-1][2]
        == physical.source("factory/batch[0]/final/mx").parts
    )
