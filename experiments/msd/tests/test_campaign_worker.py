"""Worker miss requests are deterministic and never compile inside fast execution."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from experiments.msd.campaign_worker import calibration_dependency, execute_task
from experiments.msd.standard import (
    FACTORY_ROLES,
    ExperimentSpec,
    placement_request,
)
from modules.logical_compiler.src.placement import GridFactoryPlacement, place


def test_transport_witness_requires_explicit_prepared_fixture_acknowledgement(tmp_path):
    task = witness_task(tmp_path)
    task["kind"] = "msd.transport_witness"
    with pytest.raises(ValueError, match="PREPARED_TOKEN_FIXTURE"):
        execute_task(task)


def test_two_level_witness_requires_explicit_theory_transport_assumptions(tmp_path):
    task = witness_task(tmp_path)
    task["kind"] = "msd.two_level_witness"
    task["payload"]["two_level"] = {"acknowledge_theory_transport_exclusions": False}
    with pytest.raises(ValueError, match="THEORY_TRANSPORT"):
        execute_task(task)


def test_cache_readiness_requires_existing_records_and_verified_query_file(
    tmp_path, monkeypatch
):
    from hashlib import sha256

    import experiments.msd.campaign_worker as worker

    query = calibration_dependency(witness_task(tmp_path), ("logical_x:factory0/W1",))
    path = tmp_path / "query.json"
    path.write_text(json.dumps(query), encoding="utf-8")
    task = {
        "kind": "msd.prepare_cache",
        "payload": {
            "cache_root": str(tmp_path / "cache"),
            "queries": [
                {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
            ],
        },
    }

    def absent(cache, world, members, **kwargs):
        assert kwargs["action_producer"] is kwargs["probability_producer"]
        return kwargs["action_producer"]()

    monkeypatch.setattr(worker.JointCalibrationCache, "get_or_create", absent)
    with pytest.raises(ValueError, match="CACHE_PREPARATION_REQUIRES_EXISTING"):
        execute_task(task)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="CACHE_QUERY_FILE_HASH"):
        execute_task(task)


def saved_cache_result(tmp_path):
    """Model a completed cache read; scientific validation belongs to cache tests."""
    from hashlib import sha256

    from nadit_physical_compiler.provenance import canonical_hash

    from experiments.msd.joint_cache import JointCacheResult

    paths = [tmp_path / f"{name}.json" for name in ("trace", "action", "probability")]
    for path in paths:
        # Byte identity deliberately differs from canonical JSON identity.
        path.write_bytes(
            json.dumps({"test_fixture": path.stem}, indent=2).encode() + b"\n "
        )
    return JointCacheResult(
        {"trace_sha256": canonical_hash({"test_fixture": "trace"})},
        "action-key",
        "probability-key",
        True,
        True,
        *paths,
        {"cache_load": 0.0},
        read_index_hit=True,
        artifact_bytes_sha256={
            path.stem: sha256(path.read_bytes()).hexdigest() for path in paths
        },
    )


def test_validated_byte_artifacts_avoid_reparsing_scientific_records(
    tmp_path, monkeypatch
):
    import experiments.msd.campaign_worker as worker

    cached = saved_cache_result(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("artifact declaration repeated a validated cache read")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(worker, "canonical_hash", forbidden)
    artifacts = worker._cache_artifacts(cached)
    assert artifacts == [
        {
            "path": str(getattr(cached, f"{name}_path")),
            "sha256": cached.artifact_bytes_sha256[name],
            "hash_kind": "bytes",
        }
        for name in ("trace", "action", "probability")
    ]


@pytest.mark.parametrize(
    "digests",
    (
        ["trace", "action", "probability"],
        {"trace": "0" * 64, "action": "0" * 64},
        {"trace": "g" * 64, "action": "0" * 64, "probability": "0" * 64},
    ),
)
def test_cache_byte_artifact_contract_rejects_malformed_hashes(tmp_path, digests):
    from dataclasses import replace

    import experiments.msd.campaign_worker as worker

    cached = replace(saved_cache_result(tmp_path), artifact_bytes_sha256=digests)
    with pytest.raises(ValueError, match="INVALID_CACHE_ARTIFACT_BYTE_HASHES"):
        worker._cache_artifacts(cached)


def test_cache_readiness_preserves_bytes_and_deduplicates_required_artifacts(
    tmp_path, monkeypatch
):
    from hashlib import sha256

    import experiments.msd.campaign_worker as worker

    query = calibration_dependency(witness_task(tmp_path), ("logical_x:factory0/W1",))
    path = tmp_path / "query.json"
    path.write_bytes(json.dumps(query, indent=2).encode() + b"\n")
    descriptor = {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
    task = {
        "kind": "msd.prepare_cache",
        "payload": {
            "cache_root": query["payload"]["cache_root"],
            "queries": [descriptor, descriptor],
        },
    }
    cached = saved_cache_result(tmp_path)
    originals = {
        p: p.read_bytes()
        for p in (path, cached.trace_path, cached.action_path, cached.probability_path)
    }
    observed = []

    def prepare(cache, world, members, **kwargs):
        assert cache.root == Path(task["payload"]["cache_root"])
        assert world.spec.distance == 3 and world.spec.pipelines == 2
        assert members == ("logical_x:factory0/W1",)
        assert kwargs["noise_params"] == query["payload"]["noise_params"]
        assert kwargs["shots"] == 16 and kwargs["seed"] == 7
        assert (
            kwargs["action_dependencies"] == query["payload"]["dependencies"]["actions"]
        )
        assert (
            kwargs["probability_dependencies"]
            == query["payload"]["dependencies"]["probabilities"]
        )
        for name in ("action_producer", "probability_producer"):
            with pytest.raises(ValueError, match="CACHE_PREPARATION_REQUIRES_EXISTING"):
                kwargs[name]()
        observed.append(members)
        return cached

    monkeypatch.setattr(worker.JointCalibrationCache, "get_or_create", prepare)
    result = execute_task(task)
    assert observed and result["status"] == "ok"
    assert result["result"]["queries"] == 2 and result["result"]["unique_queries"] == 1
    assert result["result"]["physical_compilation_permitted"] is False
    assert result["result"]["probability_sampling_permitted"] is False
    assert len(result["artifacts"]) == 4
    assert {entry["path"] for entry in result["artifacts"]} == {
        str(p) for p in originals
    }
    for entry in result["artifacts"]:
        assert entry["hash_kind"] == "bytes"
        assert entry["sha256"] == sha256(originals[Path(entry["path"])]).hexdigest()
    assert all(p.read_bytes() == data for p, data in originals.items())
    assert result["software_seconds"]["cache_readiness"] >= 0
    json.dumps(result, allow_nan=False)


def test_cache_readiness_rejects_query_byte_drift_before_context_or_cache(
    tmp_path, monkeypatch
):
    from hashlib import sha256

    import experiments.msd.campaign_worker as worker

    query = calibration_dependency(witness_task(tmp_path), ("logical_x:factory0/W1",))
    path = tmp_path / "query.json"
    data = json.dumps(query).encode()
    path.write_bytes(data + b" ")
    assert json.loads(path.read_bytes()) == query
    task = {
        "kind": "msd.prepare_cache",
        "payload": {
            "cache_root": str(tmp_path / "cache"),
            "queries": [{"path": str(path), "sha256": sha256(data).hexdigest()}],
        },
    }
    monkeypatch.setattr(
        worker, "_context", lambda *a: pytest.fail("read altered query")
    )
    monkeypatch.setattr(
        worker.JointCalibrationCache,
        "get_or_create",
        lambda *a, **k: pytest.fail("opened cache"),
    )
    with pytest.raises(ValueError, match="CACHE_QUERY_FILE_HASH_MISMATCH"):
        execute_task(task)


def test_stateful_missing_request_preserves_snapshot_and_destination(tmp_path):
    from experiments.msd.standard import build_world
    from modules.codes.rotated_surface.joint_factory_profile import (
        MissingJointCalibration,
    )

    task = witness_task(tmp_path)
    world = build_world(
        ExperimentSpec(3, 2),
        placement_plan=place(
            placement_request(ExperimentSpec(3, 2)),
            GridFactoryPlacement(FACTORY_ROLES, columns=2),
        ),
    )
    snapshot = world.document()
    missing = MissingJointCalibration(
        ("block_translation:factory0/W1",),
        request={
            "world": snapshot,
            "transport_targets": {
                "block_translation:factory0/W1": {
                    "origin": {"x": 0, "y": -100},
                    "home_sites": ["explicit-target"],
                }
            },
        },
    )
    child = calibration_dependency(task, missing.members, request=missing.request)
    assert child["payload"]["world_snapshot"] == snapshot
    assert child["payload"]["transport_targets"] == missing.request["transport_targets"]
    other = deepcopy(missing.request)
    other["world"]["device"]["timing"]["load_us"] += 1
    assert (
        calibration_dependency(task, missing.members, request=other)["task_id"]
        != child["task_id"]
    )
    assert missing.to_dict()["calibration_request"] == missing.request


def test_current_world_context_never_rebuilds_initial_placement(tmp_path, monkeypatch):
    from nadit_physical_compiler.provenance import canonical_hash

    import experiments.msd.campaign_worker as worker
    from experiments.msd.standard import build_world

    task = witness_task(tmp_path)
    plan = place(
        placement_request(ExperimentSpec(3, 2)),
        GridFactoryPlacement(FACTORY_ROLES, columns=2),
    )
    world = build_world(ExperimentSpec(3, 2), placement_plan=plan)
    payload = task["payload"]
    payload.update(
        world_snapshot=world.document(), world_sha256=canonical_hash(world.document())
    )
    monkeypatch.setattr(
        worker, "build_world", lambda *a, **k: pytest.fail("rebuilt initial world")
    )
    restored, _, _ = worker._context(payload)
    assert restored == world
    payload["world_snapshot"]["device"]["timing"]["load_us"] += 1
    with pytest.raises(ValueError, match="WORLD_SNAPSHOT"):
        worker._context(payload)


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_current_carrier_contracts_are_static_for_cross_factory_calls(
    tmp_path, monkeypatch, distance
):
    import experiments.msd.campaign_worker as worker
    import modules.codes.rotated_surface.joint_factory_source as sources
    from experiments.msd.joint_cache import JointCalibrationCache
    from experiments.msd.standard import build_world
    from modules.codes.rotated_surface.joint_factory_profile import (
        JointSurfaceFactoryProfile,
    )

    world = build_world(ExperimentSpec(distance, 2))
    document = JointSurfaceFactoryProfile.from_placement(
        world.placement_plan, family="fixture", noise_params={}
    ).to_dict()
    profile = worker._CachedProfile(
        document,
        world,
        JointCalibrationCache(tmp_path),
        {},
        transport_slots={
            "explicit_slot": (
                world.patch(1, "W1").binding.origin,
                world.patch(1, "W1").home_sites,
            )
        },
    )
    monkeypatch.setattr(
        sources,
        "factory_component_source",
        lambda *a, **k: pytest.fail("fast lookup rebuilt source"),
    )
    left, right = profile._patches["factory0/W1"], profile._patches["factory1/W2"]
    contract = profile.lookup("transversal_cnot", (left, right))
    assert contract.participant_blocks == (left.block_id, right.block_id)
    assert (contract.code_id, contract.distance) == (
        f"rotated_surface_d{distance}",
        distance,
    )
    assert (
        contract.source_sha256
        == profile._contract_templates[
            (contract.code_id, distance, "transversal_cnot")
        ].source_sha256
    )
    assert (
        profile.lookup(
            "block_translation", (left,), parameters=(("destination", "explicit_slot"),)
        ).result_count
        == 0
    )
    with pytest.raises(ValueError, match="DESTINATION"):
        profile.lookup("block_translation", (left,))
    assert profile.world is world
    assert profile.layout().placement_plan is profile._initial_layout.placement_plan
    assert profile.layout().placement_plan.to_dict() == world.placement_plan.to_dict()


def witness_task(tmp_path):
    spec = ExperimentSpec(3, 2)
    plan = place(
        placement_request(spec), GridFactoryPlacement(FACTORY_ROLES, columns=2)
    )
    return {
        "kind": "msd.witness",
        "payload": {
            "spec": {"distance": 3, "pipelines": 2},
            "placement": plan.to_dict(),
            "noise_params": {},
            "sampling": {"shots": 16, "seed": 7},
            "cache_root": str(tmp_path / "cache"),
            "dependencies": {
                "actions": {"test_fixture": "a1"},
                "probabilities": {"test_fixture": "p1"},
            },
            "production_seed": 0,
            "input_z_error": 0.01,
            "limits": {"raw_attempts": 2, "batches": 1},
            "calibration_budget": {
                "timeout_s": 1,
                "max_attempts": 1,
                "memory_bytes": 1024**3,
            },
        },
    }


def test_missing_frontier_becomes_one_joint_dependency_with_same_plan(
    tmp_path, monkeypatch
):
    import experiments.msd.joint_cache as cache

    def forbidden(*args, **kwargs):
        raise AssertionError("witness attempted calibration")

    monkeypatch.setattr(cache, "compile_joint_actions", forbidden)
    monkeypatch.setattr(cache, "evaluate_joint_probabilities", forbidden)
    task = witness_task(tmp_path)
    result = execute_task(task)
    assert result["status"] == "needs_dependencies"
    assert len(result["dependency_requests"]) == 1
    child = result["dependency_requests"][0]
    assert child["kind"] == "msd.calibrate"
    assert child["payload"]["placement"] == task["payload"]["placement"]
    assert len(child["payload"]["members"]) == 10
    assert not (tmp_path / "cache").exists()


def test_dependency_id_ignores_production_seed_but_retains_sampling(tmp_path):
    task = witness_task(tmp_path)
    members = ("raw_t_postselection:factory0/R",)
    first = calibration_dependency(task, members)
    other = deepcopy(task)
    other["payload"]["production_seed"] = 12
    assert calibration_dependency(other, members) == first
    other["payload"]["sampling"]["shots"] = 32
    assert calibration_dependency(other, members)["task_id"] != first["task_id"]


@pytest.mark.parametrize(
    "case_status,line_status,expected",
    [
        ("execution_failure", "complete", "software_error"),
        ("partial_failure", "protocol_failure", "software_error"),
        ("partial_failure", "expansion_budget_exhausted", "budget_exceeded"),
        ("partial_failure", "input_supply_exhausted", "ok"),
        ("partial_failure", "external_supply_exhausted", "ok"),
        ("partial_failure", "distillation_rejected", "ok"),
    ],
)
def test_worker_distinguishes_software_and_budget_failure_from_physical_rejection(
    tmp_path, monkeypatch, case_status, line_status, expected
):
    import experiments.msd.campaign_worker as worker

    case = {
        "status": case_status,
        "failure": {"code": "invalid_finalization"}
        if case_status == "execution_failure"
        else None,
        "factories": {"factory0": {"status": line_status}},
    }
    monkeypatch.setattr(worker, "run_surface_factory", lambda *a, **k: {"case": case})
    result = execute_task(witness_task(tmp_path))
    assert result["status"] == expected
    assert result["result"]["case"] == case


def test_calibration_worker_declares_all_cache_artifacts_for_resume_validation(
    tmp_path, monkeypatch
):
    from nadit_physical_compiler.provenance import canonical_hash

    import experiments.msd.campaign_worker as worker
    from experiments.msd.joint_cache import JointCacheResult

    task = witness_task(tmp_path)
    task = calibration_dependency(task, ("raw_t_postselection:factory0/R",))
    paths = [tmp_path / f"{name}.json" for name in ("trace", "action", "probability")]
    for path in paths:
        path.write_text(json.dumps({"test_fixture": path.stem}), encoding="utf-8")
    trace_hash = canonical_hash({"test_fixture": "trace"})
    cached = JointCacheResult(
        {"trace_sha256": trace_hash},
        "action-key",
        "probability-key",
        True,
        True,
        *paths,
        {"cache_load": 0.0},
    )
    monkeypatch.setattr(
        worker.JointCalibrationCache, "get_or_create", lambda *a, **k: cached
    )
    result = execute_task(task)
    assert result["status"] == "ok"
    assert {row["path"] for row in result["artifacts"]} == {str(p) for p in paths}
    for row in result["artifacts"]:
        assert row["hash_kind"] == "canonical_json"
        assert row["sha256"] == canonical_hash(
            json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        )
    json.dumps(result, allow_nan=False)


def test_witness_completion_also_requires_its_cached_trace_and_records(
    tmp_path, monkeypatch
):
    from nadit_physical_compiler.provenance import canonical_hash

    import experiments.msd.campaign_worker as worker
    from experiments.msd.joint_cache import JointCacheResult

    paths = [tmp_path / f"{name}.json" for name in ("trace", "action", "probability")]
    for path in paths:
        path.write_text(json.dumps({"test_fixture": path.stem}), encoding="utf-8")

    def lookup(cache, world, members, **kwargs):
        group = {
            "family": kwargs["family"],
            "validation_ok": True,
            "trace_sha256": canonical_hash({"test_fixture": "trace"}),
            "phase_durations_us": [1.0],
            "peak_rows": 1,
            "peak_columns": 1,
            "peak_readout_atoms": 1,
            "members": {
                member: {"measurement_phases": [], "cost_segments": []}
                for member in members
            },
        }
        return JointCacheResult(group, "action", "probability", True, True, *paths, {})

    def run(profile, **kwargs):
        profile.group(("logical_mx:factory0/W2",))
        return {
            "case": {
                "status": "complete",
                "failure": None,
                "factories": {"factory0": {"status": "complete"}},
            }
        }

    monkeypatch.setattr(worker.JointCalibrationCache, "lookup", lookup)
    monkeypatch.setattr(worker, "run_surface_factory", run)
    result = execute_task(witness_task(tmp_path))
    assert result["status"] == "ok"
    assert {item["path"] for item in result["artifacts"]} == {
        str(path) for path in paths
    }


def continuous_task(tmp_path, kind="msd.pilot"):
    from nadit_physical_compiler.provenance import canonical_hash

    task = witness_task(tmp_path)
    task["kind"] = kind
    task["payload"].update(
        output_sink={"kind": "ideal_external", "acknowledge_excluded_costs": True},
        pilot_cycles=2,
        trajectory_id="trajectory-fixture",
        layout_id="layout-fixture",
        seed=0,
        config_sha256="config-fixture",
        source_sha256="source-fixture",
        observation_policy={"warmup_us": 10, "stop_us": 50},
    )
    task["payload"]["limits"].update(max_cycles=20, max_component_calls=400)
    envelope = {
        "schema": "nadit.msd.frozen_observation_policy/1",
        "identity": {
            key: task["payload"][key]
            for key in ("layout_id", "config_sha256", "source_sha256")
        },
        "policy": task["payload"]["observation_policy"],
        "policy_sha256": canonical_hash(task["payload"]["observation_policy"]),
    }
    path = tmp_path / "frozen-policy.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    task["payload"]["observation_policy_artifact"] = {
        "path": str(path),
        "sha256": canonical_hash(envelope),
        "hash_kind": "canonical_json",
    }
    return task


def two_level_task(tmp_path, kind):
    task = continuous_task(tmp_path, kind)
    task["payload"]["production_seed"] = task["payload"]["seed"] = 17
    task["payload"]["two_level"] = {
        "level1_count": 1,
        "level2_count": 1,
        "buffer_capacity": 2,
        "producer_max_cycles": 60,
        "consumer_max_cycles": 20,
        "level1_batches": 2,
        "level2_batches": 3,
        "parking_origin": {"x": 0, "y": -1000},
        "output_sink": task["payload"].pop("output_sink"),
        "acknowledge_theory_transport_exclusions": True,
    }
    task["payload"]["observation_policy"]["output_factory_ids"] = ["factory1"]
    save_policy_artifact(task)
    return task


def save_policy_artifact(task):
    """Persist a valid hash envelope after an explicit test-policy edit."""
    from nadit_physical_compiler.provenance import canonical_hash

    payload = task["payload"]
    descriptor = payload["observation_policy_artifact"]
    path = Path(descriptor["path"])
    envelope = json.loads(path.read_text())
    envelope["policy"] = deepcopy(payload["observation_policy"])
    envelope["policy_sha256"] = canonical_hash(envelope["policy"])
    path.write_text(json.dumps(envelope), encoding="utf-8")
    descriptor["sha256"] = canonical_hash(envelope)


@pytest.mark.parametrize(
    "kind", ("msd.two_level_witness", "msd.two_level_pilot", "msd.two_level_produce")
)
def test_two_level_continuous_policy_preserves_l1_supply_and_l2_window(
    tmp_path, monkeypatch, kind
):
    from types import SimpleNamespace

    from nadit_physical_compiler.provenance import canonical_hash

    import experiments.msd.joint_cache as cache
    from experiments.msd import two_level

    task = two_level_task(tmp_path, kind)
    original = deepcopy(task)
    observed, windows = [], []
    case = {
        "status": "complete",
        "failure": None,
        "duration_us": 80,
        "factories": {f"factory{i}": {"status": "complete"} for i in range(2)},
    }

    class StubRuntime(two_level.CooperativeFactoryRuntime):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            observed.append(kwargs)

        def run(self):
            for process in observed[0]["processes"]:
                process.status = "complete"
            self.execution._clock_us = 80
            return SimpleNamespace(to_dict=lambda: case)

    monkeypatch.setattr(two_level, "CooperativeFactoryRuntime", StubRuntime)
    monkeypatch.setattr(
        two_level,
        "summarize_production",
        lambda *a, **k: windows.append(k) or {"test_fixture": True},
    )
    monkeypatch.setattr(
        cache, "compile_joint_actions", lambda *a, **k: pytest.fail("compiled")
    )
    monkeypatch.setattr(
        cache, "evaluate_joint_probabilities", lambda *a, **k: pytest.fail("sampled")
    )
    reply = execute_task(task)
    assert reply["status"] == "ok"
    producer, consumer = observed[0]["processes"]
    assert observed[0]["seed"] == 17
    assert producer.production_policy.max_cycles == 60
    assert producer.production_policy.stop_at_us is None
    assert callable(producer.production_continuation)
    assert consumer.production_continuation is None
    assert consumer.external_inputs and callable(consumer.preparation_supplier)
    assert producer.limits.batches == 2 and consumer.limits.batches == 3
    assert (
        producer.limits.max_component_calls
        == consumer.limits.max_component_calls
        == 400
    )
    assert producer.parameters == {
        "noise_model": "noise/v1",
        "noise_params": task["payload"]["noise_params"],
        "input_z_error": task["payload"]["input_z_error"],
    }
    assert (
        consumer.parameters["input_z_error"]
        == reply["result"]["models"]["level1"]["conditional_output_z_error"]
    )
    expected_cycles = 2 if kind == "msd.two_level_pilot" else 20
    assert consumer.production_policy.max_cycles == expected_cycles
    if kind == "msd.two_level_produce":
        assert consumer.production_policy.stop_at_us == 50
        assert windows == [
            {"warmup_us": 10, "stop_us": 50, "output_factory_ids": {"factory1"}}
        ]
        assert task["payload"]["observation_policy_artifact"] in reply["artifacts"]
        assert reply["result"]["observation_policy_sha256"] == canonical_hash(
            task["payload"]["observation_policy"]
        )
    else:
        assert consumer.production_policy.stop_at_us is None
        assert windows == [
            {"warmup_us": 0.0, "stop_us": 80, "output_factory_ids": {"factory1"}}
        ]
    result = reply["result"]
    assert result["entry_world"]["placement"] == task["payload"]["placement"]
    if kind != "msd.two_level_witness":
        for name in (
            "trajectory_id",
            "layout_id",
            "seed",
            "config_sha256",
            "source_sha256",
        ):
            assert result[name] == task["payload"][name]
        assert result["case_sha256"] == canonical_hash(case)
        assert result["output_sink"] == task["payload"]["two_level"]["output_sink"]
        assert result["two_level"] == task["payload"]["two_level"]
        assert result["software_times_seconds"] == result["software_seconds"]
    assert task == original


def test_two_level_policy_drift_is_rejected_before_world_or_cache(
    tmp_path, monkeypatch
):
    import experiments.msd.campaign_worker as worker

    task = two_level_task(tmp_path, "msd.two_level_produce")
    path = Path(task["payload"]["observation_policy_artifact"]["path"])
    envelope = json.loads(path.read_text())
    envelope["policy"]["stop_us"] += 1
    path.write_text(json.dumps(envelope), encoding="utf-8")
    monkeypatch.setattr(
        worker,
        "_context",
        lambda *a: pytest.fail("built world before policy validation"),
    )
    with pytest.raises(ValueError, match="POLICY_ARTIFACT_MISMATCH"):
        execute_task(task)


@pytest.mark.parametrize("selector", (None, [], ["factory0"], ["factory1", "factory1"]))
def test_two_level_production_rejects_validly_hashed_wrong_output_scope(
    tmp_path, monkeypatch, selector
):
    import experiments.msd.campaign_worker as worker

    task = two_level_task(tmp_path, "msd.two_level_produce")
    window = task["payload"]["observation_policy"]
    if selector is None:
        del window["output_factory_ids"]
    else:
        window["output_factory_ids"] = selector
    save_policy_artifact(task)
    assert worker._policy_artifacts({**task, "kind": "msd.produce"}) == [
        task["payload"]["observation_policy_artifact"]
    ]
    monkeypatch.setattr(
        worker, "_context", lambda *a: pytest.fail("built world for wrong output scope")
    )
    with pytest.raises(
        ValueError, match="TWO_LEVEL_OBSERVATION_FACTORY_SELECTION_MISMATCH"
    ):
        execute_task(task)


@pytest.mark.parametrize("kind", ("msd.two_level_pilot", "msd.two_level_produce"))
def test_two_level_continuous_missing_calibration_keeps_full_world_frontier(
    tmp_path, monkeypatch, kind
):
    import experiments.msd.joint_cache as cache

    monkeypatch.setattr(
        cache, "compile_joint_actions", lambda *a, **k: pytest.fail("implicit compile")
    )
    monkeypatch.setattr(
        cache,
        "evaluate_joint_probabilities",
        lambda *a, **k: pytest.fail("implicit sampling"),
    )
    task = two_level_task(tmp_path, kind)
    result = execute_task(task)
    assert result["status"] == "needs_dependencies"
    child = result["dependency_requests"][0]
    # L2 receives its four raw inputs from supply; it must never inject them.
    assert set(child["payload"]["members"]) == {
        "initialize_plus:factory0/W1",
        "initialize_plus:factory1/W1",
        *(f"raw_t_postselection:factory0/W{role}" for role in range(2, 6)),
    }
    assert child["payload"]["placement"] == task["payload"]["placement"]
    snapshot = child["payload"]["world_snapshot"]
    assert len(snapshot["entry_state"]["atoms"]) == 204
    assert len(snapshot["device"]["aods"]) == 1
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("change", ("conflicting_budget", "pilot_over_budget"))
def test_two_level_consumer_cycle_budgets_are_checked_before_runtime(
    tmp_path, monkeypatch, change
):
    import experiments.msd.campaign_worker as worker

    task = two_level_task(tmp_path, "msd.two_level_pilot")
    if change == "conflicting_budget":
        task["payload"]["limits"]["max_cycles"] = 21
    else:
        task["payload"]["pilot_cycles"] = 21
    monkeypatch.setattr(
        worker, "_context", lambda *a: pytest.fail("created runtime for invalid budget")
    )
    with pytest.raises(ValueError, match="CONSUMER_CYCLE_BUDGET"):
        execute_task(task)


@pytest.mark.parametrize("kind", ("msd.pilot", "msd.produce"))
def test_continuous_worker_missing_calibration_keeps_complete_frontier(
    tmp_path, monkeypatch, kind
):
    import experiments.msd.joint_cache as cache

    monkeypatch.setattr(
        cache, "compile_joint_actions", lambda *a, **k: pytest.fail("implicit compile")
    )
    task = continuous_task(tmp_path, kind)
    result = execute_task(task)
    assert result["status"] == "needs_dependencies"
    child = result["dependency_requests"][0]
    assert len(child["payload"]["members"]) == 10
    assert child["payload"]["placement"] == task["payload"]["placement"]
    assert "output_sink" not in child["payload"]
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("kind", ("msd.pilot", "msd.produce"))
def test_continuous_worker_connects_policy_and_metrics_without_changing_window(
    tmp_path, monkeypatch, kind
):
    from nadit_physical_compiler.provenance import canonical_hash

    import experiments.msd.campaign_worker as worker

    case = {
        "status": "complete",
        "failure": None,
        "duration_us": 80,
        "factories": {"factory0": {"status": "complete"}},
    }
    calls, windows = [], []
    monkeypatch.setattr(
        worker, "run_surface_factory", lambda *a, **k: calls.append(k) or {"case": case}
    )
    monkeypatch.setattr(
        worker,
        "summarize_production",
        lambda *a, **k: windows.append(k) or {"test_fixture": True},
    )
    task = continuous_task(tmp_path, kind)
    reply = execute_task(task)
    assert reply["status"] == "ok"
    result = reply["result"]
    assert calls[0]["max_component_calls"] == 400
    assert calls[0]["placement_plan"].to_dict() == task["payload"]["placement"]
    policy = calls[0]["production_policy"]
    if kind == "msd.pilot":
        assert (policy.max_cycles, policy.stop_at_us) == (2, None)
        assert windows == [{"warmup_us": 0.0, "stop_us": 80}]
    else:
        assert (policy.max_cycles, policy.stop_at_us) == (20, 50)
        assert windows == [{"warmup_us": 10, "stop_us": 50}]
        assert result["trajectory_id"] == "trajectory-fixture"
        assert result["observation_policy_sha256"] == canonical_hash(
            task["payload"]["observation_policy"]
        )
    assert result["case_sha256"] == canonical_hash(case)
    assert result["output_sink"] == task["payload"]["output_sink"]
    assert set(result["software_times_seconds"]) >= {
        "cache_load",
        "fast_execution",
        "validation",
    }
    assert "cold_calibration" not in result["software_times_seconds"]
    if kind == "msd.produce":
        assert task["payload"]["observation_policy_artifact"] in reply["artifacts"]


def test_production_requires_explicit_acknowledged_sink_before_execution(
    tmp_path, monkeypatch
):
    import experiments.msd.campaign_worker as worker

    monkeypatch.setattr(
        worker,
        "run_surface_factory",
        lambda *a, **k: pytest.fail("unexpected execution"),
    )
    task = continuous_task(tmp_path)
    task["payload"]["output_sink"]["acknowledge_excluded_costs"] = False
    with pytest.raises(ValueError):
        execute_task(task)


def test_metric_failure_preserves_case_and_cannot_publish_success(
    tmp_path, monkeypatch
):
    import experiments.msd.campaign_worker as worker

    case = {"status": "complete", "duration_us": 30, "factories": {}}
    monkeypatch.setattr(worker, "run_surface_factory", lambda *a, **k: {"case": case})

    def mismatch(*a, **k):
        raise ValueError("PRODUCTION_TRACE_HASH_MISMATCH")

    monkeypatch.setattr(worker, "summarize_production", mismatch)
    reply = execute_task(continuous_task(tmp_path))
    assert reply["status"] == "software_error"
    assert reply["result"]["case"] == case
    assert "PRODUCTION_TRACE_HASH_MISMATCH" in reply["reason"]


def test_changed_policy_artifact_cannot_start_production(tmp_path, monkeypatch):
    import experiments.msd.campaign_worker as worker

    task = continuous_task(tmp_path, "msd.produce")
    path = Path(task["payload"]["observation_policy_artifact"]["path"])
    envelope = json.loads(path.read_text())
    envelope["policy"]["stop_us"] += 1
    path.write_text(json.dumps(envelope), encoding="utf-8")
    monkeypatch.setattr(
        worker,
        "run_surface_factory",
        lambda *a, **k: pytest.fail("unexpected production"),
    )
    with pytest.raises(ValueError, match="POLICY_ARTIFACT_MISMATCH"):
        execute_task(task)
