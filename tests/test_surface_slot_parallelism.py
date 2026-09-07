"""R1 invariants for the frozen d=3 QEC interaction schedule."""
from collections import defaultdict
import unittest

from qec_schedule.compiler import PhysicalCircuitDAG
from qec_schedule.compiler.dag import OperationState
from qec_schedule.qec import create_code


class SurfaceSlotParallelismTests(unittest.TestCase):
    def test_d3_rotated_surface_code_has_four_disjoint_six_gate_slots(self):
        code = create_code()

        for primitive in ("CZ", "CNOT"):
            circuit = code.syndrome_round(primitive=primitive)
            by_slot = defaultdict(list)
            interactions = [gate for gate in circuit.gates
                            if gate.gate_type.value == primitive]
            for gate in interactions:
                by_slot[gate.metadata["slot"]].append(gate)

            self.assertEqual(sorted(by_slot), [0, 1, 2, 3])
            self.assertEqual([len(by_slot[slot]) for slot in sorted(by_slot)], [6, 6, 6, 6])
            for gates in by_slot.values():
                qubits = [qubit for gate in gates for qubit in gate.qubits]
                self.assertEqual(len(qubits), len(set(qubits)),
                                 f"{primitive} slot contains a repeated physical qubit")

    def test_dag_can_expose_each_slot_as_a_simultaneously_ready_batch(self):
        code = create_code()

        for primitive in ("CZ", "CNOT"):
            dag = PhysicalCircuitDAG(code.syndrome_round(primitive=primitive))
            by_slot = defaultdict(list)
            for gate in dag.circuit.gates:
                if gate.gate_type.value == primitive:
                    by_slot[gate.metadata["slot"]].append(gate)

            for slot in sorted(by_slot):
                target_ids = {gate.id for gate in by_slot[slot]}
                ancestors = set()
                pending = list(target_ids)
                while pending:
                    gate_id = pending.pop()
                    for predecessor in dag.predecessors(gate_id):
                        if predecessor not in ancestors:
                            ancestors.add(predecessor)
                            pending.append(predecessor)

                # A slot's disjoint interactions must not depend on one
                # another; their common prerequisites can be completed first.
                self.assertTrue(target_ids.isdisjoint(ancestors))
                for gate in dag.circuit.gates:
                    if gate.id not in ancestors:
                        continue
                    if dag.state(gate.id) == OperationState.DONE:
                        continue
                    self.assertEqual(dag.state(gate.id), OperationState.READY)
                    dag.start(gate.id)
                    dag.complete(gate.id)

                ready_ids = {gate.id for gate in dag.ready_operations()}
                self.assertTrue(target_ids <= ready_ids,
                                f"{primitive} slot {slot} was not simultaneously ready")
                dag.start_operations(target_ids)
                for gate_id in sorted(target_ids):
                    dag.complete(gate_id)


if __name__ == "__main__":
    unittest.main()
