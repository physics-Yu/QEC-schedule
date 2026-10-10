"""T203 semantic validation and explicitly fictional capability fixtures."""

from copy import deepcopy
import json
import unittest

from na_pipeline.frontend import (
    FrontendError, encoded_operation_catalog, logical_block_ref, build_t000_program,
    iter_encoded_calls, validate_encoded_program, make_encoded_call, make_encoded_program,
    adapt_logical_program, build_shor15,
)


def capability_fixture(program):
    """Shape-only fixture, not an Enola pin or R6 qualification claim."""
    blocks = {b["logical_id"]: b for b in program["blocks"]}
    entries = []
    for call in program["body"]:
        entries.append({"operation": call["operation"], "semantic_version": "1.0.0",
                        "params": call["params"].copy(),
                        "operand_profiles": {role: {"code_profile": blocks[b]["code_profile"].copy(),
                                                    "layout_profile_ref": blocks[b]["layout_profile_ref"]}
                                             for role, b in call["operands"].items()},
                        "strategy_available": True, "strategy_id": "fixture-only-" + call["id"],
                        "strategy_hash": "a"*64, "backend_used": "enola_function_kernel", "enola_pin": "b"*40,
                        "qualification": {"passed": True, "strategy_hash": "a"*64,
                                          "report_ref": "fixture://synthetic-qualification-assertion"}})
    return {"schema_version": "EncodedStrategyCapabilities/0.1.0", "fixture": True,
            "device_profile_ref": program["device_profile_ref"], "entries": entries,
            "interface_versions": program["provenance"]["interfaces"].copy()}


def small_algorithm(gate="X"):
    """Minimal explicit-reset source fixture, no generated Shor shortcut."""
    ops = [
        {"id": "r", "kind": "reset", "qubits": ["q"], "params": {"basis": "Z", "value": 0},
         "reads": [], "writes": [], "after": [], "condition": None, "source_ids": ["fixture:reset"]},
        {"id": "g", "kind": "gate", "qubits": ["q"], "params": {"name": gate},
         "reads": [], "writes": [], "after": ["r"], "condition": None, "source_ids": ["fixture:gate"]},
        {"id": "m", "kind": "measure", "qubits": ["q"], "params": {"basis": "Z"},
         "reads": [], "writes": ["answer"], "after": ["g"], "condition": None, "source_ids": ["fixture:measurement"]}]
    return {"schema_version": "LogicalProgram/0.2.0-draft", "artifact_id": "fixture-small-algorithm",
            "producer_version": "test/1", "provenance": {"fixture": True}, "input_hashes": {"fixture": "declared"},
            "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
            "qubits": [{"id": "q"}], "classical_bits": [{"id": "answer"}], "templates": {},
            "body": [{"kind": "op", "op": op} for op in ops]}


