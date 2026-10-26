"""Independent final MX calls join before their unchanged joint feedback event."""

from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace

import pytest

from modules.codes.rotated_surface.fast_factory import factory_recipe
from modules.codes.rotated_surface.object_factory import FactoryObjectCatalog
from modules.logical_compiler.examples.factory_objects import run_factory_objects
from modules.logical_compiler.examples.object_cases import forbid_atom_work
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.protocol_intents import (
    BarrierIntent,
    CallIntent,
)


@pytest.mark.parametrize("factories,seed", [(1, 0), (2, 0), (2, 1)])
def test_final_measurements_join_per_batch_and_feedback_waits_for_all(factories, seed):
    with forbid_atom_work() as counters:
        result = run_factory_objects(
            FactoryObjectCatalog.load(), factories=factories, seed=seed, cycles=2
        )
    case = result["case"]
    groups = defaultdict(list)
    for call in case["calls"]:
        if call["component_id"] == "logical_mx":
            groups[call["invocation_id"].split("/final/mx/")[0]].append(call)
    assert len(groups) == result["summary"]["batches"]
    for scope, calls in groups.items():
        assert len(calls) == 4
        assert {c["invocation_id"] for c in calls} == {
            f"{scope}/final/mx/{role}" for role in ("W2", "W3", "W4", "W5")
        }
        assert len({c["batch_id"] for c in calls}) == 1
        assert len({c["start_us"] for c in calls}) == 1
        final = next(
            e
            for e in case["events"]
            if e["occurrence"]["invocation_id"] == scope + "/final/event"
        )
        assert {d["invocation_id"] for d in final["dependencies"]} == {
            c["invocation_id"] for c in calls
        }
        assert final["released_at_us"] >= max(c["end_us"] for c in calls)
    assert not any(counters.values())
    assert result["summary"]["raw_acceptance_parameter"] == 51235 / 65536
    assert (
        result["summary"]["raw_attempts"],
        result["summary"]["raw_rejections"],
        result["summary"]["batches"],
    ) == {(1, 0): (47, 17, 2), (2, 0): (84, 24, 4), (2, 1): (107, 32, 5)}[
        factories, seed
    ]


@pytest.mark.parametrize(
    "restriction", ["shared_role", "mixed_component", "non_object"]
)
def test_final_measurement_submission_retains_order_when_not_independent(restriction):
    recipe = factory_recipe(3)
    first, second = recipe.final_measurement_calls[:2]
    if restriction == "shared_role":
        second = replace(second, participant_roles=first.participant_roles)
    elif restriction == "mixed_component":
        second = replace(second, component_id="logical_mz")
    process = object.__new__(FactoryProcess)
    process.recipe = replace(recipe, final_measurement_calls=(first, second))
    process.roles = {role: f"factory0/{role}" for role in recipe.work_roles}
    process.backend = None
    process._runtime = SimpleNamespace(
        execution=SimpleNamespace(
            describe=lambda *_: SimpleNamespace(
                parallel_mode="exclusive"
                if restriction == "non_object"
                else "object_wave"
            )
        )
    )
    flow = process._final_measurements("factory0/batch[0]", 0)
    intent = next(flow)
    assert isinstance(intent, CallIntent) and intent.call == first
    assert intent.invocation_id == "factory0/batch[0]/" + first.key
    assert flow.send(()) == BarrierIntent(0, "final/measurement[0]")
    intent = next(flow)
    assert isinstance(intent, CallIntent) and intent.call == second
    assert flow.send(()) == BarrierIntent(0, "final/measurement[1]")
    with pytest.raises(StopIteration):
        next(flow)
