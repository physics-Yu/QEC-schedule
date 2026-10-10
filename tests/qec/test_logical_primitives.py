"""T303 contract checks; no claim of atom routing or Enola execution."""

from copy import deepcopy
import unittest

from na_pipeline.qec import (LogicalPrimitiveError, build_logical_primitive, iter_physical_ops,
                             logical_primitive_capabilities, validate_primitive_contract)


class LogicalPrimitives(unittest.TestCase):
    def test_complete_core_sources_and_stable_formal_identity(self):
        for op, params, count in (("prepare", {"state": "0"}, 71), ("prepare", {"state": "+"}, 80),
                                  ("syndrome_round", {}, 56), ("logical_cx", {}, 9)):
            with self.subTest(operation=op, params=params):
                a = build_logical_primitive(op, params=params)
                b = build_logical_primitive(op, params=params)
                self.assertEqual(a, b)
                self.assertEqual(validate_primitive_contract(a), [])
                self.assertEqual(len(list(iter_physical_ops(a))), count)
                self.assertEqual(a["strategy_contract"]["operation"]["semantic_version"], "1.0.0")
                a["strategy_contract"]["groups"].clear()
                self.assertEqual(b, build_logical_primitive(op, params=params))

    def test_maintenance_never_resets_or_measures_data(self):
        p = build_logical_primitive("syndrome_round")
        ops = list(iter_physical_ops(p))
        for op in ops:
            if op["kind"] in {"reset", "measure"}:
                self.assertFalse(any(q.startswith("block/d") for q in op["qubits"]))
        self.assertEqual(sum(op["kind"] == "measure" for op in ops), 8)
        self.assertEqual(sum(op["kind"] == "reset" for op in ops), 16)
        self.assertEqual(sum(op["params"].get("name") == "CX" for op in ops), 24)
        self.assertEqual(p["strategy_contract"]["exit"]["data_effect"], "preserved_unmeasured")

    def test_readout_group_tracks_each_real_last_coupling_and_basis_change(self):
        p = build_logical_primitive("syndrome_round")
        ops = list(iter_physical_ops(p))
        by_id = {op["id"]: op for op in ops}
        group, = p["strategy_contract"]["groups"]
        self.assertEqual(group["purpose"], "maintenance_readout")
        self.assertEqual(len(group["members"]), 8)
        self.assertEqual(group["target_layout_id"], "ancilla_readout")
        self.assertIsNone(group["numeric_synchronization_tolerance_us"])
        self.assertEqual({m["encoded_result_slot"] for m in group["members"]}, {f"{basis}{i}" for basis in "xz" for i in range(4)})
        for member in group["members"]:
            q = member["physical_qubit_id"]
            last = [op for op in ops if op["params"].get("name") == "CX" and q in op["qubits"]][-1]
            self.assertEqual(member["last_coupling_op_id"], last["id"])
            measure = by_id[member["measurement_op_id"]]
            self.assertEqual(measure["qubits"], [q])
            self.assertEqual(measure["writes"], [member["result_id"]])
            self.assertEqual(measure["params"], {"basis": "Z"})
            if member["check_type"] == "X":
                h = by_id[member["basis_change_op_id"]]
                self.assertEqual(h["params"], {"name": "H"})
                self.assertIn(last["id"], h["after"])
                self.assertIn(h["id"], measure["after"])
            else:
                self.assertIsNone(member["basis_change_op_id"])
                self.assertIn(last["id"], measure["after"])
            reset = by_id[member["post_readout_reset_op_id"]]
            self.assertIn(measure["id"], reset["after"])
            self.assertEqual(reset["kind"], "reset")
        # There is no cross-member physical readout barrier or artificial time.
        for member in group["members"]:
            measure = by_id[member["measurement_op_id"]]
            self.assertTrue(all(by_id[dep]["qubits"] == measure["qubits"] or by_id[dep]["kind"] == "gate" for dep in measure["after"]))
            self.assertNotIn("t_start_us", measure)

    def test_initialization_declares_all_seventeen_transport_prerequisites(self):
        for state in ("0", "+"):
            p = build_logical_primitive("prepare", params={"state": state})
            init, readout = p["strategy_contract"]["groups"]
            self.assertEqual(init["purpose"], "patch_initialization_transport")
            self.assertEqual(init["source_layout_id"], "patch_initialization")
            self.assertEqual(init["target_layout_id"], "patch_home")
            self.assertFalse(init["destination_is_measurement_zone"])
            self.assertEqual(len(init["members"]), 17)
            ops = list(iter_physical_ops(p))
            self.assertEqual({m["physical_qubit_id"] for m in init["members"]}, {q["id"] for q in p["qubits"]})
            for member in init["members"]:
                first = next(op for op in ops if member["physical_qubit_id"] in op["qubits"])
                self.assertEqual(first["kind"], "reset")
                self.assertEqual(member["prepare_before_op_ids"], [first["id"]])
            self.assertEqual(len(readout["members"]), 8)
            conditional = [op for op in ops if op["condition"]]
            self.assertEqual(len(conditional), 6)
            self.assertTrue(all(op["reads"] == [op["condition"]["bit"]] for op in conditional))

    def test_transversal_is_separate_directed_strategy_and_has_maintenance_exit(self):
        p = build_logical_primitive("logical_cx")
        ops = list(iter_physical_ops(p))
        self.assertEqual(len(p["qubits"]), 34)
        self.assertEqual(p["strategy_contract"]["groups"], [])
        self.assertEqual(p["strategy_contract"]["operation"]["formal_operands"], ["control", "target"])
        for i, op in enumerate(ops):
            self.assertEqual(op["params"], {"name": "CX"})
            self.assertEqual(op["qubits"], [f"control/d{i}", f"target/d{i}"])
        self.assertEqual(p["strategy_contract"]["exit"]["home_relation"], "same_formal_home_as_entry")
        self.assertEqual(p["strategy_contract"]["exit"]["next_local_primitive"], "syndrome_round")
        self.assertEqual(p["strategy_contract"]["formal_bindings"]["result_slots"], [])

    def test_actual_repeat_namespaces_without_mutating_template(self):
        formal = build_logical_primitive("syndrome_round")
        template_before = deepcopy(formal["templates"])
        # Source-level instance test only: R4/R5 bind the strategy and group view.
        source = deepcopy(formal)
        source.pop("strategy_contract")
        source["body"][0]["id"] = "independent_call"
        source["body"][0]["repeat"] = 3
        ops = list(iter_physical_ops(source))
        results = [bit for op in ops for bit in op["writes"]]
        self.assertEqual(len(results), 24)
        self.assertEqual(len(set(results)), 24)
        self.assertEqual(formal["templates"], template_before)
        self.assertEqual(formal, build_logical_primitive("syndrome_round"))

    def test_reject_wrong_members_basis_direction_and_source_change(self):
        mutations = [
            lambda p: p["strategy_contract"]["groups"][0]["members"].pop(),
            lambda p: p["strategy_contract"]["groups"][0]["members"][0].update(basis_change_op_id=None),
            lambda p: p["strategy_contract"]["groups"][0].update(target_layout_id="patch_home"),
            lambda p: p["strategy_contract"]["entry"].update(orientation="mirrored"),
            lambda p: next(iter(p["templates"].values()))["body"][0]["op"].update(qubits=["d0"]),
            lambda p: p["strategy_contract"]["formal_bindings"]["result_slots"][0].update(value=0),
            lambda p: p.update(quantum_state_simulated=True),
            lambda p: p["provenance"].update(binding_scope="executed"),
            lambda p: p.update(results={"x0": {"value": 0, "origin": "fake"}}),
        ]
        for mutation in mutations:
            p = build_logical_primitive("syndrome_round")
            mutation(p)
            self.assertTrue(validate_primitive_contract(p))
        cx = build_logical_primitive("logical_cx")
        next(iter(cx["templates"].values()))["body"][0]["op"]["qubits"].reverse()
        self.assertTrue(validate_primitive_contract(cx))

    def test_capabilities_do_not_invent_strategy_qualification_or_nonclifford(self):
        capabilities = logical_primitive_capabilities()
        self.assertFalse(capabilities["compiled_strategy_available"])
        self.assertFalse(capabilities["enola_integrated"])
        self.assertFalse(capabilities["qualified"])
        for name in ("T", "logical_t", "measure", "reset", "release", "H", "logical_h"):
            with self.assertRaises(LogicalPrimitiveError):
                build_logical_primitive(name)
        for operation, params in (("prepare", {}), ("prepare", {"state": "zero"}),
                                   ("syndrome_round", {"rounds": 3}), ("logical_cx", {"condition": 1})):
            with self.assertRaises(LogicalPrimitiveError):
                build_logical_primitive(operation, params=params)


