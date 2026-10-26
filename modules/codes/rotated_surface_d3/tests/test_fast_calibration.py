"""Offline calibration requires stable, intact, physically checked sources."""

import hashlib
import json
from math import log
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.activity import (
    ActivityEvent,
    AtomActivity,
    Interval,
    derive_activity,
)
from nadit_physical_compiler.cost.noise.config import resolve

from modules.codes.rotated_surface_d3.protocols.fast_calibration import (
    _calibration_ports,
    _event_owner,
    _extract_calls,
    _factory_variants,
    _require_factory_coverage,
    _source,
    calibrate_fast_profile,
)


@pytest.mark.parametrize("failure", ("unstable", "hash", "unvalidated", "projection"))
def test_calibration_rejects_unusable_source_before_replaying(tmp_path, failure):
    source = {
        "physical": {
            "validation": {"ok": failure != "unvalidated"},
            "parallel_batches": [{}] if failure == "projection" else [],
        },
        "component_schedule": {"policy": {"batching": "maximal_compatible_frontier"}},
    }
    raw = json.dumps(source).encode()
    (tmp_path / "case.json").write_bytes(raw)
    manifest = {
        "source_stable": failure != "unstable",
        "execution_completed": True,
        "files_sha256": {"case.json": hashlib.sha256(raw).hexdigest()},
    }
    if failure == "hash":
        manifest["files_sha256"]["case.json"] = "0" * 64
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="CALIBRATION"):
        calibrate_fast_profile(tmp_path, tmp_path / "profile.json")
    assert not (tmp_path / "profile.json").exists()


def test_source_free_transport_is_owned_by_unambiguous_call_window():
    event = ActivityEvent("Move", 1, 2, (10,), ((0, 0),), ((1, 0),))
    calls = {
        "first": {"start_us": 0, "end_us": 3},
        "second": {"start_us": 3, "end_us": 6},
    }
    assert _event_owner(event, {}, calls) == "first"
    later = ActivityEvent("Store", 3, 2, (10,), ((1, 0),), ((1, 0),))
    assert _event_owner(later, {}, calls) == "second"


def batched_source():
    """Two physical member projections share one transport action and clock."""
    bindings = [
        {
            "block_id": f"factory0/W{i}",
            "origin": {"x": 100 * i, "y": 0},
            "atom_ids": [i],
        }
        for i in range(2)
    ]
    calls, nodes, parts, invocations, members = [], [], [], [], []
    for i, binding in enumerate(bindings):
        identity = f"member{i}"
        spec = {
            "participant_blocks": [binding["block_id"]],
            "waveform_key": "se/v1",
            "parallel_mode": "shared_aod_lockstep",
            "result_count": 1,
            "shared_aod": None,
            "spaces": [],
        }
        calls.append(
            {
                "invocation_id": identity,
                "component_id": "se_round",
                "part_invocations": [identity],
                "start_us": 3,
                "end_us": 6,
            }
        )
        nodes.append({"id": identity, "spec": spec})
        parts.append(
            {
                "invocation_id": identity,
                "native_operation_base": 40 + i,
                "native_operation_count": 1,
                "template_content_sha256": "same-template",
            }
        )
        invocations.append(
            {"invocation_id": identity, "result_id_base": i, "result_count": 1}
        )
        members.append(
            {
                "invocation_id": identity,
                "participant_atoms": [i],
                "execution_spec": spec,
                "steps": [
                    {
                        "batch_step_index": 0,
                        "part_invocation_id": identity,
                        "local_step_index": 0,
                        "start_us": 3,
                        "end_us": 5,
                        "batch_action_indices": [0],
                        "action_embeddings": [
                            {
                                "source_action_index": 0,
                                "batch_action_index": 0,
                                "component_source_ids": [],
                            }
                        ],
                    },
                    {
                        "batch_step_index": 1,
                        "part_invocation_id": identity,
                        "local_step_index": 1,
                        "start_us": 5,
                        "end_us": 6,
                        "batch_action_indices": [i],
                        "action_embeddings": [
                            {
                                "source_action_index": 0,
                                "batch_action_index": i,
                                "component_source_ids": [i],
                            }
                        ],
                    },
                ],
            }
        )
    events = (
        ActivityEvent("Wait", 0, 3, (), (), (), step_index=0, action_index=0),
        ActivityEvent(
            "Move",
            3,
            2,
            (0, 1),
            ((0, 0), (100, 0)),
            ((1, 0), (101, 0)),
            step_index=1,
            action_index=0,
        ),
        *(
            ActivityEvent(
                "Measure",
                5,
                1,
                (i,),
                ((100 * i + 1, 0),),
                ((100 * i + 1, 0),),
                step_index=2,
                action_index=i,
                source_ids=(40 + i,),
                measurement_ids=(i,),
            )
            for i in range(2)
        ),
    )
    activity = AtomActivity(
        6,
        tuple(
            SimpleNamespace(
                atom_id=i,
                busy=(
                    Interval(3, 5, "Move", "aod", ()),
                    Interval(5, 6, "Measure", "aod", ()),
                ),
            )
            for i in range(2)
        ),
        events,
    )
    case = {
        "calls": calls,
        "component_schedule": {"nodes": nodes},
        "physical": {
            "parts": parts,
            "bindings": bindings,
            "invocations": invocations,
            "device": {"readout": {"latency_us": 4}},
            "program": {
                "steps": [
                    {"actions": [{"duration_us": 3}]},
                    {"actions": [{"duration_us": 2}]},
                    {"actions": [{"duration_us": 1}, {"duration_us": 1}]},
                ]
            },
            "parallel_batches": [
                {
                    "batch_id": "wave",
                    "start_us": 3,
                    "action_end_us": 6,
                    "global_operation_base": 40,
                    "participant_trajectory_projection_verified": True,
                    "validation": {"ok": True},
                    "members": members,
                }
            ],
        },
    }
    return case, activity


