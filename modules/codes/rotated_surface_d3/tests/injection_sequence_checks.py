"""Dense repeated-extraction oracle, carrying real non-Clifford data amplitudes.

Only data survive a branch boundary. The next SE explicitly resets all eight
measured ancillas; introducing fresh zero ancillas therefore implements that
reset channel exactly on a conditioned pure data state. No data are corrected.
"""

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

from modules.codes.contracts.component import ComponentExpansion
from modules.codes.rotated_surface_d3.tests.dense_quantum import (
    PAULIS,
    DenseOutput,
    Vector,
    _Evolution,
)


@dataclass(frozen=True)
class ExtractionInstruction:
    """One test-oracle instruction obtained from source or actual atom geometry."""

    kind: str
    wires: tuple[int, ...]
    matrix: Vector | None = None
    result_id: int | None = None


def source_extraction(source: str) -> tuple[ExtractionInstruction, ...]:
    """Parse a full source SE once; subsequent inputs keep their complex state."""
    circuit = qiskit.qasm3.loads(source)
    if circuit.num_qubits != 17:
        raise ValueError("This extraction oracle requires seventeen source wires.")
    result = []
    for instruction in circuit.data:
        operation = instruction.operation
        wires = tuple(circuit.find_bit(q).index for q in instruction.qubits)
        if operation.name == "barrier":
            continue
        if operation.name in ("reset", "cx"):
            result.append(ExtractionInstruction(operation.name, wires))
        elif operation.name == "measure":
            identity = circuit.find_bit(instruction.clbits[0]).index
            result.append(ExtractionInstruction("measure", wires, result_id=identity))
        elif len(wires) == 1:
            result.append(
                ExtractionInstruction(
                    "matrix", wires, np.asarray(operation.to_matrix(), dtype=complex)
                )
            )
        else:
            raise ValueError(f"Unsupported extraction gate {operation.name!r}.")
    return tuple(result)


def action_extraction(
    expansion: ComponentExpansion, device: Device
) -> tuple[ExtractionInstruction, ...]:
    """Build an independent quantum program from pulses, transport and coverage."""
    wires = {atom: q for q, atom in enumerate(expansion.wire_atoms)}
    if len(wires) != 17:
        raise ValueError("This extraction oracle requires seventeen bound atoms.")
    layout = expansion.entry_state
    result: list[ExtractionInstruction] = []
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
                result.extend(
                    ExtractionInstruction("matrix", (wires[atom],), matrix)
                    for atom in action.atoms
                )
            elif isinstance(action, CZPulse):
                if device.cz is None:
                    raise ValueError("A CZ pulse requires a device CZ capability.")
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
                        result.append(
                            ExtractionInstruction("cz", (wires[a.id], wires[b.id]))
                        )
            elif isinstance(action, Reset):
                result.extend(
                    ExtractionInstruction("reset", (wires[atom],))
                    for atom in action.atoms
                )
            elif isinstance(action, Measure):
                result.extend(
                    ExtractionInstruction(
                        "measure", (wires[atom],), result_id=ref.measurement_id
                    )
                    for atom, ref in action.results
                )
            elif not isinstance(action, Load | Move | Store | Wait):
                raise TypeError(
                    f"Unsupported extraction action {type(action).__name__}."
                )
        layout = apply_step(layout, step, device)
    if layout != expansion.exit_state:
        raise ValueError("Extraction action replay disagrees with its declared exit.")
    return tuple(result)


def extract(program: tuple[ExtractionInstruction, ...], data: Vector) -> DenseOutput:
    """Run one extraction on conditioned data and fresh, explicitly reset ancillas."""
    if data.shape != (512,) or not np.isclose(np.vdot(data, data), 1, atol=1e-10):
        raise ValueError("Extraction requires a normalized nine-data-qubit vector.")
    reset_wires = tuple(
        q for inst in program if inst.kind == "reset" for q in inst.wires
    )
    if sorted(reset_wires) != list(range(9, 17)):
        raise ValueError("SE must reset exactly its eight ancillas and no data.")
    state = _Evolution(17)
    state.vector[:512] = data
    for instruction in program:
        wires = instruction.wires
        if instruction.kind == "reset":
            state.reset(wires[0])
        elif instruction.kind == "matrix":
            assert instruction.matrix is not None
            state.single(instruction.matrix, wires[0])
        elif instruction.kind == "cx":
            state.controlled_x(*wires)
        elif instruction.kind == "cz":
            state.controlled_z(*wires)
        elif instruction.kind == "measure":
            assert instruction.result_id is not None
            state.measure(instruction.result_id, wires[0])
        else:
            raise ValueError(f"Unsupported oracle instruction {instruction.kind!r}.")
    return state.output()
