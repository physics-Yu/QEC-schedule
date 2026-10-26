"""Durable exact-world cache identity and publication without physical workloads."""

from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from nadit_physical_compiler.experiments.journal import directory_lock
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd.joint_cache import (
    JointCacheDeferred,
    JointCacheMiss,
    JointCalibrationCache,
    joint_action_identity,
)
from experiments.msd.standard import ExperimentSpec, build_world


def translation_request():
    """Explicit vacancy fixture; no successful L1 production is implied."""
    world = build_world(ExperimentSpec(3, 2))
    source, receiver = world.patch(0, "W1"), world.patch(1, "W1")
    absent = set(receiver.binding.atom_ids)
    world = replace(
        world,
        state=replace(
            world.state,
            atoms=tuple(a for a in world.state.atoms if a.id not in absent),
            qubit_to_atom=tuple(
                a for a in world.state.qubit_to_atom if a not in absent
            ),
        ),
        patches=tuple(p for p in world.patches if p is not receiver),
    )
    member = f"block_translation:{source.binding.block_id}"
    return world, member, {member: (receiver.binding.origin, receiver.home_sites)}


def transition_application_fixture():
    """Synthetic endpoint evidence tests state application, not physical execution."""
    from nadit_physical_compiler.serialization import encode_device, encode_layout

    from experiments.msd.joint_transition import expected_exit
    from modules.codes.rotated_surface.translation import BlockTranslationComponent

    world, member, targets = translation_request()
    patch = world.patch(0, "W1")
    patch = replace(
        patch, binding=replace(patch.binding, site_ids=(("data", patch.home_sites[0]),))
    )
    world = replace(world, patches=(patch, *world.patches[1:]))
    entry = replace(world.state, qubit_to_atom=patch.binding.atom_ids)
    origin, homes = targets[member]
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
        "entry_state": encode_layout(entry),
        "exit_state": encode_layout(final),
        "device": encode_device(world.device),
        "transport_goals": [asdict(goal)],
        "validation": {
            "ok": True,
            "semantic": "checked",
            "checks": ["pulse", "timing", "transport_goals"],
        },
        "synthetic_test_only": True,
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
    return world, action, trace


def test_apply_joint_transition_retains_world_identity_and_original_wire_map():
    from experiments.msd.joint_transition import apply_joint_transition
    from experiments.msd.standard import ExperimentWorld

    world, action, trace = transition_application_fixture()
    before = deepcopy(world.document())
    result = apply_joint_transition(world, action, trace)
    assert result is not world
    assert (
        result.device is world.device and result.placement_plan is world.placement_plan
    )
    assert result.state.qubit_to_atom == world.state.qubit_to_atom
    assert len(result.state.qubit_to_atom) > len(trace["exit_state"]["qubit_to_atom"])
    assert world.document() == before
    source = world.patch(0, "W1")
    delivered = result.patch(0, "W1")
    update = action["state_transition"]["bindings"]["block_translation:factory0/W1"]
    assert delivered.binding.atom_ids == source.binding.atom_ids
    assert (
        delivered.factory_index == source.factory_index
        and delivered.role == source.role
    )
    assert asdict(delivered.binding) == update["exit"]
    assert delivered.home_sites == tuple(update["home_sites"])
    assert ExperimentWorld.from_document(result.document()) == result
    with pytest.raises(ValueError):
        apply_joint_transition(result, action, trace)


@pytest.mark.parametrize(
    "damage", ("hash", "validation", "device", "entry", "binding", "distance")
)
def test_apply_joint_transition_rejects_stale_or_mismatched_evidence(damage):
    from nadit_physical_compiler.serialization import encode_device

    from experiments.msd.joint_transition import apply_joint_transition

    world, action, trace = transition_application_fixture()
    if damage == "hash":
        action["trace_sha256"] = "wrong"
    elif damage == "validation":
        trace["validation"]["ok"] = False
        action["trace_sha256"] = canonical_hash(trace)
    elif damage == "device":
        trace["device"] = encode_device(
            replace(world.device, timing=replace(world.device.timing, load_us=11))
        )
        action["trace_sha256"] = canonical_hash(trace)
    elif damage == "entry":
        missing = world.state.atoms[-1].id
        world = replace(
            world,
            state=replace(
                world.state,
                atoms=world.state.atoms[:-1],
                qubit_to_atom=tuple(
                    atom for atom in world.state.qubit_to_atom if atom != missing
                ),
            ),
        )
    elif damage == "binding":
        patch = world.patches[0]
        world = replace(
            world,
            patches=(
                replace(patch, binding=replace(patch.binding, site_ids=())),
                *world.patches[1:],
            ),
        )
    else:
        world = replace(world, spec=replace(world.spec, distance=5))
    with pytest.raises(ValueError):
        apply_joint_transition(world, action, trace)


