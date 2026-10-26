"""Independent interval accounting and transparent observation of actual SE."""

import json
import re
from dataclasses import replace

import pytest
from nadit_physical_compiler import loads_qasm
from nadit_physical_compiler.atom_ir import AtomStep, Load, Move, Rotation, Store, Wait
from nadit_physical_compiler.compiler import compile_physical
from nadit_physical_compiler.contracts import TransportGoal
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.serialization import decode_result, encode_result
from nadit_physical_compiler.state import AODGrid, SLMHolder
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy
from nadit_physical_compiler.validation import validate_result

from experiments.msd.parallel_se_metrics import RecordedStrategy, partition_step
from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes.rotated_surface import get_component
from modules.physical_compiler.tests.test_nonzoned_transport_goals import (
    fixture as transport_fixture,
)


def test_parallel_action_duration_is_union_not_sum():
    step = AtomStep(
        (
            Move(AODGrid("a"), ((0, Position(0, 3)),), duration_us=3),
            Move(AODGrid("b"), ((1, Position(0, 5)),), duration_us=5),
        )
    )
    assert partition_step(step, "cz") == {"cz_move": 5}
    local = AtomStep(
        (
            Rotation("local", (0,), "X", 1, duration_us=1),
            Rotation("local", (1,), "Z", 2, duration_us=1),
        )
    )
    assert partition_step(local, "rx") == {"rotation": 1}


def test_mixed_parallel_tail_has_an_exclusive_partition():
    # This hand-built fixture tests accounting, not concurrent-action legality.
    step = AtomStep(
        (
            Load(AODGrid("a"), ((0, 0, 0),), duration_us=2),
            Move(AODGrid("b"), ((1, Position(0, 5)),), duration_us=5),
        )
    )
    phases = partition_step(step, "measure")
    assert phases == {"readout_load+readout_move": 2, "readout_move": 3}
    assert sum(phases.values()) == step.duration_us == 5
    assert partition_step(AtomStep((Wait(duration_us=0),)), "wait") == {}