class ProducerCompatibility(unittest.TestCase):
    def test_r2_production_catalog_and_t000_calls(self):
        from na_pipeline.frontend import build_t000_program, encoded_operation_catalog, iter_encoded_calls, validate_encoded_program
        source = build_t000_program(rounds=3)
        self.assertEqual(validate_encoded_program(source, require_executable=False), [])
        catalog = encoded_operation_catalog()["operations"]
        count = 0
        shapes = {}
        for call in iter_encoded_calls(source):
            p = build_logical_primitive(call["operation"], params=call["params"])
            contract = p["strategy_contract"]
            declaration = catalog[call["operation"]]
            self.assertEqual(contract["operation"]["semantic_version"], declaration["semantic_version"])
            self.assertEqual(contract["operation"]["formal_operands"], declaration["operand_roles"])
            self.assertEqual(contract["operation"]["encoded_result_slots"], declaration["result_slots"])
            count += 1
            if call["operation"] == "syndrome_round":
                shapes.setdefault(contract["contract_hash"], 0)
                shapes[contract["contract_hash"]] += 1
        self.assertEqual(count, 11)
        self.assertEqual(list(shapes.values()), [8])
        self.assertTrue(validate_encoded_program(source))  # No backend capability certificate supplied.

    def test_r1_production_profiles_resolve_every_group_member(self):
        from na_pipeline.device import grouped_device, group_layout, validate_device
        device = grouped_device()
        self.assertEqual(validate_device(device), [])
        for operation, params in (("prepare", {"state": "0"}), ("syndrome_round", {})):
            p = build_logical_primitive(operation, params=params)
            for group in p["strategy_contract"]["groups"]:
                source = group_layout(device, group["source_layout_id"])
                target = group_layout(device, group["target_layout_id"])
                roles = {member["local_role"] for member in group["members"]}
                self.assertTrue(roles <= source["slots"].keys())
                self.assertTrue(roles <= target["slots"].keys())
                self.assertEqual(roles, set(device["grouped_profile"]["groups"][group["purpose"]]["members"]))


if __name__ == "__main__":
    unittest.main()