def test_apply_return_home_wave_preserves_original_world_object():
    from experiments.msd.joint_transition import apply_joint_transition

    world = build_world(ExperimentSpec(3, 1))
    action, _probability = producers({"action": 0})
    record, trace = action(world, ("initialize_plus:factory0/W1",), family="fixture")
    assert apply_joint_transition(world, record, trace) is world


def test_translation_identity_covers_destination_and_current_world_without_routing(
    monkeypatch,
):
    from modules.codes.rotated_surface import translation

    world, member, targets = translation_request()
    monkeypatch.setattr(
        translation.StrictTransport,
        "construct",
        lambda *a, **k: pytest.fail("identity routed atoms"),
    )
    first = joint_action_identity(world, (member,), {}, transport_targets=targets)
    assert first["transport_targets"][member]["home_sites"] == list(targets[member][1])
    assert first["source_contracts"][member]["active_atoms"] == list(
        world.patch(0, "W1").binding.atom_ids
    )
    changed = replace(
        world,
        device=replace(world.device, timing=replace(world.device.timing, load_us=11)),
    )
    second = joint_action_identity(changed, (member,), {}, transport_targets=targets)
    assert canonical_hash(first) != canonical_hash(second)
    with pytest.raises(ValueError, match="TARGET_COVERAGE"):
        joint_action_identity(world, (member,), {})


def test_translation_cache_miss_uses_targets_without_producing_artifacts(tmp_path):
    world, member, targets = translation_request()
    cache = JointCalibrationCache(tmp_path / "not-created")
    with pytest.raises(JointCacheMiss) as missing:
        cache.lookup(
            world,
            (member,),
            family="stateful",
            noise_params={},
            shots=1,
            seed=0,
            action_dependencies={},
            probability_dependencies={},
            transport_targets=targets,
        )
    expected = canonical_hash(
        joint_action_identity(world, (member,), {}, transport_targets=targets)
    )
    assert missing.value.key == expected
    assert not cache.root.exists()


@pytest.mark.parametrize(
    "damage",
    (
        "undeclared",
        "spectator",
        "origin",
        "identity",
        "missing_binding",
        "wire_map",
        "site_alias",
    ),
)
def test_state_transition_checks_requested_identity_and_complete_endpoint(damage):
    from nadit_physical_compiler.serialization import encode_device, encode_layout

    from experiments.msd.joint_transition import expected_exit, validate_transition
    from modules.codes.rotated_surface.translation import BlockTranslationComponent

    world, member, targets = translation_request()
    patch = world.patch(0, "W1")
    origin, homes = targets[member]
    _, goal, binding = BlockTranslationComponent(3).native_goal(
        world.device,
        world=world.state,
        binding=patch.binding,
        target_origin=origin,
        target_home_sites=homes,
        operation_id=0,
    )
    exit_state = expected_exit(
        world.state, world.device, dict(zip(binding.atom_ids, homes, strict=True))
    )
    # Synthetic endpoint records exercise contract validation only, not routing.
    trace = {
        "entry_state": encode_layout(world.state),
        "exit_state": encode_layout(exit_state),
        "device": encode_device(world.device),
        "transport_goals": [asdict(goal)],
        "validation": {"checks": ["transport_goals"]},
    }
    transition = {
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
    }
    action = {"members": {member: {}}, "state_transition": transition}
    validate_transition(action, trace)
    if damage == "undeclared":
        del action["state_transition"]
    elif damage == "spectator":
        trace["exit_state"]["atoms"][-1]["position"]["x"] += 1
        transition["exit_state_sha256"] = canonical_hash(trace["exit_state"])
    elif damage == "origin":
        transition["bindings"][member]["exit"]["origin"]["x"] += 1
    elif damage == "identity":
        transition["bindings"][member]["exit"]["block_id"] = "renamed"
    elif damage == "missing_binding":
        transition["bindings"] = {}
    elif damage == "site_alias":
        update = transition["bindings"][member]
        update["entry"]["site_ids"] = [["data", patch.home_sites[0]]]
        update["exit"]["site_ids"] = [["data", homes[0]]]
        validate_transition(action, trace)
        update["exit"]["site_ids"] = [["data", patch.home_sites[0]]]
    else:
        trace["exit_state"]["qubit_to_atom"].reverse()
        transition["exit_state_sha256"] = canonical_hash(trace["exit_state"])
    with pytest.raises(ValueError, match="JOINT_"):
        validate_transition(action, trace)


