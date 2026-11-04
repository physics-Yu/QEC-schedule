"""Independent ideal-state and quantum-action checks for the d3 study.

These checks do not establish circuit-level fault tolerance or noisy LER.
"""

from __future__ import annotations

from itertools import combinations, product
from math import cos, hypot, sin
from typing import Any

import numpy as np
import qiskit.qasm3
import stim
from circuits import CHECKS, DATA
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector


def pauli(basis: str, support: tuple[int, ...], n: int = 17) -> stim.PauliString:
    """Build a Pauli in explicit increasing wire order."""
    p = stim.PauliString(n)
    for q in support:
        p[q] = basis
    return p


def code_checks() -> dict[str, Any]:
    """Check commutation, independence and distance by exhaustive low weights."""
    stabilizers = [pauli(b, qs, 9) for b, qs, _ in CHECKS]
    assert all(a.commutes(b) for a in stabilizers for b in stabilizers)
    lx, lz = pauli("X", (0, 3, 6), 9), pauli("Z", (0, 1, 2), 9)
    assert not lx.commutes(lz)
    stim.Tableau.from_stabilizers([*stabilizers, lz])
    group = [stim.PauliString(9)]
    for generator in stabilizers:
        group += [p * generator for p in group]
    supports = {str(p)[1:] for p in group}
    assert len(supports) == 256
    examined = 0
    for weight in range(1, 4):
        witnesses = []
        for wires in combinations(range(9), weight):
            for axes in product("XYZ", repeat=weight):
                error = stim.PauliString(9)
                for q, axis in zip(wires, axes, strict=True):
                    error[q] = axis
                examined += 1
                if (
                    all(error.commutes(s) for s in stabilizers)
                    and str(error)[1:] not in supports
                ):
                    witnesses.append(str(error))
        if witnesses:
            assert weight == 3
            return {
                "stabilizer_rank": 8,
                "logical_qubits": 1,
                "distance": 3,
                "paulis_examined": examined,
                "distance_witness": witnesses[0],
            }
    raise AssertionError("No distance-three witness")


def source_circuit(source: str) -> tuple[stim.Circuit, Any]:
    """Parse the generated QASM independently of its circuit generator."""
    qc = qiskit.qasm3.loads(source)
    circuit = stim.Circuit("I 16")
    mapping = {"reset": "R", "measure": "M", "h": "H", "cx": "CX"}
    for instruction in qc.data:
        name = instruction.operation.name
        if name == "barrier":
            circuit.append("TICK")
        else:
            if name not in mapping:
                raise ValueError(f"Unexpected source instruction: {name}")
            circuit.append(
                mapping[name], [qc.find_bit(q).index for q in instruction.qubits]
            )
    return circuit, qc


def unitary(circuit: stim.Circuit) -> stim.Tableau:
    """Extract the unitary part after checking reset/readout placement."""
    clean = stim.Circuit("I 16")
    touched, measured = set(), set()
    for inst in circuit:
        qs = {t.value for t in inst.targets_copy()}
        if inst.name == "R":
            assert not qs & touched, "Reset after a quantum operation"
        elif inst.name == "M":
            assert not qs & measured
            measured |= qs
        elif inst.name != "I":
            assert not qs & measured, "Quantum operation after readout on its wire"
            touched |= qs
            clean.append(inst)
    return stim.Tableau.from_circuit(clean)


