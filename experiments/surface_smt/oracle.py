"""Quantum evidence derived from actual Atom IR illumination and rotations.

This checks ideal stabilizer extraction and the four dangerous N/Z hooks.
It does not establish a repeated noisy memory circuit's fault distance.
"""

from itertools import combinations
from math import cos, hypot, sin

import numpy as np
import qiskit.qasm3
import stim
from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    CZPulse,
    Load,
    LocalU,
    Measure,
    Move,
    Reset,
    Rotation,
    Store,
    Wait,
)
from nadit_physical_compiler.motion import check_load, check_move, check_store
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.semantic_actions import check_action_semantics

from modules.codes.rotated_surface_d3.definition import CHECKS, DATA_COORDINATES

from .fixtures import Fixture


def _pauli(axis: str, atoms: tuple[int, ...]) -> stim.PauliString:
    value = stim.PauliString(17)
    for atom in atoms:
        value[atom] = axis
    return value


def _unitary(circuit: stim.Circuit) -> stim.Tableau:
    pure = stim.Circuit("I 16")
    for inst in circuit:
        if inst.name not in ("R", "M"):
            pure.append(inst)
    return stim.Tableau.from_circuit(pure)


def _source_circuit(source: str) -> stim.Circuit:
    parsed = qiskit.qasm3.loads(source)
    circuit = stim.Circuit("I 16")
    names = {"h": "H", "cx": "CX", "measure": "M", "reset": "R"}
    for inst in parsed.data:
        if inst.operation.name == "barrier":
            circuit.append("TICK")
        else:
            circuit.append(
                names[inst.operation.name],
                [parsed.find_bit(q).index for q in inst.qubits],
            )
    return circuit


