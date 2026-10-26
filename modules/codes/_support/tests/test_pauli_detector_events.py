"""Actual T checkpoint, arbitrary participant roles and isolated-world projection."""

from dataclasses import replace
from math import pi

import pytest
from nadit_physical_compiler.activity import (
    ActivityEvent,
    AtomActivity,
    PerAtomActivity,
)

from modules.codes._support.pauli_detector_events import detector_fault_channels
from modules.codes.rotated_surface_d3.probabilities.raw_t_detectors import (
    detector_fault_channels as legacy_detectors,
)

SEED, CHECK, SPECTATOR = 42, 7, 1000


def _event(kind, start, atoms, **kwargs):
    return ActivityEvent(
        kind, start, 1, atoms, (), (), step_index=start, action_index=0, **kwargs
    )


def _activity():
    events = (
        _event("Reset", 0, (SEED, CHECK)),
        _event("Rotation", 1, (SEED,), parameters={"axis": "Y", "angle": pi / 2}),
        _event("Rotation", 2, (SEED,), parameters={"axis": "Z", "angle": pi / 4}),
        _event("CZPulse", 3, (SEED, CHECK, SPECTATOR), pairs=((SEED, CHECK),)),
        _event("Measure", 4, (CHECK,), measurement_ids=(10,)),
    )
    atoms = tuple(
        PerAtomActivity(
            atom_id=atom,
            busy=(),
            idle=(),
            busy_us=0,
            idle_us=5,
            idle_by_holder_role={},
            loads=0,
            stores=0,
            transfers=0,
            move_count=0,
            move_distance_um=0,
            cz_count=0,
            rotation_count=0,
            measure_count=0,
            reset_count=0,
        )
        for atom in (SEED, CHECK, SPECTATOR)
    )
    return AtomActivity(5, atoms, events)


def _estimate(activity=None, channels=(), detectors=((10,),)):
    return detector_fault_channels(
        activity or _activity(),
        list(channels),
        detectors,
        wire_atoms=(CHECK, SEED),
        seed_atom=SEED,
        world_atom_ids=(SPECTATOR, SEED, CHECK),
    )


def test_more_than_64_detectors_keep_every_mask_bit_and_real_t_proof():
    channels = [
        {
            "instruction": "X_ERROR",
            "probabilities": [0.2],
            "atoms": [CHECK],
            "placement": "after",
            "event_id": 3,
        }
    ]
    faults, proof = _estimate(channels=channels, detectors=((10,),) * 80)
    assert faults == ((((1 << 80) - 1, 0.2),),)
    assert proof["center_t_identity_checks"] == proof["detector_count"] == 80
    assert proof["seed_atom"] == SEED
    assert proof["world_atom_count"] == 3
    assert proof["participant_atom_count"] == proof["propagated_wire_count"] == 2
    assert proof["logical_state_replaced_by_clifford_proxy"] is False


def test_spectator_projection_preserves_full_exclusive_channel_branches():
    from nadit_physical_compiler.cost.noise.report import PAULI_2_ORDER

    weights = [0.0] * 15
    weights[PAULI_2_ORDER.index("XI")] = 0.2
    weights[PAULI_2_ORDER.index("IX")] = 0.3
    channels = [
        {
            "instruction": "PAULI_CHANNEL_1",
            "probabilities": [0.2, 0.3, 0.1],
            "atoms": [SPECTATOR],
            "placement": "before",
            "event_id": 2,
        },
        {
            "instruction": "PAULI_CHANNEL_2",
            "probabilities": weights,
            "atoms": [CHECK, SPECTATOR],
            "placement": "after",
            "event_id": 3,
        },
    ]
    faults, proof = _estimate(channels=channels)
    assert faults[0] == ((0, 0.2), (0, 0.3), (0, 0.1))
    assert faults[1][PAULI_2_ORDER.index("XI")] == (1, 0.2)
    assert faults[1][PAULI_2_ORDER.index("IX")] == (0, 0.3)
    assert proof["zero_signature_channel_count"] == 1


def test_readout_identity_and_post_measurement_noise_locations():
    channels = [
        {
            "instruction": "M",
            "probabilities": [0.1],
            "atoms": [CHECK],
            "placement": "measurement_argument",
            "measurement_id": 10,
        },
        {
            "instruction": "X_ERROR",
            "probabilities": [0.2],
            "atoms": [CHECK],
            "placement": "after",
            "event_id": 4,
        },
    ]
    faults, _ = _estimate(channels=channels)
    assert faults == (((1, 0.1),), ((0, 0.2),))
    channels[0]["atoms"] = [SEED]
    with pytest.raises(ValueError, match="actual measurement"):
        _estimate(channels=channels)


def test_detector_dependent_on_the_actual_t_seed_is_rejected():
    activity = _activity()
    events = (
        *activity.events[:-1],
        _event("Rotation", 4, (SEED,), parameters={"axis": "Y", "angle": -pi / 2}),
        _event("Measure", 5, (SEED,), measurement_ids=(10,)),
    )
    with pytest.raises(ValueError, match="non-Clifford seed"):
        _estimate(replace(activity, duration_us=6, events=events))


@pytest.mark.parametrize("change", ("no_t", "two_t", "outside_rotation", "cross_cz"))
def test_checkpoint_and_complete_world_isolation_guards(change):
    activity = _activity()
    events = list(activity.events)
    if change == "no_t":
        events[2] = replace(events[2], parameters={"axis": "Z", "angle": pi / 2})
    elif change == "two_t":
        events.insert(3, replace(events[2], action_index=1))
    elif change == "outside_rotation":
        events[1] = replace(events[1], atoms=(SPECTATOR,))
    else:
        events[3] = replace(events[3], pairs=((CHECK, SPECTATOR),))
    with pytest.raises(ValueError):
        _estimate(replace(activity, events=tuple(events)))


def test_common_dimension_does_not_relax_legacy_d3_admission():
    with pytest.raises(ValueError, match="seventeen"):
        legacy_detectors(_activity(), [], ((10,),), wire_atoms=(CHECK, SEED))
    with pytest.raises(ValueError, match="at most 20"):
        legacy_detectors(_activity(), [], ((10,),) * 21, wire_atoms=tuple(range(17)))
    with pytest.raises(ValueError, match="complete-world"):
        detector_fault_channels(
            _activity(), [], ((10,),), wire_atoms=(CHECK, SEED), seed_atom=SEED
        )
    with pytest.raises(ValueError, match="seed atom"):
        detector_fault_channels(
            _activity(),
            [],
            ((10,),),
            wire_atoms=(CHECK, SEED),
            seed_atom=SPECTATOR,
            world_atom_ids=(SPECTATOR, SEED, CHECK),
        )
