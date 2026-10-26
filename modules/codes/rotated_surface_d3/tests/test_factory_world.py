"""Six-patch factory geometry with real component expansion and spectators."""

from dataclasses import replace
from itertools import combinations

import pytest
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.state import validate_layout

from modules.codes._support.atom_template import BindingRejected
from modules.codes.contracts.component import InvocationContext, validate_sequence
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.components.transversal import (
    TransversalCNOTComponent,
)
from modules.codes.rotated_surface_d3.definition import REFERENCE_COORDINATES
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FACTORY_ROLES,
    FactoryWorldConfig,
    make_factory_world,
)


@pytest.fixture(scope="module")
def factory():
    return make_factory_world()


def test_complete_world_has_six_disjoint_same_orientation_blocks(factory):
    validate_layout(factory.device, factory.world_state)
    assert FACTORY_ROLES == ("W1", "W2", "W3", "W4", "W5", "R")
    assert len(factory.world_state.atoms) == 102
    assert factory.world_state.qubit_to_atom == tuple(range(102))
    assert len({site for patch in factory.patches for site in patch.home_sites}) == 102
    assert factory.world_state.aod_grids == ()
    for index, role in enumerate(FACTORY_ROLES):
        patch = factory.patch(role)
        assert patch.binding.block_id == f"factory/{role}"
        assert patch.binding.origin == Position(100 * index, 0)
        assert patch.binding.atom_ids == tuple(range(17 * index, 17 * (index + 1)))
        for site, (x, y) in zip(patch.home_sites, REFERENCE_COORDINATES, strict=True):
            assert factory.device.site(site).position == Position(
                100 * index + 10 * x, 10 * y
            )
    with pytest.raises(KeyError, match="unknown"):
        factory.patch("unknown")


def test_configured_origin_identity_and_aod_inventory():
    config = FactoryWorldConfig(
        origin=Position(230, -40),
        block_spacing_columns=12,
        atom_id_base=300,
        factory_id="second-factory",
        aod_ids=("primary", "spare"),
    )
    factory = make_factory_world(config)
    validate_layout(factory.device, factory.world_state)
    assert tuple(a.id for a in factory.device.aods) == ("primary", "spare")
    assert factory.patch("R").binding.origin == Position(830, -40)
    assert factory.patch("R").binding.block_id == "second-factory/R"
    assert factory.world_state.qubit_to_atom == tuple(range(300, 402))
    assert all(p.binding.aod_id == "primary" for p in factory.patches)


def test_relative_template_reuses_shifted_factory_and_spare_aod(factory):
    reference = factory.patch("W1")
    template = get_component("se_round").compile(
        factory.device,
        home_sites=reference.home_sites,
        origin=reference.binding.origin,
        aod_id=reference.binding.aod_id,
    )
    shifted = make_factory_world(
        FactoryWorldConfig(
            origin=Position(230, -40),
            block_spacing_columns=12,
            atom_id_base=300,
            factory_id="second-factory",
            aod_ids=("primary", "spare"),
        )
    )
    binding = replace(shifted.patch("R").binding, aod_id="spare")
    output = template.bind(binding).expand(
        InvocationContext(
            "shifted-R-se", 1234, 9000, shifted.device, shifted.world_state
        )
    )
    assert output.entry_state == output.exit_state == shifted.world_state
    assert output.exit_binding == binding
    assert output.template_content_sha256 == template.content_sha256
    assert tuple(m.result.measurement_id for m in output.measurements) == tuple(
        range(9000, 9008)
    )


def test_minimum_spacing_cnot_uses_complete_world():
    factory = make_factory_world(FactoryWorldConfig(block_spacing_columns=7))
    a, b = factory.patch("W5"), factory.patch("W1")
    template = TransversalCNOTComponent().compile(
        factory.device,
        control_home_sites=a.home_sites,
        target_home_sites=b.home_sites,
        control_origin=a.binding.origin,
        target_origin=b.binding.origin,
        aod_id=a.binding.aod_id,
    )
    output = template.bind(a.binding, b.binding).expand(
        InvocationContext(
            "minimum-spacing-cx", 0, 0, factory.device, factory.world_state
        )
    )
    assert output.entry_state == output.exit_state == factory.world_state


