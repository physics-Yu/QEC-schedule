"""Schedule evidence, fixed-platform placement and preserved-attempt checks."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from neutral_atom_env.domain.models import ZoneType
from neutral_atom_env.domain.operations import Operation, OperationInterval, OperationType
from neutral_atom_experiments.qec_layout import build_qec_inputs
from neutral_atom_experiments.qec_pbc.neutral_atom import build_native_qec_inputs
from neutral_atom_experiments.qec_pbc.physical import fresh_output, operation_schedule, sparse_memory_destinations
from neutral_atom_experiments.qec_pbc.surface import memory_program
from neutral_atom_strategies.motion.single_trap import in_zone


def _plan(*, second_start=2, shared_resource=True, second_gate="g1"):
    operations = (
        Operation("op0", OperationType.RAMAN_ROTATION, "first physical pulse", 2, gate_id="g0"),
        Operation("op1", OperationType.RAMAN_ROTATION, "second physical pulse", 3,
                  gate_id=second_gate, depends_on=("op0",)),
    )
    intervals = (
        OperationInterval("op0", 0, 2, ("RAMAN:Q000",), ("Q000",)),
        OperationInterval("op1", second_start, second_start + 3,
                          ("RAMAN:Q000" if shared_resource else "RAMAN:Q001",),
                          ("Q000" if shared_resource else "Q001",)),
    )
    # Accepted-plan fixtures expose only the immutable metadata needed by the
    # evidence reader. They do not bypass an Executor or pretend to execute.
    return SimpleNamespace(id="plan0", initial_time_us=10, operations=operations, operation_intervals=intervals)


def _boundaries(*, second_start=12, second_end=15):
    return [
        {"event": {"event_type": "plan_started", "plan_id": "plan0", "time_us": 10}},
        {"event": {"event_type": "operation_started", "plan_id": "plan0", "operation_id": "op0", "time_us": 10}},
        {"event": {"event_type": "operation_completed", "plan_id": "plan0", "operation_id": "op0", "time_us": 12}},
        {"event": {"event_type": "operation_started", "plan_id": "plan0", "operation_id": "op1", "time_us": second_start}},
        {"event": {"event_type": "operation_completed", "plan_id": "plan0", "operation_id": "op1", "time_us": second_end}},
        {"event": {"event_type": "plan_completed", "plan_id": "plan0", "time_us": second_end}},
    ]


def test_absolute_schedule_uses_accepted_origin_and_committed_boundaries():
    rows, gate_times = operation_schedule((_plan(),), _boundaries())
    assert gate_times == {"g0": (10, 12), "g1": (12, 15)}
    assert [(row["start_us"], row["end_us"], row["duration_us"]) for row in rows] == [(10, 12, 2), (12, 15, 3)]
    assert [row["gate_ids"] for row in rows] == [("g0",), ("g1",)]
    assert rows[1]["depends_on"] == ("op0",)
    assert rows[0]["resources"] == ("RAMAN:Q000",)
    assert rows[0]["atom_ids"] == ("Q000",)


def test_disjoint_resources_can_have_overlapping_physical_intervals():
    rows, gates = operation_schedule((_plan(second_start=1, shared_resource=False),),
                                    _boundaries(second_start=11, second_end=14))
    assert gates == {"g0": (10, 12), "g1": (11, 14)}
    assert rows[0]["resources"] != rows[1]["resources"]


@pytest.mark.parametrize("change", ("missing", "wrong_time", "extra"))
def test_schedule_rejects_boundaries_that_do_not_match_the_accepted_plan(change):
    trace = _boundaries()
    if change == "missing":
        del trace[2]
    elif change == "wrong_time":
        trace[2]["event"]["time_us"] = 12.5
    else:
        trace.append({"event": {"event_type": "operation_started", "plan_id": "foreign",
                                "operation_id": "op0", "time_us": 99}})
    with pytest.raises(ValueError, match="boundary mismatch|exactly match accepted plans"):
        operation_schedule((_plan(),), trace)


def test_schedule_rejects_duplicate_committed_boundaries():
    trace = _boundaries()
    trace.append(trace[1])
    with pytest.raises(ValueError, match="Duplicate committed operation boundary"):
        operation_schedule((_plan(),), trace)


def test_schedule_rejects_repeated_gate_effect_and_resource_overlap():
    with pytest.raises(ValueError, match="Multiple physical intervals for gate g0"):
        operation_schedule((_plan(second_gate="g0"),), _boundaries())
    with pytest.raises(ValueError, match="Overlapping physical resource: RAMAN:Q000"):
        operation_schedule((_plan(second_start=1),), _boundaries(second_start=11, second_end=14))


def test_parallel_batch_gate_ids_share_one_physical_interval():
    plan = _plan()
    operation = replace(plan.operations[0], gate_id=None, gate_ids=("g0", "g2"))
    plan.operations = (operation, plan.operations[1])
    rows, gates = operation_schedule((plan,), _boundaries())
    assert rows[0]["gate_ids"] == ("g0", "g2")
    assert gates == {"g0": (10, 12), "g2": (10, 12), "g1": (12, 15)}


def test_sparse_destinations_use_only_existing_ez_traps_and_preserve_hardware():
    inputs = build_native_qec_inputs(memory_program(rounds=1))
    _, _, original_platform, original_placement = build_qec_inputs({"gates": []})
    destinations = sparse_memory_destinations(inputs)
    state = inputs.create_environment().state
    bindings = dict(inputs.compiled.bindings)

    assert inputs.platform == original_platform
    assert dict(inputs.placement) == original_placement
    assert len(destinations) == len(set(destinations.values())) == 17
    assert set(destinations) == set(bindings.values())
    assert all(site in state.world.traps for site in destinations.values())
    assert all(in_zone(state, state.world.traps[site].position, ZoneType.ENTANGLEMENT)
               for site in destinations.values())
    assert all(not state.world.traps[site].enabled for site in destinations.values())
    assert state.world.traps[destinations[bindings["A.d0"]]].position.x_um == 0
    assert state.world.traps[destinations[bindings["A.d0"]]].position.y_um == -100
    assert state.world.traps[destinations[bindings["A.d8"]]].position.x_um == 40
    assert state.world.traps[destinations[bindings["A.d8"]]].position.y_um == -60
    assert state.world.traps[destinations[bindings["A.Z2"]]].position.x_um == -10
    assert state.world.traps[destinations[bindings["A.Z2"]]].position.y_um == -90
    assert not state.placement.mobile_occupancy
    assert dict(state.placement.static_occupancy) == {site: atom for atom, site in original_placement.items()}


def test_sparse_memory_layout_rejects_other_patch_roles():
    inputs = build_native_qec_inputs(memory_program(patch="B", rounds=1))
    with pytest.raises(ValueError, match="canonical A patch roles"):
        sparse_memory_destinations(inputs)


def test_fresh_output_preserves_every_previous_attempt(tmp_path):
    requested = tmp_path / "physical memory"
    requested.mkdir()
    marker = requested / "evidence.json"
    marker.write_bytes(b'{"status":"failed","retain":true}')

    second = fresh_output(requested)
    (second / "successful.json").write_bytes(b'{"status":"completed"}')
    third = fresh_output(requested)

    assert second == tmp_path / "physical memory-attempt2"
    assert third == tmp_path / "physical memory-attempt3"
    assert marker.read_bytes() == b'{"status":"failed","retain":true}'
    assert (second / "successful.json").read_bytes() == b'{"status":"completed"}'
    assert third.is_dir() and not list(third.iterdir())


def test_fresh_output_also_preserves_an_existing_file(tmp_path):
    requested = tmp_path / "existing"
    requested.write_bytes(b"original evidence")
    actual = fresh_output(requested)
    assert requested.read_bytes() == b"original evidence"
    assert actual == tmp_path / "existing-attempt2"
    assert actual.is_dir()

