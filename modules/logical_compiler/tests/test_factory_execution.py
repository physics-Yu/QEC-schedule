"""Toy protocol lifecycle tests, explicitly not physical or surface-code evidence."""

from collections import Counter
from dataclasses import dataclass
from types import SimpleNamespace

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