def atom_circuit(result: Any, job: Any) -> tuple[stim.Circuit, list[int], int]:
    """Reconstruct ideal gates from actual actions and instantaneous geometry.

    CZ pairs are derived from illuminated atom positions, not source_ids or
    native DAG gate pairs. FakeBackend values are never used as quantum results.
    """
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

    circuit = stim.Circuit("I 16")
    layout = job.entry_state
    measurement_wires = []
    cz_count = 0
    matrices = {
        "X": np.array([[0, 1], [1, 0]]),
        "Y": np.array([[0, -1j], [1j, 0]]),
        "Z": np.diag([1, -1]),
    }
    for step in result.program.steps:
        for action in step.actions:
            if isinstance(action, Rotation | LocalU):
                if isinstance(action, Rotation):
                    a = action.angle / 2
                    matrix = cos(a) * np.eye(2) - 1j * sin(a) * matrices[action.axis]
                else:
                    a, p, l = action.theta / 2, action.phi, action.lam
                    matrix = np.array(
                        [
                            [cos(a), -np.exp(1j * l) * sin(a)],
                            [np.exp(1j * p) * sin(a), np.exp(1j * (p + l)) * cos(a)],
                        ]
                    )
                local = stim.Tableau.from_unitary_matrix(
                    matrix, endian="little"
                ).to_circuit()
                for atom in action.atoms:
                    for inst in local:
                        circuit.append(inst.name, [atom for _ in inst.targets_copy()])
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
                for a, b in combinations(illuminated, 2):
                    if (
                        hypot(a.position.x - b.position.x, a.position.y - b.position.y)
                        <= job.device.cz.radius_um
                    ):
                        circuit.append("CZ", [a.id, b.id])
                        cz_count += 1
            elif isinstance(action, Reset):
                circuit.append("R", action.atoms)
            elif isinstance(action, Measure):
                for atom, _ in action.results:
                    circuit.append("M", [atom])
                    measurement_wires.append(atom)
            elif not isinstance(action, Load | Move | Store | Wait):
                raise TypeError(f"Unsupported atom action {type(action).__name__}")
        circuit.append("TICK")
        layout = apply_step(layout, step, job.device)
    assert layout == result.exit_state == job.entry_state
    return circuit, measurement_wires, cz_count


def initialization(name: str, qc: Any, actual: stim.Circuit) -> dict[str, Any]:
    """Check all stabilizers and logical eigenvalue with Stim and dense vectors."""
    logical = pauli("Z", (0, 1, 2)) if name == "initialize_0" else pauli("X", (0, 3, 6))
    expected = [pauli(b, qs) for b, qs, _ in CHECKS] + [logical]
    sim = stim.TableauSimulator(seed=17)
    sim.do(actual)
    values = [sim.peek_observable_expectation(p) for p in expected]
    assert values == [1] * 9, values
    # Independent dense calculation on nine data wires, parsed from QASM.
    dense = QuantumCircuit(9)
    for inst in qc.data:
        if inst.operation.name in ("reset", "barrier"):
            continue
        wires = [qc.find_bit(q).index for q in inst.qubits]
        assert all(q < 9 for q in wires)
        dense.append(inst.operation, wires)
    vector = Statevector.from_instruction(dense).data
    target = np.zeros(512, dtype=complex)
    if name == "initialize_0":
        masks = [sum(1 << q for q in qs) for b, qs, _ in CHECKS if b == "X"]
        states = [0]
        for mask in masks:
            states += [state ^ mask for state in states]
    else:
        masks = [sum(1 << q for q in qs) for b, qs, _ in CHECKS if b == "Z"]
        states = [
            state
            for state in range(512)
            if all((state & mask).bit_count() % 2 == 0 for mask in masks)
        ]
    target[states] = 1 / np.sqrt(len(states))
    fidelity = float(abs(np.vdot(target, vector)) ** 2)
    assert abs(fidelity - 1) < 1e-12, fidelity
    return {
        "stabilizer_and_logical_expectations": values,
        "independent_dense_state_fidelity": fidelity,
        "expected_basis_terms": len(states),
    }


def syndrome_checks(circuit: stim.Circuit, wires: list[int]) -> dict[str, Any]:
    """Check the measured operators and 84 encoded-input/data-error cases."""
    stabilizers = [pauli(b, qs) for b, qs, _ in CHECKS]
    inverse = unitary(circuit).inverse()
    measured_observables = []
    for i, check in enumerate(stabilizers):
        observed = inverse.z_output(9 + i)
        assert observed == check * pauli("Z", (9 + i,)), (i, observed)
        measured_observables.append(str(observed))
    lx, lz = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    logicals = (lz, lx, 1j * lx * lz)
    errors = [stim.PauliString(17)] + [pauli(b, (q,)) for q in range(9) for b in "XYZ"]
    cases = 0
    for logical in logicals:
        prepared = stim.Tableau.from_stabilizers(
            [*stabilizers, logical, *(pauli("Z", (q,)) for q in range(9, 17))]
        )
        for error in errors:
            sim = stim.TableauSimulator(seed=17)
            sim.set_inverse_tableau(prepared.inverse())
            sim.do_pauli_string(error)
            sim.do(circuit)
            bits = dict(zip(wires, sim.current_measurement_record(), strict=True))
            expected = [not error.commutes(s) for s in stabilizers]
            assert [bits[9 + i] for i in range(8)] == expected
            assert [sim.peek_observable_expectation(s) for s in stabilizers] == [
                -1 if bit else 1 for bit in expected
            ]
            assert sim.peek_observable_expectation(logical) == (
                1 if error.commutes(logical) else -1
            )
            cases += 1
    return {
        "heisenberg_measured_observables": measured_observables,
        "encoded_states": ["+Z", "+X", "+Y"],
        "preexisting_data_error_cases": cases,
        "logical_eigenvalues_preserved": True,
    }


