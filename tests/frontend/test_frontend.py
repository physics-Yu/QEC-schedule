"""Semantic identities and rejection tests; no state vectors or sampling."""

from copy import deepcopy
from fractions import Fraction
from itertools import product
import json
import math
import unittest

from na_pipeline.frontend import (
    FrontendError, SynthesisRequiredError, build_shor15, iter_logical_ops,
    postprocess_phase, require_clifford_t, to_openqasm3, validate_logical,
)


def bits8(value):
    return [int(bit) for bit in f"{value:08b}"]


class ArithmeticIdentities(unittest.TestCase):
    """Prove the diagonal phase polynomial then use H Z H = X."""

    def setUp(self):
        self.program = build_shor15(synthesize=False)

    def prove_ccx(self, gates, controls, target):
        a, b = controls
        self.assertEqual(len(gates), 15)
        hadamards = [i for i, op in enumerate(gates) if op["params"]["name"] == "H"]
        self.assertEqual(hadamards, [0, 10])
        self.assertEqual(gates[0]["qubits"], [target])
        self.assertEqual(gates[10]["qubits"], [target])
        # These trailing gates commute with H(target), giving H D H.
        for op in gates[11:]:
            self.assertNotIn(target, op["qubits"])
        self.assertEqual(sum(op["params"]["name"] in ("T", "TDG") for op in gates), 7)
        for aa, bb, cc in product((0, 1), repeat=3):
            values = {a: aa, b: bb, target: cc}
            original = values.copy()
            phase_mod8 = 0
            for op in gates:
                name, qs = op["params"]["name"], op["qubits"]
                if name == "H":
                    continue
                if name == "CX":
                    values[qs[1]] ^= values[qs[0]]
                elif name in ("T", "TDG"):
                    phase_mod8 += (1 if name == "T" else -1) * values[qs[0]]
                else:
                    self.fail(name)
            self.assertEqual(values, original)
            self.assertEqual(phase_mod8 % 8, 4 * aa * bb * cc)
        # Thus D is exactly CCZ with no state-dependent extra phase.

    def test_exact_ccx_phase_polynomial_all_eight_inputs(self):
        total = 0
        for multiplier in (2, 4):
            ops = [n["op"] for n in self.program["templates"][f"controlled_mul{multiplier}/1"]["body"]]
            for index in range(0, len(ops), 17):
                chunk = ops[index:index + 17]
                b, a = chunk[0]["qubits"]
                self.prove_ccx(chunk[1:16], ("ctrl", a), b)
                self.assertEqual(chunk[-1]["qubits"], [b, a])
                self.assertEqual(chunk[0]["params"]["name"], "CX")
                self.assertEqual(chunk[-1]["params"]["name"], "CX")
                total += 1
        self.assertEqual(total, 5)

    def test_fredkin_boolean_identity_all_eight_inputs(self):
        for control, a, b in product((0, 1), repeat=3):
            left, right = a ^ b, b
            right ^= control & left
            left ^= right
            self.assertEqual((left, right), (b, a) if control else (a, b))

    def test_controlled_full_permutations_all_64_inputs(self):
        count = 0
        for multiplier in (2, 4):
            ops = [n["op"] for n in self.program["templates"][f"controlled_mul{multiplier}/1"]["body"]]
            for control, x in product((0, 1), range(16)):
                values = {"ctrl": control, **{f"w{i}": (x >> i) & 1 for i in range(4)}}
                for index in range(0, len(ops), 17):
                    chunk = ops[index:index + 17]
                    b, a = chunk[0]["qubits"]
                    # CCX identity is independently proved above for every instance.
                    values[a] ^= values[b]
                    values[b] ^= values["ctrl"] & values[a]
                    values[a] ^= values[b]
                output = sum(values[f"w{i}"] << i for i in range(4))
                expected = x if not control or x == 15 else multiplier * x % 15
                self.assertEqual((values["ctrl"], output), (control, expected))
                count += 1
        self.assertEqual(count, 64)


