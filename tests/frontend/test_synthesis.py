"""Static interval certificates and branch-preserving synthesis regressions."""

import cmath
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import math
import unittest

from na_pipeline.frontend import (
    build_shor15, certify_rotation, FrontendError, iter_logical_ops,
    require_clifford_t, synthesize_feedback, t_demand_for_phase, to_openqasm3, validate_logical,
)
from na_pipeline.frontend.rotation_table import ROTATIONS


def matrix_product(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(2)) for j in range(2)] for i in range(2)]


def float_error(entry):
    """Separate ordinary-complex calculation, not the interval implementation."""
    matrices = {"H": [[1/math.sqrt(2), 1/math.sqrt(2)], [1/math.sqrt(2), -1/math.sqrt(2)]],
                "T": [[1, 0], [0, cmath.exp(1j*math.pi/4)]],
                "S": [[1, 0], [0, 1j]], "X": [[0, 1], [1, 0]]}
    unitary = [[1, 0], [0, 1]]
    for name in entry["chronological_gates"]:
        unitary = matrix_product(matrices[name], unitary)
    p = entry["global_phase_pi"]
    scalar = cmath.exp(1j * math.pi * p["numerator"] / p["denominator"])
    a = entry["angle_pi"]
    target = [[1, 0], [0, cmath.exp(1j * math.pi * a["numerator"] / a["denominator"])]]
    delta = [[scalar * unitary[i][j] - target[i][j] for j in range(2)] for i in range(2)]
    # Eigenvalue of D^dagger D gives the independent operator 2-norm estimate.
    x = abs(delta[0][0])**2 + abs(delta[1][0])**2
    y = abs(delta[0][1])**2 + abs(delta[1][1])**2
    z = delta[0][0].conjugate()*delta[0][1] + delta[1][0].conjugate()*delta[1][1]
    return math.sqrt((x+y+math.sqrt((x-y)**2+4*abs(z)**2))/2)


class OperatorCertificates(unittest.TestCase):
    def test_exact_identities_and_phase_sensitive_rejection(self):
        zero = {"numerator": 0, "denominator": 1}
        for word, angle in ((["H", "H"], zero), (["S"], {"numerator": 1, "denominator": 2}),
                            (["T", "TDG"], zero)):
            result = certify_rotation(word, angle, zero)
            self.assertLess(Decimal(result["operator_error_upper_bound"]), Decimal("1e-60"))
        neg_identity = certify_rotation(["H", "H"], zero, {"numerator": 1, "denominator": 1})
        self.assertGreater(Decimal(neg_identity["operator_error_upper_bound"]), Decimal(2))

    def test_all_five_actual_words_meet_local_budget(self):
        for entry in ROTATIONS.values():
            certificate = certify_rotation(entry["chronological_gates"], entry["angle_pi"], entry["global_phase_pi"])
            bound = Decimal(certificate["operator_error_upper_bound"])
            self.assertLess(bound, Decimal("0.001") / 15)
            self.assertLess(float_error(entry), float(bound))
            self.assertFalse(certificate["phase_optimized"])
            self.assertEqual(certificate["gate_count"], len(entry["chronological_gates"]))

    def test_missing_scalar_phase_is_detectable(self):
        entry = ROTATIONS["8"]
        incorrect = certify_rotation(entry["chronological_gates"], entry["angle_pi"], {"numerator": 0, "denominator": 1})
        self.assertGreater(Decimal(incorrect["operator_error_upper_bound"]), Decimal("0.01"))

    def test_host_decimal_precision_does_not_change_certificate(self):
        entry = ROTATIONS["128"]
        reference = certify_rotation(entry["chronological_gates"], entry["angle_pi"], entry["global_phase_pi"])
        with localcontext() as ctx:
            ctx.prec = 6
            result = certify_rotation(entry["chronological_gates"], entry["angle_pi"], entry["global_phase_pi"])
        self.assertEqual(reference, result)


