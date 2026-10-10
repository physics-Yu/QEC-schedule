"""R4 author tests. Independent acceptance belongs to R6, not these helpers."""
from copy import deepcopy
import json
import unittest

from na_pipeline.backend import CompilationError, compile_physical, validate_cz_pairs, validate_motion
from na_pipeline.backend.geometry import broadcast_pairs
from na_pipeline.device import default_device
from na_pipeline.qec import build_two_block_slice, iter_physical_ops


def op(oid, kind, qubits, params, *, writes=(), reads=(), condition=None, after=()):
    return {"kind": "op", "op": {"id": oid, "kind": kind, "qubits": qubits,
        "params": params, "reads": list(reads), "writes": list(writes), "after": list(after),
        "source_ids": ["fixture:" + oid], "condition": condition}}


def fixture(nodes, n=2):
    return {"schema_version": "physical-program/0.2.0-draft", "artifact_id": "r4-unit-fixture",
            "provenance": {"fixture": True}, "execution_kind": "compile_plan",
            "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
            "qubits": [{"id": f"q{i}", "block_id": "fixture", "role": "data", "aod_group": "data"} for i in range(n)],
            "templates": {}, "body": nodes}


class CompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = default_device()
        cls.physical = build_two_block_slice(rounds=1)
        cls.plan = compile_physical(cls.physical, cls.device)

    def test_real_producer_complete_coverage(self):
        source = list(iter_physical_ops(self.physical))
        self.assertTrue(self.plan["complete"])
        self.assertFalse(self.plan["provenance"]["fixture"])
        self.assertEqual(set(self.plan["source_map"]), {o["id"] for o in source})
        actions = {a["id"]: a for a in self.plan["actions"]}
        for s in source:
            mapped = [actions[aid] for aid in self.plan["source_map"][s["id"]]]
            self.assertTrue(mapped)
            self.assertTrue(all(s["id"] in a["source_ids"] for a in mapped))
            self.assertTrue(all(a["payload"]["source_metadata"] == s.get("metadata", {}) for a in mapped))
            self.assertTrue(all(a["payload"]["source_reads"] == s["reads"] and a["payload"]["source_writes"] == s["writes"] for a in mapped))
            if s["kind"] == "measure":
                self.assertEqual([a["payload"]["writes"] for a in mapped if a["payload"]["writes"]], [s["writes"]])
                self.assertTrue(all(not a["payload"]["writes"] for a in mapped if a["kind"] != "measure"))
            if s["kind"] == "gate" and s["params"]["name"] == "CX":
                gates = [a for a in mapped if a["kind"] == "gate"]
                self.assertEqual([a["payload"]["name"] for a in gates], ["H", "CZ", "H"])
                self.assertEqual(gates[0]["atoms"], gates[2]["atoms"])
                self.assertGreaterEqual(gates[2]["t_start_us"], gates[1]["t_end_us"])
        self.assertEqual(self.plan["stats"]["atom_count"], 34)
        self.assertEqual(self.plan["stats"]["max_live_physical_ops"], 1)

    def test_parallel_single_qubit_actions(self):
        p = fixture([op("h0", "gate", ["q0"], {"name": "H"}), op("h1", "gate", ["q1"], {"name": "H"})])
        a = compile_physical(p, self.device)["actions"]
        self.assertEqual(a[0]["t_start_us"], a[1]["t_start_us"])
        self.assertFalse(set(a[0]["resources"]) & set(a[1]["resources"]))

    def test_ready_and_feedback_latency(self):
        p = fixture([op("m", "measure", ["q0"], {"basis": "Z"}, writes=["b"]),
                     op("x", "gate", ["q1"], {"name": "X"}, reads=["b"], condition={"bit": "b", "equals": 1})])
        d = deepcopy(self.device)
        d["timings_us"]["result_latency"] = 1_000_000.
        d["timings_us"]["feedback_latency"] = 29.
        a = compile_physical(p, d)["actions"]
        measure = next(x for x in a if x["kind"] == "measure")
        conditional = next(x for x in a if x["condition"])
        self.assertEqual(measure["payload"]["result_ready_us"], measure["t_end_us"] + 1_000_000.)
        self.assertGreaterEqual(conditional["t_start_us"], measure["payload"]["result_ready_us"] + 29.)
        self.assertIn(measure["id"], conditional["depends_on"])

    def test_budget_is_failure_and_prefix_is_not_complete(self):
        with self.assertRaises(CompilationError) as caught:
            compile_physical(self.physical, self.device, max_ops=3)
        self.assertEqual(caught.exception.code, "OP_BUDGET_EXHAUSTED")
        self.assertFalse(caught.exception.partial_program["complete"])
        self.assertEqual(caught.exception.partial_program["stats"]["physical_op_count"], 3)
        p = fixture([op("h", "gate", ["q0"], {"name": "H"})])
        self.assertTrue(compile_physical(p, self.device, max_ops=1)["complete"])

    def test_no_cross_instance_results(self):
        p = build_two_block_slice(rounds=2)
        a = compile_physical(p, self.device)
        results = [x["payload"]["result_id"] for x in a["actions"] if x["kind"] == "measure"]
        expected = [o["writes"][0] for o in iter_physical_ops(p) if o["kind"] == "measure"]
        self.assertEqual(results, expected)
        self.assertEqual(len(results), len(set(results)))

    def test_inputs_not_mutated_and_fresh_runs(self):
        p, d = deepcopy(self.physical), deepcopy(self.device)
        a = compile_physical(p, d)
        self.assertEqual(p, self.physical)
        self.assertEqual(d, self.device)
        self.assertEqual(a["actions"], self.plan["actions"])
        a["initial_state"]["atoms"][0]["position_um"][0] = -123
        self.assertNotEqual(a["initial_state"], self.plan["initial_state"])
        json.dumps(self.plan, allow_nan=False)

    def test_extra_broadcast_pair_is_rejected(self):
        d = deepcopy(self.device)
        d["geometry"]["initial_spacing_um"] = 2.
        p = fixture([op("cz", "gate", ["q0", "q1"], {"name": "CZ"})], n=9)
        with self.assertRaises(CompilationError) as caught:
            compile_physical(p, d)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_MULTIBODY_BROADCAST")
        self.assertFalse(caught.exception.partial_program["complete"])

    def test_conditional_two_qubit_has_explicit_boundary(self):
        p = fixture([op("m", "measure", ["q0"], {"basis": "Z"}, writes=["b"]),
                     op("c", "gate", ["q0", "q1"], {"name": "CX"}, reads=["b"], condition={"bit": "b", "equals": 1})])
        with self.assertRaises(CompilationError) as caught:
            compile_physical(p, self.device)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_CONDITIONAL_OPERATION")

    def test_rotation_params_survive(self):
        params = {"name": "RZ", "angle": .321, "angle_unit": "rad"}
        p = fixture([op("rz", "gate", ["q0"], params)])
        self.assertEqual(compile_physical(p, self.device)["actions"][0]["payload"]["params"], params)

    def test_unknown_parameters_and_evidence_are_not_erased(self):
        p = fixture([op("h", "gate", ["q0"], {"name": "H", "hidden_control": "q1"})])
        with self.assertRaises(CompilationError) as caught:
            compile_physical(p, self.device)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_PARAMETERS")
        p["loss_enabled"] = True
        with self.assertRaises(CompilationError) as caught:
            compile_physical(p, self.device)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_EVIDENCE")

    def test_malformed_input_and_missing_decomposition_gate(self):
        with self.assertRaises(CompilationError) as caught:
            compile_physical({}, self.device)
        self.assertEqual(caught.exception.code, "PHYSICAL_PROGRAM_SCHEMA")
        p = fixture([op("cx", "gate", ["q0", "q1"], {"name": "CX"})])
        d = deepcopy(self.device)
        d["operations"]["native_1q_gates"].remove("H")
        with self.assertRaises(CompilationError) as caught:
            compile_physical(p, d)
        self.assertEqual(caught.exception.code, "DEVICE_GATE_UNSUPPORTED")

    def test_all_results_keep_measurement_actions_and_transport(self):
        for oid, ids in self.plan["source_map"].items():
            actions = [a for a in self.plan["actions"] if a["id"] in ids]
            if any(a["kind"] == "measure" for a in actions):
                kinds = [a["kind"] for a in actions]
                self.assertEqual(kinds.count("pickup"), 2)
                self.assertEqual(kinds.count("drop"), 2)
                self.assertEqual(kinds.count("measure"), 1)
                self.assertGreaterEqual(kinds.count("move"), 2)


