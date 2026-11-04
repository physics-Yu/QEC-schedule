"""Independent end-to-end checks for strict simultaneous transport batches."""

from collections import Counter
from itertools import combinations
from math import hypot
from pathlib import Path

import pytest

from nadit_physical_compiler.atom_ir import CZPulse, Load, Measure, Move, Store
from nadit_physical_compiler.compiler import CompilationResult
from nadit_physical_compiler.device import Device, Region, load_device
from nadit_physical_compiler.execution import FakeBackend
from nadit_physical_compiler.motion import check_load, check_move, check_store
from nadit_physical_compiler.physical_ir import PhysicalDAG, ResultRef
from nadit_physical_compiler.replay import apply_step, replay
from nadit_physical_compiler.state import (
    AODHolder,
    AtomLayout,
    AtomState,
    SLMHolder,
    validate_layout,
)

MODULE = Path(__file__).parents[1]


class RecordingBackend:
    """Record each stable source measurement while returning a chosen test case."""

    def __init__(self, bit: int | None) -> None:
        self.calls: list[ResultRef] = []
        self.bit = bit
        self.seeded = FakeBackend(17)

    def measure(self, result: ResultRef) -> int:
        self.calls.append(result)
        return self.seeded.measure(result) if self.bit is None else self.bit


@pytest.fixture
def device() -> Device:
    return load_device(MODULE / "configs/multipair_flexible.json")


def _entry(device: Device, count: int = 4) -> AtomLayout:
    sites = [site for site in device.slm_sites if site.id.startswith("storage_")]
    atoms = tuple(
        AtomState(37 + index * 13, site.position, SLMHolder(site.id))
        for index, site in enumerate(sites[:count])
    )
    return AtomLayout(atoms, qubit_to_atom=tuple(atom.id for atom in atoms))


def _audit(
    dag: PhysicalDAG, result: CompilationResult, device: Device, entry: AtomLayout
) -> None:
    """Check emitted geometry, time, dependencies, and source coverage."""
    layout = entry
    covered: Counter[int] = Counter()
    outcomes = {record.result: record for record in result.measurements}
    aod = device.aod("transport")
    for start, step in result.program.timeline():
        for action in step.actions:
            covered.update(action.source_ids)
            if isinstance(action, Load):
                checked = check_load(
                    device,
                    layout,
                    action.grid,
                    {atom: (row, column) for atom, row, column in action.bindings},
                )
                assert checked.ok, checked.message
                assert action.duration_us == device.timing.load_us
            elif isinstance(action, Move):
                checked = check_move(device, layout, action.grid, dict(action.targets))
                assert checked.ok, checked.message
                maximum = max(
                    hypot(
                        target.x - layout.atom(atom).position.x,
                        target.y - layout.atom(atom).position.y,
                    )
                    for atom, target in action.targets
                )
                assert action.duration_us == pytest.approx(
                    device.timing.move_duration(maximum)
                )
            elif isinstance(action, Store):
                checked = check_store(
                    device, layout, action.grid, dict(action.bindings)
                )
                assert checked.ok, checked.message
                assert action.duration_us == device.timing.store_us
            elif isinstance(action, CZPulse):
                assert device.cz is not None
                assert isinstance(action.coverage, Region)
                illuminated = [
                    atom
                    for atom in layout.atoms
                    if action.coverage.contains(atom.position)
                ]
                actual = {
                    frozenset((first.id, second.id))
                    for first, second in combinations(illuminated, 2)
                    if hypot(
                        first.position.x - second.position.x,
                        first.position.y - second.position.y,
                    )
                    <= device.cz.radius_um
                }
                intended = {
                    frozenset(entry.qubit_to_atom[q] for q in dag.nodes[index].qubits)
                    for index in action.source_ids
                }
                assert actual == intended
                assert {atom.id for atom in illuminated} == set().union(*intended)
                for index in action.source_ids:
                    record = result.operations[index]
                    assert record.start_us == start
                    assert record.end_us == start + device.cz.duration_us
            elif isinstance(action, Measure):
                assert device.readout is not None
                for atom_id, reference in action.results:
                    atom = layout.atom(atom_id)
                    assert isinstance(atom.holder, AODHolder)
                    assert device.zones_at(atom.position, "measure")
                    assert outcomes[reference].available_at_us == pytest.approx(
                        start + action.duration_us + device.readout.latency_us
                    )
            if isinstance(action, Load | Move | Store):
                if aod.max_columns is not None:
                    assert len(action.grid.columns) <= aod.max_columns
                if aod.max_rows is not None:
                    assert len(action.grid.rows) <= aod.max_rows
        layout = apply_step(layout, step, device)
        validate_layout(device, layout)
    assert layout == result.exit_state == replay(result.program, entry, device)
    for record in result.operations:
        assert covered[record.operation_id] == (1 if record.status == "emitted" else 0)
    for before, after in dag.edges:
        assert result.operations[before].end_us <= result.operations[after].start_us
    for node, record in zip(dag.nodes, result.operations, strict=True):
        if node.condition is not None:
            measurement = outcomes[node.condition.result]
            assert record.start_us >= measurement.available_at_us
            assert (record.status == "skipped") == (
                node.condition.value != measurement.value
            )