class FeedbackSynthesis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = build_shor15()
        cls.ops = list(iter_logical_ops(cls.program))

    def test_complete_source_and_preserved_io(self):
        require_clifford_t(self.program)
        self.assertEqual(validate_logical(self.program), [])
        self.assertEqual(len(self.ops), 2069)
        self.assertEqual(sum(op["kind"] == "measure" for op in self.ops), 8)
        self.assertEqual(sum(op["kind"] == "reset" for op in self.ops), 13)
        self.assertFalse(any(op["params"].get("name") == "P" for op in self.ops))
        self.assertEqual(len(self.program["synthesis_certificates"]), 5)
        self.assertEqual(len(self.program["branch_global_phases"]), 15)
        self.assertLess(Decimal(self.program["synthesis"]["certified_path_error_upper_bound"]), Decimal("0.001"))

    def test_each_primitive_keeps_original_condition_and_measurement_causality(self):
        for node in self.program["body"]:
            if "synthesis_certificate_ref" not in node:
                continue
            children = [op for op in self.ops if op.get("synthesis_instance_id") == node["id"]]
            self.assertTrue(children)
            source = node["logical_source_op"]
            self.assertEqual(children[0]["branch_global_phase_pi"], self.program["templates"][node["template_id"]]["metadata"]["global_phase_pi"])
            for op in children:
                self.assertEqual(op["condition"], source["condition"])
                self.assertIn(source["condition"]["bit"], op["reads"])
                self.assertIn(source["id"], op["source_ids"])
                self.assertEqual(op["qubits"], source["qubits"])

    def test_all_256_branch_counts_match_actual_gate_inventory(self):
        summary = self.program["resource_summary"]
        counts = []
        for value in range(256):
            bits = [int(b) for b in f"{value:08b}"]
            values = {f"phase[{i}]": bit for i, bit in enumerate(bits)}
            actual = sum(op["params"].get("name") in ("T", "TDG") and
                         (op["condition"] is None or values[op["condition"]["bit"]] == 1)
                         for op in self.ops)
            formula = summary["unconditional_t_like"] + sum(count * values[bit] for bit, count in summary["conditional_t_like_by_bit_equals_one"].items())
            self.assertEqual(actual, formula)
            counts.append(actual)
        self.assertEqual((min(counts), max(counts)), (35, 817))
        for bits, expected in (([0]*8, 35), ([1]*8, 817), ([0,1,0,0,0,0,0,0], 35)):
            report = t_demand_for_phase(self.program, bits)
            self.assertEqual(report["t_like_count"], expected)
            self.assertEqual(len(report["requests"]), expected)
            self.assertEqual(report["execution_kind"], "compile_plan")

    def test_precision_tightening_never_relabels_existing_words(self):
        with self.assertRaisesRegex(FrontendError, "SYNTHESIS_PRECISION_UNMET"):
            build_shor15(synthesis_error_budget=1e-6)
        unchanged = synthesize_feedback(self.program)
        self.assertEqual(unchanged, self.program)
        unchanged["branch_global_phases"].clear()
        self.assertTrue(self.program["branch_global_phases"])

    def test_changed_word_certificate_phase_or_control_fails(self):
        for mutation in ("word", "certificate", "phase", "condition", "quantum_control", "omitted_instance", "status_bypass"):
            program = deepcopy(self.program)
            call = next(n for n in program["body"] if "synthesis_certificate_ref" in n)
            ref = call["synthesis_certificate_ref"]
            if mutation == "word":
                program["templates"][ref]["body"][0]["op"]["params"]["name"] = "X"
            elif mutation == "certificate":
                program["synthesis_certificates"][ref]["operator_error_upper_bound"] = "0"
            elif mutation == "phase":
                program["branch_global_phases"][0]["global_phase_pi"]["numerator"] += 1
            elif mutation == "condition":
                call["condition"] = {"bit": "phase[0]", "equals": 1}
            elif mutation == "quantum_control":
                call["condition_scope"] = "quantum"
            elif mutation == "status_bypass":
                program["synthesis"]["status"] = "incomplete"
            else:
                program["body"].remove(call)
            with self.assertRaises(FrontendError, msg=mutation):
                require_clifford_t(program)

    def test_qasm_exports_retained_conditional_global_phases(self):
        source = to_openqasm3(self.program)
        self.assertEqual(source.count("gphase("), 15)
        self.assertEqual(source.count(" = measure "), 8)
        self.assertNotIn(" p(", source)
        for line in source.splitlines():
            if "gphase(" in line:
                self.assertTrue(line.startswith("if (phase["))


if __name__ == "__main__":
    unittest.main()