def test_fused_transport_calibrates_each_member_once_with_its_own_measurement():
    case, activity = batched_source()
    entries, evidence = _extract_calls(
        case, activity, resolve({"transport": {"move_loss": 0.1}, "readout_flip": 0.2})
    )
    item = entries["se_round"]
    assert item["primitive_counts"]["targets_Move"] == 1
    assert item["primitive_counts"]["targets_Measure"] == 1
    assert item["phase_durations_us"] == [2, 1]
    assert item["result_ready_offsets_us"] == [7]
    assert [event["log_survival"] for event in item["events"]] == pytest.approx(
        [log(0.9), log(0.8)]
    )
    assert evidence["se_round"]["source_invocations"] == ["member0", "member1"]
    assert {row[0] for row in item["busy"]} == {0}


def test_validated_array_manifest_accepts_batched_reference(tmp_path):
    case, _ = batched_source()
    case["physical"]["validation"] = {"ok": True}
    raw = json.dumps(case).encode()
    (tmp_path / "case.json").write_bytes(raw)
    manifest = {
        "schema": "nadit.factory_array_manifest/1",
        "source_stable": True,
        "execution_completed": True,
        "files_sha256": {"case.json": hashlib.sha256(raw).hexdigest()},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    loaded, provenance = _source(tmp_path)
    assert loaded == case
    assert provenance == manifest


def event_source(*quality_values):
    from modules.codes.rotated_surface_d3.probabilities.preparation import (
        preparation_port,
    )
    from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
        FactoryExperimentModel,
    )

    ports = [
        preparation_port(name) for name in ("initialize_plus", "raw_t_postselection")
    ]
    model = FactoryExperimentModel(input_z_error=0.01)
    ports.extend(model.consumption_event({"input_z_error": p}) for p in quality_values)
    return {
        "probability_models": {port.content_sha256: port.to_dict() for port in ports}
    }


def test_theory_array_ports_keep_joint_models_and_do_not_fabricate_proxy_routing():
    case = event_source(0.01, 0.0001)
    result = _calibration_ports(case)
    assert set(result["preparation_ports"]) == {
        "initialize_plus",
        "raw_t_postselection",
    }
    assert result["consumption_port"] == {}
    original = {
        key: port
        for key, port in case["probability_models"].items()
        if port["port_id"] == "rotated_surface_d3.t_injection.logical_z"
    }
    assert len(original) == 2
    assert result["theory_consumption_ports"] == original
    assert {
        port["model"]["parameters"]["input_z_error"] for port in original.values()
    } == {0.01, 0.0001}


