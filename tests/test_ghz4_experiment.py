"""End-to-end regression tests for the four-logical GHZ experiment."""
from pathlib import Path
import unittest

from experiments.ghz4 import FourLogicalSurfaceCode, build_logical_program, build_physical_circuit
from experiments.ghz4.config import build_block_placements
from experiments.ghz4.metrics import build_metrics
from experiments.ghz4.verify import verify_ghz_trace
from qec_schedule.compiler import GateType, PhysicalCircuitDAG
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.scheduler import RuntimeScheduler
from qec_schedule.trace import validate_trace


ROOT = Path(__file__).resolve().parents[1]


class GHZ4ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_hardware_config(ROOT / "configs/ghz4_rich.yaml")
        cls.code = FourLogicalSurfaceCode()
        cls.program = build_logical_program(measurement_basis="Z")
        cls.circuit = build_physical_circuit(cls.program, code=cls.code)
        cls.state = build_initial_state(
            cls.code, cls.config,
            placements=build_block_placements(cls.code, cls.config),
        )
        cls.plan = GateLowerer().lower(cls.circuit, cls.state)
        cls.trace = RuntimeScheduler(cls.config).run(cls.plan, cls.state)
        cls.trace["metrics"] = build_metrics(cls.trace, cls.program, cls.circuit,
                                               basis="Z", profile="ghz4_rich")

    def test_composite_code_and_transversal_lowering(self):
        self.assertEqual(len(self.code.data_qubits()), 36)
        self.assertEqual(len(self.code.ancilla_qubits()), 32)
        self.assertEqual(sum(gate.gate_type == GateType.CZ and
                             str(gate.metadata.get("logical_operation_id", "")).startswith("GHZ_CNOT")
                             for gate in self.circuit.gates), 27)
        self.assertEqual(len(self.plan.requests), len(self.circuit.gates))
        self.assertNotIn("position", self.plan.to_dict()["requests"][0])
        self.assertEqual(PhysicalCircuitDAG(self.circuit).edge_count > 0, True)

    def test_rich_runtime_exposes_cross_block_concurrency(self):
        metrics = self.trace["metrics"]
        self.assertTrue(validate_trace(self.trace))
        self.assertEqual(metrics["ghz_transversal_cz_count"], 27)
        self.assertGreaterEqual(metrics["peak_fanout_pairs_per_Rydberg_epoch"], 18)
        self.assertGreaterEqual(metrics["peak_qec_pairs_per_Rydberg_epoch"], 24)
        self.assertGreaterEqual(metrics["peak_atoms_per_AOD_epoch"], 36)
        verification = verify_ghz_trace(self.trace, basis="Z", require_full_concurrency=True)
        self.assertTrue(verification["passed"])
        self.assertEqual(verification["stabilizer_expectations"],
                         {"Z0Z1": 1, "Z1Z2": 1, "Z2Z3": 1})


if __name__ == "__main__":
    unittest.main()
