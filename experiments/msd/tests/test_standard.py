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
@pytest.mark.parametrize("pipelines", [1, 2, 3, 4])
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
        {"pipelines": True},
        {"window_padding_um": -1},
        {"patch_gap_um": 0},
        {"factory_gap_um": -5},
    ],
)
def test_invalid_experiment_rejected(kwargs):
    with pytest.raises(ValueError):
        ExperimentSpec(**kwargs)


def test_explicit_placements_bind_exact_origins_and_keep_standard_device_rules():
    from nadit_physical_compiler.device import Position

    from experiments.msd.standard import placement_request
    from modules.logical_compiler.src.placement import (
        BlockPlacement,
        ExplicitPlacement,
        place,
    )

    spec = ExperimentSpec(3, 1)
    request = placement_request(spec)
    positions = {
        block.block_id: BlockPlacement(Position(-130 + 110 * i, -60 - 90 * (i % 2)))
        for i, block in enumerate(request.blocks)
    }
    plan = place(replace(request, positions=positions), ExplicitPlacement())
    world = build_world(spec, placement_plan=plan)
    assert world.placement_plan is plan
    assert {
        patch.binding.block_id: patch.binding.origin for patch in world.patches
    } == {name: value.origin for name, value in positions.items()}
    assert world.device.zones[0].bounds.y_max == 0
    assert world.device.zones[1].bounds.y_min == 50
    assert world.document()["placement"] == plan.to_dict()
    validate_layout(world.device, world.state)


def test_standard_rejects_a_valid_plan_outside_its_storage_halfplane():
    from nadit_physical_compiler.device import Position

    from experiments.msd.standard import placement_request
    from modules.logical_compiler.src.placement import (
        BlockPlacement,
        ExplicitPlacement,
        place,
    )

    spec = ExperimentSpec()
    request = placement_request(spec)
    positions = {
        block.block_id: BlockPlacement(Position(100 * i, 0))
        for i, block in enumerate(request.blocks)
    }
    plan = place(replace(request, positions=positions), ExplicitPlacement())
    with pytest.raises(ValueError, match="STORAGE_HALFPLANE"):
        build_world(spec, placement_plan=plan)


