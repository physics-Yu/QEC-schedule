"""Mixed-distance source/cache boundaries; no native physical compilation runs."""

from dataclasses import asdict, replace
from hashlib import sha256
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_device, encode_layout

from experiments.msd import joint_factory_calibration as calibration
from experiments.msd.joint_cache import JointCalibrationCache, joint_action_identity
from experiments.msd.joint_transition import apply_joint_transition, expected_exit
from experiments.msd.standard import ExperimentSpec, add_buffer_sites, build_world
from experiments.msd.tests.test_joint_cache import request
from modules.codes.rotated_surface.growth import injection_indices
from modules.codes.rotated_surface.joint_factory_source import factory_component_source
from modules.codes.rotated_surface.translation import BlockTranslationComponent


def mixed_world():
    return build_world(ExperimentSpec(5, 2, factory_distances=(3, 5)))


@pytest.mark.parametrize("component", ("se_round", "raw_t_postselection"))
def test_mixed_action_identity_uses_each_actual_carrier_definition(component):
    world = mixed_world()
    members = tuple(f"{component}:factory{i}/W1" for i in range(2))
    identity = joint_action_identity(world, members, {"fixture": True})
    assert canonical_hash(identity["world"]) == canonical_hash(world.document())
    for index, distance in enumerate((3, 5)):
        contract = identity["source_contracts"][members[index]]
        source = factory_component_source(component, distance)
        patch = world.patch(index, "W1")
        assert contract["code_id"] == f"rotated_surface_d{distance}"
        assert contract["distance"] == distance
        assert (
            contract["source_sha256"] == sha256(source.source_qasm.encode()).hexdigest()
        )
        assert contract["active_atoms"] == [
            patch.binding.atom_ids[i] for i in source.wire_indices
        ]
        assert contract["result_count"] == (
            24 if component == "raw_t_postselection" else distance**2 - 1
        )
        if component == "raw_t_postselection":
            assert contract["wire_indices"] == list(injection_indices(distance))


def test_uniform_action_identity_preserves_legacy_source_contract_shape():
    world = build_world(ExperimentSpec(3, 1))
    member = "se_round:factory0/W1"
    contract = joint_action_identity(world, (member,), {})["source_contracts"][member]
    assert set(contract) == {
        "source_sha256",
        "wire_indices",
        "result_count",
        "active_atoms",
    }


def test_action_dependencies_include_current_world_definition_resolver():
    from experiments.msd.joint_cache import action_dependency_fingerprints

    assert "experiments/msd/standard.py" in action_dependency_fingerprints()["files"]


@pytest.mark.parametrize("entry", ("identity", "compile"))
def test_one_cross_distance_cnot_is_rejected_before_native_compilation(
    monkeypatch, entry
):
    world = mixed_world()
    members = ("transversal_cnot:factory0/W1,factory1/W1",)
    monkeypatch.setattr(
        calibration,
        "compile_physical",
        lambda *a, **k: pytest.fail("reached native compilation"),
    )
    with pytest.raises(ValueError, match="JOINT_COMPONENT_CODE_DISTANCE_MISMATCH"):
        if entry == "identity":
            joint_action_identity(world, members, {})
        else:
            calibration.compile_joint_actions(world, members, family="fixture")


@pytest.mark.parametrize(
    "component,wires,results", (("se_round", 66, 32), ("transversal_cnot", 132, 0))
)
def test_independent_mixed_frontier_reaches_one_compile_boundary_with_all_spectators(
    monkeypatch,
    component,
    wires,
    results,
):
    world = mixed_world()
    roles = ("W1", "W2") if component == "transversal_cnot" else ("W1",)
    members = tuple(
        component + ":" + ",".join(f"factory{i}/{role}" for role in roles)
        for i in range(2)
    )

    class SourceCaptured(Exception):
        pass

    def capture(dag, device, *, strategy, entry_state):
        assert device is world.device
        assert dag.num_qubits == wires and dag.num_clbits == results
        assert entry_state.atoms == world.state.atoms
        assert len(entry_state.atoms) == 396
        assert entry_state.qubit_to_atom == tuple(
            atom
            for i in range(2)
            for role in roles
            for atom in world.patch(i, role).binding.atom_ids
        )
        raise SourceCaptured

    monkeypatch.setattr(calibration, "compile_physical", capture)
    with pytest.raises(SourceCaptured):
        calibration.compile_joint_actions(world, members, family="fixture")


