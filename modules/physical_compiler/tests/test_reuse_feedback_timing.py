"""Reuse observes result availability and actual positions after local controls."""

from dataclasses import replace
from pathlib import Path

import pytest
from reuse_compiler_support import _dag, _strategy
from strict_compiler_support import RecordingBackend, _audit, _entry

from nadit_physical_compiler import (
    AtomLayout,
    AtomState,
    Device,
    GateLayer,
    Load,
    PhysicalDAG,
    PlacementPlan,
    ResultRef,
    compile_physical,
    load_device,
)

MODULE = Path(__file__).parents[1]


@pytest.fixture
def device() -> Device:
    return load_device(MODULE / "configs/multipair_flexible.json")


@pytest.mark.parametrize("bit", [1])
def test_compiled_result_enables_reuse_while_actions_wait_for_feedback(
    device: Device, bit: int
) -> None:
    assert device.readout is not None
    device = replace(device, readout=replace(device.readout, latency_us=100_000))
    dag = _dag("c = measure q[0]; cz q[1],q[2]; if(c) { rz(0.2) q[1]; } cz q[1],q[2];")
    entry = _entry(device)
    backend = RecordingBackend(bit)
    strategy = _strategy(device)
    observations: list[tuple[GateLayer, tuple[int, ...], tuple[ResultRef, ...]]] = []

    class ObservedPlacer:
        def place(
            self,
            dag: PhysicalDAG,
            layer: GateLayer,
            layout: AtomLayout,
            device: Device,
            *,
            reuse_qubits: tuple[int, ...] = (),
            following: GateLayer | None = None,
            retained_atoms: tuple[AtomState, ...] = (),
        ) -> PlacementPlan:
            if dag.nodes[layer.operation_ids[0]].name == "cz":
                observations.append((layer, reuse_qubits, tuple(backend.calls)))
            return strategy.placer.place(
                dag,
                layer,
                layout,
                device,
                reuse_qubits=reuse_qubits,
                following=following,
                retained_atoms=retained_atoms,
            )

    result = compile_physical(
        dag,
        device,
        strategy=replace(strategy, placer=ObservedPlacer()),
        entry_state=entry,
        measurement_backend=backend,
    )

    _audit(dag, result, device, entry)
    measurement = result.measurements[0]
    first_layer, reuse_qubits, calls = observations[0]
    first_cz = result.operations[first_layer.operation_ids[0]]
    assert calls == (measurement.result,)
    assert first_cz.end_us < measurement.available_at_us
    assert reuse_qubits == (1, 2)
    assert backend.calls == [measurement.result]
    assert len(observations) == 2
    dependent = next(node for node in dag.nodes if node.condition is not None)
    assert result.operations[dependent.id].start_us >= measurement.available_at_us
    for qubit in reuse_qubits:
        assert (
            sum(
                atom == entry.qubit_to_atom[qubit]
                for step in result.program.steps
                for action in step.actions
                if isinstance(action, Load)
                for atom, _, _ in action.bindings
            )
            == 2
        )