@pytest.mark.parametrize(
    "changes",
    [
        {"block_spacing_columns": 6},
        {"block_spacing_columns": True},
        {"atom_id_base": -1},
        {"atom_id_base": True},
        {"factory_id": ""},
        {"aod_ids": ()},
        {"aod_ids": ("same", "same")},
        {"aod_ids": ("",)},
        {"origin": "not-a-position"},
    ],
)
def test_invalid_factory_config(changes):
    with pytest.raises(ValueError):
        FactoryWorldConfig(**changes)


@pytest.mark.parametrize(
    "name", ["initialize_plus", "raw_t", "se_round", "logical_s", "logical_x"]
)
@pytest.mark.parametrize("role", FACTORY_ROLES)
def test_single_patch_actions_validate_in_full_102_atom_world(factory, name, role):
    patch = factory.patch(role)
    template = get_component(name).compile(
        factory.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    output = template.bind(patch.binding).expand(
        InvocationContext(
            f"{role}/{name}", 500, 1000, factory.device, factory.world_state
        )
    )
    assert output.entry_state == output.exit_state == factory.world_state
    assert len(output.exit_state.atoms) == 102
    assert output.validation_checks
    assert output.wire_atoms == patch.binding.atom_ids
    assert all(m.atom_id in patch.binding.atom_ids for m in output.measurements)


WORK_ROLES = FACTORY_ROLES[:5]
SUPPORTS = (*combinations(WORK_ROLES, 3), WORK_ROLES)
RECIPE_PAIRS = tuple(
    sorted(
        {(role, support[0]) for support in SUPPORTS for role in support[1:]}
        | {(role, "R") for role in WORK_ROLES}
        | {("W2", "W1")}
    )
)


@pytest.mark.parametrize(("control", "target"), RECIPE_PAIRS)
def test_every_recipe_cnot_pair_preserves_complete_spectator_world(
    factory, control, target
):
    a, b = factory.patch(control), factory.patch(target)
    template = TransversalCNOTComponent().compile(
        factory.device,
        control_home_sites=a.home_sites,
        target_home_sites=b.home_sites,
        control_origin=a.binding.origin,
        target_origin=b.binding.origin,
        aod_id=a.binding.aod_id,
    )
    output = template.bind(a.binding, b.binding).expand(
        InvocationContext(
            f"cx/{control}/{target}", 1000, 2000, factory.device, factory.world_state
        )
    )
    assert output.entry_state == output.exit_state == factory.world_state
    assert len(output.exit_state.atoms) == 102
    assert output.exit_participant_bindings == (a.binding, b.binding)
    assert output.validation_checks


def test_sequential_components_share_world_and_pending_result_identity(factory):
    patch = factory.patch("R")
    parts = []
    current, start = factory.world_state, 0.0
    for index, name in enumerate(("raw_t", "se_round", "logical_s")):
        template = get_component(name).compile(
            factory.device,
            home_sites=patch.home_sites,
            origin=patch.binding.origin,
            aod_id=patch.binding.aod_id,
        )
        part = template.bind(patch.binding).expand(
            InvocationContext(
                f"sequence/{index}", start, index * 8, factory.device, current
            )
        )
        parts.append(part)
        current, start = part.exit_state, part.action_end_us
    validate_sequence(parts)
    assert current == factory.world_state
    assert all(m.value is None for part in parts for m in part.measurements)
    assert len({m.result for part in parts for m in part.measurements}) == 24
    assert parts[1].start_us < parts[0].results_ready_us


def test_changed_spectator_occupancy_is_not_ignored(factory):
    patch = factory.patch("R")
    template = get_component("se_round").compile(
        factory.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    atoms = list(factory.world_state.atoms)
    atoms[0] = replace(atoms[0], position=atoms[-1].position, holder=atoms[-1].holder)
    invalid_world = replace(factory.world_state, atoms=tuple(atoms))
    with pytest.raises(BindingRejected, match="complete-world"):
        template.bind(patch.binding).expand(
            InvocationContext("occupied", 0, 0, factory.device, invalid_world)
        )