def verify_quantum(fixture: Fixture, program: AtomProgram) -> dict:
    """Raise on an invalid witness; return independently computed evidence."""
    layout, device, dag = fixture.entry_state, fixture.device, fixture.dag
    actual = stim.Circuit("I 16")
    step_circuits: list[stim.Circuit] = []
    wire_source_end: dict[tuple[int, int], int] = {}
    seen: set[int] = set()
    parents = {n.id: set() for n in dag.nodes}
    for a, b in dag.edges:
        parents[b].add(a)
    measured = []
    reset = []
    cz_count = 0
    matrices = {
        "X": np.array([[0, 1], [1, 0]]),
        "Y": np.array([[0, -1j], [1j, 0]]),
        "Z": np.diag([1, -1]),
    }
    for step_index, step in enumerate(program.steps):
        part = stim.Circuit()
        emitted = tuple(i for action in step.actions for i in action.source_ids)
        if len(emitted) != len(set(emitted)) or seen.intersection(emitted):
            raise ValueError("Native operations must be emitted exactly once.")
        if any(not parents[i] <= seen for i in emitted):
            raise ValueError("Native per-wire dependencies are not respected.")
        for action in step.actions:
            constraint = None
            if isinstance(action, Load):
                constraint = check_load(
                    device,
                    layout,
                    action.grid,
                    {a: (r, c) for a, r, c in action.bindings},
                )
            elif isinstance(action, Move):
                constraint = check_move(
                    device, layout, action.grid, dict(action.targets)
                )
            elif isinstance(action, Store):
                constraint = check_store(
                    device, layout, action.grid, dict(action.bindings)
                )
            if constraint is not None and not constraint.ok:
                raise ValueError(f"Transport {constraint.rule}: {constraint.message}")
            if isinstance(action, Rotation | LocalU):
                if isinstance(action, Rotation):
                    angle = action.angle / 2
                    matrix = (
                        cos(angle) * np.eye(2) - 1j * sin(angle) * matrices[action.axis]
                    )
                else:
                    a, p, lam = action.theta / 2, action.phi, action.lam
                    matrix = np.array(
                        [
                            [cos(a), -np.exp(1j * lam) * sin(a)],
                            [np.exp(1j * p) * sin(a), np.exp(1j * (p + lam)) * cos(a)],
                        ]
                    )
                local = stim.Tableau.from_unitary_matrix(
                    matrix, endian="little"
                ).to_circuit()
                for atom in action.atoms:
                    for inst in local:
                        part.append(inst.name, [atom for _ in inst.targets_copy()])
            elif isinstance(action, CZPulse):
                illuminated = [
                    a
                    for a in layout.atoms
                    if (
                        a.id in action.coverage
                        if isinstance(action.coverage, tuple)
                        else action.coverage.contains(a.position)
                    )
                ]
                pairs = {
                    tuple(sorted((a.id, b.id)))
                    for a, b in combinations(illuminated, 2)
                    if hypot(a.position.x - b.position.x, a.position.y - b.position.y)
                    <= device.cz.radius_um
                }
                expected = {
                    tuple(sorted(dag.nodes[i].qubits)) for i in action.source_ids
                }
                if pairs != expected:
                    raise ValueError(
                        f"Actual interactions {pairs} differ from intended {expected}."
                    )
                for pair in sorted(pairs):
                    part.append("CZ", pair)
                cz_count += len(pairs)
            elif isinstance(action, Reset):
                reset.extend(action.atoms)
                part.append("R", action.atoms)
            elif isinstance(action, Measure):
                for atom, result in action.results:
                    measured.append((atom, result.measurement_id))
                    part.append("M", [atom])
            elif not isinstance(action, Load | Move | Store | Wait):
                raise TypeError(f"Unsupported oracle action {type(action).__name__}.")
            failures = check_action_semantics(dag, device, layout, action, step)
            if failures:
                raise ValueError(f"Action semantics: {failures}")
            for node_id in action.source_ids:
                node = dag.nodes[node_id]
                for qubit in node.qubits:
                    wire_source_end[node.source_id, qubit] = step_index
        seen.update(emitted)
        actual += part
        step_circuits.append(part)
        actual.append("TICK")
        layout = apply_step(layout, step, device)
    if seen != set(range(len(dag.nodes))):
        raise ValueError("The program omitted native operations.")
    if layout != fixture.entry_state:
        raise ValueError("The full round did not return every atom to its home.")
    expected_measurements = {
        (n.qubits[0], n.result.measurement_id) for n in dag.nodes if n.name == "measure"
    }
    if (
        set(measured) != expected_measurements
        or len(measured) != 8
        or sorted(reset) != list(range(9, 17))
    ):
        raise ValueError(
            "Reset or measurement identity differs from the fixed SE source."
        )
    if _unitary(actual) != _unitary(_source_circuit(fixture.source_qasm)):
        raise ValueError("Actual Atom IR and source Clifford tableaux differ.")
    inverse = _unitary(actual).inverse()
    for i, (basis, support) in enumerate(CHECKS):
        if inverse.z_output(9 + i) != _pauli(basis, support) * _pauli("Z", (9 + i,)):
            raise ValueError(
                f"Measurement {i} does not measure its declared stabilizer."
            )
    parsed = qiskit.qasm3.loads(fixture.scheduling_qasm)
    hooks = []
    for i, (basis, support) in enumerate(CHECKS):
        if len(support) != 4:
            continue
        ancilla = 9 + i
        cx_sources = [
            j
            for j, inst in enumerate(parsed.data)
            if inst.operation.name == "cx"
            and ancilla in [parsed.find_bit(q).index for q in inst.qubits]
        ]
        suffix = stim.Circuit("I 16")
        for part in step_circuits[wire_source_end[cx_sources[1], ancilla] + 1 :]:
            suffix += part
        tableau = _unitary(suffix)
        error = tableau.x_output(ancilla) if basis == "X" else tableau.z_output(ancilla)
        data = [q for q in range(9) if error[q]]
        axis = 1 if basis == "X" else 0
        if (
            len(data) != 2
            or DATA_COORDINATES[data[0]][axis] != DATA_COORDINATES[data[1]][axis]
        ):
            raise ValueError(f"Ancilla {ancilla} has changed its N/Z hook direction.")
        hooks.append("horizontal" if basis == "X" else "vertical")
    return {
        "valid": True,
        "cz_count": cz_count,
        "measurements": len(measured),
        "hook_directions": hooks,
        "round_home": True,
        "native_operations": len(seen),
        "quantum_scope": "Ideal stabilizer extraction and N/Z hooks; not full circuit fault distance.",
    }
