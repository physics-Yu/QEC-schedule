"""Independent small plans exercise the generic SMT-to-Atom-IR boundary."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from nadit_physical_compiler.atom_ir import CZPulse, Load, Measure, Move, Reset, Store
from nadit_physical_compiler.capabilities import (
    CZCapability,
    LocalControl,
    ReadoutCapability,
)
from nadit_physical_compiler.compilers.contracts import (
    InvalidProgramResult,
    ProgramContext,
)
from nadit_physical_compiler.compilers.registry import select
from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.execution import FakeBackend
from nadit_physical_compiler.experiments import spec as experiment_spec
from nadit_physical_compiler.job import compile_job
from nadit_physical_compiler.physical_ir import (
    Condition,
    PhysicalDAG,
    PhysicalOperation,
    ResultRef,
)
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.smt.checker import check_lowering, check_plan
from nadit_physical_compiler.smt.contracts import Plan, Snapshot
from nadit_physical_compiler.smt.lowering import lower_plan
from nadit_physical_compiler.state import AODHolder, AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.support import UnsupportedJob
from nadit_physical_compiler.validation import validate_result


def context_and_plan(motion="flexible"):
    """Two atoms reset, interact, return home, and share one readout exposure."""
    bounds = Region(-1, -1, 7, 1)
    device = Device(
        "tiny-smt",
        (Zone("shared", bounds, ("cz", "reset", "measure", "rotation")),),
        (SLMSite("a", Position(0, 0)), SLMSite("b", Position(6, 0))),
        (AOD("aod", bounds, 1, motion=motion),),
        Timing(3, 7, 1),
        cz=CZCapability("cz", 2.1, 5),
        readout=ReadoutCapability("readout", 11, 13, max_atoms=None),
        local=LocalControl("local", 1, 2),
    )
    nodes = (
        PhysicalOperation(0, "reset", (0,), (), ()),
        PhysicalOperation(1, "reset", (1,), (), ()),
        PhysicalOperation(2, "cz", (0, 1), (), ()),
        PhysicalOperation(3, "measure", (0,), (0,), (), source_id=41),
        PhysicalOperation(4, "measure", (1,), (1,), (), source_id=73),
    )
    dag = PhysicalDAG(2, 2, nodes, ((0, 2), (1, 2), (2, 3), (2, 4)))
    entry = AtomLayout(
        (
            AtomState(7, Position(0, 0), SLMHolder("a")),
            AtomState(11, Position(6, 0), SLMHolder("b")),
        ),
        qubit_to_atom=(7, 11),
    )
    home = Snapshot((Position(0, 0), Position(6, 0)), (False, False))
    loaded = replace(home, carried=(False, True), columns=(6,), rows=(0,))
    near = replace(loaded, positions=(Position(0, 0), Position(2, 0)), columns=(2,))
    plan = Plan(
        (home, home, loaded, near, near, loaded, home, home),
        ("none", "load", "move", "none", "move", "store", "none"),
        ((0, 1), (), (), (2,), (), (), (3, 4)),
    )
    return ProgramContext(dag, device, "aod", None, entry), plan


@pytest.mark.parametrize("motion", ["flexible", "rigid"])
def test_lower_plan_preserves_controls_results_and_home(motion):
    context, plan = context_and_plan(motion)
    backend = FakeBackend(overrides={ResultRef(41): 1, ResultRef(73): 0})
    result = lower_plan(context, plan, backend)
    actions = [action for step in result.program.steps for action in step.actions]
    assert [type(action) for action in actions] == [
        Reset,
        Load,
        Move,
        CZPulse,
        Move,
        Store,
        Measure,
    ]
    assert [action.duration_us for action in actions] == [2, 3, 4, 5, 4, 7, 11]
    assert actions[0].atoms == (7, 11)
    assert actions[-1].results == ((7, ResultRef(41)), (11, ResultRef(73)))
    assert [
        (record.result, record.value, record.available_at_us)
        for record in result.measurements
    ] == [(ResultRef(41), 1, 49), (ResultRef(73), 0, 49)]
    assert result.exit_state == context.entry_state
    assert (
        replay(result.program, context.entry_state, context.device)
        == context.entry_state
    )
    assert result.program.duration_us == 36
    assert result.duration_us == 49
    report = validate_result(
        result, entry_state=context.entry_state, device=context.device, dag=context.dag
    )
    assert report["ok"], report
    assert check_plan(context, plan) == []
    assert check_lowering(context, plan, result) == []


def test_registry_resolves_smt_without_loading_solver():
    context, _ = context_and_plan()
    compiler, options = select(
        context,
        {"kind": "smt", "xs": [0, 2, 6], "ys": [0], "horizon": 7},
        entry={"kind": "explicit"},
    )
    assert compiler.__class__.__name__ == "SMTCompiler"
    assert options["timeout_s"] == 60
    assert options["time_quantum_us"] == 0.001


def test_smt_admission_and_budget_follow_declared_capabilities():
    context, _ = context_and_plan()
    options = {"kind": "smt", "xs": [0, 2, 6], "ys": [0], "horizon": 7}
    _, records = experiment_spec.apply_budget(
        options, {"timeout_s": 100, "search_nodes": 50}
    )
    assert records["timeout_s"]["path"] == "worker.timeout_s"
    assert records["search_nodes"]["status"] == "not_applicable"
    nodes = list(context.dag.nodes)
    nodes[4] = replace(nodes[4], condition=Condition(ResultRef(41)))
    conditional = replace(context, dag=replace(context.dag, nodes=tuple(nodes)))
    with pytest.raises(UnsupportedJob, match="feedback"):
        select(conditional, options, entry={"kind": "explicit"})
    with pytest.raises(UnsupportedJob, match="entry"):
        select(context, options, entry={"kind": "initial_storage"})


def test_smt_rejects_carried_entry_before_solver_import():
    context, _ = context_and_plan()
    compiler, options = select(
        context,
        {"kind": "smt", "xs": [0, 2, 6], "ys": [0], "horizon": 7},
        entry={"kind": "explicit"},
    )
    atoms = list(context.entry_state.atoms)
    atoms[1] = replace(atoms[1], holder=AODHolder("other-aod", 0, 0))
    carried = replace(
        context, entry_state=replace(context.entry_state, atoms=tuple(atoms))
    )
    with pytest.raises(UnsupportedJob, match="SLM-held entry"):
        compiler.compile(carried, options, FakeBackend())


def test_lowering_preserves_empty_line_identity_and_allocates_fresh_load_ids():
    context, plan = context_and_plan()
    states = tuple(
        replace(state, columns=(*state.columns, state.columns[0] + 1))
        if state.columns
        else state
        for state in plan.states
    )
    plan = replace(
        plan,
        states=(*states, states[2], states[0]),
        transitions=(*plan.transitions, "load", "store"),
        operations=(*plan.operations, (), ()),
    )
    result = lower_plan(context, plan, FakeBackend())
    transports = [
        action
        for step in result.program.steps
        for action in step.actions
        if isinstance(action, Load | Move | Store)
    ]
    assert [(line.id, line.coordinate) for line in transports[0].grid.columns] == [
        (0, 6),
        (1, 7),
    ]
    assert [(line.id, line.coordinate) for line in transports[1].grid.columns] == [
        (0, 2),
        (1, 3),
    ]
    assert [(line.id, line.coordinate) for line in transports[2].grid.columns] == [
        (0, 6),
        (1, 7),
    ]
    assert [(line.id, line.coordinate) for line in transports[4].grid.columns] == [
        (2, 6),
        (3, 7),
    ]
    assert result.exit_state == context.entry_state
    report = validate_result(
        result, entry_state=context.entry_state, device=context.device, dag=context.dag
    )
    assert report["ok"], report


def test_job_rejects_invalid_duration_from_smt_adapter(monkeypatch):
    context, plan = context_and_plan()
    result = lower_plan(context, plan, FakeBackend())
    steps = list(result.program.steps)
    steps[0] = replace(steps[0], actions=(replace(steps[0].actions[0], duration_us=0),))
    broken = replace(result, program=replace(result.program, steps=tuple(steps)))
    compiler, options = select(
        context,
        {"kind": "smt", "xs": [0, 2, 6], "ys": [0], "horizon": 7},
        entry={"kind": "explicit"},
    )
    monkeypatch.setattr(type(compiler), "compile", lambda *args: broken)
    job = SimpleNamespace(
        dag=context.dag,
        device=context.device,
        document={"aod": "aod", "strategy": options},
        catalog=None,
        entry_state=context.entry_state,
        strategy=compiler,
        measurement_backend=FakeBackend(),
    )
    with pytest.raises(InvalidProgramResult, match="duration_mismatch"):
        compile_job(job)


@pytest.mark.parametrize(
    "change, rule",
    [
        ("ghost", "intersection"),
        ("store", "intersection"),
        ("home", "final_home"),
        ("duplicate", "operation_coverage"),
        ("dependency", "dependency_order"),
    ],
)
def test_independent_plan_checks_reject_tampering(change, rule):
    context, plan = context_and_plan()
    states = list(plan.states)
    if change == "ghost":
        states[2] = replace(states[2], carried=(False, False))
    elif change == "store":
        states[6] = replace(states[6], columns=(6,), rows=(0,))
    elif change == "home":
        states[-1] = replace(
            states[-1], positions=tuple(reversed(states[-1].positions))
        )
    elif change == "duplicate":
        plan = replace(plan, operations=((0, 0, 1), *plan.operations[1:]))
    else:
        groups = list(plan.operations)
        groups[0], groups[3] = (), (0, 1, 2)
        plan = replace(plan, operations=tuple(groups))
    errors = check_plan(context, replace(plan, states=tuple(states)))
    assert any(rule in error for error in errors), errors


@pytest.mark.parametrize("motion", ["flexible", "rigid"])
def test_independent_rigid_check_includes_empty_lines(motion):
    context, plan = context_and_plan(motion)
    states = list(plan.states)
    for index in (2, 5):
        states[index] = replace(states[index], columns=(6, 7))
    for index in (3, 4):
        states[index] = replace(states[index], columns=(2, 4))
    errors = check_plan(context, replace(plan, states=tuple(states)))
    if motion == "rigid":
        assert any("rigid_translation" in error for error in errors)
    else:
        assert errors == []


def test_independent_rank_check_rejects_atom_switching_lines():
    context, plan = context_and_plan()
    states = list(plan.states)
    for index in (2, 5):
        states[index] = replace(states[index], columns=(6, 7))
    for index in (3, 4):
        states[index] = replace(states[index], columns=(1, 2))
    errors = check_plan(context, replace(plan, states=tuple(states)))
    assert any("line_rank" in error for error in errors), errors


def test_lowering_snapshot_check_detects_extra_empty_line():
    from nadit_physical_compiler.state import AODLine

    context, plan = context_and_plan()
    result = lower_plan(context, plan, FakeBackend())
    steps = list(result.program.steps)
    action = steps[1].actions[0]
    changed = replace(
        action,
        grid=replace(action.grid, columns=(*action.grid.columns, AODLine(99, 7))),
    )
    steps[1] = replace(steps[1], actions=(changed,))
    result = replace(result, program=replace(result.program, steps=tuple(steps)))
    errors = check_lowering(context, plan, result)
    assert any("snapshot_mismatch at state 2" in error for error in errors), errors
