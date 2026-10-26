"""Small ideal state-vector checks, including actual non-Clifford rotations.

This is a test oracle for preparations with leading deterministic resets and
terminal measurements. It is not a noise simulator or production execution.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from math import cos, hypot, sin

import numpy as np
import qiskit.qasm3
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
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.replay import apply_step
from numpy.typing import NDArray

from modules.codes.contracts.component import ComponentExpansion

Vector = NDArray[np.complex128]
PAULIS = {
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.diag([1, -1]).astype(complex),
}


def _single(vector: Vector, matrix: Vector, wire: int) -> None:
    """Apply a 2x2 matrix in place using little-endian wire indices."""
    blocks = vector.reshape(-1, 2, 1 << wire)
    zero, one = blocks[:, 0, :].copy(), blocks[:, 1, :].copy()
    blocks[:, 0, :] = matrix[0, 0] * zero + matrix[0, 1] * one
    blocks[:, 1, :] = matrix[1, 0] * zero + matrix[1, 1] * one


@dataclass(frozen=True)
class DenseOutput:
    """State immediately before terminal measurements and their wire mapping."""

    vector: Vector
    measurements: tuple[tuple[int, int], ...]


class _Evolution:
    """Evolve a pure state; reject operations outside the narrow oracle scope."""

    def __init__(self, wires: int) -> None:
        self.vector = np.zeros(1 << wires, dtype=complex)
        self.vector[0] = 1
        self.indices = np.arange(1 << wires)
        self.measurements: list[tuple[int, int]] = []

    def before_measurement(self) -> None:
        if self.measurements:
            raise ValueError("Dense oracle requires all measurements to be terminal.")

    def single(self, matrix: Vector, wire: int) -> None:
        self.before_measurement()
        _single(self.vector, matrix, wire)

    def reset(self, wire: int) -> None:
        self.before_measurement()
        excited = self.vector[(self.indices & (1 << wire)) != 0]
        if float(np.vdot(excited, excited).real) > 1e-12:
            raise ValueError("Oracle only supports resets of known-zero input wires.")

    def controlled_x(self, control: int, target: int) -> None:
        self.before_measurement()
        lower = self.indices[
            ((self.indices & (1 << control)) != 0)
            & ((self.indices & (1 << target)) == 0)
        ]
        upper = lower | (1 << target)
        self.vector[lower], self.vector[upper] = (
            self.vector[upper].copy(),
            self.vector[lower].copy(),
        )

    def controlled_z(self, a: int, b: int) -> None:
        self.before_measurement()
        self.vector[
            ((self.indices & (1 << a)) != 0) & ((self.indices & (1 << b)) != 0)
        ] *= -1

    def measure(self, identity: int, wire: int) -> None:
        if any(identity == mid or wire == q for mid, q in self.measurements):
            raise ValueError("Repeated measurement identity or measured wire.")
        self.measurements.append((identity, wire))

    def output(self) -> DenseOutput:
        return DenseOutput(self.vector, tuple(self.measurements))


def source_state(source: str) -> DenseOutput:
    """Simulate the source with dense complex matrices, including physical T."""
    circuit = qiskit.qasm3.loads(source)
    state = _Evolution(circuit.num_qubits)
    for instruction in circuit.data:
        operation = instruction.operation
        wires = [circuit.find_bit(q).index for q in instruction.qubits]
        if operation.name == "barrier":
            continue
        if operation.name == "measure":
            state.measure(circuit.find_bit(instruction.clbits[0]).index, wires[0])
        elif operation.name == "reset":
            state.reset(wires[0])
        elif operation.name == "cx":
            state.controlled_x(*wires)
        elif len(wires) == 1:
            state.single(np.asarray(operation.to_matrix(), dtype=complex), wires[0])
        else:
            raise ValueError(f"Unsupported source operation {operation.name!r}.")
    return state.output()


def action_state(expansion: ComponentExpansion, device: Device) -> DenseOutput:
    """Simulate atom actions; infer CZ pairs from live geometry and illumination.

    No source DAG operations or source qubit pairs enter this calculation.
    Transport is ideal here, but determines the illuminated interaction pairs.
    """
    wires = {atom: q for q, atom in enumerate(expansion.wire_atoms)}
    state, layout = _Evolution(len(wires)), expansion.entry_state
    for step in expansion.program.steps:
        for action in step.actions:
            if isinstance(action, Rotation | LocalU):
                if isinstance(action, Rotation):
                    half = action.angle / 2
                    matrix = (
                        cos(half) * np.eye(2) - 1j * sin(half) * PAULIS[action.axis]
                    )
                else:
                    half, phi, lam = action.theta / 2, action.phi, action.lam
                    matrix = np.array(
                        [
                            [cos(half), -np.exp(1j * lam) * sin(half)],
                            [
                                np.exp(1j * phi) * sin(half),
                                np.exp(1j * (phi + lam)) * cos(half),
                            ],
                        ]
                    )
                for atom in action.atoms:
                    state.single(matrix, wires[atom])
            elif isinstance(action, CZPulse):
                if device.cz is None:
                    raise ValueError("A CZ action requires a device CZ capability.")
                illuminated = [
                    atom
                    for atom in layout.atoms
                    if (
                        atom.id in action.coverage
                        if isinstance(action.coverage, tuple)
                        else action.coverage.contains(atom.position)
                    )
                ]
                for a, b in combinations(illuminated, 2):
                    if (
                        hypot(a.position.x - b.position.x, a.position.y - b.position.y)
                        <= device.cz.radius_um
                    ):
                        state.controlled_z(wires[a.id], wires[b.id])
            elif isinstance(action, Reset):
                for atom in action.atoms:
                    state.reset(wires[atom])
            elif isinstance(action, Measure):
                for atom, result in action.results:
                    state.measure(result.measurement_id, wires[atom])
            elif not isinstance(action, Load | Move | Store | Wait):
                raise TypeError(f"Unsupported atom action {type(action).__name__}.")
        layout = apply_step(layout, step, device)
    if layout != expansion.exit_state:
        raise ValueError("Dense action replay disagrees with the declared exit.")
    return state.output()


def data_branch(
    output: DenseOutput, values: Mapping[int, int], *, data_wires: int = 9
) -> tuple[Vector | None, float]:
    """Project terminal ancillas, returning normalized data and branch probability."""
    if set(values) != {mid for mid, _ in output.measurements}:
        raise ValueError("Supply exactly one bit per terminal measurement.")
    count = output.vector.size.bit_length() - 1
    if {q for _, q in output.measurements} != set(range(data_wires, count)):
        raise ValueError("All nondatum wires must be terminally measured ancillas.")
    if any(type(value) is not int or value not in (0, 1) for value in values.values()):
        raise ValueError("Branch outcomes must be integer bits.")
    offset = sum(values[mid] << wire for mid, wire in output.measurements)
    vector = output.vector[np.arange(1 << data_wires) | offset].copy()
    probability = float(np.vdot(vector, vector).real)
    if probability < 1e-14:
        return None, probability
    return vector / np.sqrt(probability), probability


def apply_pauli(vector: Vector, terms: Sequence[tuple[int, str]]) -> Vector:
    """Apply an independently specified data Pauli, returning a fresh vector."""
    result = vector.copy()
    for wire, basis in terms:
        _single(result, PAULIS[basis], wire)
    return result


def expectation(vector: Vector, terms: Sequence[tuple[int, str]]) -> float:
    """Evaluate a Hermitian Pauli product without a stabilizer simulator."""
    value = np.vdot(vector, apply_pauli(vector, terms))
    if abs(value.imag) > 1e-10:
        raise ValueError("Expected a real Hermitian observable expectation.")
    return float(value.real)