@pytest.mark.slow
def test_explicit_plan_runs_existing_joint_se_with_one_shared_aod():
    from nadit_physical_compiler.atom_ir import CZPulse
    from nadit_physical_compiler.device import Position
    from nadit_physical_compiler.serialization import decode_result

    from experiments.msd.parallel_se import compile_se_case
    from experiments.msd.standard import placement_request
    from modules.logical_compiler.src.placement import (
        BlockPlacement,
        ExplicitPlacement,
        place,
    )

    spec = ExperimentSpec(3, 2)
    request = placement_request(spec)
    positions = {
        block.block_id: BlockPlacement(
            Position(-130 + 110 * (i % 6), -60 - 200 * (i // 6))
        )
        for i, block in enumerate(request.blocks)
    }
    plan = place(replace(request, positions=positions), ExplicitPlacement())
    _, document, _ = compile_se_case(spec, placement_plan=plan)
    assert document["validation"]["ok"] is True
    result = decode_result(document)
    owners = document["se_instances"]["node_owners"]
    assert any(
        isinstance(action, CZPulse)
        and len({owners[source] for source in action.source_ids}) == 2
        for step in result.program.steps
        for action in step.actions
    )
    assert len(document["device"]["aods"]) == 1


@pytest.mark.parametrize(
    ("distance", "pipelines", "expected"),
    [
        (3, 1, "ef18a2db6a90a5e2726cc2b3532ada01895b842e141f38cb1d843880ea41800f"),
        (3, 2, "440a1eab64a69d3302fc7c9b5486d563836fa5f721021cefc89bc96cd22565a2"),
        (3, 4, "6d10c2356c8158792cc6d6c8723cf9f6d73d4925bf2c15d3ddaa709276ac3379"),
        (5, 1, "27db516d72e03d99fb558b967c6fc95b4c89bee106c33471a9a26249f7863f6a"),
        (5, 2, "7b85a4fa696649165cd30f89378d836f2e25769f93370e03ba992e7dfdb96e7e"),
        (5, 4, "aea2f33f90b18b6633c945020bc7a78a578dc41875961a8061a3ae2062851632"),
        (7, 1, "f6d5c7a1832b8c166e2fa84c6042723a5a3226b884adf0a257e9d5b68a747723"),
        (7, 2, "6657cbdd6a47c68e591d4531c92bcae807c62675a59bfc05521de226739814be"),
        (7, 4, "39b6a46b2aaec0b60ee56d193ebe216ca2dc95810eb24763f72c846839022570"),
    ],
)
def test_pre_extraction_world_coordinates_and_device_are_exact(
    distance, pipelines, expected
):
    from nadit_physical_compiler.provenance import canonical_hash

    document = build_world(
        ExperimentSpec(distance=distance, pipelines=pipelines)
    ).document()
    # Placement provenance is new; every existing world field remains identical.
    document.pop("placement", None)
    assert canonical_hash(document) == expected


def test_world_document_restores_current_bindings_and_vacancy_without_rebuilding(
    monkeypatch,
):
    import json

    from nadit_physical_compiler.state import SLMHolder

    from experiments.msd import standard

    world = build_world(ExperimentSpec(3, 2))
    source, destination = world.patch(0, "W1"), world.patch(1, "W1")
    removed = set(destination.binding.atom_ids)
    targets = dict(zip(source.binding.atom_ids, destination.home_sites, strict=True))
    world = replace(
        world,
        device=replace(world.device, timing=replace(world.device.timing, load_us=11)),
        state=replace(
            world.state,
            atoms=tuple(
                replace(
                    atom,
                    position=world.device.site(targets[atom.id]).position,
                    holder=SLMHolder(targets[atom.id]),
                )
                if atom.id in targets
                else atom
                for atom in world.state.atoms
                if atom.id not in removed
            ),
            qubit_to_atom=tuple(
                reversed(
                    tuple(
                        atom
                        for atom in world.state.qubit_to_atom
                        if atom not in removed
                    )
                )
            ),
        ),
        patches=tuple(
            replace(
                patch,
                binding=replace(
                    patch.binding,
                    origin=destination.binding.origin,
                    site_ids=(("data", destination.home_sites[0]),),
                ),
                home_sites=destination.home_sites,
            )
            if patch is source
            else patch
            for patch in world.patches
            if patch is not destination
        ),
    )
    document = json.loads(json.dumps(world.document()))
    for name in ("build_world", "place", "generate"):
        monkeypatch.setattr(
            standard,
            name,
            lambda *args, **kwargs: pytest.fail("world restoration regenerated layout"),
        )
    restored = standard.ExperimentWorld.from_document(document)
    assert restored == world
    assert json.loads(json.dumps(restored.document())) == document
    assert len(restored.patches) < len(restored.placement_plan.blocks)
    assert (
        restored.patch(0, "W1").binding.origin
        != restored.placement_plan.placements["factory0/W1"].origin
    )
    assert restored.device.timing.load_us == 11


@pytest.mark.parametrize(
    "damage",
    (
        "schema",
        "standard",
        "spec",
        "home",
        "origin",
        "alias",
        "role",
        "atom_order",
        "plan",
        "metadata",
    ),
)
def test_world_document_rejects_inconsistent_saved_state(damage):
    import json

    from experiments.msd.standard import ExperimentWorld

    document = json.loads(json.dumps(build_world(ExperimentSpec(3, 1)).document()))
    patch = document["patches"][0]
    if damage in ("schema", "standard"):
        document[damage] = "wrong"
    elif damage == "spec":
        document["parameters"]["distance"] = 5
    elif damage == "home":
        patch["home_sites"][0] = patch["home_sites"][1]
    elif damage == "origin":
        patch["binding"]["origin"]["x"] += 1
    elif damage == "alias":
        patch["binding"]["site_ids"] = [["role", "missing"]]
    elif damage == "role":
        patch["role"] = "W2"
    elif damage == "atom_order":
        patch["binding"]["atom_ids"].reverse()
    elif damage == "plan":
        document["placement"]["geometry_fingerprint"] = "wrong"
    else:
        document["physical_execution"] = True
    with pytest.raises(ValueError):
        ExperimentWorld.from_document(document)


@pytest.mark.parametrize("distance", (3, 5))
def test_buffer_sites_preserve_all_atoms_and_controls_with_explicit_empty_grids(
    distance,
):
    from nadit_physical_compiler.device import Position

    from experiments.msd.standard import ExperimentWorld, add_buffer_sites
    from modules.codes.rotated_surface import definition

    world = build_world(ExperimentSpec(distance, 2 if distance == 3 else 1))
    origins = {
        "buffer_left": Position(-200, -2 * distance * 10 - 100),
        "buffer_right": Position(
            world.device.zones[0].bounds.x_max + 40, -2 * distance * 10
        ),
    }
    enlarged, targets = add_buffer_sites(world, origins)
    assert enlarged.state is world.state
    assert enlarged.patches is world.patches
    assert enlarged.placement_plan is world.placement_plan
    assert (
        enlarged.device.slm_sites[: len(world.device.slm_sites)]
        == world.device.slm_sites
    )
    assert (
        enlarged.device.pair_arrays[: len(world.device.pair_arrays)]
        == world.device.pair_arrays
    )
    for field in ("timing", "readout", "local", "cz", "global_control"):
        assert getattr(enlarged.device, field) is getattr(world.device, field)
    assert len(enlarged.device.aods) == len(world.device.aods) == 1
    assert (
        replace(enlarged.device.aods[0], workspace=world.device.aods[0].workspace)
        == world.device.aods[0]
    )
    assert (
        len(enlarged.device.slm_sites) - len(world.device.slm_sites)
        == 4 * (2 * distance + 1) ** 2
    )
    assert enlarged.device.zones[0].bounds.y_max == 0
    assert enlarged.device.zones[1].bounds.y_min == 50
    assert enlarged.device.zones[0].bounds.x_min < world.device.zones[0].bounds.x_min
    assert enlarged.device.zones[0].bounds.x_max > world.device.zones[0].bounds.x_max
    occupied = {atom.holder.site_id for atom in world.state.atoms}
    for slot, origin in origins.items():
        target_origin, homes = targets[slot]
        assert target_origin == origin
        assert len(homes) == 2 * distance**2 - 1
        assert not occupied.intersection(homes)
        for home, (x, y) in zip(
            homes, definition(distance).reference_coordinates, strict=True
        ):
            assert enlarged.device.site(home).position == Position(
                origin.x + 10 * x, origin.y + 10 * y
            )
        array = next(item for item in enlarged.device.pair_arrays if item.id == slot)
        assert array.zone == "shared"
        for left, right in array.pairs:
            a, b = (
                enlarged.device.site(left).position,
                enlarged.device.site(right).position,
            )
            assert b == Position(a.x + 2, a.y)
            assert enlarged.device.aods[0].workspace.contains(b)
            assert enlarged.device.zones[0].bounds.contains(b)
    assert ExperimentWorld.from_document(enlarged.document()) == enlarged
    assert add_buffer_sites(world, {}) == (world, {})


@pytest.mark.parametrize(
    "damage",
    (
        "slot_id",
        "block_id",
        "site_id",
        "empty_id",
        "existing_sites",
        "two_slots",
        "halfplane",
        "near_pairs",
    ),
)
def test_buffer_sites_reject_conflicts_without_mutating_world(damage):
    from nadit_physical_compiler.device import Position

    from experiments.msd.standard import add_buffer_sites

    world = build_world(ExperimentSpec(3, 1))
    before = world.document()
    origins = {"buffer": Position(-200, -100)}
    if damage == "slot_id":
        origins = {world.device.pair_arrays[0].id: Position(-200, -100)}
    elif damage == "block_id":
        origins = {world.patches[0].binding.block_id: Position(-200, -100)}
    elif damage == "site_id":
        origins = {world.device.slm_sites[0].id: Position(-200, -100)}
    elif damage == "empty_id":
        origins = {"": Position(-200, -100)}
    elif damage == "existing_sites":
        origins = {"buffer": world.patches[0].binding.origin}
    elif damage == "two_slots":
        origins["another"] = origins["buffer"]
    elif damage == "halfplane":
        origins = {"buffer": Position(-200, -59)}
    else:
        current = world.patches[0].binding.origin
        origins = {"buffer": Position(current.x + 1, current.y)}
    with pytest.raises(ValueError, match="BUFFER"):
        add_buffer_sites(world, origins)
    assert world.document() == before


def test_buffer_slot_identity_cannot_be_reused_at_another_origin():
    from nadit_physical_compiler.device import Position

    from experiments.msd.standard import add_buffer_sites

    world, _targets = add_buffer_sites(
        build_world(ExperimentSpec(3, 1)), {"buffer": Position(-200, -100)}
    )
    with pytest.raises(ValueError, match="BUFFER"):
        add_buffer_sites(world, {"buffer": Position(-400, -100)})


@pytest.mark.parametrize("distances", [(3, 5), (3, 7), (3, 5, 7)])
def test_mixed_factory_distances_bind_distinct_real_atom_sets_and_roundtrip(distances):
    from experiments.msd.standard import (
        FACTORY_ROLES,
        ExperimentWorld,
        placement_request,
    )
    from modules.codes.rotated_surface import definition

    spec = ExperimentSpec(max(distances), len(distances), factory_distances=distances)
    world = build_world(spec)
    assert len(world.state.atoms) == 6 * sum(
        definition(d).atom_count for d in distances
    )
    assert set(placement_request(spec).geometries) == {
        f"rotated_surface_d{d}" for d in distances
    }
    atom_sets = []
    for index, distance in enumerate(distances):
        assert spec.factory_distance(index) == distance
        for role in FACTORY_ROLES:
            patch = world.patch(index, role)
            assert (
                patch.code == f"rotated_surface_d{distance}"
                and patch.distance == distance
            )
            assert world.block_definition(patch.binding.block_id) == definition(
                distance
            )
            assert (
                len(patch.binding.atom_ids)
                == len(patch.home_sites)
                == definition(distance).atom_count
            )
            atom_sets.append(set(patch.binding.atom_ids))
    assert (
        sum(map(len, atom_sets)) == len(set.union(*atom_sets)) == len(world.state.atoms)
    )
    assert all(atom.position.y <= 0 for atom in world.state.atoms)
    assert len(world.device.aods) == 1
    original = reference_device()
    assert world.device.timing == replace(original.timing, load_us=10, store_us=10)
    assert world.device.readout == replace(
        original.readout, duration_us=100, latency_us=0
    )
    assert world.device.local == original.local and world.device.cz == original.cz
    document = world.document()
    assert document["parameters"]["factory_distances"] == list(distances)
    assert all(
        row["distance"] == distances[row["factory_index"]]
        for row in document["patches"]
    )
    restored = ExperimentWorld.from_document(document)
    assert restored == world and restored.document() == document


def test_uniform_optional_metadata_does_not_change_old_document_shape():
    spec = ExperimentSpec(3, 2)
    assert spec.to_dict() == {
        "distance": 3,
        "pipelines": 2,
        "patch_gap_um": 40.0,
        "factory_gap_um": 40.0,
        "window_padding_um": 20.0,
    }
    document = build_world(spec).document()
    assert "factory_distances" not in document["parameters"]
    assert all(
        "code" not in patch and "distance" not in patch for patch in document["patches"]
    )


@pytest.mark.parametrize(
    "maximum,distances",
    [(5, (3,)), (5, (3, 4)), (3, (3, 5)), (7, (3, 5)), (5, (True, 5))],
)
def test_mixed_distance_spec_rejects_length_even_boolean_and_maximum_mismatch(
    maximum, distances
):
    with pytest.raises(ValueError):
        ExperimentSpec(maximum, 2, factory_distances=distances)


def test_mixed_explicit_plan_is_retained_and_each_patch_uses_its_own_grid():
    from nadit_physical_compiler.device import Position

    from experiments.msd.standard import (
        FACTORY_ROLES,
        ExperimentWorld,
        placement_request,
    )
    from modules.logical_compiler.src.placement import (
        BlockPlacement,
        ExplicitPlacement,
        VerticalFactoryPlacement,
        place,
    )

    spec = ExperimentSpec(5, 2, factory_distances=(3, 5))
    request = placement_request(spec)
    original = place(request, VerticalFactoryPlacement(FACTORY_ROLES))
    positions = {
        name: BlockPlacement(Position(p.origin.x - 150, p.origin.y - 100))
        for name, p in original.placements.items()
    }
    plan = place(replace(request, positions=positions), ExplicitPlacement())
    world = build_world(spec, placement_plan=plan)
    assert world.placement_plan is plan
    assert {p.binding.block_id: p.binding.origin for p in world.patches} == {
        name: p.origin for name, p in positions.items()
    }
    assert len(world.device.pair_arrays[0].left) == 7
    assert len(world.device.pair_arrays[6].left) == 11
    assert ExperimentWorld.from_document(world.document()) == world


@pytest.mark.parametrize(
    "damage",
    ["distance_only", "code", "shared_atoms", "homes", "maximum", "metadata_missing"],
)
def test_mixed_world_restoration_rejects_retagging_or_inconsistent_geometry(damage):
    from copy import deepcopy

    from experiments.msd.standard import ExperimentWorld

    document = deepcopy(
        build_world(ExperimentSpec(5, 2, factory_distances=(3, 5))).document()
    )
    first = document["patches"][0]
    if damage == "distance_only":
        first.update(code="rotated_surface_d5", distance=5)
    elif damage == "code":
        first["code"] = "rotated_surface_d5"
    elif damage == "shared_atoms":
        first["binding"]["atom_ids"] = document["patches"][1]["binding"]["atom_ids"]
    elif damage == "homes":
        first["home_sites"] = document["patches"][1]["home_sites"]
    elif damage == "maximum":
        document["parameters"]["distance"] = 7
    else:
        del first["code"], first["distance"]
    with pytest.raises(ValueError):
        ExperimentWorld.from_document(document)


def test_current_converted_binding_roundtrip_uses_actual_atoms_not_initial_plan_label():
    """Synthetic valid world state only; this does not claim a growth protocol."""
    from nadit_physical_compiler.device import Position
    from nadit_physical_compiler.state import AtomState, SLMHolder

    from experiments.msd.standard import ExperimentWorld
    from modules.codes.rotated_surface import definition

    world = build_world(ExperimentSpec(5, 2, factory_distances=(3, 5)))
    source, receiver = world.patch(0, "W1"), world.patch(1, "W1")
    new_ids = tuple(range(len(world.state.atoms), len(world.state.atoms) + 32))
    ids = source.binding.atom_ids + new_ids
    moved = replace(
        source,
        code="rotated_surface_d5",
        distance=5,
        binding=replace(source.binding, origin=receiver.binding.origin, atom_ids=ids),
        home_sites=receiver.home_sites,
    )
    removed = set(source.binding.atom_ids + receiver.binding.atom_ids)
    atoms = tuple(a for a in world.state.atoms if a.id not in removed) + tuple(
        AtomState(
            atom,
            Position(
                receiver.binding.origin.x + 10 * x, receiver.binding.origin.y + 10 * y
            ),
            SLMHolder(home),
        )
        for atom, home, (x, y) in zip(
            ids, receiver.home_sites, definition(5).reference_coordinates, strict=True
        )
    )
    current = replace(
        world,
        state=replace(
            world.state, atoms=atoms, qubit_to_atom=tuple(a.id for a in atoms)
        ),
        patches=tuple(
            moved if p is source else p for p in world.patches if p is not receiver
        ),
    )
    assert current.placement_plan is world.placement_plan
    assert current.block_definition(source.binding.block_id) == definition(5)
    assert ExperimentWorld.from_document(current.document()) == current


def test_mixed_parking_requires_explicit_supported_distance_and_keeps_world_controls():
    from nadit_physical_compiler.device import Position

    from experiments.msd.standard import ExperimentWorld, add_buffer_sites

    world = build_world(ExperimentSpec(5, 2, factory_distances=(3, 5)))
    origins = {"seed_parking": Position(-300, -100)}
    with pytest.raises(ValueError, match="BUFFER.*DISTANCE"):
        add_buffer_sites(world, origins)
    enlarged, targets = add_buffer_sites(world, origins, distances={"seed_parking": 3})
    assert len(targets["seed_parking"][1]) == 17
    assert len(enlarged.device.slm_sites) - len(world.device.slm_sites) == 2 * 7**2
    assert enlarged.state is world.state and enlarged.patches is world.patches
    assert enlarged.device.timing is world.device.timing
    assert ExperimentWorld.from_document(enlarged.document()) == enlarged
    for values in ({}, {"seed_parking": 4}, {"seed_parking": 7}, {"other": 3}):
        with pytest.raises(ValueError, match="BUFFER.*DISTANCE"):
            add_buffer_sites(world, origins, distances=values)
