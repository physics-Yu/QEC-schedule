"""Real noise/v1 cost evaluation without inventing observed measurement bits."""

import json
from dataclasses import replace
from hashlib import sha256
from math import exp

import pytest
from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Load, Reset, Store
from nadit_physical_compiler.compiler import CompiledOperation
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.physical_ir import Condition
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import encode_dag, encode_program
from nadit_physical_compiler.state import AODGrid, AODLine

from modules.logical_compiler.src.protocols.cost import (
    evaluate_physical_cost,
    evaluate_physical_cost_intervals,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.tests.test_protocol_physical import _part
from modules.logical_compiler.tests.test_protocol_physical import (
    setup_world as setup_world,  # noqa: PLC0414
)


@pytest.fixture
def bundle(setup_world):
    device, world, (a, b) = setup_world
    context = PhysicalContext(device, world, (a, b))
    context.invoke(lambda invocation: _part(invocation, a, "rotation"), "first", 0)
    context.invoke(lambda invocation: _part(invocation, b), "readout", 1)
    context.invoke(lambda invocation: _part(invocation, a, "rotation"), "last", 0)
    return context.finalize()


def test_known_independent_gate_noise_product_and_scope(bundle):
    report = evaluate_physical_cost(
        bundle, {"single": {"backend": "pauli", "probabilities": [0.1, 0, 0]}}
    )
    assert report["model"] == "noise"
    assert report["metrics"]["no_fault_probability"] == pytest.approx(0.9**2)
    assert report["metrics"]["fidelity"] == pytest.approx((1 - 2 * 0.1 / 3) ** 2)
    assert report["metrics"]["fidelity_kind"] == "physical_error_product_proxy"
    assert report["scope"] == "selected_actions_unobserved_measurements"
    assert report["physical_execution"] is False
    assert report["measurement_evidence"] == "unobserved"
    assert report["logical_success"] is None
    assert len(report["noise"]["channels"]) == 2
    assert all(
        channel["instruction"] == "PAULI_CHANNEL_1"
        for channel in report["noise"]["channels"]
    )


def test_changed_noise_parameters_change_report_but_not_source(bundle):
    original = bundle.to_json()
    parameters = {"single": {"backend": "pauli", "probabilities": [0.1, 0, 0]}}
    first = evaluate_physical_cost(bundle, parameters)
    parameters["single"]["probabilities"][0] = 0.2
    second = evaluate_physical_cost(bundle, parameters)
    assert first["params_hash"] != second["params_hash"]
    assert first["source_bundle_sha256"] == second["source_bundle_sha256"]
    assert first["result_hash"] == second["result_hash"]
    assert second["metrics"]["no_fault_probability"] == pytest.approx(0.8**2)
    assert first["params"]["single"]["probabilities"] == [0.1, 0.0, 0.0]
    assert bundle.to_json() == original


def test_pending_results_remain_unobserved_and_structural_bits_are_not_exported(bundle):
    before = bundle.pending_measurements
    assert before and all(output.value is None for output in before)
    report = evaluate_physical_cost(bundle, {"readout_flip": 0.25})
    assert report["metrics"]["no_fault_probability"] == pytest.approx(0.75)
    channel = report["noise"]["channels"][0]
    assert channel["instruction"] == "M"
    assert channel["measurement_id"] == before[0].result.measurement_id
    assert channel["probabilities"] == [0.25]
    assert "measurements" not in report
    assert "value" not in channel
    assert report["structural_measurement_values_exported"] is False
    assert bundle.pending_measurements == before
    assert bundle.to_dict()["pending_measurements"][0]["value"] is None
    assert json.loads(json.dumps(report)) == report


def test_identical_inputs_produce_a_reproducible_report(bundle):
    params = {"readout_flip": 0.03, "exposure": {"slm_t2_us": 1000}}
    assert evaluate_physical_cost(bundle, params) == evaluate_physical_cost(
        bundle, params
    )


def test_cost_requires_explicit_parameter_mapping(bundle):
    with pytest.raises(TypeError):
        evaluate_physical_cost(bundle)
    with pytest.raises(ValueError, match="PARAMETERS"):
        evaluate_physical_cost(bundle, None)
    with pytest.raises(ValueError):
        evaluate_physical_cost(bundle, {"unsupported_assumption": 0.1})


def test_unvalidated_bundle_is_rejected(bundle):
    document = bundle.to_dict()
    document["validation"]["ok"] = False
    changed = replace(bundle, _snapshot_json=json.dumps(document))
    with pytest.raises(ValueError, match="VALIDATED"):
        evaluate_physical_cost(changed, {})


def test_actual_observed_values_are_rejected_instead_of_replaced_with_zero(bundle):
    changed = replace(
        bundle,
        pending_measurements=(replace(bundle.pending_measurements[0], value=1),),
    )
    with pytest.raises(ValueError, match="OBSERVED"):
        evaluate_physical_cost(changed, {})


def test_unresolved_physical_feedback_cannot_consume_structural_placeholder_bits(
    bundle,
):
    measurement = bundle.pending_measurements[0]
    nodes = (
        *bundle.dag.nodes[:-1],
        replace(bundle.dag.nodes[-1], condition=Condition(measurement.result, 0)),
    )
    changed = replace(bundle, dag=replace(bundle.dag, nodes=nodes))
    with pytest.raises(ValueError, match="CONDITION"):
        evaluate_physical_cost(changed, {})


def test_revalidation_rejects_invalid_physics_even_if_snapshot_claims_validity(bundle):
    first_step = bundle.program.steps[0]
    wrong_rotation = replace(first_step.actions[0], angle=0.0)
    changed_program = replace(
        bundle.program,
        steps=(
            replace(first_step, actions=(wrong_rotation,)),
            *bundle.program.steps[1:],
        ),
    )
    document = bundle.to_dict()
    document["program"] = encode_program(changed_program)
    assert document["validation"]["ok"] is True
    changed = replace(
        bundle, program=changed_program, _snapshot_json=json.dumps(document)
    )
    with pytest.raises(ValueError, match="VALIDATION"):
        evaluate_physical_cost(changed, {})


def test_bundle_records_must_match_their_validation_snapshot(bundle):
    document = bundle.to_dict()
    document["program"]["global_phase"] = 0.5
    changed = replace(bundle, _snapshot_json=json.dumps(document))
    with pytest.raises(ValueError, match="CONTENT_MISMATCH"):
        evaluate_physical_cost(changed, {})


def test_exported_qasm_is_real_readable_selected_dag_text_with_its_own_hash(bundle):
    report = evaluate_physical_cost(bundle, {})
    source = report["generated_qasm"]
    assert report["generated_from_selected_dag"] is True
    assert sha256(source.encode("utf-8")).hexdigest() == report["generated_qasm_sha256"]
    loaded = loads_qasm(source)
    assert (loaded.num_qubits, loaded.num_clbits) == (
        bundle.dag.num_qubits,
        bundle.dag.num_clbits,
    )
    assert [
        (node.name, node.qubits, node.clbits, node.params) for node in loaded.nodes
    ] == [
        (node.name, node.qubits, node.clbits, node.params) for node in bundle.dag.nodes
    ]
    assert report["generated_qasm_roundtrip_checked"] is True
    assert loaded.edges != bundle.dag.edges
    assert report["source_ids_and_extra_edges_in_generated_qasm"] is False


def test_generated_qasm_preserves_nonzero_global_phase(setup_world):
    device, world, (a, b) = setup_world
    context = PhysicalContext(device, world, (a, b))

    def phased(invocation):
        part = _part(invocation, a, "rotation")
        return replace(
            part,
            program=replace(part.program, global_phase=0.37),
            dag=replace(part.dag, global_phase=0.37),
        )

    context.invoke(phased, "phase", 0)
    report = evaluate_physical_cost(context.finalize(), {})
    assert "gphase(" in report["generated_qasm"]
    assert loads_qasm(report["generated_qasm"]).global_phase == pytest.approx(0.37)


def test_qasm_bridge_explicitly_rejects_nodes_outside_native_serialization_profile(
    bundle,
):
    changed_dag = replace(
        bundle.dag,
        nodes=(
            replace(bundle.dag.nodes[0], name="h", params=()),
            *bundle.dag.nodes[1:],
        ),
    )
    document = bundle.to_dict()
    document["dag"] = encode_dag(changed_dag)
    changed = replace(bundle, dag=changed_dag, _snapshot_json=json.dumps(document))
    with pytest.raises(ValueError, match="UNSUPPORTED_COST_GATE"):
        evaluate_physical_cost(changed, {})


def test_interval_cost_excludes_readout_and_retains_each_owned_gate(bundle):
    report = evaluate_physical_cost_intervals(
        bundle,
        {"single": {"probabilities": [0.1, 0, 0]}, "readout_flip": 0.2},
        include_intervals=[(0, 2), (5, 7)],
    )
    assert report["model"] == "noise" and report["version"] == "v1.1"
    assert report["metrics"]["no_fault_probability"] == pytest.approx(0.9**2)
    assert all(c["instruction"] != "M" for c in report["noise"]["channels"])
    selection = report["interval_selection"]
    assert selection["include_intervals"] == [[0, 2], [5, 7]]
    assert selection["selected_event_indices"] == [0, 2]
    assert selection["selected_duration_us"] == 4
    assert selection["discrete_channels"] == "complete_action_ownership"
    assert selection["full_trace_probability_equivalence_claimed"] is False
    assert report["logical_success"] is None
    assert report["physical_execution"] is False


def test_discrete_channel_ownership_counts_boundary_readout_exactly_once(bundle):
    params = {"single": {"probabilities": [0.1, 0, 0]}, "readout_flip": 0.2}
    first = evaluate_physical_cost_intervals(bundle, params, include_intervals=[(0, 5)])
    second = evaluate_physical_cost_intervals(
        bundle, params, include_intervals=[(5, 10)]
    )
    assert first["metrics"]["no_fault_probability"] == pytest.approx(0.9 * 0.8)
    assert second["metrics"]["no_fault_probability"] == pytest.approx(0.9)
    assert sum(c["instruction"] == "M" for c in first["noise"]["channels"]) == 1
    assert all(c["instruction"] != "M" for c in second["noise"]["channels"])


def test_clipped_readout_tail_recomputes_t2_and_loss_for_all_atoms_once(bundle):
    report = evaluate_physical_cost_intervals(
        bundle,
        {"exposure": {"slm_t2_us": 10}, "transport": {"slm_loss_per_us": 0.03}},
        include_intervals=[(7, 9)],
    )
    identity = (1 + exp(-2 / 10)) / 2
    assert report["metrics"]["no_fault_probability"] == pytest.approx(
        identity**3 * exp(-3 * 2 * 0.03)
    )
    channels = report["noise"]["channels"]
    assert len(channels) == 3
    assert all(c["duration_us"] == 2 and c["start_us"] == 7 for c in channels)
    assert report["interval_selection"]["source_horizon_us"] == 10
    assert all(item.value is None for item in bundle.pending_measurements)


def test_adjacent_intervals_merge_before_exposure_recomputation(bundle):
    params = {"exposure": {"slm_t2_us": 10}}
    whole = evaluate_physical_cost_intervals(bundle, params, include_intervals=[(7, 9)])
    split = evaluate_physical_cost_intervals(
        bundle, params, include_intervals=[(8, 9), (7, 8)]
    )
    assert split == whole


def test_disconnected_t2_intervals_have_explicit_independent_channel_partition(bundle):
    report = evaluate_physical_cost_intervals(
        bundle, {"exposure": {"slm_t2_us": 10}}, include_intervals=[(7, 8), (9, 10)]
    )
    expected = ((1 + exp(-1 / 10)) / 2) ** 6
    assert report["metrics"]["no_fault_probability"] == pytest.approx(expected)
    assert len(report["noise"]["channels"]) == 6
    assert report["interval_selection"]["exposure_partition"] == (
        "original_activity_interval_intersections_with_merged_include_intervals"
    )
    assert (
        report["interval_selection"]["full_trace_probability_equivalence_claimed"]
        is False
    )


def test_wait_action_can_be_clipped_without_repeating_discrete_effects(setup_world):
    device, world, (a, b) = setup_world
    context = PhysicalContext(device, world, (a, b))
    context.invoke(lambda invocation: _part(invocation, a, "rotation"), "first", 0)
    context.wait_until(12, reason="test_fixture_wait")
    report = evaluate_physical_cost_intervals(
        context.finalize(),
        {"transport": {"slm_loss_per_us": 0.1}},
        include_intervals=[(4, 7)],
    )
    assert report["metrics"]["no_fault_probability"] == pytest.approx(exp(-3 * 3 * 0.1))
    assert report["interval_selection"]["event_index_map"] == [
        {
            "selected_event_id": 0,
            "source_event_id": 1,
            "start_us": 4.0,
            "duration_us": 3.0,
        }
    ]


@pytest.mark.parametrize("intervals", [[(0, 1)], [(3, 5)], [(4, 6)]])
def test_partial_nonwait_actions_are_rejected(bundle, intervals):
    with pytest.raises(ValueError, match="CROSSES_ACTION"):
        evaluate_physical_cost_intervals(bundle, {}, include_intervals=intervals)


@pytest.mark.parametrize(
    "intervals",
    [
        [(0, 2), (1, 2)],
        [(0, 11)],
        [(-1, 1)],
        [(3, 3)],
        [(4, 3)],
        [(0, float("inf"))],
        [(True, 2)],
        [(0,)],
    ],
)
def test_invalid_interval_selections_are_rejected(bundle, intervals):
    with pytest.raises(ValueError, match="INVALID_COST_INTERVAL"):
        evaluate_physical_cost_intervals(bundle, {}, include_intervals=intervals)


def test_empty_interval_selection_is_an_explicit_neutral_product(bundle):
    report = evaluate_physical_cost_intervals(
        bundle, {"readout_flip": 0.5}, include_intervals=[]
    )
    assert report["metrics"]["no_fault_probability"] == 1
    assert report["noise"]["channels"] == []
    assert report["interval_selection"]["selected_duration_us"] == 0
    assert report["interval_selection"]["selected_event_indices"] == []


def test_full_interval_preserves_original_activity_partition_and_model_result(bundle):
    params = {
        "single": {"probabilities": [0.03, 0.01, 0.02]},
        "readout_flip": 0.2,
        "exposure": {"slm_t2_us": 10},
        "transport": {"slm_loss_per_us": 0.03},
    }
    original = bundle.to_json()
    full = evaluate_physical_cost(bundle, params)
    selected = evaluate_physical_cost_intervals(
        bundle, params, include_intervals=[(0, 10)]
    )
    assert selected["metrics"] == full["metrics"]
    assert selected["noise"] == full["noise"]
    assert selected["source_bundle_sha256"] == full["source_bundle_sha256"]
    assert (
        selected["interval_selection"]["source_activity_sha256"]
        == (selected["interval_selection"]["selected_activity_sha256"])
    )
    assert bundle.to_json() == original


@pytest.mark.parametrize(
    "params",
    [
        {"single": {"backend": "ideal"}},
        {"cz": {"backend": "ideal"}},
        {"single_overrides": {"Y": {"backend": "ideal"}}},
    ],
)
def test_interval_profile_rejects_native_gate_backends(bundle, params):
    with pytest.raises(ValueError, match="INTERVAL_NOISE_PROFILE"):
        evaluate_physical_cost_intervals(bundle, params, include_intervals=[(0, 10)])


def test_reset_after_channel_belongs_to_its_complete_action_at_right_boundary(
    setup_world,
):
    device, world, (a, b) = setup_world
    device = replace(
        device,
        zones=(replace(device.zones[0], operations=("rotate", "measure", "reset")),),
    )
    context = PhysicalContext(device, world, (a, b))

    def reset(invocation):
        part = _part(invocation, a, "rotation")
        action = Reset("local", a.atom_ids, duration_us=2, source_ids=(0,))
        return replace(
            part,
            program=AtomProgram((AtomStep((action,)),)),
            dag=replace(
                part.dag, nodes=(replace(part.dag.nodes[0], name="reset", params=()),)
            ),
        )

    context.invoke(reset, "reset-fixture", 0)
    context.wait_until(5, reason="test_fixture_wait")
    bundle = context.finalize()
    before = evaluate_physical_cost_intervals(
        bundle, {"reset_flip": 0.2}, include_intervals=[(0, 2)]
    )
    after = evaluate_physical_cost_intervals(
        bundle, {"reset_flip": 0.2}, include_intervals=[(2, 5)]
    )
    assert before["metrics"]["no_fault_probability"] == pytest.approx(0.8)
    assert before["noise"]["channels"][0]["placement"] == "after"
    assert after["metrics"]["no_fault_probability"] == 1
    with pytest.raises(ValueError, match="CROSSES_ACTION"):
        evaluate_physical_cost_intervals(bundle, {}, include_intervals=[(1, 2)])


def test_transport_discrete_loss_and_holder_exposure_are_counted_once(setup_world):
    device, world, (a, b) = setup_world
    context = PhysicalContext(device, world, (a, b))

    def transported(invocation):
        part = _part(invocation, a, "rotation")
        grid = AODGrid("aod0", (AODLine(0, 0),), (AODLine(0, 10),))
        program = AtomProgram(
            (
                AtomStep((Load(grid, ((11, 0, 0),), duration_us=1, source_ids=(0,)),)),
                AtomStep(
                    (
                        Store(
                            AODGrid("aod0"),
                            ((11, "s1"),),
                            duration_us=1,
                            source_ids=(0,),
                        ),
                    )
                ),
                *part.program.steps,
            )
        )
        return replace(
            part,
            program=program,
            exit_state=replay(program, part.entry_state, device),
            operations=(CompiledOperation(0, "emitted", 0, 4),),
        )

    context.invoke(transported, "transport-fixture", 0)
    bundle = context.finalize()
    report = evaluate_physical_cost_intervals(
        bundle,
        {
            "transport": {
                "load_loss": 0.2,
                "store_loss": 0.3,
                "slm_loss_per_us": 0.01,
                "aod_loss_per_us": 0.02,
            },
        },
        include_intervals=[(0, 2)],
    )
    # Five atom-us in SLM, one atom-us in AOD, plus one load and one store.
    expected = 0.8 * 0.7 * exp(-5 * 0.01 - 0.02)
    assert report["metrics"]["no_fault_probability"] == pytest.approx(expected)
    assert report["noise"]["loss"]["all_atoms_survive_probability"] == pytest.approx(
        expected
    )
    assert [event["cause"] for event in report["noise"]["loss"]["events"]].count(
        "load"
    ) == 1
    assert [event["cause"] for event in report["noise"]["loss"]["events"]].count(
        "store"
    ) == 1
    with pytest.raises(ValueError, match="CROSSES_ACTION"):
        evaluate_physical_cost_intervals(bundle, {}, include_intervals=[(0, 0.5)])


def test_interval_evidence_is_json_serializable_and_distinguishes_selected_activity(
    bundle,
):
    first = evaluate_physical_cost_intervals(bundle, {}, include_intervals=[(0, 2)])
    last = evaluate_physical_cost_intervals(bundle, {}, include_intervals=[(5, 7)])
    assert json.loads(json.dumps(first)) == first
    assert first["source_bundle_sha256"] == last["source_bundle_sha256"]
    assert first["source_dag_sha256"] == last["source_dag_sha256"]
    assert (
        first["interval_selection"]["source_activity_sha256"]
        == last["interval_selection"]["source_activity_sha256"]
    )
    assert (
        first["interval_selection"]["selected_activity_sha256"]
        != last["interval_selection"]["selected_activity_sha256"]
    )
    assert first["time_scope"] == "disjoint_include_intervals"
    assert first["probability_kind"] == "physical_no_fault_proxy"
    assert first["interval_selection"]["schema"] == "nadit.physical_cost_intervals/1"
    assert first["interval_selection"]["noise_profile"] == "independent_pauli_rates_v1"


def test_zero_duration_gate_requires_unambiguous_interior_ownership(setup_world):
    device, world, (a, b) = setup_world
    device = replace(device, local=replace(device.local, rotation_us=0))
    context = PhysicalContext(device, world, (a, b))
    context.wait_until(1, reason="test_fixture_before_instantaneous_gate")

    def instantaneous(invocation):
        part = _part(invocation, a, "rotation")
        action = replace(part.program.steps[0].actions[0], duration_us=0)
        return replace(
            part,
            program=AtomProgram((AtomStep((action,)),)),
            operations=(CompiledOperation(0, "emitted", 0, 0),),
        )

    context.invoke(instantaneous, "test_fixture_instantaneous_gate", 0)
    context.wait_until(3, reason="test_fixture_after_instantaneous_gate")
    bundle = context.finalize()
    params = {"single": {"probabilities": [0.2, 0, 0]}}
    report = evaluate_physical_cost_intervals(
        bundle, params, include_intervals=[(0, 3)]
    )
    assert report["metrics"]["no_fault_probability"] == pytest.approx(0.8)
    assert report["noise"]["channels"][0]["duration_us"] == 0
    with pytest.raises(ValueError, match="AMBIGUOUS_ZERO_DURATION_ACTION"):
        evaluate_physical_cost_intervals(bundle, params, include_intervals=[(1, 3)])


def test_interval_evaluator_does_not_bypass_validation_for_empty_selection(bundle):
    document = bundle.to_dict()
    document["validation"]["ok"] = False
    changed = replace(bundle, _snapshot_json=json.dumps(document))
    with pytest.raises(ValueError, match="UNVALIDATED_COST_BUNDLE"):
        evaluate_physical_cost_intervals(changed, {}, include_intervals=[])
