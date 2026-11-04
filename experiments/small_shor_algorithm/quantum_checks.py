"""Independent ideal-state evidence for the small Shor compilation campaign."""

from itertools import combinations
from math import hypot

import numpy as np
from nadit_physical_compiler.atom_ir import (
    CPhasePulse,
    CZPulse,
    LocalU,
    Measure,
    Reset,
)
from nadit_physical_compiler.replay import apply_step
from qiskit import qasm3
from qiskit.circuit.library import CPhaseGate, CZGate, HGate, PhaseGate, TdgGate, TGate
from qiskit.quantum_info import Statevector


def check_raw_static_source(source_path, trajectory):
    """Compare the original QASM unitary with the imported native DAG state."""
    circuit = qasm3.loads(source_path.read_text(encoding="utf-8"))
    unitary = circuit.copy_empty_like()
    started = False
    for item in circuit.data:
        if item.operation.name == "reset":
            if started:
                raise ValueError("Static source check requires leading resets.")
            continue
        if item.operation.name in ("measure", "barrier"):
            continue
        started = True
        unitary.append(item.operation, item.qubits)
    reference = Statevector.from_instruction(unitary).data
    fidelity = float(abs(np.vdot(reference, trajectory[4])) ** 2)
    assert abs(fidelity - 1) < 1e-10, fidelity
    return fidelity


def project(vector, qubit, bit):
    """Project onto a recorded outcome and return its conditional probability."""
    mask = ((np.arange(len(vector)) >> qubit) & 1) == bit
    probability = float(np.sum(np.abs(vector[mask]) ** 2))
    if probability < 1e-13:
        raise ValueError(f"Impossible ideal outcome: qubit {qubit}, bit {bit}.")
    result = vector.copy()
    result[~mask] = 0
    return result / np.sqrt(probability), probability


def local(vector, qubit, matrix):
    """Apply an explicit 2x2 matrix using little-endian amplitude indices."""
    ids = np.arange(len(vector))
    zero = ids[(ids & (1 << qubit)) == 0]
    one = zero | (1 << qubit)
    result = vector.copy()
    result[zero] = matrix[0, 0] * vector[zero] + matrix[0, 1] * vector[one]
    result[one] = matrix[1, 0] * vector[zero] + matrix[1, 1] * vector[one]
    return result


def source_trajectory(dag, seed=17):
    """Use Qiskit gate matrices to sample one valid source-DAG trajectory."""
    rng = np.random.default_rng(seed)
    state = Statevector.from_int(0, 2**dag.num_qubits)
    outcomes, resets, probabilities = {}, {}, {}
    pre_readout = None
    constructors = {
        "h": HGate,
        "t": TGate,
        "tdg": TdgGate,
        "p": PhaseGate,
        "cz": CZGate,
        "cp": CPhaseGate,
    }
    for node in dag.nodes:
        if (
            node.condition
            and outcomes[node.condition.result.measurement_id] != node.condition.value
        ):
            continue
        if node.name in ("barrier", "global_phase"):
            continue
        if node.name in ("measure", "reset"):
            q = node.qubits[0]
            p1 = float(state.probabilities([q])[1])
            bit = int(rng.random() < p1)
            if node.name == "measure" and pre_readout is None:
                pre_readout = state.data.copy()
            vector, probability = project(state.data, q, bit)
            if node.name == "measure":
                outcomes[node.source_id] = bit
                probabilities[node.source_id] = probability
            else:
                resets[node.id] = bit
                if bit:
                    vector = local(vector, q, np.array([[0, 1], [1, 0]]))
            state = Statevector(vector)
        else:
            state = state.evolve(
                constructors[node.name](*node.params), list(node.qubits)
            )
    return outcomes, resets, probabilities, state.data, pre_readout


def check_atom_trajectory(job, result, trajectory):
    """Replay actual illuminated pairs and explicit U matrices, independently."""
    outcomes, resets, probabilities, expected, source_pre = trajectory
    state = np.zeros(2**job.dag.num_qubits, dtype=complex)
    state[0] = 1
    layout = job.entry_state
    wires = {atom: q for q, atom in enumerate(layout.qubit_to_atom)}
    probability_errors = []
    pre_readout = None
    for step in result.program.steps:
        for action in step.actions:
            if isinstance(action, LocalU):
                theta, phi, lam = action.theta, action.phi, action.lam
                c, s = np.cos(theta / 2), np.sin(theta / 2)
                matrix = np.array(
                    [
                        [c, -np.exp(1j * lam) * s],
                        [np.exp(1j * phi) * s, np.exp(1j * (phi + lam)) * c],
                    ]
                )
                for atom in action.atoms:
                    state = local(state, wires[atom], matrix)
            elif isinstance(action, CZPulse | CPhasePulse):
                coverage = action.coverage
                atoms = [
                    a
                    for a in layout.atoms
                    if (
                        a.id in coverage
                        if isinstance(coverage, tuple)
                        else coverage.contains(a.position)
                    )
                ]
                capability = (
                    job.device.cphase
                    if isinstance(action, CPhasePulse)
                    else job.device.cz
                )
                angle = action.angle if isinstance(action, CPhasePulse) else np.pi
                ids = np.arange(len(state))
                for a, b in combinations(atoms, 2):
                    if (
                        hypot(a.position.x - b.position.x, a.position.y - b.position.y)
                        <= capability.radius_um
                    ):
                        mask = ((ids >> wires[a.id]) & 1) & ((ids >> wires[b.id]) & 1)
                        state[mask.astype(bool)] *= np.exp(1j * angle)
            elif isinstance(action, Reset):
                for atom, source_id in zip(
                    action.atoms, action.source_ids, strict=True
                ):
                    bit = resets[source_id]
                    state, _ = project(state, wires[atom], bit)
                    if bit:
                        state = local(state, wires[atom], np.array([[0, 1], [1, 0]]))
            elif isinstance(action, Measure):
                if pre_readout is None:
                    pre_readout = state.copy()
                for atom, ref in action.results:
                    state, probability = project(
                        state, wires[atom], outcomes[ref.measurement_id]
                    )
                    probability_errors.append(
                        abs(probability - probabilities[ref.measurement_id])
                    )
        layout = apply_step(layout, step, job.device)
    fidelity = float(abs(np.vdot(expected, state)) ** 2)
    evidence = {
        "final_state_fidelity": fidelity,
        "max_conditional_probability_error": max(probability_errors, default=0),
    }
    if not any(n.condition for n in job.dag.nodes):
        evidence["pre_readout_state_fidelity"] = float(
            abs(np.vdot(source_pre, pre_readout)) ** 2
        )
        evidence["pre_readout_probability_max_error"] = float(
            np.max(np.abs(abs(source_pre) ** 2 - abs(pre_readout) ** 2))
        )
    assert abs(fidelity - 1) < 1e-10, evidence
    assert evidence["max_conditional_probability_error"] < 1e-10, evidence
    if "pre_readout_state_fidelity" in evidence:
        assert abs(evidence["pre_readout_state_fidelity"] - 1) < 1e-10, evidence
    return evidence
