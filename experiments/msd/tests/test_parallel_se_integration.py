"""Verify simultaneous SE submission using actual compiled actions and controls."""

from collections import Counter

import pytest
from nadit_physical_compiler.atom_ir import CZPulse, Measure, Store
from nadit_physical_compiler.device import loads_device
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import decode_layout, decode_result

from experiments.msd import parallel_se
from experiments.msd.standard import ExperimentSpec


@pytest.fixture(scope="module")
def compiled_controls():
    """Compile small real controls once; never overlay separately compiled traces."""
    cases = {}
    for pipelines, mode, index in (
        (1, "joint", None),
        (1, "serial", None),
        (1, "solo", 0),
        (2, "joint", None),
        (2, "serial", None),
        (2, "solo", 0),
        (2, "solo", 1),
    ):
        calls = []
        original = parallel_se.compile_physical

        def one_compile(dag, device, _calls=calls, _original=original, **kwargs):
            _calls.append((dag.num_qubits, len(kwargs["entry_state"].atoms)))
            return _original(dag, device, **kwargs)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(parallel_se, "compile_physical", one_compile)
            case = parallel_se.compile_se_case(
                ExperimentSpec(3, pipelines), mode, factory_index=index
            )
        instances = 1 if mode == "solo" else pipelines
        assert calls == [(17 * instances, 102 * pipelines)]
        cases[pipelines, mode, index] = case
    return cases


def test_n1_joint_serial_and_solo_have_identical_physical_execution(compiled_controls):
    cases = [
        compiled_controls[1, mode, index]
        for mode, index in (("joint", None), ("serial", None), ("solo", 0))
    ]
    row, document, _ = cases[0]
    for compared_row, compared, _ in cases[1:]:
        assert compared_row["metrics"] == row["metrics"]
        assert compared_row["device_sha256"] == row["device_sha256"]
        assert compared["program"] == document["program"]
        assert compared["entry_state"] == document["entry_state"]
        assert compared["measurements"] == document["measurements"]


def test_n2_has_real_multi_owner_cz_pulses_and_preserves_measurement_ownership(
    compiled_controls,
):
    row, document, _ = compiled_controls[2, "joint", None]
    result = decode_result(document)
    node_owners = document["se_instances"]["node_owners"]
    measurement_owners = dict(document["se_instances"]["measurement_owners"])
    active_atoms = document["entry_state"]["qubit_to_atom"]
    atom_owners = {atom: index // 17 for index, atom in enumerate(active_atoms)}
    actions = [action for step in result.program.steps for action in step.actions]
    # Source IDs name actually executed native CZs. Ambient coverage of spectator
    # atoms alone does not count as evidence of simultaneous factory operations.
    multi_owner_cz = [
        action
        for action in actions
        if isinstance(action, CZPulse)
        and len({node_owners[source] for source in action.source_ids}) > 1
    ]
    assert multi_owner_cz
    assert all(
        {node_owners[source] for source in action.source_ids} == {0, 1}
        for action in multi_owner_cz
    )
    measured = []
    for action in actions:
        if isinstance(action, Measure):
            assert action.duration_us == 100
            assert action.retain_atoms
            for atom, reference in action.results:
                owner = measurement_owners[reference.measurement_id]
                assert atom_owners[atom] == owner
                measured.append((atom, reference.measurement_id, owner))
    assert len(measured) == len({atom for atom, _, _ in measured}) == 16
    assert len({mid for _, mid, _ in measured}) == 16
    assert Counter(owner for _, _, owner in measured) == {0: 8, 1: 8}
    assert len(result.measurements) == row["expected_measurements"] == 16
    assert row["metrics"]["atom_count"] == 204
    assert row["scheduler"]["single_physical_compile"] is True
    assert row["scheduler"]["submitted_at_us"] == 0


def test_controls_keep_identical_full_world_and_serial_round_sums_all_solos(
    compiled_controls,
):
    joint_row, joint, _ = compiled_controls[2, "joint", None]
    serial_row, serial, _ = compiled_controls[2, "serial", None]
    solos = [compiled_controls[2, "solo", index] for index in (0, 1)]
    for row, document, _ in ((serial_row, serial, None), *solos):
        assert row["device_sha256"] == joint_row["device_sha256"]
        assert document["device"] == joint["device"]
        assert document["entry_state"]["atoms"] == joint["entry_state"]["atoms"]
        assert row["source_tree_sha256"] == joint_row["source_tree_sha256"]
    assert serial_row["metrics"]["execution_duration_us"] == pytest.approx(
        sum(row["metrics"]["execution_duration_us"] for row, _, _ in solos),
        abs=1e-8,
    )


def test_round_completion_includes_final_return_and_all_results(compiled_controls):
    import json

    for row, document, _ in compiled_controls.values():
        result = decode_result(document)
        entry = decode_layout(document["entry_state"])
        device = loads_device(json.dumps(document["device"]))
        assert replay(result.program, entry, device) == result.exit_state == entry
        stores = [
            start + action.duration_us
            for start, step in result.program.timeline()
            for action in step.actions
            if isinstance(action, Store)
        ]
        last_result = max(record.available_at_us for record in result.measurements)
        assert max(stores) > last_result
        assert max(stores) == pytest.approx(result.program.duration_us, abs=1e-8)
        assert row["metrics"]["execution_duration_us"] == result.duration_us
        assert result.duration_us == max(result.program.duration_us, last_result)
        for key in (
            "accepted_outputs",
            "accepted_output_throughput_per_s",
            "logical_error_probability",
        ):
            assert row["metrics"][key] is None


def test_observed_partition_and_concurrency_match_actual_completed_program(
    compiled_controls,
):
    for (pipelines, mode, _), (row, document, schedule) in compiled_controls.items():
        result = decode_result(document)
        assert row["scheduler"]["time_partition_us"] == schedule["time_partition_us"]
        assert sum(schedule["time_partition_us"].values()) == pytest.approx(
            result.program.duration_us, abs=1e-8
        )
        expected_peak = pipelines if mode == "joint" else 1
        assert schedule["concurrency"]["peak_active_factory_count"] == expected_peak
        destinations = schedule["measured_destinations"]
        assert len(destinations) == row["expected_measurements"]
        assert all(item["y_um"] >= 50 for item in destinations)
        assert len({item["measurement_id"] for item in destinations}) == len(
            destinations
        )
        assert {item["factory_id"] for item in destinations} == set(
            row["factory_indices"]
        )
        assert max(
            item["final_home_us"] for item in schedule["per_factory"]
        ) == pytest.approx(result.program.duration_us, abs=1e-8)
        if expected_peak > 1:
            assert schedule["concurrency"]["multi_factory_active_time_us"] > 0
            assert any(
                len(item["participant_factory_ids"]) > 1
                for item in schedule["cz_pulses"]
            )


@pytest.mark.parametrize(
    "mode,index",
    (
        ("unknown", None),
        ("solo", None),
        ("solo", -1),
        ("solo", 2),
        ("solo", True),
        ("joint", 0),
        ("serial", 1),
    ),
)
def test_invalid_mode_selection_rejected_before_source_or_world(
    monkeypatch, mode, index
):
    def forbidden_snapshot():
        raise AssertionError("Invalid invocation reached source/world construction.")

    monkeypatch.setattr(parallel_se, "source_snapshot", forbidden_snapshot)
    with pytest.raises(ValueError):
        parallel_se.compile_se_case(ExperimentSpec(3, 2), mode, factory_index=index)
