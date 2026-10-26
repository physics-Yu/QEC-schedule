"""Native relocation shares one ready frontier and actual AOD planning."""

from dataclasses import replace

import pytest

from nadit_physical_compiler.atom_ir import CZPulse, Load, Measure, Rotation, Store
from nadit_physical_compiler.capabilities import (
    CZCapability,
    LocalControl,
    ReadoutCapability,
)
from nadit_physical_compiler.compiler import CompilationResult, compile_physical
from nadit_physical_compiler.contracts import TransportGoal
from nadit_physical_compiler.device import (
    AOD,
    Device,
    PairArray,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy
from nadit_physical_compiler.validation import validate_result


def fixture(*, readout: bool = False) -> tuple[Device, AtomLayout, TransportGoal]:
    """Three participants and one spectator, with real vacant receiving cells."""
    left = tuple(tuple(f"l{r}_{c}" for c in range(6)) for r in range(3))
    right = tuple(tuple(f"r{r}_{c}" for c in range(6)) for r in range(3))
    sites = tuple(
        SLMSite(f"{side}{r}_{c}", Position(10 * c + shift, -10 * r))
        for r in range(3)
        for c in range(6)
        for side, shift in (("l", 0), ("r", 2))
    )
    device = Device(
        "joint-goals",
        (
            Zone("storage", Region(-2, -22, 55, 2), ("cz", "rotate", "reset")),
            Zone("readout", Region(-2, 50, 55, 70), ("measure",)),
        ),
        sites,
        (AOD("a", Region(-5, -25, 60, 75), 1),),
        Timing(10, 10, 1),
        cz=CZCapability("rydberg", 4.6, 0.5, allow_spectators=True),
        local=LocalControl("local", 1, 5),
        readout=ReadoutCapability("camera", 100, 0, 5, True, ("aod",), None),
        pair_arrays=(PairArray("cells", "storage", left, right),),
    )
    homes = ("l0_0", "l0_1", "l1_0" if readout else "l1_2", "l2_4")
    entry = AtomLayout(
        tuple(
            AtomState(i, device.site(home).position, SLMHolder(home))
            for i, home in enumerate(homes)
        ),
        qubit_to_atom=(0, 1, 2, 3),
    )
    return device, entry, TransportGoal(1, ((2, "l2_0" if readout else "l1_3"),))


def compile_case(
    name: str = "cz",
) -> tuple[Device, AtomLayout, TransportGoal, PhysicalDAG, CompilationResult]:
    device, entry, goal = fixture(readout=name == "measure")
    qubits = (0, 1) if name == "cz" else (0,)
    dag = PhysicalDAG(
        4,
        int(name == "measure"),
        (
            PhysicalOperation(
                0,
                name,
                qubits,
                (0,) if name == "measure" else (),
                (0.25,) if name == "rz" else (),
            ),
            PhysicalOperation(1, "relocate", (2,), (), ()),
        ),
        (),
    )
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    result = compile_physical(dag, device, strategy=strategy, entry_state=entry)
    return device, entry, goal, dag, result


def test_ready_relocation_and_disjoint_gate_share_layer() -> None:
    _, _, _, _, result = compile_case()
    assert result.layers[0].operation_ids == (0, 1)
    assert len(result.layers) == 1


@pytest.mark.parametrize("name", ["cz", "measure", "rz"])
def test_joint_plan_preserves_atoms_and_leaves_only_requested_relocation(
    name: str,
) -> None:
    device, entry, goal, dag, result = compile_case(name)
    assert result.exit_state == replay(result.program, entry, device)
    expected_site = goal.targets[0][1]
    assert result.exit_state.atom(2) == AtomState(
        2, device.site(expected_site).position, SLMHolder(expected_site)
    )
    assert all(result.exit_state.atom(i) == entry.atom(i) for i in (0, 1, 3))
    assert result.exit_state.qubit_to_atom == entry.qubit_to_atom
    assert result.exit_state.aod_grids == ()
    report = validate_result(result, entry_state=entry, device=device, dag=dag)
    assert report["ok"], report
    relocation_stores = [
        a
        for s in result.program.steps
        for a in s.actions
        if isinstance(a, Store) and 1 in a.source_ids
    ]
    assert relocation_stores and (2, expected_site) in relocation_stores[-1].bindings


@pytest.mark.parametrize("name", ["cz", "measure"])
def test_gate_arrival_and_relocation_use_same_physical_load(name: str) -> None:
    _, _, _, _, result = compile_case(name)
    loads = [a for s in result.program.steps for a in s.actions if isinstance(a, Load)]
    assert any(
        2 in {b[0] for b in a.bindings} and bool({0, 1} & {b[0] for b in a.bindings})
        for a in loads
    )
    operation_type = CZPulse if name == "cz" else Measure
    assert (
        sum(
            isinstance(a, operation_type)
            for s in result.program.steps
            for a in s.actions
        )
        == 1
    )


def test_local_gate_overlaps_actual_transport_step() -> None:
    device, _, _, _, result = compile_case("rz")
    first = result.program.steps[0]
    assert any(isinstance(a, Load) for a in first.actions)
    assert any(isinstance(a, Rotation) for a in first.actions)
    assert result.operations[0].start_us == result.operations[1].start_us == 0
    assert device.local is not None
    assert result.operations[0].end_us == device.local.rotation_us


@pytest.mark.parametrize("site", ["l0_0", "missing"])
def test_invalid_destination_rejected_before_emission(site: str) -> None:
    device, entry, goal = fixture()
    goal = replace(goal, targets=((2, site),))
    dag = PhysicalDAG(4, 0, (PhysicalOperation(0, "relocate", (2,), (), ()),), ())
    goal = replace(goal, operation_id=0)
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    with pytest.raises((ValueError, KeyError)):
        compile_physical(dag, device, strategy=strategy, entry_state=entry)


def test_relocation_target_cannot_create_unintended_cz_pair() -> None:
    device, entry, goal = fixture()
    goal = replace(goal, targets=((2, "r2_4"),))
    dag = PhysicalDAG(
        4,
        0,
        (
            PhysicalOperation(0, "cz", (0, 1), (), ()),
            PhysicalOperation(1, "relocate", (2,), (), ()),
        ),
        (),
    )
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    with pytest.raises(ValueError, match="unintended"):
        compile_physical(dag, device, strategy=strategy, entry_state=entry)


def test_goals_use_native_wires_and_share_one_joint_frontier() -> None:
    device, entry, goal = fixture()
    ids = (41, 7, 90, 3)
    entry = replace(
        entry,
        atoms=tuple(replace(a, id=ids[a.id]) for a in entry.atoms),
        qubit_to_atom=ids,
    )
    second = TransportGoal(2, ((3, "l2_5"),))
    dag = PhysicalDAG(
        4,
        0,
        (
            PhysicalOperation(0, "cz", (0, 1), (), ()),
            PhysicalOperation(1, "relocate", (2,), (), ()),
            PhysicalOperation(2, "relocate", (3,), (), ()),
        ),
        (),
    )
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal, second)
    )
    result = compile_physical(dag, device, strategy=strategy, entry_state=entry)
    assert result.layers[0].operation_ids == (0, 1, 2)
    assert result.exit_state.atom(90).holder == SLMHolder("l1_3")
    assert result.exit_state.atom(3).holder == SLMHolder("l2_5")
    assert result.exit_state.qubit_to_atom == ids
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]


