"""Native mechanical goals require replayed endpoints and transport provenance."""

from dataclasses import dataclass, replace

import pytest

from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    Load,
    Move,
    Rotation,
    Store,
    Wait,
)
from nadit_physical_compiler.compiler import (
    CompilationResult,
    CompiledOperation,
    compile_physical,
)
from nadit_physical_compiler.contracts import AtomFragment, GateLayer, TransportGoal
from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
)
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import decode_result, encode_result
from nadit_physical_compiler.state import (
    AODGrid,
    AODLine,
    AtomLayout,
    AtomState,
    SLMHolder,
)
from nadit_physical_compiler.validation import validate_result


def native_case():
    device = Device(
        "transport-goal",
        zones=(),
        slm_sites=(
            SLMSite("home", Position(0, 0)),
            SLMSite("delivery", Position(0, 10)),
            SLMSite("later", Position(0, 20)),
            SLMSite("spectator", Position(30, 0)),
        ),
        aods=(AOD("transport", Region(-5, -5, 40, 40), min_spacing=1),),
        timing=Timing(load_us=1, store_us=1, move_us_per_um=1),
    )
    entry = AtomLayout(
        (
            AtomState(17, Position(0, 0), SLMHolder("home")),
            AtomState(9, Position(30, 0), SLMHolder("spectator")),
        ),
        (),
        (17, 9),
    )
    dag = PhysicalDAG(2, 0, (PhysicalOperation(0, "relocate", (0,), (), ()),), ())
    goal = TransportGoal(0, ((0, "delivery"),))
    program = AtomProgram(transport_steps(0, 0, 10, "delivery"))
    result = CompilationResult(
        program,
        replay(program, entry, device),
        (CompiledOperation(0, "emitted", 0, 12),),
        (),
        (GateLayer((0,)),),
        (goal,),
    )
    return dag, device, entry, result


def transport_steps(source, initial_y, final_y, target):
    first = AODGrid("transport", (AODLine(0, initial_y),), (AODLine(0, 0),))
    last = AODGrid("transport", (AODLine(0, final_y),), (AODLine(0, 0),))
    return (
        AtomStep((Load(first, ((17, 0, 0),), duration_us=1, source_ids=(source,)),)),
        AtomStep(
            (
                Move(
                    last,
                    ((17, Position(0, final_y)),),
                    duration_us=abs(final_y - initial_y),
                    source_ids=(source,),
                ),
            )
        ),
        AtomStep(
            (
                Store(
                    AODGrid("transport"),
                    ((17, target),),
                    duration_us=1,
                    source_ids=(source,),
                ),
            )
        ),
    )


@dataclass
class FixtureStrategy:
    transport_goals: tuple[TransportGoal, ...]
    fragment: AtomFragment
    lookahead_enabled: bool = False

    def select(self, dag, ready):
        return GateLayer(ready)

    def lower(self, dag, layer, layout, device, **kwargs):
        return self.fragment


def test_compiler_captures_goals_and_serialization_preserves_optional_registry():
    dag, device, entry, expected = native_case()
    result = compile_physical(
        dag,
        device,
        entry_state=entry,
        strategy=FixtureStrategy(
            expected.transport_goals,
            AtomFragment(expected.program.steps, expected.exit_state, (0,)),
        ),
    )
    assert result == expected
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]
    encoded = encode_result(result, entry_state=entry, job={}, provenance={})
    assert encoded["transport_goals"] == [
        {"operation_id": 0, "targets": [[0, "delivery"]]}
    ]
    assert decode_result(encoded) == result
    gate_only = replace(result, transport_goals=())
    encoded = encode_result(gate_only, entry_state=entry, job={}, provenance={})
    assert "transport_goals" not in encoded
    assert decode_result(encoded).transport_goals == ()


@pytest.mark.parametrize(
    "damage", ("missing", "wrong_node", "wrong_wire", "unknown_site", "params")
)
def test_compiler_rejects_mismatched_goal_registry(damage):
    dag, device, entry, result = native_case()
    goals = result.transport_goals
    if damage == "missing":
        goals = ()
    elif damage == "wrong_node":
        goals = (TransportGoal(1, ((0, "delivery"),)),)
    elif damage == "wrong_wire":
        goals = (TransportGoal(0, ((1, "delivery"),)),)
    elif damage == "unknown_site":
        goals = (TransportGoal(0, ((0, "absent"),)),)
    else:
        dag = replace(dag, nodes=(replace(dag.nodes[0], params=(1,)),))
    with pytest.raises(ValueError, match="[Tt]ransport|relocate"):
        compile_physical(
            dag,
            device,
            entry_state=entry,
            strategy=FixtureStrategy(
                goals, AtomFragment(result.program.steps, result.exit_state, (0,))
            ),
        )


