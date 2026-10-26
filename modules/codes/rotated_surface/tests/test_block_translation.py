"""Exact-identity block translation contracts; no two-level delivery claim."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.state import SLMHolder

from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface.translation import BlockTranslationComponent


def empty_receiver():
    """Construct an explicitly vacant receiving patch, not an ordinary L2 factory."""
    world = build_world(ExperimentSpec(3, 2))
    source, destination = world.patch(0, "W1"), world.patch(1, "W1")
    removed = set(destination.binding.atom_ids)
    entry = replace(
        world.state,
        atoms=tuple(a for a in world.state.atoms if a.id not in removed),
        qubit_to_atom=tuple(a for a in world.state.qubit_to_atom if a not in removed),
    )
    return world, source, destination, entry


@pytest.mark.parametrize(
    "damage",
    (
        "occupied",
        "missing_site",
        "duplicate_site",
        "shape",
        "source_roles",
        "no_movement",
    ),
)
def test_invalid_translation_rejected_before_transport_planning(monkeypatch, damage):
    from modules.codes.rotated_surface import translation

    world, source, destination, entry = empty_receiver()
    binding = source.binding
    target_origin, target_sites = destination.binding.origin, destination.home_sites
    if damage == "occupied":
        occupant = world.patch(0, "W2").binding.atom_ids[0]
        entry = replace(
            entry,
            atoms=tuple(
                replace(
                    atom,
                    position=world.device.site(target_sites[0]).position,
                    holder=SLMHolder(target_sites[0]),
                )
                if atom.id == occupant
                else atom
                for atom in entry.atoms
            ),
        )
    elif damage == "missing_site":
        target_sites = ("missing", *target_sites[1:])
    elif damage == "duplicate_site":
        target_sites = (target_sites[1], *target_sites[1:])
    elif damage == "shape":
        target_origin = Position(target_origin.x + 1, target_origin.y)
    elif damage == "source_roles":
        binding = replace(binding, atom_ids=tuple(reversed(binding.atom_ids)))
    else:
        target_origin, target_sites = source.binding.origin, source.home_sites
    monkeypatch.setattr(
        translation.StrictTransport,
        "construct",
        lambda *a, **k: pytest.fail("invalid request reached routing"),
    )
    with pytest.raises(ValueError, match="TRANSLATION"):
        BlockTranslationComponent(3).compile(
            world.device,
            world=entry,
            binding=binding,
            target_origin=target_origin,
            target_home_sites=target_sites,
        )


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_translation_contract_is_same_code_identity_with_no_quantum_operation(distance):
    component = BlockTranslationComponent(distance)
    assert component.description.code_id == f"rotated_surface_d{distance}"
    assert component.description.measurements == ()
    assert component.result_count == 0
    assert not hasattr(component, "source_qasm")


def test_native_goal_uses_current_wire_binding_without_planning_or_relabeling(
    monkeypatch,
):
    from modules.codes.rotated_surface import translation

    world, source, destination, entry = empty_receiver()
    # Deliberately use a nonidentity wire order; atom IDs are never wire indices.
    entry = replace(entry, qubit_to_atom=tuple(reversed(entry.qubit_to_atom)))
    monkeypatch.setattr(
        translation.StrictTransport,
        "construct",
        lambda *a, **k: pytest.fail("static goal construction invoked transport"),
    )
    node, goal, exit_binding = BlockTranslationComponent(3).native_goal(
        world.device,
        world=entry,
        binding=source.binding,
        target_origin=destination.binding.origin,
        target_home_sites=destination.home_sites,
        operation_id=7,
    )
    assert node.id == goal.operation_id == 7
    assert node.name == "relocate" and node.clbits == () and node.params == ()
    assert (
        tuple(entry.qubit_to_atom[wire] for wire in node.qubits)
        == source.binding.atom_ids
    )
    assert tuple(site for _, site in goal.targets) == destination.home_sites
    assert exit_binding.atom_ids == source.binding.atom_ids
    assert exit_binding.block_id == source.binding.block_id
    assert exit_binding.origin == destination.binding.origin


def test_native_goal_rejects_atoms_outside_the_compilation_wire_domain():
    world, source, destination, entry = empty_receiver()
    entry = replace(entry, qubit_to_atom=entry.qubit_to_atom[1:])
    with pytest.raises(ValueError, match="TRANSLATION_SOURCE_WIRE_MISSING"):
        BlockTranslationComponent(3).native_goal(
            world.device,
            world=entry,
            binding=source.binding,
            target_origin=destination.binding.origin,
            target_home_sites=destination.home_sites,
            operation_id=0,
        )


def test_translation_rejects_backend_spectator_transport_before_accepting_exit(
    monkeypatch,
):
    from nadit_physical_compiler.atom_ir import AtomStep, Move
    from nadit_physical_compiler.contracts import AtomFragment
    from nadit_physical_compiler.state import AODGrid

    from modules.codes.rotated_surface import translation

    world, source, destination, entry = empty_receiver()
    spectator = next(
        atom for atom in entry.atoms if atom.id not in source.binding.atom_ids
    )

    def unexpected_transport(self, before, target, device):
        # A synthetic planner defect: touched spectator is hidden by correct
        # declared exit metadata. This is not a valid native-motion fixture.
        action = Move(
            AODGrid(self.aod_id), ((spectator.id, spectator.position),), duration_us=0
        )
        return AtomFragment((AtomStep((action,)),), target)

    monkeypatch.setattr(translation.StrictTransport, "construct", unexpected_transport)
    monkeypatch.setattr(
        translation,
        "validate_result",
        lambda *a, **k: pytest.fail("unowned transport reached validation"),
    )
    with pytest.raises(ValueError, match="TRANSLATION_TRANSPORTED_SPECTATOR"):
        BlockTranslationComponent(3).compile(
            world.device,
            world=entry,
            binding=source.binding,
            target_origin=destination.binding.origin,
            target_home_sites=destination.home_sites,
        )


@pytest.mark.slow
def test_actual_translation_preserves_spectators_and_native_context(monkeypatch):
    from nadit_physical_compiler.atom_ir import Load, Move, Store
    from nadit_physical_compiler.provenance import canonical_hash
    from nadit_physical_compiler.serialization import encode_device, encode_layout

    from modules.codes.rotated_surface import translation
    from modules.logical_compiler.src.protocols.physical import PhysicalContext

    world, source, destination, entry = empty_receiver()
    context = PhysicalContext(world.device, entry, (source.binding,))
    compiled = BlockTranslationComponent(3).compile(
        world.device,
        world=context.world,
        binding=source.binding,
        target_origin=destination.binding.origin,
        target_home_sites=destination.home_sites,
    )
    assert compiled.device_sha256 == canonical_hash(encode_device(world.device))
    assert compiled.entry_world_sha256 == canonical_hash(encode_layout(context.world))
    monkeypatch.setattr(
        translation.StrictTransport,
        "construct",
        lambda *a, **k: pytest.fail("expand silently replanned transport"),
    )
    changed_device = replace(
        world.device, timing=replace(world.device.timing, load_us=11)
    )
    with pytest.raises(ValueError, match="TRANSLATION_DEVICE_CHANGED"):
        compiled.expand(
            InvocationContext("changed", 0, 0, changed_device, context.world)
        )
    spectator = next(
        atom for atom in context.world.atoms if atom.id not in source.binding.atom_ids
    )
    changed_world = replace(
        context.world,
        atoms=tuple(
            replace(atom, position=Position(atom.position.x + 1, atom.position.y))
            if atom.id == spectator.id
            else atom
            for atom in context.world.atoms
        ),
    )
    with pytest.raises(ValueError, match="TRANSLATION_WORLD_CHANGED"):
        compiled.expand(InvocationContext("changed", 0, 0, world.device, changed_world))
    before = context.world
    parts = context.invoke(compiled, "translated", result_count=0)
    part = parts[0]
    assert part.exit_binding.atom_ids == source.binding.atom_ids
    assert part.exit_binding.block_id == source.binding.block_id
    assert part.exit_binding.origin == destination.binding.origin
    assert context.bindings[source.binding.block_id] == part.exit_binding
    assert context.world.qubit_to_atom == before.qubit_to_atom
    assert {atom.id for atom in context.world.atoms} == {
        atom.id for atom in before.atoms
    }
    for atom in before.atoms:
        if atom.id not in source.binding.atom_ids:
            assert context.world.atom(atom.id) == atom
    for atom_id, site in zip(
        source.binding.atom_ids, destination.home_sites, strict=True
    ):
        assert context.world.atom(atom_id).holder == SLMHolder(site)
        assert context.world.atom(atom_id).position == world.device.site(site).position
    for step in part.program.steps:
        for action in step.actions:
            assert isinstance(action, (Load, Move, Store))
            if isinstance(action, Load):
                assert action.duration_us == world.device.timing.load_us
            if isinstance(action, Store):
                assert action.duration_us == world.device.timing.store_us
    assert context.finalize().validation["ok"]
