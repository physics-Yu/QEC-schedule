"""Independent schedules for homogeneous object waves and retained AOD leases."""

from dataclasses import replace

import pytest

from modules.codes.contracts.parallel import ComponentPhase
from modules.logical_compiler.src.estimation.phases import (
    PhaseInvocation,
    schedule_phases,
)


def readout(lift=50, share="same-grid"):
    aod = ("aod:transport",)
    return (
        ComponentPhase("load", 10, "transfer", aod, share, acquire=aod),
        ComponentPhase("outbound", lift, "movement", aod, share),
        ComponentPhase(
            "measure", 100, "measurement", (*aod, "camera"), share, results=1
        ),
        ComponentPhase("return", lift, "movement", aod, share),
        ComponentPhase("store", 10, "transfer", aod, share, release=aod),
    )


def member(name, stages, component="read"):
    return PhaseInvocation(name, "test_fixture", component, stages)


def test_same_component_shared_command_is_counted_once():
    plan = schedule_phases((member("a", readout()), member("b", readout())))
    assert plan.duration_us == 220
    assert len(plan.steps) == 5
    assert all(step["members"] == ["a", "b"] for step in plan.steps)
    assert plan.measurements["a"] == ((160, 0),)
    assert plan.measurements["b"] == ((160, 0),)
    assert plan.resource_busy_us["aod:transport"] == 220
    assert plan.resource_busy_us["camera"] == 100


def test_incompatible_transports_queue_through_measurement_and_return():
    plan = schedule_phases(
        (member("a", readout(50, None)), member("b", readout(70, None)))
    )
    assert plan.duration_us == 480
    b_load = next(s for s in plan.steps if s["members"] == ["b"])
    assert b_load["start_us"] == 220  # Not 60 (outbound end) or 160 (readout end).
    assert plan.waits == (
        {
            "member": "b",
            "phase": "load",
            "start_us": 0.0,
            "end_us": 220.0,
            "resources": ["aod:transport"],
        },
    )


def test_same_component_can_use_local_control_while_peer_holds_aod():
    local = ComponentPhase("local", 5, "gate", ("local",), None)
    plan = schedule_phases(
        (member("a", readout(50, None)), member("b", (local, *readout(50, None))))
    )
    first = {s["phase"]: s for s in plan.steps if s["start_us"] == 0}
    assert first["local"]["end_us"] == 5
    assert first["load"]["end_us"] == 10
    assert plan.duration_us == 440


def test_different_components_are_rejected_even_with_disjoint_resources():
    with pytest.raises(ValueError, match="HETEROGENEOUS"):
        schedule_phases((member("a", readout()), member("b", readout(), "other")))


def test_matching_load_does_not_merge_incompatible_lease_continuations():
    a, b = readout(), readout(70)
    plan = schedule_phases((member("a", a), member("b", b)))
    assert plan.duration_us == 480


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf")])
def test_invalid_duration_fails_before_scheduling(duration):
    with pytest.raises(ValueError, match="PHASE"):
        replace(readout()[0], duration_us=duration)


def test_unbalanced_resource_lease_fails():
    with pytest.raises(ValueError, match="LEASE"):
        schedule_phases((member("a", readout()[:-1]),))


def test_deadline_reports_stage_instead_of_returning_partial_success():
    with pytest.raises(TimeoutError, match="object_wave.*budget"):
        schedule_phases((member("a", readout()),), timeout_seconds=0)
