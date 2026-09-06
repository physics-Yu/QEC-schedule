"""Independent Clifford propagation checks; no production quantum-state simulator."""
from collections import Counter
from dataclasses import replace
import json
import random
import unittest

from qec_schedule.compiler import PhysicalCircuit, PhysicalGate
from qec_schedule.qec import create_code
from tests.test_step1 import RepetitionCode


def conjugate(x, z, sign, gate):
    """Binary Hermitian Pauli conjugation including the +/- sign."""
    q = gate.qubits[0]
    if gate.gate_type == "H":
        sign ^= x[q] & z[q]
        x[q], z[q] = z[q], x[q]
    elif gate.gate_type == "CNOT":
        c, t = gate.qubits
        sign ^= x[c] & z[t] & (x[t] ^ z[c] ^ 1)
        x[t] ^= x[c]
        z[c] ^= z[t]
    elif gate.gate_type == "CZ":
        c, t = gate.qubits
        # Direct CZ Pauli rule, independent of production H-CZ-H lowering.
        sign ^= x[c] & x[t] & (z[c] ^ z[t])
        z[t] ^= x[c]
        z[c] ^= x[t]
    else:
        raise AssertionError(gate.gate_type)
    return sign


def propagated(circuit, gates, qubit, basis):
    x, z = {q: 0 for q in circuit.qubits}, {q: 0 for q in circuit.qubits}
    x[qubit], z[qubit] = int(basis in "XY"), int(basis in "ZY")
    sign = 0
    for gate in gates:
        sign = conjugate(x, z, sign, gate)
    terms = {q: "Y" if x[q] and z[q] else "X" if x[q] else "Z"
             for q in circuit.qubits if x[q] or z[q]}
    return terms, sign


class SyndromeTests(unittest.TestCase):
    def test_counts_interactions_and_lifecycle(self):
        code = create_code()
        for primitive, expected in (("CNOT", {"PREPARE":8, "RESET":8, "MEASURE_Z":8, "H":8, "CNOT":24}),
                                    ("CZ", {"PREPARE":8, "RESET":8, "MEASURE_Z":8, "H":56, "CZ":24})):
            circuit = code.syndrome_round(primitive=primitive)
            self.assertEqual(Counter(g.gate_type.value for g in circuit.gates), expected)
            for check in code.stabilizers():
                gates = [g for g in circuit.gates if g.metadata["stabilizer"] == check.id]
                pairs = [g for g in gates if g.gate_type == primitive]
                self.assertEqual([(g.metadata["slot"], g.metadata["data_qubit"]) for g in pairs], list(check.interactions))
                for g in pairs:
                    data = g.metadata["data_qubit"]
                    self.assertEqual(g.qubits, (check.ancilla, data) if check.basis == "X" else (data, check.ancilla))
                self.assertEqual(gates[0].gate_type, "PREPARE")
                self.assertEqual([g.gate_type for g in gates[-2:]], ["MEASURE_Z", "RESET"])
            self.assertEqual(json.loads(json.dumps(circuit.to_dict()))["schema_version"], 1)

    def assert_measures_checks(self, code, circuit, order):
        for check in code.stabilizers():
            measure_index = next(i for i, g in enumerate(order) if g.gate_type == "MEASURE_Z" and g.qubits == (check.ancilla,))
            unitary = [g for g in order[:measure_index] if g.gate_type in ("H", "CZ", "CNOT")]
            terms, sign = propagated(circuit, reversed(unitary), check.ancilla, "Z")
            # Input ancilla is |0>: U† Z_a U = Z_a S_data (positive sign).
            self.assertEqual(terms, {check.ancilla:"Z", **dict(check.operator.terms)})
            self.assertEqual(sign, 0)

    def test_actual_measured_paulis_and_cz_equivalence(self):
        for code in (create_code(), RepetitionCode()):
            cx, cz = code.syndrome_round(primitive="CNOT"), code.syndrome_round()
            self.assert_measures_checks(code, cx, cx.gates)
            self.assert_measures_checks(code, cz, cz.gates)
            # Match action on an entire generating set, including phase signs.
            cxu = [g for g in cx.gates if g.gate_type in ("H", "CNOT")]
            czu = [g for g in cz.gates if g.gate_type in ("H", "CZ")]
            for q in cx.qubits:
                for basis in "XZ":
                    self.assertEqual(propagated(cx, cxu, q, basis), propagated(cz, czu, q, basis))

    def test_dependencies_allow_safe_reordering(self):
        code = create_code()
        for primitive in ("CZ", "CNOT"):
            circuit = code.syndrome_round(primitive=primitive)
            last = {}
            for g in circuit.gates:
                for q in g.qubits:
                    if q in last: self.assertIn(last[q], g.predecessors)
                    last[q] = g.id
            for seed in range(8):
                rng, done, pending, order = random.Random(seed), set(), list(circuit.gates), []
                while pending:
                    ready = [g for g in pending if set(g.predecessors) <= done]
                    self.assertTrue(ready)
                    gate = rng.choice(ready)
                    done.add(gate.id)
                    pending.remove(gate)
                    order.append(gate)
                self.assert_measures_checks(code, circuit, order)

    def test_repeated_rounds(self):
        circuit = create_code().syndrome_round(rounds=3)
        self.assertEqual(len(circuit.gates), 312)
        self.assertEqual(len({g.id for g in circuit.gates}), 312)
        keys = [g.metadata["measurement_key"] for g in circuit.gates if g.gate_type == "MEASURE_Z"]
        self.assertEqual(len(set(keys)), 24)
        for r in (1, 2):
            resets = {g.id for g in circuit.gates if g.metadata["round"] == r-1 and g.gate_type == "RESET"}
            for g in circuit.gates:
                if g.metadata["round"] == r and g.gate_type == "PREPARE":
                    self.assertTrue(resets <= set(g.predecessors))

    def test_invalid_inputs_and_schedule(self):
        for rounds in (0, -1, 1.5, True):
            with self.assertRaises(ValueError): create_code().syndrome_round(rounds=rounds)
        with self.assertRaises(ValueError): create_code().syndrome_round(primitive="ISWAP")
        with self.assertRaises(ValueError): PhysicalGate("g", "CZ", ("a", "a"))
        with self.assertRaises(ValueError): PhysicalCircuit(("a",), (PhysicalGate("g", "H", ("a",), ("missing",)),))
        code = create_code()
        # Moving one shared interaction before an opposite-basis check can
        # preserve stabilizer commutation but invalidate extraction.
        check = code._checks[0]
        code._checks = (replace(check, interactions=((0,"L0:d0"), (1,"L0:d1"), (4,"L0:d3"), (5,"L0:d4"))), *code._checks[1:])
        with self.assertRaises(ValueError): code.syndrome_round()


if __name__ == "__main__": unittest.main()