def hook_checks(reference: stim.Circuit) -> list[dict[str, Any]]:
    """Propagate four representative source-level mid-check ancilla faults.

    This establishes the direction of the weight-two hooks, not circuit-level
    distance. Native-pulse faults and other fault locations are not enumerated.
    """
    expanded = []
    for inst in reference:
        if inst.name in ("R", "M"):
            continue
        if inst.name == "CX":
            targets = [t.value for t in inst.targets_copy()]
            for k in range(0, len(targets), 2):
                expanded.append(stim.CircuitInstruction("CX", targets[k : k + 2]))
        else:
            expanded.append(inst)
    checked = []
    for i, (basis, support, _) in enumerate(CHECKS):
        if len(support) != 4:
            continue
        ancilla = 9 + i
        locations = [
            k
            for k, inst in enumerate(expanded)
            if inst.name == "CX" and ancilla in [t.value for t in inst.targets_copy()]
        ]
        assert len(locations) == 4
        suffix = stim.Circuit("I 16")
        for inst in expanded[locations[1] + 1 :]:
            suffix.append(inst)
        table = stim.Tableau.from_circuit(suffix)
        propagated = (
            table.x_output(ancilla) if basis == "X" else table.z_output(ancilla)
        )
        data = [q for q in range(9) if propagated[q] != 0]
        assert len(data) == 2, propagated
        axis = 1 if basis == "X" else 0
        assert DATA[data[0]][axis] == DATA[data[1]][axis], (basis, data)
        assert all(propagated[q] == (1 if basis == "X" else 3) for q in data)
        checked.append(
            {
                "check": i,
                "fault": f"{basis}{ancilla} after its second CX",
                "data_support": data,
                "direction": "horizontal" if basis == "X" else "vertical",
            }
        )
    return checked


def negative_controls(source: str) -> dict[str, bool]:
    """Distinguish ideal measurement correctness from hook-order correctness."""
    lines = source.splitlines()
    positions = [
        i for i, line in enumerate(lines) if line.startswith("cx ") and "q[10]" in line
    ]
    assert len(positions) == 4
    a, b = positions[1:3]
    lines[a], lines[b] = lines[b], lines[a]
    incorrect, _ = source_circuit("\n".join(lines))
    # This particular reordering preserves the ideal measured operators but
    # turns one horizontal X hook into a vertical hook along logical X.
    syndrome_checks(incorrect, list(range(9, 17)))
    missing = source.splitlines()
    missing[positions[0]] = ""
    omitted, _ = source_circuit("\n".join(missing))
    rejected = {"changed_hook_order_still_passes_ideal_measurement_check": True}
    for name, check in (
        (
            "omitted_coupling_rejected_by_measurement_check",
            lambda: syndrome_checks(omitted, list(range(9, 17))),
        ),
        ("incorrect_order_rejected_by_hook_check", lambda: hook_checks(incorrect)),
    ):
        try:
            check()
        except AssertionError:
            rejected[name] = True
        else:
            raise AssertionError(f"Negative control was not rejected: {name}")
    return rejected


def check_operation(
    name: str, source: str, result: Any, job: Any
) -> tuple[dict[str, Any], stim.Circuit]:
    """Compare source and Atom IR quantum semantics, ignoring global phase."""
    reference, qc = source_circuit(source)
    actual, wires, cz_count = atom_circuit(result, job)
    assert unitary(reference) == unitary(actual), (
        "Source/atom Clifford unitary mismatch"
    )
    expected_cz = 24 if name == "se_round" else 8
    assert cz_count == expected_cz
    report = {
        "source_atom_unitaries_equal_up_to_global_phase": True,
        "geometry_derived_cz_count": cz_count,
        "atom_measurement_order": wires,
        "fake_measurement_values_used_for_quantum_checks": False,
    }
    if name == "se_round":
        report["source_se"] = syndrome_checks(reference, list(range(9, 17)))
        report["atom_se"] = syndrome_checks(actual, wires)
        report["source_mid_check_hooks"] = hook_checks(reference)
        report["negative_controls"] = negative_controls(source)
    else:
        report["initialization"] = initialization(name, qc, actual)
    return report, actual
