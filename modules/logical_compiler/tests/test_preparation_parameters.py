"""Preserve code-owned preparation parameters through every logical entry."""

from dataclasses import replace

import pytest
from test_factory_execution import CODE, toy_recipe
from test_factory_process import _run
from test_scheduled_factory import BatchedPhysical, DeclaredBackend

from modules.logical_compiler.src.protocols.factory import FactoryExecutor
from modules.logical_compiler.src.scheduling import ComponentScheduler

PARAMETERS = (("extra_rounds", 2),)


def recipe():
    base = toy_recipe()
    return replace(
        base,
        initial_preparations=tuple(
            replace(p, parameters=PARAMETERS) for p in base.initial_preparations
        ),
        rotations=tuple(
            replace(r, preparation=replace(r.preparation, parameters=PARAMETERS))
            for r in base.rotations
        ),
    )


class ParameterBackend(DeclaredBackend):
    def bind_call(self, component_id, participants, parameters=()):
        if component_id == "toy.raw":
            assert parameters == PARAMETERS
        return super().bind_call(component_id, participants, ())


@pytest.mark.parametrize("scheduled", (False, True))
def test_default_and_explicit_scheduler_forward_preparation_parameters(scheduled):
    physical = BatchedPhysical()
    case = (
        FactoryExecutor(
            code=CODE,
            recipe=recipe(),
            backend=ParameterBackend(),
            physical=physical,
            role_bindings={role: role for role in physical.bindings},
            distance=1,
            case_id="parameter-forwarding",
            seed=17,
            scheduler=ComponentScheduler() if scheduled else None,
        )
        .run()
        .to_dict()
    )
    assert case["status"] == "complete", case["failure"]
    assert all(
        call["parameters"] == dict(PARAMETERS)
        for call in case["calls"]
        if call["component_id"] == "toy.raw"
    )


def test_cooperative_process_forwards_same_preparation_parameters_on_retry():
    case, _ = _run(
        scripts=({"prep:W1": ("rejected", "accepted")},),
        recipe=recipe(),
        backend_factory=lambda *_: ParameterBackend(
            {"prep:W1": ("rejected", "accepted")}
        ),
    )
    assert case["status"] == "complete", case.get("failure")
    calls = case["factories"]["line-0"]["calls"]
    assert (
        len(
            [
                call
                for call in calls
                if "/prepare/W1/" in call["invocation_id"]
                and call["component_id"] == "toy.raw"
            ]
        )
        == 2
    )
    assert all(
        call["parameters"] == dict(PARAMETERS)
        for call in calls
        if call["component_id"] == "toy.raw"
    )