@pytest.mark.parametrize(
    "damage",
    (
        "missing_registry",
        "wrong_endpoint",
        "unattributed_store",
        "wait_only",
        "wrong_binding",
        "forged_interval",
    ),
)
def test_validator_rejects_missing_or_forged_transport_proof(damage):
    dag, device, entry, result = native_case()
    if damage == "missing_registry":
        result = replace(result, transport_goals=())
    elif damage == "wrong_endpoint":
        result = replace(result, transport_goals=(TransportGoal(0, ((0, "later"),)),))
    elif damage == "unattributed_store":
        steps = result.program.steps
        result = replace(
            result,
            program=AtomProgram(
                (*steps[:2], AtomStep((replace(steps[2].actions[0], source_ids=()),)))
            ),
        )
    elif damage == "wait_only":
        result = replace(
            result,
            program=AtomProgram((AtomStep((Wait(duration_us=12, source_ids=(0,)),)),)),
            exit_state=entry,
        )
    elif damage == "wrong_binding":
        result = replace(
            result, exit_state=replace(result.exit_state, qubit_to_atom=(9, 17))
        )
    else:
        result = replace(result, operations=(CompiledOperation(0, "emitted", 0, 11),))
    assert not validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]


def test_goal_endpoint_is_checked_at_its_completion_before_later_transport():
    dag, device, entry, result = native_case()
    dag = replace(
        dag,
        nodes=(*dag.nodes, PhysicalOperation(1, "relocate", (0,), (), ())),
        edges=((0, 1),),
    )
    program = AtomProgram((*result.program.steps, *transport_steps(1, 10, 20, "later")))
    result = replace(
        result,
        program=program,
        exit_state=replay(program, entry, device),
        operations=(*result.operations, CompiledOperation(1, "emitted", 12, 24)),
        layers=(*result.layers, GateLayer((1,))),
        transport_goals=(*result.transport_goals, TransportGoal(1, ((0, "later"),))),
    )
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]
    result = replace(
        result,
        transport_goals=(TransportGoal(0, ((0, "later"),)), result.transport_goals[1]),
    )
    assert not validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]


def test_goal_validation_requires_native_dag():
    _dag, device, entry, result = native_case()
    assert not validate_result(result, entry_state=entry, device=device)["ok"]


def test_partially_satisfied_goal_keeps_stationary_wire_but_noop_is_rejected():
    dag, device, entry, result = native_case()
    dag = replace(dag, nodes=(replace(dag.nodes[0], qubits=(0, 1)),))
    result = replace(
        result, transport_goals=(TransportGoal(0, ((0, "delivery"), (1, "spectator"))),)
    )
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]
    program = AtomProgram(transport_steps(0, 0, 0, "home"))
    result = replace(
        result,
        program=program,
        exit_state=entry,
        operations=(CompiledOperation(0, "emitted", 0, 2),),
        transport_goals=(TransportGoal(0, ((0, "home"), (1, "spectator"))),),
    )
    checked = validate_result(result, entry_state=entry, device=device, dag=dag)
    assert any(item["rule"] == "transport_goal_noop" for item in checked["failures"])


@pytest.mark.parametrize("damage", ("unattributed_move", "gate_action"))
def test_endpoint_alone_does_not_replace_native_transport_provenance(damage):
    dag, device, entry, result = native_case()
    steps = result.program.steps
    if damage == "unattributed_move":
        program = AtomProgram(
            (
                steps[0],
                AtomStep((replace(steps[1].actions[0], source_ids=()),)),
                steps[2],
            )
        )
    else:
        program = AtomProgram(
            (
                *steps,
                AtomStep(
                    (
                        Rotation(
                            "unavailable", (17,), "X", 0, duration_us=1, source_ids=(0,)
                        ),
                    )
                ),
            )
        )
        result = replace(result, operations=(CompiledOperation(0, "emitted", 0, 13),))
    result = replace(result, program=program)
    checked = validate_result(result, entry_state=entry, device=device, dag=dag)
    assert any(
        item["rule"] == "transport_goal_provenance" for item in checked["failures"]
    )


@pytest.mark.parametrize("stripped_prefix", (1, 2))
def test_unattributed_transport_prefix_cannot_shift_goal_start(stripped_prefix):
    dag, device, entry, result = native_case()
    program = AtomProgram(
        tuple(
            AtomStep((replace(step.actions[0], source_ids=()),))
            if index < stripped_prefix
            else step
            for index, step in enumerate(result.program.steps)
        )
    )
    result = replace(
        result,
        program=program,
        operations=(
            CompiledOperation(0, "emitted", 1 if stripped_prefix == 1 else 11, 12),
        ),
    )
    checked = validate_result(result, entry_state=entry, device=device, dag=dag)
    assert not checked["ok"]
    assert any(item["rule"] == "transport_goal_proof" for item in checked["failures"])


def test_goal_can_finish_inside_parallel_step_before_unrelated_wait():
    dag, device, entry, result = native_case()
    steps = result.program.steps
    result = replace(
        result,
        program=AtomProgram(
            (*steps[:2], AtomStep((*steps[2].actions, Wait(duration_us=5))))
        ),
    )
    assert result.duration_us == 16
    assert result.operations[0].end_us == 12
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]
