"""Check the user's hardware standard independently of compiler scheduling."""

from dataclasses import replace
from itertools import pairwise

import pytest
from nadit_physical_compiler.state import validate_layout

from experiments.msd.standard import ExperimentSpec, build_world, reference_device


def test_only_requested_timing_fields_change():
    original = reference_device()
    world = build_world(ExperimentSpec(distance=3, pipelines=2))
    device = world.device
    assert device.timing == replace(original.timing, load_us=10, store_us=10)
    assert device.readout == replace(original.readout, duration_us=100, latency_us=0)
    assert device.local == original.local
    assert device.cz == original.cz
    validate_layout(device, world.state)


@pytest.mark.parametrize("distance", [3, 5, 7, 9])
@pytest.mark.parametrize("pipelines", [1, 2, 4])
def test_vertical_array_and_halfplanes(distance, pipelines):
    world = build_world(ExperimentSpec(distance=distance, pipelines=pipelines))
    assert len(world.state.atoms) == 6 * pipelines * (2 * distance**2 - 1)
    assert len({a.position for a in world.state.atoms}) == len(world.state.atoms)
    assert all(a.position.y <= 0 for a in world.state.atoms)
    tops = [world.patch(line, "W1").binding.origin.y for line in range(pipelines)]
    assert all(a > b for a, b in pairwise(tops))
    gate, readout = world.device.zones
    assert gate.bounds.y_max == 0
    assert readout.bounds.y_min == 50
    assert readout.operations == ("measure",)
    assert {"cz", "reset", "rotate"} <= set(gate.operations)
    assert all(
        world.device.aod("transport").workspace.contains(a.position)
        for a in world.state.atoms
    )
    validate_layout(world.device, world.state)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"distance": 2},
        {"distance": 4},
        {"pipelines": 0},
        {"pipelines": 3},
        {"window_padding_um": -1},
        {"patch_gap_um": 0},
        {"factory_gap_um": -5},
    ],
)
def test_invalid_experiment_rejected(kwargs):
    with pytest.raises(ValueError):
        ExperimentSpec(**kwargs)
