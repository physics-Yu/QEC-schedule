"""Actual T checkpoint, arbitrary participant roles and isolated-world projection."""

from dataclasses import replace
from math import pi

from nadit_physical_compiler.activity import (
    ActivityEvent,
    AtomActivity,
    PerAtomActivity,
)

from modules.codes._support.pauli_detector_events import detector_fault_channels

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


def test_spectator_only_pulse_before_seed_does_not_claim_ideal_entanglement():
    activity = _activity()
    pulse = _event("CZPulse", 1.5, (SEED, CHECK, SPECTATOR), pairs=())
    projected = replace(
        activity, events=(*activity.events[:2], pulse, *activity.events[2:])
    )
    _, proof = _estimate(projected)
    assert proof["center_t_identity_checks"] == 1
