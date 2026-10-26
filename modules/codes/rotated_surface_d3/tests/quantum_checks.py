"""Independent ideal quantum calculations used only by component tests."""

from itertools import combinations
from math import cos, hypot, sin

import numpy as np
import qiskit.qasm3
import stim
from nadit_physical_compiler.atom_ir import (
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
from nadit_physical_compiler.replay import apply_step


def pauli(basis, support, n=17):
    result = stim.PauliString(n)
    for q in support:
        result[q] = basis
    return result


def source_stim(source):
    qc = qiskit.qasm3.loads(source)
    circuit = stim.Circuit("I 16")
    measurements = []
    mapping = {"reset": "R", "h": "H", "cx": "CX", "measure": "M"}
    for inst in qc.data:
        if inst.operation.name == "barrier":
            circuit.append("TICK")
        else:
            qs = [qc.find_bit(q).index for q in inst.qubits]
            circuit.append(mapping[inst.operation.name], qs)
            if inst.operation.name == "measure":
                measurements.extend(qc.find_bit(c).index for c in inst.clbits)
    return circuit, measurements


def action_stim(expansion, device):
    """Derive gates from actual illuminated geometry, never copying DAG pairs."""
    wires = {atom: i for i, atom in enumerate(expansion.wire_atoms)}
    circuit = stim.Circuit("I 16")
    layout = expansion.entry_state
    ids = []
    matrices = {
        "X": np.array([[0, 1], [1, 0]]),
        "Y": np.array([[0, -1j], [1j, 0]]),
        "Z": np.diag([1, -1]),
    }
    for step in expansion.program.steps:
        for action in step.actions:
            if isinstance(action, Rotation | LocalU):
                if isinstance(action, Rotation):
                    a = action.angle / 2
                    matrix = cos(a) * np.eye(2) - 1j * sin(a) * matrices[action.axis]
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
                        circuit.append(
                            inst.name, [wires[atom] for _ in inst.targets_copy()]
                        )
            elif isinstance(action, CZPulse):
                atoms = [
                    a
                    for a in layout.atoms
                    if (
                        a.id in action.coverage
                        if isinstance(action.coverage, tuple)
                        else action.coverage.contains(a.position)
                    )
                ]
                for a, b in combinations(atoms, 2):
                    if (
                        hypot(a.position.x - b.position.x, a.position.y - b.position.y)
                        <= device.cz.radius_um
                    ):
                        circuit.append("CZ", [wires[a.id], wires[b.id]])
            elif isinstance(action, Reset):
                circuit.append("R", [wires[a] for a in action.atoms])
            elif isinstance(action, Measure):
                for atom, ref in action.results:
                    circuit.append("M", [wires[atom]])
                    ids.append(ref.measurement_id)
            elif not isinstance(action, Load | Move | Store | Wait):
                raise TypeError(type(action))
        layout = apply_step(layout, step, device)
        circuit.append("TICK")
    assert layout == expansion.exit_state
    return circuit, ids


def postselect(circuit, values, sim=None):
    """Enumerate a quantum branch for verification, not a production accept rule."""
    sim = sim or stim.TableauSimulator(seed=23)
    index, probability = 0, 1.0
    for inst in circuit:
        if inst.name == "M":
            for target in inst.targets_copy():
                bit = values[index]
                expectation = sim.peek_z(target.value)
                probability *= (1 + (1 - 2 * bit) * expectation) / 2
                sim.postselect_z(target.value, desired_value=bool(bit))
                index += 1
        else:
            sim.do(inst)
    assert index == len(values)
    return sim, probability


def unitary(circuit):
    part = stim.Circuit("I 16")
    for inst in circuit:
        if inst.name not in ("R", "M"):
            part.append(inst)
    return stim.Tableau.from_circuit(part)
