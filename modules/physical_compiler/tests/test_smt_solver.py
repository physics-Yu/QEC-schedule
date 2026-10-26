"""Exact tiny optima and unsatisfiable bounds, independently replayed."""

from dataclasses import replace

from nadit_physical_compiler.capabilities import (
    CZCapability,
    LocalControl,
    ReadoutCapability,
)
from nadit_physical_compiler.compilers.contracts import ProgramContext
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
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation
from nadit_physical_compiler.smt.contracts import Plan, Snapshot
from nadit_physical_compiler.smt.solver import solve
from nadit_physical_compiler.state import AODGrid, AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.validation import validate_result


def tiny_context(radius=2.1):
    region = Region(0, 0, 10, 0)
    device = Device(
        "tiny-smt",
        (Zone("shared", region, ("cz", "rotate", "reset")),),
        tuple(SLMSite(str(x), Position(x, 0)) for x in (0, 2, 10)),
        (AOD("a", region, 1),),
        Timing(3, 5, 1),
        cz=CZCapability("cz", radius, 0.4),
        local=LocalControl("local", 1, 2),
    )
    entry = AtomLayout(
        (
            AtomState(0, Position(0, 0), SLMHolder("0")),
            AtomState(1, Position(10, 0), SLMHolder("10")),
        ),
        (AODGrid("a"),),
        (0, 1),
    )
    dag = PhysicalDAG(2, 0, (PhysicalOperation(0, "cz", (0, 1), (), ()),), ())
    return ProgramContext(dag, device, "a", None, entry)


def test_tiny_period_optimum_and_independent_replay():
    context = tiny_context()
    solved = solve(
        context,
        {
            "xs": [0, 2, 10],
            "ys": [0],
            "horizon": 5,
            "timeout_s": 20,
            "time_quantum_us": 0.1,
        },
        FakeBackend(),
    )
    assert solved.result is not None
    assert solved.evidence["status"] == "optimal_in_domain"
    assert abs(solved.result.program.duration_us - 24.4) < 1e-9
    assert solved.evidence["lower_bound_ticks"] == 244
    assert solved.result.exit_state.atoms == context.entry_state.atoms
    assert validate_result(
        solved.result,
        entry_state=context.entry_state,
        device=context.device,
        dag=context.dag,
    )["ok"]


def test_impossible_interaction_is_unsat_not_timeout():
    solved = solve(
        tiny_context(radius=1),
        {
            "xs": [0, 10],
            "ys": [0],
            "horizon": 3,
            "timeout_s": 10,
            "time_quantum_us": 0.1,
        },
        FakeBackend(),
    )
    assert solved.result is None
    assert solved.evidence["status"] == "unsat_in_domain"
    assert solved.evidence["queries"][0]["status"] == "unsat"


def test_seed_check_does_not_sample_backend_and_period_waits_for_result():
    context = tiny_context()
    context = replace(
        context,
        device=replace(
            context.device,
            zones=(Zone("shared", Region(0, 0, 10, 0), ("reset", "measure")),),
            readout=ReadoutCapability("readout", 5, latency_us=7),
        ),
        dag=PhysicalDAG(
            2,
            1,
            (
                PhysicalOperation(0, "reset", (0,), (), ()),
                PhysicalOperation(1, "measure", (0,), (0,), ()),
            ),
            ((0, 1),),
        ),
    )
    state = Snapshot(
        tuple(a.position for a in context.entry_state.atoms), (False, False)
    )
    seed = Plan((state, state, state), ("none", "none"), ((0,), (1,)))
    calls = []

    class CountingBackend:
        def measure(self, reference):
            calls.append(reference)
            return 1

    solved = solve(
        context,
        {
            "xs": [0, 2, 10],
            "ys": [0],
            "horizon": 2,
            "timeout_s": 10,
            "time_quantum_us": 0.1,
        },
        CountingBackend(),
        seed=seed,
    )
    assert solved.result is not None
    assert calls == [context.dag.nodes[1].result]
    assert solved.result.duration_us == 14
    assert solved.evidence["upper_bound_ticks"] == 140
    assert solved.evidence["status"] == "optimal_in_domain"