class PhaseAndPostprocess(unittest.TestCase):
    def test_feedback_symbolic_identity_for_all_256_exact_phase_strings(self):
        """Check fractional angles only; not a Shor probability distribution."""
        program = build_shor15(synthesize=False)
        ops = {op["id"]: op for op in iter_logical_ops(program)}
        for value in range(256):
            expected_bits = bits8(value)
            known = {}
            for round_ in program["rounds"]:
                j = round_["power_index"]
                residual = Fraction(value * (1 << j), 256)
                for op_id in round_["feedback_ops"]:
                    op = ops[op_id]
                    bit = op["condition"]["bit"]
                    self.assertIn(bit, known)
                    angle = op["params"]["angle_pi"]
                    residual += known[bit] * Fraction(angle["numerator"], 2 * angle["denominator"])
                self.assertEqual(residual % 1, Fraction(expected_bits[j], 2))
                known[f"phase[{j}]"] = expected_bits[j]

    def test_success_is_classically_derived(self):
        for value in (64, 192):
            report = postprocess_phase(bits8(value))
            self.assertEqual(report["factors"], [3, 5])
            self.assertEqual(report["period"], 4)
            self.assertFalse(report["minimal_order_proven"])
            self.assertEqual(report["origin"], "fake")
        generic = postprocess_phase(bits8(43), N=21, a=2)
        self.assertEqual(generic["factors"], [3, 7])
        self.assertEqual(generic["period"], 6)

    def test_zero_and_reduced_phase_do_not_force_success(self):
        self.assertEqual(postprocess_phase(bits8(0))["reason"], "zero_phase_no_period_information")
        report = postprocess_phase(bits8(128))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["factors"], [])
        self.assertEqual(report["candidate_checks"][0]["rejection"], "not_a_period")

    def test_every_reported_factor_is_nontrivial_and_divides_N(self):
        for N, a in ((15, 2), (21, 2), (17, 3), (9, 2)):
            for value in range(256):
                result = postprocess_phase(bits8(value), N=N, a=a)
                if result["status"] == "success":
                    self.assertEqual(math.prod(result["factors"]), N)
                    self.assertTrue(all(1 < factor < N for factor in result["factors"]))
                    self.assertEqual(pow(a, result["period"], N), 1)
                else:
                    self.assertFalse(result["factors"])

    def test_invalid_inputs_fail(self):
        for bits in ([], [0] * 7, [0] * 9, [False] * 8, [0.0] * 8, [2] * 8, "01000000"):
            with self.assertRaises(FrontendError):
                postprocess_phase(bits)
        with self.assertRaises(FrontendError):
            postprocess_phase(bits8(64), origin="quantum_sample")
        self.assertEqual(postprocess_phase(bits8(0), N=15, a=3)["reason"], "classical_gcd_precheck")


