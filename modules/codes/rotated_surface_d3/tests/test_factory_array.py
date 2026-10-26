"""Actual shared geometry and finite budgets for multiple six-patch factories."""

import pytest
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.state import validate_layout

from modules.codes.rotated_surface_d3.protocols.factory_array import (
    FactoryArrayConfig,
    make_factory_array,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import FACTORY_ROLES
from modules.codes.rotated_surface_d3.protocols.parallel import describe_execution


def test_two_lines_share_one_complete_world_and_real_finite_budgets():
    array = make_factory_array()
    validate_layout(array.device, array.world_state)
    assert len(array.world_state.atoms) == 204
    assert len(array.bindings) == 12
    assert tuple(a.id for a in array.device.aods) == ("transport",)
    assert (array.device.aods[0].max_rows, array.device.aods[0].max_columns) == (4, 48)
    assert array.device.readout.max_atoms == 96
    first, second = array.factories
    assert first.factory_id == "factory0"
    assert second.factory_id == "factory1"
    assert set(first.atom_ids).isdisjoint(second.atom_ids)
    assert tuple(first.bindings) == FACTORY_ROLES
    assert second.bindings["W1"].origin == Position(620, 0)
    assert array.factory(1) is array.factory("factory1") is second
    assert all(array.bindings[b.block_id] == b for b in second.bindings.values())
    assert len(array.device.slm_sites) == array.budget["slm_site_count"]
    assert array.budget["aod_max_columns"] == 48
    assert array.budget["readout_extra_height_um"] == 20
    assert array.device.aods[0].workspace.y_max >= 135
    readout = next(z for z in array.device.zones if "measure" in z.operations)
    shared = next(z for z in array.device.zones if "cz" in z.operations)
    assert readout.bounds.y_min == 90
    assert readout.bounds.y_max == 130
    assert shared.bounds.y_max == 80 < readout.bounds.y_min
    assert min(s.position.x for s in array.device.slm_sites) == -20
    assert max(s.position.x for s in array.device.slm_sites) > 1180


@pytest.mark.parametrize("count", [1, 3])
def test_arbitrary_count_translation_and_id_ranges(count):
    array = make_factory_array(
        FactoryArrayConfig(
            factory_count=count,
            origin=Position(230, -40),
            atom_id_base=500,
            factory_id_prefix="line",
            aod_id="shared",
            block_spacing_columns=12,
        )
    )
    validate_layout(array.device, array.world_state)
    assert array.world_state.qubit_to_atom == tuple(range(500, 500 + 102 * count))
    assert array.device.aods[0].max_columns == 24 * count
    assert array.device.readout.max_atoms == 48 * count
    for index, factory in enumerate(array.factories):
        assert factory.factory_id == f"line{index}"
        assert factory.bindings["W1"].origin == Position(230 + 740 * index, -40)
        assert all(binding.aod_id == "shared" for binding in factory.bindings.values())


@pytest.mark.parametrize(
    "changes",
    [
        {"factory_count": 0},
        {"factory_count": True},
        {"factory_gap_columns": -1},
        {"block_spacing_columns": 6},
        {"shared_padding_columns": -1},
        {"shared_top_margin_um": 25},
        {"readout_extra_height_um": -1},
        {"aod_max_rows": 3},
        {"aod_max_columns": 3},
        {"max_readout_atoms": 7},
        {"atom_id_base": True},
        {"factory_id_prefix": ""},
        {"aod_id": ""},
    ],
)
def test_invalid_configuration(changes):
    with pytest.raises(ValueError):
        FactoryArrayConfig(**changes)


def test_every_patch_has_the_same_shared_row_profile():
    array = make_factory_array()
    specs = [
        describe_execution(array.device, "raw_t", (binding,), {})
        for binding in array.bindings.values()
    ]
    assert {s.parallel_mode for s in specs} == {"shared_aod_lockstep"}
    assert len({s.shared_aod.row_trajectory_key for s in specs}) == 1
    assert all(s.shared_aod.max_columns == 48 for s in specs)
    with pytest.raises(KeyError):
        array.factory("missing")
    with pytest.raises(KeyError):
        array.factory(-1)


def test_real_last_patch_component_preserves_all_other_atoms():
    from modules.codes.contracts.component import InvocationContext
    from modules.codes.rotated_surface_d3.protocols.factory_backend import (
        SurfaceFactoryBackend,
    )

    array = make_factory_array()
    binding = array.factory(1).bindings["R"]
    backend = SurfaceFactoryBackend(array.device)
    bound = backend.bind_call("se_round", (binding,))
    output = bound.expand(
        InvocationContext("last-se", 0, 1000, array.device, array.world_state)
    )
    assert output.exit_state == array.world_state
    assert len(output.exit_state.atoms) == 204
    assert all(m.atom_id in binding.atom_ids for m in output.measurements)