class EncodedSemantics(unittest.TestCase):
    def setUp(self):
        self.program = build_t000_program()

    def test_minimal_program_and_real_boundaries(self):
        self.assertEqual(validate_encoded_program(self.program, require_executable=False), [])
        self.assertEqual({e["code"] for e in validate_encoded_program(self.program)}, {"STRATEGY_UNAVAILABLE"})
        self.assertEqual(self.program["expected_final_lifecycle"], {"L0": "live", "L1": "live"})
        self.assertFalse(self.program["provenance"]["fixture"])
        self.assertEqual(self.program["strategy_qualification"], "not_asserted")

    def test_catalog_does_not_invent_implementations(self):
        catalog = encoded_operation_catalog()
        for item in catalog["operations"].values():
            self.assertTrue(item["semantic_defined"])
            self.assertFalse(item["strategy_available"])
            self.assertFalse(item["qualified"])
            self.assertFalse(item["executable"])
        for name in ("logical_t", "logical_tdg"):
            self.assertEqual(catalog["operations"][name]["resource_requirements"], ["encoded_magic_resource_consumption_protocol"])
        self.assertEqual(catalog["operations"]["reset"]["post_lifecycle"], "unprepared")

    def test_result_and_group_binding_is_instance_local(self):
        calls = list(iter_encoded_calls(self.program))
        self.assertEqual(len(calls), 11)
        results = [result for call in calls for result in call["writes"]]
        self.assertEqual(len(results), 80)
        self.assertEqual(len(set(results)), 80)
        self.assertIn("before.L0/r0/x0", results)
        self.assertIn("before.L0/r2/x0", results)
        init_groups = [g for c in calls for g in c["groups"] if g["purpose"] == "patch_initialization_transport"]
        readout_groups = [g for c in calls for g in c["groups"] if g["purpose"] == "maintenance_readout"]
        self.assertEqual(len(init_groups), 2)
        self.assertEqual(len(readout_groups), 10)
        for g in init_groups:
            self.assertEqual({m["role"] for m in g["members"]}, {f"d{i}" for i in range(9)} | {f"{s}{i}" for s in "xz" for i in range(4)})
        for g in readout_groups:
            self.assertEqual(len(g["members"]), 8)
            self.assertEqual([m["check_type"] for m in g["members"]].count("X"), 4)
            self.assertTrue(all(m["measurement_basis"] == "Z" for m in g["members"]))
            self.assertTrue(all(m["result_id"] in results for m in g["members"]))
        calls[0]["groups"][0]["members"].clear()
        self.assertEqual(len(next(iter_encoded_calls(self.program))["groups"][0]["members"]), 17)

    def test_no_implicit_global_barrier_and_cx_resume(self):
        calls = {c["id"]: c for c in iter_encoded_calls(self.program)}
        self.assertEqual(calls["prepare.L1/r0"]["after"], [])
        self.assertEqual(calls["before.L1/r0"]["after"], ["prepare.L1/r0"])
        self.assertEqual(calls["couple/r0"]["after"], ["before.L0/r2", "before.L1/r2"])
        self.assertEqual(calls["after.L0/r0"]["after"], ["couple/r0"])
        self.assertEqual(calls["after.L1/r0"]["after"], ["couple/r0"])
        self.assertFalse(any(c["operation"] == "reset" for c in calls.values()))

    def test_parameters_directions_groups_and_repeats_reject(self):
        for kind in ("params", "direction", "alias", "orientation", "missing_member", "basis", "repeat", "duplicate"):
            p = deepcopy(self.program)
            if kind == "params": p["body"][0]["params"]["state"] = "1"
            elif kind == "direction": p["body"][4]["operands"] = {"left": "L0", "right": "L1"}
            elif kind == "alias": p["body"][4]["operands"]["target"] = "L0"
            elif kind == "orientation": p["blocks"][0]["code_profile"]["orientation"] = "rotated90"
            elif kind == "missing_member": p["body"][1]["groups"][0]["members"].pop()
            elif kind == "basis": p["body"][1]["groups"][0]["members"][0]["measurement_basis"] = "X"
            elif kind == "repeat": p["body"][0]["repeat"] = 2
            else: p["body"].append(deepcopy(p["body"][0]))
            self.assertTrue(validate_encoded_program(p, require_executable=False), kind)

    def test_missing_block_dependency_and_live_prepare_reject(self):
        p = deepcopy(self.program)
        p["body"][1]["after"] = []
        self.assertIn("MISSING_BLOCK_ORDER", {e["code"] for e in validate_encoded_program(p, require_executable=False)})
        p = deepcopy(self.program)
        p["body"].append(make_encoded_call("overwrite", "prepare", {"block": "L0"}, params={"state": "0"}, after=["after.L0"]))
        self.assertIn("INVALID_LIFECYCLE", {e["code"] for e in validate_encoded_program(p, require_executable=False)})

    def test_destructive_measure_reset_release_and_no_resurrection(self):
        block = logical_block_ref("A")
        calls = [make_encoded_call("p", "prepare", {"block": "A"}, params={"state": "0"}),
                 make_encoded_call("m", "measure", {"block": "A"}, params={"basis": "X"}, after=["p"]),
                 make_encoded_call("r", "reset", {"block": "A"}, after=["m"]),
                 make_encoded_call("free", "release", {"block": "A"}, after=["r"])]
        p = make_encoded_program([block], calls)
        self.assertFalse(validate_encoded_program(p, require_executable=False))
        p["body"].append(make_encoded_call("bad", "syndrome_round", {"block": "A"}, after=["free"]))
        self.assertIn("INVALID_LIFECYCLE", {e["code"] for e in validate_encoded_program(p, require_executable=False)})

    def test_conditional_unitary_has_real_result_dependency(self):
        p = deepcopy(self.program)
        cx = p["body"][4]
        cx["condition"] = {"bit": "before.L0/r2/x0", "equals": 1}
        cx["reads"] = [cx["condition"]["bit"]]
        self.assertFalse(validate_encoded_program(p, require_executable=False))
        self.assertIn("CONDITIONAL_STRATEGY_UNAVAILABLE", {e["code"] for e in validate_encoded_program(p, capabilities=capability_fixture(p))})
        cx["condition"]["bit"] = "after.L0/r0/x0"
        cx["reads"] = [cx["condition"]["bit"]]
        self.assertIn("READ_WITHOUT_PRODUCER_DEPENDENCY", {e["code"] for e in validate_encoded_program(p, require_executable=False)})
        p = deepcopy(self.program)
        p["body"][0]["condition"] = {"bit": "future", "equals": 1}
        p["body"][0]["reads"] = ["future"]
        self.assertIn("CONDITIONAL_LIFECYCLE_UNSUPPORTED", {e["code"] for e in validate_encoded_program(p, require_executable=False)})

    def test_capability_snapshot_checks_identity_and_qualification_separately(self):
        fixture = capability_fixture(self.program)
        # Only the declared fixture assertions are checked; no R6 files or Enola are run.
        self.assertEqual(validate_encoded_program(self.program, capabilities=fixture), [])
        old_profile = deepcopy(fixture)
        old_profile["interface_versions"]["IF-PATCH-GROUP-001"] = "0.1.0"
        self.assertIn("CAPABILITY_CONTRACT_MISMATCH", {e["code"] for e in validate_encoded_program(self.program, capabilities=old_profile)})
        for mutation, expected in (("available", "STRATEGY_UNAVAILABLE"), ("qualified", "STRATEGY_NOT_QUALIFIED"),
                                   ("hash", "STRATEGY_NOT_QUALIFIED"), ("backend", "ENOLA_PROVENANCE_REQUIRED"),
                                   ("pin", "ENOLA_PROVENANCE_REQUIRED"), ("device", "CAPABILITY_PROFILE_MISMATCH")):
            changed = deepcopy(fixture)
            for entry in changed["entries"]:
                if mutation == "available": entry["strategy_available"] = False
                elif mutation == "qualified": entry["qualification"]["passed"] = False
                elif mutation == "hash": entry["qualification"]["strategy_hash"] = "c"*64
                elif mutation == "backend": entry["backend_used"] = "local"
                elif mutation == "pin": entry["enola_pin"] = "unverified"
            if mutation == "device": changed["device_profile_ref"] = "another-device"
            self.assertIn(expected, {e["code"] for e in validate_encoded_program(self.program, capabilities=changed)}, mutation)

    def test_json_determinism_and_semantic_registry_copy_isolation(self):
        self.assertEqual(self.program, build_t000_program())
        self.assertEqual(self.program, json.loads(json.dumps(self.program)))
        catalog = encoded_operation_catalog()
        catalog["operations"]["syndrome_round"]["result_slots"].clear()
        self.assertEqual(len(encoded_operation_catalog()["operations"]["syndrome_round"]["result_slots"]), 8)

    def test_unknown_semantics_and_prepopulated_results_cannot_hide_in_calls(self):
        for key, value in (("reported_bit", 0), ("result_ready_us", 0), ("native_gate", "T")):
            program = deepcopy(self.program)
            program["body"][1][key] = value
            self.assertIn("UNKNOWN_CALL_FIELD", {e["code"] for e in validate_encoded_program(program, require_executable=False)})
        with self.assertRaisesRegex(FrontendError, "UNDEFINED_OPERATION"):
            make_encoded_call("u", "unimplemented_new_protocol", {"block": "L0"})