@pytest.fixture(scope="module")
def observed_joint_se():
    world = build_world(ExperimentSpec(distance=3, pipelines=2))
    source = get_component("se_round", 3).source_qasm
    bodies = []
    for factory in range(2):
        body = "\n".join(source.splitlines()[2:])
        body = re.sub(r"\bq\b", f"q{factory}", body)
        bodies.append(re.sub(r"\bm\b", f"m{factory}", body))
    dag = loads_qasm('OPENQASM 3.0; include "stdgates.inc";\n' + "\n".join(bodies))
    patches = [world.patch(factory, "W1") for factory in range(2)]
    atoms = tuple(atom for patch in patches for atom in patch.binding.atom_ids)
    entry = replace(world.state, qubit_to_atom=atoms)
    size = len(patches[0].binding.atom_ids)
    owners = tuple(node.qubits[0] // size for node in dag.nodes)
    atom_owners = {
        atom: factory
        for factory, patch in enumerate(patches)
        for atom in patch.binding.atom_ids
    }
    base = NonZonedStrategy("transport", GatePairCatalog.from_pair_arrays(world.device))
    observer = RecordedStrategy(base, owners, atom_owners)
    result = compile_physical(dag, world.device, strategy=observer, entry_state=entry)
    unchanged = compile_physical(dag, world.device, strategy=base, entry_state=entry)
    assert result == unchanged
    assert validate_result(result, entry_state=entry, device=world.device, dag=dag)[
        "ok"
    ]
    return observer, result, entry, world.device


def test_recorder_preserves_schedule_and_partitions_elapsed_time(observed_joint_se):
    observer, result, entry, device = observed_joint_se
    report = observer.report(result, entry, device)
    assert sum(report["time_partition_us"].values()) == pytest.approx(
        result.program.duration_us
    )
    assert observer.clock_us == pytest.approx(result.program.duration_us)
    assert report["concurrency"]["peak_active_factory_count"] == 2
    assert report["concurrency"]["shared_transport_batch_count"] > 0
    assert (
        0
        < report["concurrency"]["multi_factory_active_time_us"]
        <= result.program.duration_us
    )
    assert all(
        set(row["selected_operation_ids"]) <= set(row["ready_operation_ids"])
        for row in observer.records
    )
    assert sum(
        row["end_us"] - row["start_us"] for row in observer.records
    ) == pytest.approx(result.program.duration_us)


def test_completion_includes_return_transport_and_spectators_do_not_own_gates(
    observed_joint_se,
):
    observer, result, entry, device = observed_joint_se
    report = observer.report(result, entry, device)
    assert len(report["measured_destinations"]) == 16
    assert {item["factory_id"] for item in report["measured_destinations"]} == {0, 1}
    assert all(item["y_um"] >= 50 for item in report["measured_destinations"])
    for factory in report["per_factory"]:
        assert factory["action_completion_us"] == factory["final_home_us"]
        assert factory["final_home_us"] > factory["measurement_ready_us"]
    for pulse in report["cz_pulses"]:
        assert pulse["illuminated_atom_count"] == len(entry.atoms) == 204
        assert pulse["spectator_atom_count"] == 204 - pulse["participant_atom_count"]
        assert pulse["unowned_spectator_atom_count"] == 170
        assert pulse["participant_factory_ids"] == [0, 1]
    assert all(
        batch["end_us"] > batch["start_us"] for batch in report["transport_batches"]
    )
    # Reporting twice does not append or alter scheduler observations.
    assert observer.report(result, entry, device) == report


def test_unobserved_wait_is_rejected_instead_of_inventing_schedule_times(
    observed_joint_se,
):
    observer, result, entry, device = observed_joint_se
    altered = replace(
        result,
        program=replace(
            result.program,
            steps=(AtomStep((Wait(duration_us=1),)), *result.program.steps),
        ),
    )
    with pytest.raises(ValueError, match="unobserved"):
        observer.report(altered, entry, device)


def test_recorder_preserves_native_goal_through_compilation_and_serialization():
    world = build_world(ExperimentSpec(distance=3, pipelines=1))
    atom = world.state.atoms[0]
    assert isinstance(atom.holder, SLMHolder)
    destination = atom.holder.site_id.replace("home_", "guest_", 1)
    goal = TransportGoal(0, ((0, destination),))
    dag = PhysicalDAG(
        len(world.state.qubit_to_atom),
        0,
        (PhysicalOperation(0, "relocate", (0,), (), ()),),
        (),
    )
    base = NonZonedStrategy(
        "transport",
        GatePairCatalog.from_pair_arrays(world.device),
        transport_goals=(goal,),
    )
    observer = RecordedStrategy(base, (0,), {atom.id: 0})
    result = compile_physical(
        dag, world.device, strategy=observer, entry_state=world.state
    )
    assert result.transport_goals == (goal,)
    assert result.exit_state.atom(atom.id).holder == SLMHolder(destination)
    assert result.exit_state.qubit_to_atom == world.state.qubit_to_atom
    assert all(
        result.exit_state.atom(other.id) == other
        for other in world.state.atoms
        if other.id != atom.id
    )
    encoded = encode_result(result, entry_state=world.state, job={}, provenance={})
    decoded = decode_result(json.loads(json.dumps(encoded)))
    assert decoded == result
    checked = validate_result(
        decoded, entry_state=world.state, device=world.device, dag=dag
    )
    assert checked["ok"], checked
    assert "transport_goals" in checked["checks"]
    assert observer.clock_us == pytest.approx(result.duration_us)
    report = observer.report(result, world.state, world.device)
    assert report["per_factory"][0]["final_home_us"] is None
    assert (
        report["per_factory"][0]["final_destination_us"] == result.operations[0].end_us
    )


def recorded_goal_case(name):
    device, entry, goal = transport_fixture(readout=name == "measure")
    dag = PhysicalDAG(
        4,
        int(name == "measure"),
        (
            PhysicalOperation(
                0,
                name,
                (0, 1) if name == "cz" else (0,),
                (0,) if name == "measure" else (),
                (),
            ),
            PhysicalOperation(1, "relocate", (2,), (), ()),
        ),
        (),
    )
    base = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    observer = RecordedStrategy(base, (0, 1), {0: 0, 1: 0, 2: 1})
    result = compile_physical(dag, device, strategy=observer, entry_state=entry)
    checked = validate_result(result, entry_state=entry, device=device, dag=dag)
    assert checked["ok"], checked
    return observer, result, entry, device


@pytest.mark.parametrize("name", ("cz", "measure"))
def test_recorded_mixed_goal_keeps_partial_store_batch_until_last_unload(name):
    observer, result, entry, device = recorded_goal_case(name)
    report = observer.report(result, entry, device)
    loads = [
        a for step in result.program.steps for a in step.actions if isinstance(a, Load)
    ]
    stores = [
        (start + a.duration_us, a)
        for start, step in result.program.timeline()
        for a in step.actions
        if isinstance(a, Store)
    ]
    assert len(report["transport_batches"]) == len(loads)
    partial = [a for _end, a in stores if a.grid.rows or a.grid.columns]
    if name == "measure":
        assert partial, "Fixture must exercise a real permanent-mover partial Store."
        assert len(loads) == 1
        assert report["transport_batches"][0]["end_us"] == stores[-1][0]
        assert report["transport_batches"][0]["atom_count"] == len(loads[0].bindings)
    owners = {row["factory_id"]: row for row in report["per_factory"]}
    assert owners[1]["final_home_us"] is None
    assert owners[1]["final_destination_us"] == result.operations[1].end_us
    assert owners[0]["final_home_us"] == owners[0]["action_completion_us"]
    assert sum(report["time_partition_us"].values()) == pytest.approx(
        result.duration_us
    )
    assert observer.report(result, entry, device) == report


@pytest.mark.parametrize("damage", ("target", "binding", "spectator"))
def test_stateful_report_rejects_forged_endpoint_or_world_identity(damage):
    observer, result, entry, device = recorded_goal_case("cz")
    if damage == "target":
        changed = replace(result.transport_goals[0], targets=((2, "l1_4"),))
        # Keep the recorder declaration synchronized to test endpoint replay,
        # independently of an outer registry mismatch guard.
        observer.base = replace(observer.base, transport_goals=(changed,))
        result = replace(result, transport_goals=(changed,))
    elif damage == "binding":
        result = replace(
            result, exit_state=replace(result.exit_state, qubit_to_atom=(1, 0, 2, 3))
        )
    else:
        result = replace(
            result,
            exit_state=replace(
                result.exit_state,
                atoms=(
                    *result.exit_state.atoms[:3],
                    replace(result.exit_state.atoms[3], position=Position(41, -20)),
                ),
            ),
        )
    with pytest.raises(ValueError, match="endpoint|exit state|binding"):
        observer.report(result, entry, device)


def test_omitted_goals_do_not_disable_strict_return_home_report():
    observer, result, entry, device = recorded_goal_case("cz")
    observer.base = replace(observer.base, transport_goals=())
    result = replace(result, transport_goals=())
    with pytest.raises(ValueError, match="back at home"):
        observer.report(result, entry, device)