def test_explicit_proxy_port_is_separate_from_theory_evidence():
    from modules.codes.rotated_surface_d3.protocols.cost_proxy import (
        ROUTING_REFERENCE,
        _routing_port,
    )

    case = event_source(0.01)
    proxy = _routing_port(
        {
            "routing_reference": ROUTING_REFERENCE,
            "actual_quality_status": "unsupported",
            "actual_quality_source_port_sha256": "1" * 64,
        }
    )
    case["probability_models"][proxy.content_sha256] = proxy.to_dict()
    result = _calibration_ports(case)
    assert result["consumption_port"]["port_id"] == proxy.port_id
    assert result["consumption_port"]["outcomes"] == proxy.to_dict()["outcomes"]
    assert len(result["theory_consumption_ports"]) == 1


@pytest.mark.parametrize(
    "missing", ["initialize_plus", "raw_t_postselection", "T consumption"]
)
def test_missing_calibration_events_report_explicit_coverage_error(missing):
    case = event_source() if missing == "T consumption" else event_source(0.01)
    case["probability_models"] = {
        key: port
        for key, port in case["probability_models"].items()
        if port["port_id"] != f"rotated_surface_d3.{missing}.canonical_preparation"
    }
    with pytest.raises(ValueError, match="INCOMPLETE_CALIBRATION_EVENTS"):
        _calibration_ports(case)


@pytest.mark.parametrize(
    "missing",
    [
        ("logical_s", ()),
        ("logical_x", ()),
        ("transversal_cnot", (-100.0, 0.0)),
        ("transversal_cnot", (500.0, 0.0)),
    ],
)
def test_factory_coverage_includes_unsampled_branches_and_signed_geometries(missing):
    variants = _factory_variants()
    assert missing in variants
    entries = {
        str(index): {"component_id": component, "geometry": list(geometry)}
        for index, (component, geometry) in enumerate(variants)
    }
    _require_factory_coverage(entries)
    incomplete = {
        key: item
        for key, item in entries.items()
        if (item["component_id"], tuple(item["geometry"])) != missing
    }
    with pytest.raises(ValueError, match="INCOMPLETE_FACTORY_CALIBRATION"):
        _require_factory_coverage(incomplete)


def test_incomplete_source_fails_before_correction_compilation_or_profile_write(
    monkeypatch, tmp_path
):
    from modules.codes.rotated_surface_d3.protocols import (
        fast_calibration as calibration,
    )
    from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
        FactoryExperimentModel,
    )
    from modules.codes.rotated_surface_d3.tests.test_fast_round_policy import (
        calibration_case,
    )

    case = calibration_case()
    case["physical"]["pending_measurements"] = []
    model = FactoryExperimentModel("theory", 0.01)
    case["probability_models"]["consumption"] = model.consumption_event(
        {"input_z_error": 0.01}
    ).to_dict()
    monkeypatch.setattr(
        calibration,
        "_source",
        lambda _: (
            case,
            {"noise_parameters": {}, "experiment_model": model.to_dict()},
        ),
    )
    monkeypatch.setattr(
        calibration, "_check_sources", lambda _: {"source": "fingerprint"}
    )
    monkeypatch.setattr(calibration, "derive_activity", lambda _: None)
    monkeypatch.setattr(calibration, "_extract_calls", lambda *args: ({}, {}))

    def unexpected_corrections(*args):
        raise AssertionError("Coverage must be checked before physical supplementation")

    monkeypatch.setattr(calibration, "_corrections", unexpected_corrections)
    with pytest.raises(ValueError, match="INCOMPLETE_FACTORY_CALIBRATION"):
        calibrate_fast_profile(tmp_path, tmp_path / "profile.json")
    assert not (tmp_path / "profile.json").exists()