def producers(counts):
    """Return explicitly synthetic artifacts; these tests prove cache mechanics only."""

    def action(world, members, *, family):
        counts["action"] += 1
        identity = joint_action_identity(world, members, {})
        contracts = identity["source_contracts"]
        participants = {member: contracts[member]["active_atoms"] for member in members}
        entry = world.document()["entry_state"]
        entry["qubit_to_atom"] = [
            atom for member in members for atom in participants[member]
        ]
        trace = {
            "schema": "nadit.result/2",
            "validation": {
                "ok": True,
                "semantic": "checked",
                "checks": ["pulse", "timing"],
            },
            "entry_state": entry,
            "exit_state": deepcopy(entry),
            "device": world.document()["device"],
            "synthetic_test_only": True,
            "action_family": family,
        }
        record = {
            "schema": "nadit.joint_actions/1",
            "family": family,
            "members": {
                member: {
                    "measurement_phases": [],
                    "cost_segments": [],
                    "primitive_counts": {},
                }
                for member in members
            },
            "validation_ok": True,
            "trace_sha256": canonical_hash(trace),
            "phase_durations_us": [2],
            "peak_rows": 1,
            "peak_columns": 1,
            "peak_readout_atoms": 0,
            "participant_atoms": participants,
            "measurement_ids": {},
            "source_contracts": {
                member: {
                    key: value
                    for key, value in contract.items()
                    if key != "active_atoms"
                }
                for member, contract in contracts.items()
            },
            "shared_metrics": {"atom_time_us": 204},
        }
        return record, trace

    def probability(action, trace, *, noise_params, shots, seed):
        counts["probability"] += 1
        return {
            "schema": "nadit.joint_probabilities/1",
            "trace_sha256": canonical_hash(trace),
            "raw_ports": {},
            "noise_params": deepcopy(noise_params),
            "shots": shots,
            "seed": seed,
            "probability_wall_seconds": 0,
        }

    return action, probability


def request(cache, world, counts, **options):
    action, probability = producers(counts)
    arguments = {
        "family": "profile-world",
        "noise_params": {},
        "shots": 16,
        "seed": 7,
        "action_dependencies": {"compiler": "a1"},
        "probability_dependencies": {"model": "p1"},
        "action_producer": action,
        "probability_producer": probability,
    }
    arguments.update(options)
    members = arguments.pop("members", ("logical_x:factory0/W1",))
    return cache.get_or_create(world, members, **arguments)