class StructuredProgram(unittest.TestCase):
    def setUp(self):
        self.program = build_shor15(synthesize=False)

    def test_structure_counts_and_lifecycle(self):
        self.assertEqual(validate_logical(self.program), [])
        ops = list(iter_logical_ops(self.program))
        self.assertEqual(len(self.program["rounds"]), 8)
        self.assertEqual([r["power_index"] for r in self.program["rounds"]], list(range(7, -1, -1)))
        self.assertEqual([r["controlled_multiplier"] for r in self.program["rounds"]], [1] * 6 + [4, 2])
        self.assertEqual(len([n for n in self.program["body"] if n["kind"] == "call"]), 8)
        self.assertEqual(len([op for op in ops if op["kind"] == "measure"]), 8)
        self.assertEqual(len([op for op in ops if op["kind"] == "reset"]), 13)
        self.assertEqual(len([op for op in ops if op["condition"]]), 28)
        self.assertEqual(len([op for op in ops if op["params"].get("name") == "P"]), 15)
        self.assertEqual(len([op for op in ops if op["params"].get("name") in ("T", "TDG")]), 41)
        self.assertIsNone(self.program["resource_summary"]["total_t_like"])
        self.assertEqual(self.program["resource_summary"]["modular_multiply_t_like"], 35)
        self.assertFalse(self.program["provenance"]["fixture"])
        self.assertTrue(self.program["lifecycle"]["work_persists_across_rounds"])
        # No work reset after initialization, no output values in a compile plan.
        self.assertTrue(all(op["qubits"] == ["ctrl"] for op in ops[5:] if op["kind"] == "reset"))
        self.assertTrue(all("value" not in op["params"] for op in ops if op["kind"] == "measure"))

    def test_budget_and_fail_closed_handoff(self):
        pending = [op for op in iter_logical_ops(self.program) if op["params"].get("name") == "P"]
        self.assertAlmostEqual(sum(op["params"]["error_budget"] for op in pending), 1e-3)
        self.assertTrue(all(op["params"]["error_bound"] is None for op in pending))
        self.program["synthesis"]["clifford_t_ready"] = True  # Metadata cannot bypass the gate check.
        with self.assertRaises(SynthesisRequiredError) as caught:
            require_clifford_t(self.program)
        self.assertEqual(len(caught.exception.operations), 15)
        for epsilon in (0, -1, 1, float("nan"), float("inf"), True, "0.001"):
            with self.assertRaises(FrontendError):
                build_shor15(synthesis_error_budget=epsilon)

    def test_json_roundtrip_determinism_and_copy_isolation(self):
        self.assertEqual(build_shor15(synthesize=False), self.program)
        restored = json.loads(json.dumps(self.program, allow_nan=False))
        self.assertEqual(list(iter_logical_ops(restored)), list(iter_logical_ops(self.program)))
        ops = list(iter_logical_ops(self.program))
        ops[0]["params"]["value"] = 1
        self.assertEqual(next(iter_logical_ops(self.program))["params"]["value"], 0)

    def test_dependency_and_source_rebinding(self):
        emitted = set()
        ops = list(iter_logical_ops(self.program))
        for op in ops:
            self.assertTrue(set(op["after"]).issubset(emitted))
            self.assertTrue(op["source_ids"])
            self.assertNotIn(op["id"], emitted)
            emitted.add(op["id"])
        # Empty U1 retains its source record on the following real operation.
        after_identity = next(op for op in ops if op["id"] == "round7/readout_h")
        self.assertIn("round7/multiply", after_identity["source_ids"])

    def test_distinct_template_calls_do_not_share_result_names(self):
        fixture = deepcopy(self.program)
        fixture["provenance"]["fixture"] = True
        template = {"formal_qubits": ["q"], "body": [
            {"kind": "op", "op": {"id": "m", "kind": "measure", "qubits": ["q"],
              "params": {"basis": "Z"}, "reads": [], "writes": ["b"], "after": [],
              "source_ids": ["fixture:m"], "condition": None}},
            {"kind": "op", "op": {"id": "x", "kind": "gate", "qubits": ["q"],
              "params": {"name": "X"}, "reads": ["b"], "writes": [], "after": ["m"],
              "source_ids": ["fixture:x"], "condition": {"bit": "b", "equals": 1}}}]}
        fixture["templates"] = {"test": template}
        fixture["body"] = [{"kind": "call", "id": name, "template_id": "test", "repeat": 1,
                            "bindings": {"q": "ctrl"}, "after": [], "source_ids": ["fixture"]}
                           for name in ("first", "second")]
        ops = list(iter_logical_ops(fixture))
        self.assertEqual([op["writes"] for op in ops if op["kind"] == "measure"], [["first/b"], ["second/b"]])
        self.assertEqual(ops[1]["condition"]["bit"], "first/b")
        self.assertEqual(ops[3]["reads"], ["second/b"])
        self.assertEqual(ops[3]["after"], ["second/m"])

    def test_unknown_nodes_gates_and_noncausal_reads_reject(self):
        for mutation in ("node", "gate", "causality", "qubit", "repeat", "angle"):
            program = deepcopy(self.program)
            if mutation == "node":
                program["body"][0] = {"kind": "teleport_without_circuit"}
            elif mutation == "gate":
                program["body"][4]["op"]["params"]["name"] = "UNSUPPORTED"
            elif mutation == "qubit":
                program["body"][4]["op"]["qubits"] = ["missing"]
            elif mutation == "repeat":
                next(n for n in program["body"] if n["kind"] == "call")["repeat"] = 2
            else:
                feedback = next(n["op"] for n in program["body"] if n["kind"] == "op" and n["op"]["condition"])
                if mutation == "causality":
                    feedback["after"] = []
                else:
                    feedback["params"]["angle_rad"] = 0.0
            self.assertTrue(validate_logical(program), mutation)

    def test_qasm_preserves_measurements_resets_conditions_and_angles(self):
        qasm = to_openqasm3(self.program)
        self.assertTrue(qasm.startswith('OPENQASM 3.0;\ninclude "stdgates.inc";'))
        self.assertEqual(qasm.count(" = measure "), 8)
        self.assertEqual(qasm.count("reset q["), 13)
        self.assertEqual(qasm.count("if (phase["), 28)
        self.assertEqual(qasm.count(" p("), 15)
        self.assertIn("p(-1*pi/128)", qasm)
        self.assertIn("if (phase[1] == 1) { sdg q[0]; }", qasm)
        self.assertIn("phase[0] = measure q[0];", qasm)

    def test_evidence_and_phase_convention_are_not_silently_relabeled(self):
        for mutation in ("envelope", "hardware", "phase", "gate_angle", "gate_write"):
            program = deepcopy(self.program)
            feedback = next(n["op"] for n in program["body"] if n["kind"] == "op" and n["op"]["condition"])
            if mutation == "envelope":
                del program["artifact_id"]
            elif mutation == "hardware":
                program["hardware_executed"] = True
            elif mutation == "phase":
                feedback["params"]["phase_convention"] = "RZ"
            elif mutation == "gate_angle":
                feedback["params"]["name"] = "T"
            else:
                feedback["writes"] = ["phase[0]"]
            self.assertTrue(validate_logical(program), mutation)


if __name__ == "__main__":
    unittest.main()