def test_mixed_raw_probability_projects_only_each_d3_injection_subset(monkeypatch):
    world = mixed_world()
    members = (
        "raw_t_postselection:factory0/R",
        "raw_t_postselection:factory1/R",
        "se_round:factory1/W1",
    )
    identity = joint_action_identity(world, members, {})
    trace = {"entry_state": {}, "exit_state": {}, "synthetic_test_only": True}
    action = {
        "schema": "nadit.joint_actions/1",
        "validation_ok": True,
        "trace_sha256": canonical_hash(trace),
        "members": {member: {} for member in members},
        "participant_atoms": {
            member: contract["active_atoms"]
            for member, contract in identity["source_contracts"].items()
        },
        "measurement_ids": {
            member: list(range(index * 24, (index + 1) * 24))
            for index, member in enumerate(members)
        },
        "source_contracts": identity["source_contracts"],
    }
    observed = []
    monkeypatch.setattr(calibration, "derive_activity", lambda _: "synthetic-activity")
    monkeypatch.setattr(
        calibration,
        "model_for",
        lambda _: SimpleNamespace(
            evaluate=lambda *a: {
                "noise": {"channels": []},
                "params_hash": "noise-fixture",
            }
        ),
    )
    monkeypatch.setattr(
        calibration,
        "projected_raw_port",
        lambda activity, channels, atoms, results, **kwargs: (
            observed.append((atoms, results, kwargs)) or {"synthetic_projection": True}
        ),
    )
    result = calibration.evaluate_joint_probabilities(
        action, trace, noise_params={}, shots=16, seed=4, revalidate=False
    )
    assert set(result["raw_ports"]) == set(members[:2])
    assert [atoms for atoms, _, _ in observed] == [
        tuple(world.patch(i, "R").binding.atom_ids[q] for q in injection_indices(d))
        for i, d in enumerate((3, 5))
    ]
    assert all(
        len(atoms) == 17
        and len(results) == 24
        and options["shots"] == 16
        and options["seed"] == 4
        for atoms, results, options in observed
    )


def translation_fixture():
    world, slots = add_buffer_sites(
        mixed_world(), {"park3": Position(-200, -1000)}, distances={"park3": 3}
    )
    patch = world.patch(0, "W1")
    member = "block_translation:" + patch.binding.block_id
    origin, homes = slots["park3"]
    entry = replace(world.state, qubit_to_atom=patch.binding.atom_ids)
    _node, goal, binding = BlockTranslationComponent(3).native_goal(
        world.device,
        world=entry,
        binding=patch.binding,
        target_origin=origin,
        target_home_sites=homes,
        operation_id=0,
    )
    final = expected_exit(
        entry, world.device, dict(zip(binding.atom_ids, homes, strict=True))
    )
    trace = {
        "schema": "nadit.result/2",
        "device": encode_device(world.device),
        "entry_state": encode_layout(entry),
        "exit_state": encode_layout(final),
        "transport_goals": [asdict(goal)],
        "synthetic_test_only": True,
        "validation": {
            "ok": True,
            "semantic": "checked",
            "checks": ["pulse", "timing", "transport_goals"],
        },
    }
    action = {
        "schema": "nadit.joint_actions/1",
        "validation_ok": True,
        "trace_sha256": canonical_hash(trace),
        "members": {member: {}},
        "state_transition": {
            "schema": "nadit.joint_world_transition/1",
            "entry_state_sha256": canonical_hash(trace["entry_state"]),
            "exit_state_sha256": canonical_hash(trace["exit_state"]),
            "bindings": {
                member: {
                    "distance": 3,
                    "entry": asdict(patch.binding),
                    "exit": asdict(binding),
                    "home_sites": list(homes),
                }
            },
        },
    }
    return world, member, {member: slots["park3"]}, action, trace


def test_mixed_translation_uses_source_carrier_distance_and_preserves_other_codes():
    world, member, targets, action, trace = translation_fixture()
    identity = joint_action_identity(world, (member,), {}, transport_targets=targets)
    assert identity["source_contracts"][member]["distance"] == 3
    updated = apply_joint_transition(world, action, trace)
    assert (
        updated.device is world.device
        and updated.placement_plan is world.placement_plan
    )
    assert updated.state.qubit_to_atom == world.state.qubit_to_atom
    assert updated.patch(1, "W1") == world.patch(1, "W1")
    assert (
        updated.patch(0, "W1").binding.atom_ids == world.patch(0, "W1").binding.atom_ids
    )
    assert updated.patch(0, "W1").home_sites == targets[member][1]


def test_mixed_translation_native_registry_uses_seventeen_source_atoms(monkeypatch):
    world, member, targets, _action, _trace = translation_fixture()

    class SourceCaptured(Exception):
        pass

    def capture(dag, device, *, strategy, entry_state):
        assert dag.num_qubits == 17 and dag.nodes[-1].name == "relocate"
        assert len(strategy.transport_goals) == 1
        assert len(strategy.transport_goals[0].targets) == 17
        assert entry_state.atoms == world.state.atoms and device is world.device
        raise SourceCaptured

    monkeypatch.setattr(calibration, "compile_physical", capture)
    with pytest.raises(SourceCaptured):
        calibration.compile_joint_actions(
            world, (member,), family="fixture", transport_targets=targets
        )


def test_mixed_cache_replays_verified_source_contracts_without_compilation(tmp_path):
    world = mixed_world()
    members = ("logical_x:factory0/W1", "logical_x:factory1/W1")
    counts = {"action": 0, "probability": 0}
    first = request(JointCalibrationCache(tmp_path), world, counts, members=members)
    second = request(JointCalibrationCache(tmp_path), world, counts, members=members)
    assert second.read_index_hit and first.group == second.group
    assert counts == {"action": 1, "probability": 1}