@pytest.mark.parametrize(
    "damage", ("device", "spectator", "wires", "participants", "source")
)
def test_producer_cannot_publish_another_world_under_requested_key(tmp_path, damage):
    world = build_world(ExperimentSpec(3, 1))
    counts = {"action": 0, "probability": 0}
    producer, probability = producers(counts)

    def wrong_action(world, members, *, family):
        action, trace = producer(world, members, family=family)
        if damage == "device":
            trace["device"]["timing"]["load_us"] += 1
        elif damage == "spectator":
            for field in ("entry_state", "exit_state"):
                trace[field]["atoms"][-1]["position"]["x"] += 1
        elif damage == "wires":
            for field in ("entry_state", "exit_state"):
                trace[field]["qubit_to_atom"].reverse()
        elif damage == "participants":
            action["participant_atoms"][members[0]] = []
        else:
            action["source_contracts"][members[0]]["source_sha256"] = "0" * 64
        action["trace_sha256"] = canonical_hash(trace)
        return action, trace

    with pytest.raises(ValueError, match="JOINT_REQUEST"):
        request(
            JointCalibrationCache(tmp_path),
            world,
            counts,
            action_producer=wrong_action,
            probability_producer=probability,
        )
    assert counts["probability"] == 0
    assert not list(tmp_path.rglob("action.json"))


def test_resume_reuses_actions_and_probability_but_noise_only_recomputes_probability(
    tmp_path,
):
    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    first = request(JointCalibrationCache(tmp_path), world, counts)
    resumed = request(JointCalibrationCache(tmp_path), world, counts)
    assert first.group == resumed.group
    assert not first.action_hit and not first.probability_hit
    assert resumed.action_hit and resumed.probability_hit
    changed = request(
        JointCalibrationCache(tmp_path),
        world,
        counts,
        noise_params={"readout_flip": 0.01},
    )
    assert changed.action_hit and not changed.probability_hit
    assert changed.action_key == first.action_key
    assert changed.probability_key != first.probability_key
    assert counts == {"action": 1, "probability": 2}


@pytest.mark.parametrize(
    "change", ("spectator", "device", "source", "shots", "seed", "probability_source")
)
def test_dependency_changes_invalidate_only_the_required_layer(tmp_path, change):
    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    cache = JointCalibrationCache(tmp_path)
    first = request(cache, world, counts)
    options = {}
    if change == "spectator":
        world = build_world(ExperimentSpec(3, 2))
    elif change == "device":
        world = replace(
            world,
            device=replace(
                world.device, timing=replace(world.device.timing, load_us=11)
            ),
        )
    elif change == "source":
        options["action_dependencies"] = {"compiler": "a2"}
    elif change == "shots":
        options["shots"] = 32
    elif change == "seed":
        options["seed"] = 8
    else:
        options["probability_dependencies"] = {"model": "p2"}
    changed = request(cache, world, counts, **options)
    if change in ("spectator", "device", "source"):
        assert changed.action_key != first.action_key and not changed.action_hit
    else:
        assert changed.action_key == first.action_key and changed.action_hit
    assert not changed.probability_hit


@pytest.mark.parametrize("damage", ("trace", "record", "partial"))
def test_partial_or_corrupt_action_publication_is_not_a_hit(tmp_path, damage):
    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    cache = JointCalibrationCache(tmp_path)
    first = request(cache, world, counts)
    directory = tmp_path / "actions" / first.action_key
    target = directory / ("trace.json" if damage == "trace" else "action.json")
    if damage == "partial":
        target.unlink()
    else:
        target.write_text('{"corrupt":true}', encoding="utf-8")
    repaired = request(cache, world, counts)
    assert not repaired.action_hit
    assert counts["action"] == 2


def test_key_lock_is_deferred_and_never_interpreted_as_success(tmp_path):
    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    cache = JointCalibrationCache(tmp_path)
    first = request(cache, world, counts)
    # A completed record remains readable during another writer's unrelated work.
    (tmp_path / "actions" / first.action_key / "action.json").unlink()
    with (
        directory_lock(tmp_path / "actions" / first.action_key),
        pytest.raises(JointCacheDeferred),
    ):
        request(cache, world, counts)
    assert counts["action"] == 1


