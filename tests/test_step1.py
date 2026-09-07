import itertools
import unittest

from qec_schedule.logical import LogicalInstruction, LogicalOp, LogicalProgram
from qec_schedule.qec import CSSCode, CodeRegistry, PauliProduct, Stabilizer, create_code


class RepetitionCode(CSSCode):
    """Independent [[3,1]] bit-flip example for testing the replacement seam."""
    name = "repetition"

    def data_qubits(self): return ("b0", "b1", "b2")
    def ancilla_qubits(self): return ("a0", "a1")
    def stabilizers(self):
        return (
            Stabilizer("s0", "a0", PauliProduct((("b0", "Z"), ("b1", "Z"))), ((0, "b0"), (1, "b1"))),
            Stabilizer("s1", "a1", PauliProduct((("b1", "Z"), ("b2", "Z"))), ((0, "b1"), (1, "b2"))),
        )
    def logical_x(self): return (PauliProduct(tuple((q, "X") for q in self.data_qubits())),)
    def logical_z(self): return (PauliProduct((("b0", "Z"),)),)


class Step1Tests(unittest.TestCase):
    def test_default_topology_and_distance(self):
        code = create_code()
        self.assertEqual(len(code.data_qubits()), 9)
        self.assertEqual(len(code.ancilla_qubits()), 8)
        self.assertEqual(len(code.x_stabilizers()), 4)
        self.assertEqual(len(code.z_stabilizers()), 4)
        self.assertEqual(sorted(len(s.operator.support) for s in code.stabilizers()), [2]*4 + [4]*4)
        # Independently enumerate the binary stabilizer group (rank 8).
        index = {q: i for i, q in enumerate(code.data_qubits())}
        def binary(op):
            return sum((1 << (index[q] + offset)) for q, p in op.terms
                       for offset in ((0,) if p == "X" else (9,) if p == "Z" else (0, 9)))
        generators = [binary(s.operator) for s in code.stabilizers()]
        group = {0}
        for g in generators:
            group |= {v ^ g for v in tuple(group)}
        self.assertEqual(len(group), 256)
        # No weight 1/2 logical Pauli, and at least one weight 3 logical Pauli.
        found = False
        for weight in (1, 2, 3):
            for support in itertools.combinations(code.data_qubits(), weight):
                for bases in itertools.product("XYZ", repeat=weight):
                    op = PauliProduct(tuple(zip(support, bases)))
                    if binary(op) not in group and all(op.commutes_with(s.operator) for s in code.stabilizers()):
                        self.assertEqual(weight, 3)
                        found = True
        self.assertTrue(found)

    def test_registry_and_multiple_blocks(self):
        registry = CodeRegistry()
        registry.register("repetition", RepetitionCode)
        self.assertEqual(len(registry.create("repetition").data_qubits()), 3)
        with self.assertRaises(ValueError): registry.register("repetition", RepetitionCode)
        with self.assertRaises(ValueError): registry.create("missing")
        a, b = create_code(block_id="A"), create_code(block_id="B")
        self.assertFalse(set(a.data_qubits() + a.ancilla_qubits()) & set(b.data_qubits() + b.ancilla_qubits()))
        for distance in (1, True):
            with self.assertRaises(ValueError): create_code(distance=distance)

    def test_odd_surface_code_distance_five(self):
        code = create_code(distance=5)
        self.assertEqual(len(code.data_qubits()), 25)
        self.assertEqual(len(code.ancilla_qubits()), 24)
        self.assertEqual(len(code.x_stabilizers()), 12)
        self.assertEqual(len(code.z_stabilizers()), 12)
        self.assertEqual(sorted(len(s.operator.support) for s in code.stabilizers()),
                         [2] * 8 + [4] * 16)
        self.assertEqual(len(code.logical_x()[0].support), 5)
        self.assertEqual(len(code.logical_z()[0].support), 5)
        self.assertEqual(len(code.syndrome_round().gates), 336)

    def test_logical_program(self):
        prepare = LogicalInstruction("p", LogicalOp.PREPARE_0, ("L0",))
        idle = LogicalInstruction("i", LogicalOp.IDLE, ("L0",), ("p",), rounds=3)
        LogicalProgram(("L0",), (prepare, idle))
        with self.assertRaises(ValueError): LogicalProgram(("L0",), (idle, prepare))
        with self.assertRaises(ValueError): LogicalProgram(("L1",), (prepare,))
        with self.assertRaises(ValueError): LogicalInstruction("c", LogicalOp.CNOT, ("L0", "L0"))
        with self.assertRaises(ValueError): LogicalInstruction("i", LogicalOp.IDLE, ("L0",), rounds=0)


if __name__ == "__main__": unittest.main()
