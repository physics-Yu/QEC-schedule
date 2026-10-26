"""Local correction alignment preserves emitted operations and source clocks."""

from math import pi

import pytest
from nadit_physical_compiler.atom_ir import AtomStep, LocalU, Reset, Rotation, Wait

from modules.logical_compiler.src.protocols.local_batch import align_local_lanes


def _pulse(atom, source, *, axis="X", duration=1):
    return Rotation(
        "local", (atom,), axis, pi, duration_us=duration, source_ids=(source,)
    )


def test_different_classes_and_depths_preserve_every_action_and_member_end():
    first = _pulse(10, 0)
    second = LocalU("local", (20,), pi, 0, pi, duration_us=1, source_ids=(1,))
    last = _pulse(20, 2, axis="Z")
    lanes = ((AtomStep((first,)),), (AtomStep((second,)), AtomStep((last,))), ())
    aligned = align_local_lanes(lanes, start_us=100000.125)
    assert aligned.steps == (AtomStep((first, second)), AtomStep((last,)))
    assert aligned.member_step_indices == ((0,), (0, 1), ())
    assert aligned.member_action_indices == (((0,),), ((1,), (0,)), ())
    assert aligned.member_action_end_us == (100001.125, 100002.125, 100000.125)
    assert aligned.action_end_us == 100002.125
    assert aligned.steps[0].actions[0] is first
    assert aligned.steps[0].actions[1] is second


def test_all_identity_classes_remain_zero_actions_and_zero_duration():
    aligned = align_local_lanes(((), ()), start_us=47.25)
    assert aligned.steps == ()
    assert aligned.member_step_indices == ((), ())
    assert aligned.member_action_indices == ((), ())
    assert aligned.member_action_end_us == (47.25, 47.25)
    assert aligned.action_end_us == 47.25


def test_existing_zero_wait_keeps_its_slot_without_delaying_following_pulse():
    noop = Wait(duration_us=0)
    first, second = _pulse(10, 0), _pulse(20, 1, axis="Z")
    aligned = align_local_lanes(
        ((AtomStep((noop,)), AtomStep((first,))), (AtomStep((second,)),)),
        start_us=7,
    )
    assert aligned.steps == (AtomStep((noop, first, second)),)
    assert aligned.member_step_indices == ((0, 0), (0,))
    assert aligned.member_action_indices == (((0,), (1,)), ((2,),))
    assert aligned.member_action_end_us == (8, 8)


@pytest.mark.parametrize(
    "action", [Wait(duration_us=1), Reset("local", (0,), duration_us=1)]
)
def test_non_correction_actions_are_rejected(action):
    with pytest.raises(ValueError, match="LOCAL_BATCH_UNSUPPORTED_ACTION"):
        align_local_lanes(((AtomStep((action,)),),), start_us=0)


def test_incompatible_local_pulse_boundaries_cannot_be_padded_or_split():
    with pytest.raises(ValueError, match="LOCAL_BATCH_DURATION_MISMATCH"):
        align_local_lanes(
            (
                (AtomStep((_pulse(1, 0, duration=1),)),),
                (AtomStep((_pulse(2, 1, duration=2),)),),
            ),
            start_us=0,
        )


def test_original_sequential_floating_clock_is_preserved_exactly():
    lane = tuple(AtomStep((_pulse(1, i, duration=0.1),)) for i in range(11))
    other = (AtomStep((_pulse(2, 11, duration=0.1),)),)
    start = 1000000.125
    clock = start
    for step in lane:
        clock += step.duration_us
    aligned = align_local_lanes((lane, other), start_us=start)
    assert aligned.action_end_us == clock
    assert aligned.member_action_end_us == (clock, start + 0.1)