def test_failed_producer_leaves_no_completion_and_restart_can_continue(tmp_path):
    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    cache = JointCalibrationCache(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("injected worker failure")

    with pytest.raises(RuntimeError, match="injected worker failure"):
        request(cache, world, counts, action_producer=fail)
    assert not list(tmp_path.glob("actions/*/action.json"))
    completed = request(cache, world, counts)
    assert not completed.action_hit and counts == {"action": 1, "probability": 1}


def test_frontier_order_is_canonical_but_subset_is_a_different_action(tmp_path):
    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    cache = JointCalibrationCache(tmp_path)
    members = ("logical_x:factory0/W1", "logical_x:factory0/W2")
    first = request(cache, world, counts, members=members)
    reordered = request(cache, world, counts, members=tuple(reversed(members)))
    subset = request(cache, world, counts, members=members[:1])
    assert reordered.action_key == first.action_key and reordered.action_hit
    assert subset.action_key != first.action_key and not subset.action_hit
    assert counts == {"action": 2, "probability": 2}


def test_probability_failure_does_not_erase_completed_action(tmp_path):
    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    cache = JointCalibrationCache(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("probability worker failure")

    with pytest.raises(RuntimeError, match="probability worker failure"):
        request(cache, world, counts, probability_producer=fail)
    assert len(list(tmp_path.glob("actions/*/action.json"))) == 1
    assert not list(tmp_path.glob("probabilities/*/probability.json"))
    result = request(cache, world, counts)
    assert result.action_hit and not result.probability_hit
    assert counts == {"action": 1, "probability": 1}


def test_trusted_completed_action_does_not_repeat_physical_validation(
    tmp_path, monkeypatch
):
    from experiments.msd import joint_cache

    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    flags = []
    _, synthetic = producers(counts)

    def evaluate(action, trace, *, noise_params, shots, seed, revalidate=True):
        flags.append(revalidate)
        return synthetic(
            action, trace, noise_params=noise_params, shots=shots, seed=seed
        )

    monkeypatch.setattr(joint_cache, "evaluate_joint_probabilities", evaluate)
    request(JointCalibrationCache(tmp_path), world, counts, probability_producer=None)
    resumed = request(
        JointCalibrationCache(tmp_path),
        world,
        counts,
        probability_producer=None,
        noise_params={"readout_flip": 0.01},
    )
    assert resumed.action_hit and not resumed.probability_hit
    assert flags == [False, False]
    assert counts == {"action": 1, "probability": 2}


def test_read_only_lookup_returns_both_layer_misses_without_writing_or_producing(
    tmp_path, monkeypatch
):
    from experiments.msd import joint_cache

    counts = {"action": 0, "probability": 0}
    world = build_world(ExperimentSpec(3, 1))
    cache = JointCalibrationCache(tmp_path / "cache")
    kwargs = {
        "family": "profile-world",
        "noise_params": {},
        "shots": 16,
        "seed": 7,
        "action_dependencies": {"compiler": "a1"},
        "probability_dependencies": {"model": "p1"},
    }

    def forbidden(*args, **kwargs):
        pytest.fail("read-only lookup performed offline work")

    monkeypatch.setattr(joint_cache, "compile_joint_actions", forbidden)
    monkeypatch.setattr(joint_cache, "evaluate_joint_probabilities", forbidden)
    with monkeypatch.context() as context:
        context.setattr(joint_cache, "directory_lock", forbidden)
        context.setattr(joint_cache, "write_json", forbidden)
        with pytest.raises(JointCacheMiss) as missing:
            cache.lookup(world, ("logical_x:factory0/W1",), **kwargs)
        assert missing.value.layer == "actions"
        assert missing.value.to_dict() == {
            "schema": "nadit.joint_cache_miss/1",
            "layer": "actions",
            "key": missing.value.key,
            "reason": "no_complete_compatible_record",
        }
        assert not cache.root.exists()

    created = request(cache, world, counts)
    with monkeypatch.context() as context:
        context.setattr(joint_cache, "directory_lock", forbidden)
        context.setattr(joint_cache, "write_json", forbidden)
        hit = cache.lookup(world, ("logical_x:factory0/W1",), **kwargs)
        assert hit.group == created.group
        assert hit.action_hit and hit.probability_hit
        assert hit.software_seconds["action_calibration"] == 0
        assert hit.software_seconds["probability_calibration"] == 0
        created.probability_path.unlink()
        before = sorted(str(path) for path in cache.root.rglob("*"))
        with pytest.raises(JointCacheMiss) as missing:
            cache.lookup(world, ("logical_x:factory0/W1",), **kwargs)
        assert missing.value.layer == "probabilities"
        assert missing.value.key == created.probability_key
        assert sorted(str(path) for path in cache.root.rglob("*")) == before
    assert counts == {"action": 1, "probability": 1}


def hot_lookup(cache, world, **options):
    arguments = {
        "family": "profile-world",
        "noise_params": {},
        "shots": 16,
        "seed": 7,
        "action_dependencies": {"compiler": "a1"},
        "probability_dependencies": {"model": "p1"},
    }
    arguments.update(options)
    return cache.lookup(world, ("logical_x:factory0/W1",), **arguments)


def test_valid_read_index_skips_scientific_json_parsing_and_preserves_caller_family(
    tmp_path,
    monkeypatch,
):
    from hashlib import sha256

    from experiments.msd import joint_cache

    world = build_world(ExperimentSpec(3, 1))
    counts = {"action": 0, "probability": 0}
    first = request(JointCalibrationCache(tmp_path), world, counts)
    assert len(list(tmp_path.glob("read_indexes/*/index.json"))) == 1
    original = joint_cache._read

    def observed(path, **kwargs):
        if path.name in ("action.json", "trace.json", "probability.json"):
            pytest.fail("hot lookup parsed a full scientific JSON artifact")
        return original(path, **kwargs)

    monkeypatch.setattr(joint_cache, "_read", observed)
    monkeypatch.setattr(
        joint_cache, "write_json", lambda *a, **k: pytest.fail("lookup wrote index")
    )
    monkeypatch.setattr(
        joint_cache, "directory_lock", lambda *a, **k: pytest.fail("lookup locked")
    )
    hot = hot_lookup(
        JointCalibrationCache(tmp_path), world, family="new-current-world-family"
    )
    assert hot.read_index_hit is True
    assert hot.artifact_bytes_sha256 == {
        "action": sha256(first.action_path.read_bytes()).hexdigest(),
        "trace": sha256(first.trace_path.read_bytes()).hexdigest(),
        "probability": sha256(first.probability_path.read_bytes()).hexdigest(),
    }
    assert first.artifact_bytes_sha256 == hot.artifact_bytes_sha256
    assert hot.group == {**first.group, "family": "new-current-world-family"}
    assert hot.action_hit and hot.probability_hit
    assert counts == {"action": 1, "probability": 1}


@pytest.mark.parametrize("artifact", ("action_path", "trace_path", "probability_path"))
def test_hot_index_checks_every_original_file_bytes_before_reuse(tmp_path, artifact):
    world = build_world(ExperimentSpec(3, 1))
    first = request(
        JointCalibrationCache(tmp_path), world, {"action": 0, "probability": 0}
    )
    path = getattr(first, artifact)
    altered = path.read_bytes() + b" "
    path.write_bytes(altered)
    # Equivalent JSON is still scientifically valid, but its old byte proof is
    # invalid: a read-only query must perform the full validation again.
    result = hot_lookup(JointCalibrationCache(tmp_path), world)
    assert result.read_index_hit is False
    assert result.artifact_bytes_sha256 is None
    assert result.group == first.group
    assert path.read_bytes() == altered


@pytest.mark.parametrize("damage", ("schema", "reader", "query", "payload", "missing"))
def test_bad_or_missing_read_index_falls_back_without_recompilation(tmp_path, damage):
    import json

    world = build_world(ExperimentSpec(3, 1))
    counts = {"action": 0, "probability": 0}
    first = request(JointCalibrationCache(tmp_path), world, counts)
    path = next(tmp_path.glob("read_indexes/*/index.json"))
    if damage == "missing":
        path.unlink()
    else:
        value = json.loads(path.read_text())
        if damage == "schema":
            value["schema"] = "obsolete"
        elif damage == "reader":
            value["reader_sha256"] = "0" * 64
        elif damage == "query":
            value["query"]["shots"] += 1
        else:
            value["group"]["phase_durations_us"] = [99999]
        path.write_text(json.dumps(value), encoding="utf-8")
    files_before = sorted(str(item) for item in tmp_path.rglob("*"))
    result = hot_lookup(JointCalibrationCache(tmp_path), world)
    assert result.group == first.group
    assert result.read_index_hit is False
    assert sorted(str(item) for item in tmp_path.rglob("*")) == files_before
    assert counts == {"action": 1, "probability": 1}


def test_explicit_get_or_create_prepares_legacy_index_without_scientific_writes(
    tmp_path,
    monkeypatch,
):
    from experiments.msd import joint_cache

    world = build_world(ExperimentSpec(3, 1))
    counts = {"action": 0, "probability": 0}
    first = request(JointCalibrationCache(tmp_path), world, counts)
    next(tmp_path.glob("read_indexes/*/index.json")).unlink()
    originals = {
        path: path.read_bytes()
        for path in (first.action_path, first.trace_path, first.probability_path)
    }
    write = joint_cache.write_json

    def only_index(path, document):
        assert path.name == "index.json"
        write(path, document)

    def no_producer(*args, **kwargs):
        pytest.fail("read preparation recompiled or resampled completed science")

    monkeypatch.setattr(joint_cache, "write_json", only_index)
    prepared = request(
        JointCalibrationCache(tmp_path),
        world,
        counts,
        action_producer=no_producer,
        probability_producer=no_producer,
    )
    assert (
        prepared.group == first.group
        and prepared.action_hit
        and prepared.probability_hit
    )
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert hot_lookup(JointCalibrationCache(tmp_path), world).read_index_hit is True


@pytest.mark.parametrize(
    "options",
    (
        {"noise_params": {"readout_flip": 0.02}},
        {"shots": 17},
        {"seed": 8},
        {"probability_dependencies": {"model": "p2"}},
    ),
)
def test_read_query_never_reuses_another_probability_request(tmp_path, options):
    world = build_world(ExperimentSpec(3, 1))
    counts = {"action": 0, "probability": 0}
    request(JointCalibrationCache(tmp_path), world, counts)
    with pytest.raises(JointCacheMiss) as missing:
        hot_lookup(JointCalibrationCache(tmp_path), world, **options)
    assert missing.value.layer == "probabilities"
    assert counts == {"action": 1, "probability": 1}


def test_read_index_cannot_cover_changed_source_participants(tmp_path):
    import json

    world = build_world(ExperimentSpec(3, 1))
    counts = {"action": 0, "probability": 0}
    first = request(JointCalibrationCache(tmp_path), world, counts)
    action = json.loads(first.action_path.read_text())
    action["record"]["participant_atoms"]["logical_x:factory0/W1"] = []
    action["record_sha256"] = canonical_hash(action["record"])
    first.action_path.write_text(json.dumps(action), encoding="utf-8")
    with pytest.raises(JointCacheMiss) as missing:
        hot_lookup(JointCalibrationCache(tmp_path), world)
    assert missing.value.layer == "actions"


@pytest.mark.slow
def test_split_actual_joint_raw_trace_reuses_actions_for_new_noise(monkeypatch):
    from experiments.msd import joint_factory_calibration as calibration

    world = build_world(ExperimentSpec(3, 2))
    members = ("raw_t_postselection:factory0/R", "raw_t_postselection:factory1/R")
    action, trace = calibration.compile_joint_actions(
        world, members, family="split-test"
    )
    monkeypatch.setattr(
        calibration,
        "compile_physical",
        lambda *a, **k: pytest.fail("recompiled actions"),
    )
    zero = calibration.evaluate_joint_probabilities(
        action, trace, noise_params={}, shots=16, seed=0
    )
    changed = calibration.evaluate_joint_probabilities(
        action, trace, noise_params={"readout_flip": 0.01}, shots=16, seed=0
    )
    assert zero["trace_sha256"] == changed["trace_sha256"] == action["trace_sha256"]
    assert zero["noise_params_hash"] != changed["noise_params_hash"]
    assert action["shared_metrics"]["atom_time_us"] == pytest.approx(
        len(world.state.atoms) * sum(action["phase_durations_us"])
    )
    for member in members:
        assert len(action["measurement_ids"][member]) == 24
        assert zero["raw_ports"][member]["outcomes"][0]["probability"] == 1
