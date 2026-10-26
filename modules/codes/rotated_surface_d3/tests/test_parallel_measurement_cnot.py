"""Pure measurement/pair profiles and translated templates on one real AOD."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.atom_ir import Load, Measure, Move, Store
from nadit_physical_compiler.device import Position, Region

from modules.codes._support import atom_template
from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface_d3.protocols.factory_array import make_factory_array
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.parallel import (
    describe_execution,
    pair_reference_device,
    pair_reference_origins,
)


@pytest.fixture(scope="module")
def array_world():
    return make_factory_array()


def _forbid_compilation(*args, **kwargs):
    raise AssertionError("Execution declarations and template reuse must not compile")


def _pair(world, factory, roles=("W2", "W3")):
    bindings = world.factory(factory).bindings
    return tuple(bindings[role] for role in roles)


@pytest.mark.parametrize("name", ("logical_mx", "logical_mz"))
def test_measurement_declares_nine_readouts_without_compilation(
    array_world, monkeypatch, name
):
    backend = SurfaceFactoryBackend(array_world.device)
    monkeypatch.setattr(atom_template, "compile_physical", _forbid_compilation)
    first, second = (
        backend.describe_execution(name, (array_world.factory(i).bindings["W2"],))
        for i in (0, 1)
    )
    assert first.parallel_mode == second.parallel_mode == "shared_aod_lockstep"
    assert first.waveform_key == second.waveform_key
    assert first.result_count == second.result_count == 9
    assert first.shared_aod.peak_readout_atoms == 9
    assert first.shared_aod.peak_rows == first.shared_aod.peak_columns == 3
    assert first.shared_aod.aod_id == second.shared_aod.aod_id == "transport"


def _check_actions(source, spec):
    claim, envelope = spec.shared_aod, spec.spaces[0].region
    peaks = [0, 0, 0]
    for step in source.program.steps:
        readouts = 0
        for action in step.actions:
            if isinstance(action, Load | Move | Store):
                assert action.grid.aod_id == claim.aod_id
                peaks[0] = max(peaks[0], len(action.grid.rows))
                peaks[1] = max(peaks[1], len(action.grid.columns))
                assert len(action.grid.rows) <= claim.peak_rows
                assert len(action.grid.columns) <= claim.peak_columns
                assert all(
                    claim.column_min <= column.coordinate <= claim.column_max
                    for column in action.grid.columns
                )
                assert all(
                    envelope.y_min <= row.coordinate <= envelope.y_max
                    for row in action.grid.rows
                )
            if isinstance(action, Measure):
                readouts += len(action.results)
            coverage = getattr(action, "coverage", None)
            if isinstance(coverage, Region):
                assert envelope.contains(Position(coverage.x_min, coverage.y_min))
                assert envelope.contains(Position(coverage.x_max, coverage.y_max))
        peaks[2] = max(peaks[2], readouts)
        assert readouts <= claim.peak_readout_atoms
    return tuple(peaks)


@pytest.mark.parametrize("name", ("logical_mx", "logical_mz"))
def test_translated_measurements_reuse_template_and_honor_real_demands(
    array_world, monkeypatch, name
):
    backend = SurfaceFactoryBackend(array_world.device)
    bindings = tuple(array_world.factory(i).bindings["W2"] for i in (1, 0))
    first = backend.bind_call(name, (bindings[0],))
    monkeypatch.setattr(atom_template, "compile_physical", _forbid_compilation)
    second = backend.bind_call(name, (bindings[1],))
    assert first.expander.template is second.expander.template
    for index, (binding, call) in enumerate(
        zip(bindings, (first, second), strict=True)
    ):
        source = call.expand(
            InvocationContext(
                f"measure-{index}",
                37,
                index * 9,
                array_world.device,
                array_world.world_state,
            )
        )
        spec = backend.describe_execution(name, (binding,))
        assert _check_actions(source, spec) == (3, 3, 9)
        assert source.exit_state == array_world.world_state
        assert len(source.measurements) == 9
        assert all(result.value is None for result in source.measurements)
        assert source.exit_binding == binding


@pytest.mark.parametrize("name", ("logical_mx", "logical_mz"))
def test_nine_atom_measurement_does_not_claim_an_eight_atom_readout(array_world, name):
    device = replace(
        array_world.device,
        readout=replace(array_world.device.readout, max_atoms=8),
    )
    spec = SurfaceFactoryBackend(device).describe_execution(
        name, (array_world.factory(0).bindings["W2"],)
    )
    assert spec.parallel_mode == "exclusive"
    assert spec.shared_aod is None


@pytest.mark.parametrize("name", ("logical_mx", "logical_mz"))
def test_measurement_profile_fits_exact_three_by_three_grid(array_world, name):
    device = replace(
        array_world.device,
        aods=(replace(array_world.device.aods[0], max_rows=3, max_columns=3),),
        readout=replace(array_world.device.readout, max_atoms=9),
    )
    backend = SurfaceFactoryBackend(device)
    binding = array_world.factory(0).bindings["W2"]
    spec = backend.describe_execution(name, (binding,))
    assert spec.parallel_mode == "shared_aod_lockstep"
    source = backend.bind_call(name, (binding,)).expand(
        InvocationContext("three-by-three", 0, 0, device, array_world.world_state)
    )
    assert _check_actions(source, spec) == (3, 3, 9)


@pytest.mark.parametrize("roles", (("W2", "W3"), ("W3", "W2")))
def test_translated_cnot_declares_both_participants_without_compilation(
    array_world, monkeypatch, roles
):
    backend = SurfaceFactoryBackend(array_world.device)
    monkeypatch.setattr(atom_template, "compile_physical", _forbid_compilation)
    pairs = tuple(_pair(array_world, i, roles) for i in (0, 1))
    specs = tuple(
        backend.describe_execution("transversal_cnot", pair) for pair in pairs
    )
    assert specs[0].waveform_key == specs[1].waveform_key
    for pair, spec in zip(pairs, specs, strict=True):
        assert spec.parallel_mode == "shared_aod_lockstep"
        assert spec.participant_blocks == tuple(binding.block_id for binding in pair)
        assert spec.result_count == spec.shared_aod.peak_readout_atoms == 0
        assert spec.shared_aod.peak_rows == spec.shared_aod.peak_columns == 3
        assert spec.exclusive_resources == ()
        assert all(spec.spaces[0].region.contains(binding.origin) for binding in pair)
    assert specs[0].shared_aod.column_max < specs[1].shared_aod.column_min


@pytest.mark.parametrize("roles", (("W2", "W3"), ("W3", "W2")))
def test_translated_cnot_reuses_pair_template_and_preserves_all_participants(
    array_world, monkeypatch, roles
):
    backend = SurfaceFactoryBackend(array_world.device)
    pairs = tuple(_pair(array_world, i, roles) for i in (1, 0))
    first = backend.bind_call("transversal_cnot", pairs[0])
    monkeypatch.setattr(atom_template, "compile_physical", _forbid_compilation)
    second = backend.bind_call("transversal_cnot", pairs[1])
    assert (
        first.expander.expander.atomic.template
        is second.expander.expander.atomic.template
    )
    for index, (pair, call) in enumerate(zip(pairs, (first, second), strict=True)):
        source = call.expand(
            InvocationContext(
                f"cnot-{index}", 41, 0, array_world.device, array_world.world_state
            )
        )
        spec = backend.describe_execution("transversal_cnot", pair)
        assert _check_actions(source, spec) == (3, 3, 0)
        assert source.participant_bindings == source.exit_participant_bindings == pair
        assert source.wire_atoms == tuple(
            atom for binding in pair for atom in binding.atom_ids
        )
        assert source.exit_state == array_world.world_state
        assert source.exit_binding is None
        assert source.measurements == ()


def test_cnot_waveform_includes_signed_relative_displacement(array_world):
    backend = SurfaceFactoryBackend(array_world.device)
    specs = tuple(
        backend.describe_execution("transversal_cnot", _pair(array_world, 0, roles))
        for roles in (("W2", "W3"), ("W3", "W2"), ("W2", "W4"))
    )
    assert all(spec.parallel_mode == "shared_aod_lockstep" for spec in specs)
    assert len({spec.waveform_key for spec in specs}) == 3


@pytest.mark.parametrize("limitation", ("vertical", "sites", "rows", "columns"))
def test_unsupported_pair_profiles_remain_exclusive(array_world, limitation):
    device, pair = array_world.device, _pair(array_world, 0)
    if limitation == "vertical":
        pair = (pair[0], replace(pair[1], origin=Position(pair[1].origin.x, 10)))
    elif limitation == "sites":
        pair = (replace(pair[0], site_ids=(("explicit", "home_r1_c11"),)), pair[1])
    else:
        aod = replace(device.aods[0], **{f"max_{limitation}": 2})
        device = replace(device, aods=(aod,))
    spec = describe_execution(device, "transversal_cnot", pair, {})
    assert spec.parallel_mode == "exclusive"
    assert spec.shared_aod is None
    assert spec.waveform_key is None


def test_pair_reference_helpers_reject_vertical_or_missing_reference_tiles(array_world):
    control, target = _pair(array_world, 0)
    vertical = replace(target, origin=Position(target.origin.x, 10))
    with pytest.raises(ValueError, match="horizontal"):
        pair_reference_origins(array_world.device, control, vertical)
    with pytest.raises(ValueError, match="reference tiles"):
        pair_reference_origins(
            replace(array_world.device, pair_arrays=()), control, target
        )
    with pytest.raises(ValueError, match="share one row"):
        pair_reference_device(
            array_world.device, control.aod_id, control.origin, vertical.origin
        )