class MotionTests(unittest.TestCase):
    @staticmethod
    def atom(aid, p, row, col):
        return {"atom_id": aid, "position_um": p, "carrier": "AOD", "aod_group": "data",
                "row_id": row, "column_id": col}

    @staticmethod
    def tr(a, end):
        return {"atom_id": a["atom_id"], "from_um": a["position_um"], "to_um": end,
                "row_id": a["row_id"], "column_id": a["column_id"]}

    def test_crossing_columns_even_without_atom_collision(self):
        a = self.atom("a", [0., 0.], "r0", "c0")
        b = self.atom("b", [10., 10.], "r1", "c1")
        errors = validate_motion([a, b], [self.tr(a, [10., 0.]), self.tr(b, [0., 10.])], "data")
        self.assertIn("AXIS_CROSSING", [e["code"] for e in errors])
        self.assertNotIn("ATOM_COLLISION", [e["code"] for e in errors])

    def test_omitted_shared_row_resident(self):
        a = self.atom("a", [0., 0.], "r0", "c0")
        b = self.atom("b", [10., 0.], "r0", "c1")
        errors = validate_motion([a, b], [self.tr(a, [0., 10.])], "data")
        self.assertIn("SHARED_AXIS", [e["code"] for e in errors])
        self.assertEqual(validate_motion([a, b], [self.tr(a, [0., 10.]), self.tr(b, [10., 10.])], "data"), [])

    def test_swept_collision_and_teleport(self):
        a = self.atom("a", [0., 0.], "r0", "c0")
        b = {"atom_id": "b", "position_um": [5., 5.], "carrier": "SLM", "aod_group": "data"}
        errors = validate_motion([a, b], [self.tr(a, [10., 10.])], "data")
        self.assertIn("ATOM_COLLISION", [e["code"] for e in errors])
        tr = self.tr(a, [10., 0.]); tr["from_um"] = [1., 0.]
        self.assertIn("TELEPORT", [e["code"] for e in validate_motion([a], [tr], "data")])

    def test_all_edges_preserved_multibody_rejected_disjoint_pairs_supported(self):
        zone = {"bounds_um": [[None, None], [None, None]]}
        atoms = [{"atom_id": aid, "position_um": p} for aid, p in
                 (("a", [0., 0.]), ("b", [2., 0.]), ("c", [4., 0.]))]
        pairs = broadcast_pairs(atoms, zone, 2.)
        self.assertEqual(pairs, [["a", "b"], ["b", "c"]])
        self.assertEqual(validate_cz_pairs(pairs)[0]["atom_id"], "b")
        atoms += [{"atom_id": "d", "position_um": [6., 3.]},
                  {"atom_id": "spectator", "position_um": [20., 20.]}]
        atoms[2]["position_um"] = [4., 3.]
        pairs = broadcast_pairs(atoms, zone, 2.)
        self.assertEqual(pairs, [["a", "b"], ["c", "d"]])
        self.assertEqual(validate_cz_pairs(pairs), [])


if __name__ == "__main__":
    unittest.main()