@pytest.mark.parametrize(
    "tamper", ("atoms", "missing_step", "wrong_source", "duplicate_action")
)
def test_calibration_rejects_inconsistent_batch_member_projection(tamper):
    case, activity = batched_source()
    member = case["physical"]["parallel_batches"][0]["members"][0]
    if tamper == "atoms":
        member["participant_atoms"] = [1]
    elif tamper == "missing_step":
        member["steps"].pop()
    elif tamper == "wrong_source":
        member["steps"][1]["action_embeddings"][0]["component_source_ids"] = [1]
    else:
        member["steps"][0]["action_embeddings"].append(
            member["steps"][0]["action_embeddings"][0]
        )
    with pytest.raises(ValueError, match="CALIBRATION"):
        _extract_calls(case, activity, resolve({}))


@pytest.mark.slow
def test_real_shared_aod_component_wave_calibrates_without_a_serial_reference():
    from nadit_physical_compiler.atom_ir import Measure, Move

    from modules.codes.rotated_surface_d3.protocols.factory_backend import (
        SurfaceFactoryBackend,
    )
    from modules.codes.rotated_surface_d3.protocols.factory_world import (
        make_factory_world,
    )
    from modules.logical_compiler.src.protocols.parallel_physical import (
        PhysicalBatchRequest,
    )
    from modules.logical_compiler.src.protocols.physical import PhysicalContext
    from modules.logical_compiler.src.scheduling import (
        ComponentNode,
        ComponentScheduler,
    )

    world = make_factory_world()
    backend = SurfaceFactoryBackend(world.device)
    physical = PhysicalContext(world.device, world.world_state, world.bindings.values())
    scheduler = ComponentScheduler()
    bindings = (world.bindings["W2"], world.bindings["W3"])
    scheduler.add(
        *(
            ComponentNode(
                f"member{i}", backend.describe_execution("se_round", (binding,))
            )
            for i, binding in enumerate(bindings)
        )
    )
    physical.wait_until(7, reason="reference_entry_wait")
    admission = scheduler.admit(7, snapshot_id=physical.snapshot_id)
    assert admission is not None and len(admission.nodes) == 2
    requests = tuple(
        PhysicalBatchRequest(
            node.id, backend.bind_call("se_round", (binding,)), node.spec.result_count
        )
        for node, binding in zip(admission.nodes, bindings, strict=True)
    )
    batch = physical.invoke_batch(admission, requests)
    bundle = physical.finalize().to_dict()
    assert bundle["validation"]["ok"] is True
    case = {
        "component_schedule": scheduler.snapshot(),
        "physical": bundle,
        "calls": [
            {
                "invocation_id": invocation.invocation_id,
                "part_invocations": invocation.part_invocations,
                "component_id": "se_round",
                "start_us": invocation.start_us,
                "end_us": invocation.action_end_us,
            }
            for invocation in batch.invocations
        ],
    }
    activity = derive_activity(
        {**bundle, "measurements": bundle["pending_measurements"]}
    )
    entries, evidence = _extract_calls(
        case, activity, resolve({"transport": {"move_loss": 0.1}, "readout_flip": 0.2})
    )
    item = entries["se_round"]
    parts = batch.member_parts[0][1]
    actions = [
        action
        for part in parts
        for step in part.program.steps
        for action in step.actions
    ]
    moves = sum(len(action.targets) for action in actions if isinstance(action, Move))
    measured = sum(
        len(action.results) for action in actions if isinstance(action, Measure)
    )
    assert item["primitive_counts"]["targets_Move"] == moves
    assert item["primitive_counts"]["targets_Measure"] == measured
    assert sum(event["log_survival"] for event in item["events"]) == pytest.approx(
        moves * log(0.9) + measured * log(0.8)
    )
    assert item["phase_durations_us"] == [
        step.duration_us for part in parts for step in part.program.steps
    ]
    assert item["result_ready_offsets_us"] == pytest.approx(
        [
            measurement.available_at_us - 7
            for part in parts
            for measurement in part.measurements
        ]
    )
    assert evidence["se_round"]["source_invocations"] == ["member0", "member1"]