def test_readout_capacity_keeps_goal_in_shared_physical_plan() -> None:
    device, entry, _ = fixture(readout=True)
    assert device.readout is not None
    device = replace(device, readout=replace(device.readout, max_atoms=1))
    goal = TransportGoal(2, ((2, "l2_0"),))
    dag = PhysicalDAG(
        4,
        2,
        (
            PhysicalOperation(0, "measure", (0,), (0,), ()),
            PhysicalOperation(1, "measure", (1,), (1,), ()),
            PhysicalOperation(2, "relocate", (2,), (), ()),
        ),
        (),
    )
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    result = compile_physical(dag, device, strategy=strategy, entry_state=entry)
    assert result.layers[0].operation_ids == (0, 1, 2)
    loads = [a for s in result.program.steps for a in s.actions if isinstance(a, Load)]
    assert any({b[0] for b in a.bindings} == {0, 2} for a in loads)
    measurements = [
        a for s in result.program.steps for a in s.actions if isinstance(a, Measure)
    ]
    assert len(measurements) == 2
    assert all(len(a.results) == 1 for a in measurements)
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]


def test_partial_presatisfied_goal_is_legal_and_all_noop_is_rejected() -> None:
    device, entry, _ = fixture()
    dag = PhysicalDAG(4, 0, (PhysicalOperation(0, "relocate", (2, 3), (), ()),), ())
    goal = TransportGoal(0, ((2, "l1_3"), (3, "l2_4")))
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    result = compile_physical(dag, device, strategy=strategy, entry_state=entry)
    assert result.exit_state.atom(3) == entry.atom(3)
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]
    with pytest.raises(ValueError, match="displace"):
        compile_physical(dag, device, strategy=strategy, entry_state=result.exit_state)


def test_following_gate_uses_committed_relocation_position() -> None:
    device, entry, _ = fixture()
    goal = TransportGoal(0, ((2, "l1_3"),))
    dag = PhysicalDAG(
        4,
        0,
        (
            PhysicalOperation(0, "relocate", (2,), (), ()),
            PhysicalOperation(1, "rz", (2,), (), (0.25,)),
        ),
        ((0, 1),),
    )
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    result = compile_physical(dag, device, strategy=strategy, entry_state=entry)
    assert [layer.operation_ids for layer in result.layers] == [(0,), (1,)]
    assert result.operations[1].start_us >= result.operations[0].end_us
    assert result.exit_state.atom(2).holder == SLMHolder("l1_3")
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]


def test_global_pulse_mixed_with_transport_is_explicitly_unsupported() -> None:
    device, entry, goal = fixture()
    dag = PhysicalDAG(
        4,
        0,
        (
            PhysicalOperation(0, "global_ry", (0, 1, 3), (), (0.25,)),
            PhysicalOperation(1, "relocate", (2,), (), ()),
        ),
        (),
    )
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_MIXED_TRANSPORT_OPERATION"):
        compile_physical(dag, device, strategy=strategy, entry_state=entry)


def test_one_row_capacity_splits_actual_batches_inside_joint_frontier() -> None:
    device, entry, goal = fixture()
    device = replace(device, aods=(replace(device.aods[0], max_rows=1),))
    dag = PhysicalDAG(
        4,
        0,
        (
            PhysicalOperation(0, "cz", (0, 1), (), ()),
            PhysicalOperation(1, "relocate", (2,), (), ()),
        ),
        (),
    )
    strategy = NonZonedStrategy(
        "a", GatePairCatalog.from_pair_arrays(device), transport_goals=(goal,)
    )
    result = compile_physical(dag, device, strategy=strategy, entry_state=entry)
    assert result.layers[0].operation_ids == (0, 1)
    arrivals = []
    for step in result.program.steps:
        if any(isinstance(a, CZPulse) for a in step.actions):
            break
        arrivals.extend(a for a in step.actions if isinstance(a, Load))
    assert len(arrivals) == 2
    assert all(len(action.grid.rows) == 1 for action in arrivals)
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]