class AlgorithmBoundary(unittest.TestCase):
    def test_no_automatic_full_shor_or_physical_t(self):
        with self.assertRaisesRegex(FrontendError, "SHOR_ADAPTER_NOT_ENABLED"):
            adapt_logical_program(build_shor15(synthesize=False), {"ctrl": "C", **{f"w{i}": f"W{i}" for i in range(4)}})
        with self.assertRaisesRegex(FrontendError, "STRATEGY_UNAVAILABLE"):
            adapt_logical_program(small_algorithm("T"), {"q": "A"})

    def test_small_source_adapter_and_result_aliases_with_fixture_contract(self):
        expected = make_encoded_program([logical_block_ref("A")], [
            make_encoded_call("r/encoded", "prepare", {"block": "A"}, params={"state": "0"}),
            make_encoded_call("g/encoded", "logical_x", {"block": "A"}, after=["r/encoded"]),
            make_encoded_call("m/encoded", "measure", {"block": "A"}, params={"basis": "Z"}, after=["g/encoded"])])
        source = small_algorithm()
        result = adapt_logical_program(source, {"q": "A"}, capabilities=capability_fixture(expected))
        self.assertEqual(result["algorithm_result_aliases"], {"answer": "m/encoded/r0/value"})
        self.assertEqual(result["source_program_ref"]["artifact_id"], source["artifact_id"])
        self.assertEqual(len(result["source_program_ref"]["canonical_sha256"]), 64)
        self.assertEqual(result["body"][1]["source_operation"], source["body"][1]["op"])
        self.assertFalse(any(call["operation"] == "X" for call in result["body"]))
        self.assertTrue(result["provenance"]["fixture"])
        self.assertTrue(result["capability_snapshot_ref"]["fixture"])

    def test_t_capability_requires_resource_protocol_even_with_qualification_assertion(self):
        expected = make_encoded_program([logical_block_ref("A")], [
            make_encoded_call("r/encoded", "prepare", {"block": "A"}, params={"state": "0"}),
            make_encoded_call("g/encoded", "logical_t", {"block": "A"}, after=["r/encoded"]),
            make_encoded_call("m/encoded", "measure", {"block": "A"}, params={"basis": "Z"}, after=["g/encoded"])])
        with self.assertRaisesRegex(FrontendError, "MAGIC_RESOURCE_STRATEGY_REQUIRED"):
            adapt_logical_program(small_algorithm("T"), {"q": "A"}, capabilities=capability_fixture(expected))


if __name__ == "__main__":
    unittest.main()
