"""Participant scopes retain actual global waiting and physical channel ownership."""

import json
from dataclasses import replace
from math import exp

import pytest
from nadit_physical_compiler.activity import ActivityEvent, AtomActivity
from nadit_physical_compiler.provenance import canonical_hash

from modules.logical_compiler.src.protocols.cost import evaluate_physical_cost_intervals
from modules.logical_compiler.src.protocols.participant_cost import (
    _participant_activity,
    evaluate_participant_cost,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.tests.test_protocol_cost import bundle as bundle  # noqa: PLC0414
from modules.logical_compiler.tests.test_protocol_physical import _part
from modules.logical_compiler.tests.test_protocol_physical import (
    setup_world as setup_world,  # noqa: PLC0414
)


def cost(bundle, ids, *, intervals=((0, 10),), params=None, owner="line0"):
    return evaluate_participant_cost(
        bundle,
        {} if params is None else params,
        participant_atom_ids=ids,
        include_intervals=intervals,
        owner_id=owner,
    )


def test_only_selected_actual_gate_targets_and_readout_results_are_charged(bundle):
    params = {"single": {"probabilities": [0.1, 0, 0]}, "readout_flip": 0.25}
    a = cost(bundle, [11], params=params)
    b = cost(bundle, [7], params=params, owner="line1")
    assert a["metrics"]["no_fault_probability"] == pytest.approx(0.9**2)
    assert b["metrics"]["no_fault_probability"] == pytest.approx(0.75)
    assert a["interval_selection"]["selected_event_indices"] == [0, 2]
    assert b["interval_selection"]["selected_event_indices"] == [1]
    assert (
        b["noise"]["channels"][0]["measurement_id"]
        == bundle.pending_measurements[0].result.measurement_id
    )
    assert a["participant_selection"]["atom_ids"] == [11]
    assert a["participant_selection"]["atom_ids_sha256"] == canonical_hash(
        {"atom_ids": [11]}
    )
    assert a["participant_selection"]["owner_id"] == "line0"
    assert a["source_bundle_sha256"] == b["source_bundle_sha256"]
    assert (
        a["interval_selection"]["selected_activity_sha256"]
        != b["interval_selection"]["selected_activity_sha256"]
    )
    assert a["logical_success"] is None and a["physical_execution"] is False
    assert all(m.value is None for m in bundle.pending_measurements)
    assert json.loads(json.dumps(a)) == a


def test_foreign_readout_does_not_block_own_idle_interval_clipping(bundle):
    report = cost(
        bundle, [11], intervals=[(3, 4)], params={"exposure": {"slm_t2_us": 10}}
    )
    assert report["metrics"]["no_fault_probability"] == pytest.approx(
        (1 + exp(-0.1)) / 2
    )
    assert report["interval_selection"]["selected_event_indices"] == []
    with pytest.raises(ValueError, match="CROSSES_ACTION"):
        cost(bundle, [7], intervals=[(3, 4)])


def test_waiting_for_peer_keeps_own_storage_noise_and_only_own_exclusions(setup_world):
    device, world, (a, b) = setup_world
    context = PhysicalContext(device, world, (a, b))
    context.invoke(lambda c: _part(c, a, "rotation"), "line0/raw", 0)
    context.invoke(lambda c: _part(c, b, "rotation"), "line1/retry", 0)
    context.wait_until(12, reason="waiting_peers")
    bundle = context.finalize()
    report = cost(
        bundle,
        [11],
        intervals=[(2, 12)],
        params={"transport": {"slm_loss_per_us": 0.1}},
    )
    # Excluding this line's [0,2] raw horizon does not exclude peer [2,4].
    assert report["metrics"]["no_fault_probability"] == pytest.approx(exp(-1))
    assert report["interval_selection"]["source_horizon_us"] == 12
    assert report["interval_selection"]["selected_duration_us"] == 10
    assert (
        report["participant_selection"]["other_participant_waiting_excluded"] is False
    )


def test_all_atoms_scope_equals_existing_global_interval_metrics(bundle):
    params = {
        "single": {"probabilities": [0.1, 0, 0]},
        "readout_flip": 0.1,
        "transport": {"slm_loss_per_us": 0.01},
        "exposure": {"slm_t2_us": 10},
    }
    global_report = evaluate_physical_cost_intervals(
        bundle, params, include_intervals=[(0, 10)]
    )
    selected = cost(bundle, [99, 11, 7], params=params)
    assert selected["metrics"] == global_report["metrics"]
    assert selected["noise"] == global_report["noise"]
    assert selected["interval_selection"] == global_report["interval_selection"]
    assert selected == cost(bundle, [7, 11, 99], params=params)


@pytest.mark.parametrize("ids", [[], [11, 11], [True], [999], [11.0]])
def test_invalid_participant_sets_fail(bundle, ids):
    with pytest.raises(ValueError, match="PARTICIPANT"):
        cost(bundle, ids)


def test_invalid_owner_and_unsupported_model_fail(bundle):
    with pytest.raises(ValueError, match="OWNER"):
        cost(bundle, [11], owner=" ")
    with pytest.raises(ValueError, match="NOISE_PROFILE"):
        cost(bundle, [11], params={"single": {"backend": "ideal"}})


def test_unobserved_validation_is_mandatory(bundle):
    document = bundle.to_dict()
    document["validation"]["ok"] = False
    with pytest.raises(ValueError, match="VALIDATED"):
        cost(replace(bundle, _snapshot_json=json.dumps(document)), [11])


def test_fixture_fused_action_projection_preserves_positions_results_and_source_ids():
    # Model-independent projection unit fixture; real public validation is covered above.
    events = (
        ActivityEvent(
            "Move",
            0,
            10,
            (7, 11),
            ((0, 0), (10, 0)),
            ((0, 5), (10, 8)),
            source_ids=(3, 4),
        ),
        ActivityEvent(
            "Measure",
            10,
            3,
            (7, 11),
            ((0, 5), (10, 8)),
            ((0, 5), (10, 8)),
            measurement_ids=(50, 80),
        ),
    )
    projected, indices = _participant_activity(
        AtomActivity(13, (), events), frozenset((11,))
    )
    assert indices == [0, 1]
    assert projected.events[0].atoms == (11,)
    assert projected.events[0].starts == ((10, 0),)
    assert projected.events[0].ends == ((10, 8),)
    assert projected.events[0].source_ids == (3, 4)
    assert projected.events[1].measurement_ids == (80,)


def test_fixture_cross_owner_cz_is_rejected_but_real_illumination_spectator_is_kept():
    event = ActivityEvent(
        "CZPulse",
        0,
        1,
        (7, 11, 99),
        ((0, 0), (2, 0), (10, 0)),
        ((0, 0), (2, 0), (10, 0)),
        pairs=((7, 11),),
        source_ids=(42,),
    )
    activity = AtomActivity(1, (), (event,))
    with pytest.raises(ValueError, match="CROSS_PARTICIPANT_CZ"):
        _participant_activity(activity, frozenset((11,)))
    spectator, _ = _participant_activity(activity, frozenset((99,)))
    assert spectator.events[0].atoms == (99,)
    assert spectator.events[0].pairs == ()
    assert spectator.events[0].source_ids == (42,)


@pytest.fixture(scope="module")
def real_shared_bundle():
    from modules.codes.rotated_surface_d3.protocols.factory_array import (
        make_factory_array,
    )
    from modules.codes.rotated_surface_d3.protocols.factory_backend import (
        SurfaceFactoryBackend,
    )
    from modules.logical_compiler.src.protocols.parallel_physical import (
        PhysicalBatchRequest,
    )
    from modules.logical_compiler.src.scheduling import (
        ComponentNode,
        ComponentScheduler,
    )

    array = make_factory_array()
    backend = SurfaceFactoryBackend(array.device)
    context = PhysicalContext(array.device, array.world_state, array.bindings.values())
    scheduler = ComponentScheduler(mode="parallel")
    bindings = tuple(factory.bindings["W1"] for factory in array.factories)
    scheduler.add(
        *(
            ComponentNode(f"{i}/se", backend.describe_execution("se_round", (binding,)))
            for i, binding in enumerate(bindings)
        )
    )
    admission = scheduler.admit(0, snapshot_id=context.snapshot_id)
    assert len(admission.nodes) == 2
    requests = tuple(
        PhysicalBatchRequest(
            node.id, backend.bind_call("se_round", (binding,)), node.spec.result_count
        )
        for node, binding in zip(admission.nodes, bindings, strict=True)
    )
    batch = context.invoke_batch(admission, requests)
    assert batch.action_end_us == pytest.approx(658.8174904678644)
    return array, context.finalize(), batch


def test_actual_fused_transport_readout_and_residence_factor_per_line(
    real_shared_bundle,
):
    array, bundle, batch = real_shared_bundle
    params = {
        "single": {"probabilities": [0.001, 0, 0]},
        "readout_flip": 0.01,
        "transport": {"load_loss": 0.002, "store_loss": 0.003, "slm_loss_per_us": 1e-6},
    }
    intervals = [(0, batch.results_ready_us)]
    whole = evaluate_physical_cost_intervals(
        bundle, params, include_intervals=intervals
    )
    reports = [
        cost(
            bundle,
            factory.atom_ids,
            intervals=intervals,
            params=params,
            owner=factory.factory_id,
        )
        for factory in array.factories
    ]
    assert reports[0]["metrics"]["no_fault_probability"] * reports[1]["metrics"][
        "no_fault_probability"
    ] == pytest.approx(whole["metrics"]["no_fault_probability"])
    for factory, report in zip(array.factories, reports, strict=True):
        assert report["participant_selection"]["source_atom_count"] == 204
        channels = report["noise"]["channels"]
        assert sum(c["instruction"] == "M" for c in channels) == 8
        assert all(set(c["atoms"]) <= set(factory.atom_ids) for c in channels)
        assert any(
            len(e["source_atom_ids"]) > len(e["selected_atom_ids"]) > 0
            for e in report["participant_selection"]["events"]
        )
        assert report["logical_success"] is None
    assert all(m.value is None for m in bundle.pending_measurements)


def test_actual_cross_boundary_cz_rejected_by_public_adapter(real_shared_bundle):
    array, bundle, batch = real_shared_bundle
    with pytest.raises(ValueError, match="CROSS_PARTICIPANT_CZ"):
        cost(
            bundle,
            [array.factory(0).bindings["W1"].atom_ids[0]],
            intervals=[(0, batch.results_ready_us)],
        )
