import json
import random
import unittest

from qec_schedule.compiler import OperationState, PhysicalCircuit, PhysicalCircuitDAG, PhysicalGate
from qec_schedule.qec import create_code
from tests.test_step1 import RepetitionCode


def gate(name, qubit, parents=()):
    return PhysicalGate(name, "H", (qubit,), parents)


def fork_join():
    return PhysicalCircuitDAG(PhysicalCircuit(("a", "b", "c"), (
        gate("root", "a"), gate("left", "a", ("root",)),
        gate("right", "b", ("root",)), gate("join", "c", ("left", "right")),
    )))


class DAGTests(unittest.TestCase):
    def test_predecessors_successors_and_join(self):
        dag = fork_join()
        self.assertEqual(dag.predecessors("join"), ("left", "right"))
        self.assertEqual(dag.successors("root"), ("left", "right"))
        self.assertEqual(dag.successors("join"), ())
        self.assertEqual(dag.edge_count, 4)
        self.assertEqual([g.id for g in dag.ready_operations()], ["root"])
        dag.start("root")
        self.assertFalse(dag.ready_operations())
        dag.complete("root")
        self.assertEqual([g.id for g in dag.ready_operations()], ["left", "right"])
        dag.start_operations(("left", "right"))
        dag.complete("right")
        self.assertEqual(dag.state("join"), OperationState.WAITING)
        dag.complete("left")
        self.assertEqual(dag.state("join"), OperationState.READY)
        dag.start("join")
        self.assertFalse(dag.is_complete)
        dag.complete("join")
        self.assertTrue(dag.is_complete)
        self.assertFalse(dag.ready_operations())
        self.assertFalse(dag.running_operations())

    def test_unlock_without_global_layer_barrier(self):
        dag = PhysicalCircuitDAG(PhysicalCircuit(("a", "b"), (
            gate("a0", "a"), gate("b0", "b"), gate("a1", "a", ("a0",)),
        )))
        dag.start_operations(("a0", "b0"))
        dag.complete("a0")
        self.assertEqual([g.id for g in dag.ready_operations()], ["a1"])
        dag.start("a1")
        self.assertEqual({g.id for g in dag.running_operations()}, {"b0", "a1"})

    def test_invalid_transitions_are_atomic(self):
        dag = fork_join()
        with self.assertRaises(ValueError): dag.complete("root")
        with self.assertRaises(ValueError): dag.start("join")
        with self.assertRaises(ValueError): dag.start_operations(("root", "join"))
        with self.assertRaises(ValueError): dag.start_operations(("root", "root"))
        with self.assertRaises(KeyError): dag.start_operations(("root", "missing"))
        self.assertEqual(dag.state("root"), OperationState.READY)
        self.assertFalse(dag.running_operations())
        dag.start("root")
        with self.assertRaises(ValueError): dag.start("root")
        dag.complete("root")
        before = dag.ready_operations()
        with self.assertRaises(ValueError): dag.complete("root")
        with self.assertRaises(ValueError): dag.start("root")
        self.assertEqual(dag.ready_operations(), before)
        for query in (dag.state, dag.predecessors, dag.successors, dag.complete):
            with self.assertRaises(KeyError): query("missing")

    def test_unordered_input_cycle_and_missing_references(self):
        dag = PhysicalCircuitDAG.from_gates(("a",), (gate("next", "a", ("first",)), gate("first", "a")))
        self.assertEqual(dag.topological_order(), ("first", "next"))
        for gates in (
            (gate("a", "a", ("b",)), gate("b", "a", ("a",))),
            (gate("a", "a", ("absent",)),),
            (gate("a", "a"), gate("a", "a")),
            (gate("a", "unknown"),),
        ):
            with self.assertRaises(ValueError): PhysicalCircuitDAG.from_gates(("a",), gates)
        with self.assertRaises(ValueError): PhysicalCircuitDAG.from_gates(("a", "a"), ())

    def test_requires_explicit_same_qubit_order_but_accepts_transitive_path(self):
        with self.assertRaisesRegex(ValueError, "Missing dependency order"):
            PhysicalCircuitDAG(PhysicalCircuit(("a",), (gate("a0", "a"), gate("a1", "a"))))
        dag = PhysicalCircuitDAG.from_gates(("a", "b"), (
            gate("a0", "a"), gate("b0", "b", ("a0",)), gate("a1", "a", ("b0",)),
        ))
        self.assertEqual(dag.predecessors("a1"), ("b0",))  # No invented direct edge.

    def test_empty_graph_and_independent_execution(self):
        empty = PhysicalCircuitDAG(PhysicalCircuit((), ()))
        self.assertTrue(empty.is_complete)
        self.assertEqual(empty.topological_order(), ())
        self.assertEqual(empty.edge_count, 0)
        dag = fork_join()
        replay = PhysicalCircuitDAG(dag.circuit)
        dag.start("root")
        self.assertEqual(replay.state("root"), OperationState.READY)
        with self.assertRaises(TypeError): dag.gates["root"] = gate("root", "a")

    def test_generated_codes_random_completions_and_export(self):
        # Exercise actual generated dependencies for both primitives, repeats,
        # independent code families, and randomly chosen starts/completions.
        for code in (create_code(), RepetitionCode()):
            for primitive in ("CZ", "CNOT"):
                circuit = code.syndrome_round(rounds=3, primitive=primitive)
                for seed in range(4):
                    dag, rng, done = PhysicalCircuitDAG(circuit), random.Random(seed), set()
                    serialized = json.loads(json.dumps(dag.to_dict()))
                    self.assertEqual(serialized["kind"], "physical_circuit_dag")
                    for g in circuit.gates:
                        for p in dag.predecessors(g.id):
                            self.assertIn(g.id, dag.successors(p))
                    iterations = 0
                    while not dag.is_complete:
                        eligible = {g.id for g in circuit.gates if dag.state(g.id) in (OperationState.WAITING, OperationState.READY)
                                    and set(g.predecessors) <= done}
                        self.assertEqual({g.id for g in dag.ready_operations()}, eligible)
                        ready = list(dag.ready_operations())
                        if ready:
                            selected = rng.sample(ready, rng.randint(1, len(ready)))
                            dag.start_operations(g.id for g in selected)
                        active = list(dag.running_operations())
                        self.assertTrue(active)
                        atoms = [q for g in active for q in g.qubits]
                        self.assertEqual(len(atoms), len(set(atoms)))
                        chosen = rng.choice(active)
                        self.assertTrue(set(chosen.predecessors) <= done)
                        dag.complete(chosen.id)
                        done.add(chosen.id)
                        iterations += 1
                        self.assertLessEqual(iterations, len(circuit.gates))
                    self.assertEqual(done, set(dag.gates))
                    self.assertEqual(dag.to_dict(), serialized)  # Topology unchanged by execution.


if __name__ == "__main__":
    unittest.main()
