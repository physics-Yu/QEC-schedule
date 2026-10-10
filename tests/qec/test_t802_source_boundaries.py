"""R3-owned derived checks for E01/E07 and K01/K04/K05; not R6 qualification."""

from copy import deepcopy
import unittest

from na_pipeline.qec import build_logical_primitive, check_projection_window, iter_physical_ops, validate_primitive_contract


def projection_fixture():
    def op(id, kind, qubits, params, writes=()):
        return {"kind": "op", "op": {"id": id, "kind": kind, "qubits": qubits, "params": params,
                 "reads": [], "writes": list(writes), "after": [], "source_ids": [f"K01:{id}"], "condition": None}}
    return {"schema_version": "physical-program/0.2.0-draft", "artifact_id": "K01-derived-source-fixture",
            "provenance": {"fixture": True, "kind": "R3_source_boundary_test"}, "templates": {},
            "qubits": [{"id": q, "block_id": "fixture", "role": "data", "aod_group": "data"} for q in ("a", "b", "c", "d")],
            "body": [op("cz0", "gate", ["a", "b"], {"name": "CZ"}),
                     op("h", "gate", ["b"], {"name": "H"}),
                     op("cz1", "gate", ["a", "b"], {"name": "CZ"})]}


class T802SourceBoundaries(unittest.TestCase):
    def test_k01_reject_two_pairs_across_real_h_boundary(self):
        p = projection_fixture()
        ops = list(iter_physical_ops(p))
        self.assertIn("cz0", ops[1]["after"])
        self.assertIn("h", ops[2]["after"])
        before = deepcopy(p)
        for commutable in (True, False):
            errors = check_projection_window(p, ["cz0", "cz1"], commutable=commutable)
            self.assertIn("NON_PAIR_BOUNDARY_CROSSED", {e["code"] for e in errors})
        self.assertEqual(check_projection_window(p, ["cz0"]), [])
        self.assertEqual(check_projection_window(p, ["cz1"]), [])
        self.assertEqual(p, before)
        p["body"][0]["op"]["params"]["unexplained_angle"] = 0.25
        self.assertIn("PROJECTION_OPERATION_UNSUPPORTED", {e["code"] for e in check_projection_window(p, ["cz0"])})

    def test_measure_reset_wait_and_classical_boundaries_are_not_erased(self):
        variants = [
            [{"id": "middle", "kind": "reset", "qubits": ["b"], "params": {"basis": "Z"}}],
            [{"id": "middle", "kind": "wait", "qubits": ["b"], "params": {"duration_us": 7}}],
            [{"id": "measure", "kind": "measure", "qubits": ["b"], "params": {"basis": "Z"}, "writes": ["bit"]},
             {"id": "classical", "kind": "classical", "qubits": [], "params": {"operation": "xor"}, "reads": ["bit"], "writes": ["copy"]}],
        ]
        for variant in variants:
            p = projection_fixture()
            middle = []
            for item in variant:
                fields = {"reads": [], "writes": [], "after": [], "source_ids": ["boundary_fixture"], "condition": None, **item}
                middle.append({"kind": "op", "op": fields})
            p["body"][1:2] = middle
            self.assertIn("NON_PAIR_BOUNDARY_CROSSED", {e["code"] for e in check_projection_window(p, ["cz0", "cz1"])})

    def test_actual_syndrome_layers_and_cx_are_safe_antichains(self):
        p = build_logical_primitive("syndrome_round")
        ops = list(iter_physical_ops(p))
        for layer in range(4):
            ids = [op["id"] for op in ops if op.get("metadata", {}).get("syndrome_layer") == layer]
            self.assertEqual(len(ids), 6)
            self.assertEqual(check_projection_window(p, ids), [])
        all_pairs = [op["id"] for op in ops if op["params"].get("name") == "CX"]
        self.assertIn("DEPENDENT_PAIR_OPERATIONS", {e["code"] for e in check_projection_window(p, all_pairs)})
        cx = build_logical_primitive("logical_cx")
        self.assertEqual(check_projection_window(cx, [op["id"] for op in iter_physical_ops(cx)]), [])

    def test_k04_late_x_basis_rejects_early_common_readout(self):
        from na_pipeline.device import grouped_device, group_layout, validate_readout_batch
        p = build_logical_primitive("syndrome_round")
        members = p["strategy_contract"]["groups"][0]["members"]
        self.assertTrue(next(m for m in members if m["local_role"] == "x0")["basis_change_op_id"])
        device = grouped_device()
        layout = group_layout(device, "ancilla_readout")
        entries = []
        for m in members:
            role = m["local_role"]
            entries.append({"atom_id": f"fixture:{role}", "bank_id": "fixture:bank", "site_id": role,
                            "position_um": layout["slots"][role]["position_um"], "basis": "Z",
                            "t_start_us": 120, "t_end_us": 120 + device["timings_us"]["measure"],
                            "earliest_ready_us": 130 if role == "x0" else 120,
                            "result_id": f"fixture:{role}:result", "result_ready_us": 120 + device["timings_us"]["measure"] + device["timings_us"]["result_latency"]})
        self.assertIn("READOUT_BEFORE_READY", {e["code"] for e in validate_readout_batch(device, entries)})
        for entry in entries:
            for key in ("t_start_us", "t_end_us", "result_ready_us"):
                entry[key] += 10
        self.assertEqual(validate_readout_batch(device, entries), [])
        self.assertEqual(len({e["result_id"] for e in entries}), 8)

    def test_k05_partial_initialization_rejected_at_source_and_device_boundary(self):
        from na_pipeline.device import grouped_device, group_layout, validate_group_transfer
        p = build_logical_primitive("prepare", params={"state": "0"})
        members = p["strategy_contract"]["groups"][0]["members"]
        self.assertEqual(len(members), 17)
        p["strategy_contract"]["groups"][0]["members"] = [m for m in members if m["local_role"].startswith("d")]
        self.assertIn("GROUP_CONTRACT_CHANGED", {e["code"] for e in validate_primitive_contract(p)})
        device = grouped_device()
        layout = group_layout(device, "patch_initialization")
        atoms = {f"fixture:{slot}": {"position_um": item["position_um"], "carrier": "SLM"} for slot, item in layout["slots"].items()}
        partial = {slot: f"fixture:{slot}" for slot in layout["slots"] if slot.startswith("d")}
        errors = validate_group_transfer(device, "patch_initialization_transport", atoms, partial, target_layout_id="patch_home")
        self.assertIn("GROUP_MEMBERS", {e["code"] for e in errors})
        complete = {slot: f"fixture:{slot}" for slot in layout["slots"]}
        self.assertEqual(validate_group_transfer(device, "patch_initialization_transport", atoms, complete, target_layout_id="patch_home"), [])

    def test_removed_h_and_reversed_cx_fail_existing_formal_contract(self):
        p = build_logical_primitive("syndrome_round")
        template = next(iter(p["templates"].values()))
        template["body"] = [n for n in template["body"] if n["op"]["id"] != "read_basis_x0"]
        self.assertIn("PHYSICAL_SOURCE_CHANGED", {e["code"] for e in validate_primitive_contract(p)})
        p = build_logical_primitive("logical_cx")
        next(iter(p["templates"].values()))["body"][0]["op"]["qubits"].reverse()
        self.assertIn("PHYSICAL_SOURCE_CHANGED", {e["code"] for e in validate_primitive_contract(p)})


if __name__ == "__main__":
    unittest.main()
