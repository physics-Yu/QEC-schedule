"""R3 tests for geometry-free semantic lowering."""
import json
import unittest

from qec_schedule.compiler import (EntangleRequest, MeasureRequest, PrepareRequest,
                                   ResetRequest, SemanticRequestPlan, SingleQubitRequest)
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.qec import create_code


class SemanticRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_hardware_config("configs/hardware_default.yaml")
        cls.code = create_code()
        cls.state = build_initial_state(cls.code, cls.config)

    def test_full_round_emits_one_semantic_request_per_physical_gate(self):
        circuit = self.code.syndrome_round()
        plan = GateLowerer().lower(circuit, self.state)
        self.assertIsInstance(plan, SemanticRequestPlan)
        self.assertEqual(len(plan.requests), len(circuit.gates))
        entangles = [r for r in plan.requests if isinstance(r, EntangleRequest)]
        self.assertEqual(len(entangles), 24)
        self.assertEqual(len([r for r in plan.requests if isinstance(r, MeasureRequest)]), 8)
        self.assertEqual(len([r for r in plan.requests if isinstance(r, PrepareRequest)]), 8)
        self.assertEqual(len([r for r in plan.requests if isinstance(r, ResetRequest)]), 8)
        self.assertTrue(all(isinstance(r, SingleQubitRequest) for r in plan.requests
                            if r not in entangles and not isinstance(r, (MeasureRequest, PrepareRequest, ResetRequest))))

    def test_requests_contain_no_compile_time_destination_or_movement_fields(self):
        plan = GateLowerer().lower(self.code.syndrome_round(), self.state)
        forbidden = {"pair_slot", "measurement_site", "target", "target_coordinate",
                     "sources", "targets", "MOVE", "PICKUP", "DROPOFF"}
        for request in plan.requests:
            serialized = json.dumps(request.to_dict())
            self.assertTrue(forbidden.isdisjoint(request.to_dict()))
            self.assertFalse(any(token in serialized for token in ("pair_slot", "measurement_site", "target_coordinate")))
        self.assertEqual(plan.to_dict()["kind"], "semantic_hardware_requests")

    def test_dependencies_are_preserved_and_lowering_does_not_mutate_state(self):
        circuit = self.code.syndrome_round()
        before = self.state.to_dict()
        plan = GateLowerer().lower(circuit, self.state)
        for gate, request in zip(circuit.gates, plan.requests):
            self.assertEqual(request.id, gate.id)
            self.assertEqual(request.dependencies, gate.predecessors)
        self.assertEqual(self.state.to_dict(), before)

    def test_lowering_without_hardware_state_uses_qubit_ids_as_logical_atom_handles(self):
        plan = GateLowerer().lower(self.code.syndrome_round())
        entangle = next(r for r in plan.requests if isinstance(r, EntangleRequest))
        self.assertTrue(all(atom.startswith("L0:") for atom in entangle.atoms))


if __name__ == "__main__":
    unittest.main()
