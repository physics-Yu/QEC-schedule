"""Batch readout preserves physical results, spacing, and return layouts."""

from dataclasses import replace

import pytest
from strict_transport_support import _case

from nadit_physical_compiler import loads_qasm
from nadit_physical_compiler.atom_ir import AtomProgram, Move
from nadit_physical_compiler.capabilities import ReadoutCapability
from nadit_physical_compiler.compiler import compile_physical
from nadit_physical_compiler.contracts import GateLayer
from nadit_physical_compiler.device import Device, Position, Region, Zone
from nadit_physical_compiler.physical_ir import PhysicalDAG
from nadit_physical_compiler.placement import PairPlacer
from nadit_physical_compiler.readout import BatchReadout
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.scheduling import ReadyScheduler
from nadit_physical_compiler.state import AtomLayout
from nadit_physical_compiler.strategies import SearchSmarterStrategy
from nadit_physical_compiler.transport import StrictTransport
from nadit_physical_compiler.validation import validate_result


def setup_readout(
    sources: tuple[tuple[float, float], ...],
    *,
    capacity: int | None = None,
    stationary: tuple[tuple[float, float], ...] = (),
    height: float = 20,
    columns: int | None = None,
) -> tuple[Device, AtomLayout]:
    device, entry, _ = _case(sources, sources, stationary=stationary, columns=columns)
    return replace(
        device,
        zones=(Zone("measurement", Region(0, 40, 50, 40 + height), ("measure",)),),
        readout=ReadoutCapability("camera", 10, 500, 5, True, ("aod",), capacity),
    ), entry


def measure_dag(n: int) -> PhysicalDAG:
    return loads_qasm(
        'OPENQASM 3.0; include "stdgates.inc"; '
        f"qubit[{n}] q; bit[{n}] c; c = measure q;"
    )


def test_single_readout_finds_free_interior_when_anchors_are_busy() -> None:
    device, entry = setup_readout(((0, 0),), stationary=((0, 40), (50, 40)), height=0)
    dag = measure_dag(1)
    plan = PairPlacer("a").place(dag, GateLayer((0,)), entry, device)
    point = plan.execution_layout.atom(0).position
    assert 5 <= point.x <= 45 and point.y == 40
    assert plan.exit_layout == entry


def test_batch_readout_finds_free_positions_between_occupied_grid_anchors() -> None:
    device, entry = setup_readout(
        ((0, 0),), stationary=tuple((x, 40) for x in range(0, 51, 5)), height=0
    )
    dag = measure_dag(1)
    fragment = BatchReadout("a").lower(dag, GateLayer((0,)), entry, device)
    move = next(a for s in fragment.steps for a in s.actions if isinstance(a, Move))
    assert move.targets[0][1].x not in set(range(0, 51, 5))
    assert replay(AtomProgram(fragment.steps), entry, device) == entry


@pytest.mark.parametrize("padding", [1_000_000])
def test_half_plane_readout_uses_source_coordinates_independently_of_window_extent(
    padding: float,
) -> None:
    device, entry = setup_readout(((0, 0), (5, 0), (0, -5), (5, -5)))
    workspace = Region(-10 - padding, -10 - padding, 20 + padding, 70 + padding)
    device = replace(
        device,
        aods=(replace(device.aods[0], workspace=workspace),),
        zones=(
            Zone(
                "readout",
                Region(-10 - padding, 50, 20 + padding, 70 + padding),
                ("measure",),
            ),
        ),
    )
    dag = measure_dag(4)
    result = compile_physical(
        dag,
        device,
        strategy=SearchSmarterStrategy(
            ReadyScheduler(max_measurements=None),
            PairPlacer("a"),
            StrictTransport("a"),
            readout=BatchReadout("a"),
        ),
        entry_state=entry,
    )
    moves = [a for s in result.program.steps for a in s.actions if isinstance(a, Move)]
    assert dict(moves[0].targets) == {
        0: Position(0, 55),
        1: Position(5, 55),
        2: Position(0, 50),
        3: Position(5, 50),
    }
    assert validate_result(result, entry_state=entry, device=device, dag=dag)["ok"]
    assert replay(result.program, entry, device) == entry
