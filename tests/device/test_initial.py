"""T103 t=0 declaration checks, separate from placement/runtime qualification."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from na_pipeline.device import (
    DeviceModelError, build_preinitialized_state, default_device, grouped_device,
    group_layout, patch_geometry, preinitialized_device, validate_device,
    validate_preinitialized_state, validate_readout_batch,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class PreinitializedDeviceTests(unittest.TestCase):
    def test_new_profile_has_no_initialization_zone_or_transport(self):
        device = preinitialized_device()
        self.assertEqual(validate_device(device), [])
        self.assertEqual(device["entry_mode"], "preinitialized")
        profile = device["grouped_profile"]
        self.assertNotIn("initialization_zone", profile)
        self.assertEqual(set(profile["layouts"]), {"patch_home", "ancilla_readout"})
        self.assertEqual(set(profile["groups"]), {"maintenance_readout"})
        with self.assertRaises(DeviceModelError):
            group_layout(device, "patch_initialization")

    def test_legacy_profiles_and_operating_parameters_preserved(self):
        self.assertEqual(digest(default_device()), "1c436306473c9938e7febf7abceb1ebceb28a52c7c5fc6d3e5aa02bf338ccf5f")
        self.assertEqual(digest(grouped_device()), "8fccbae5109b845f58b5d8cb46a540d8a50978d9038656e393a96ce15e330ba5")
        new = preinitialized_device()
        for key in ("timings_us", "movement", "geometry", "aod_groups", "operations", "measurement", "reset"):
            self.assertEqual(new[key], default_device()[key])
        self.assertIn("measure", new["operations"]["action_kinds"])
        self.assertIn("reset", new["operations"]["action_kinds"])

    def test_geometry_copy_bounds_ports_and_no_orientation_guessing(self):
        device = preinitialized_device()
        geometry = patch_geometry(device)
        self.assertEqual(geometry["cell_extent_um"], [40, 60])
        self.assertEqual(len(geometry["ports"]["data_coupling"]["members"]), 9)
        self.assertEqual(len(geometry["ports"]["ancilla_departure"]["members"]), 8)
        geometry["cell_extent_um"][0] = 999
        self.assertEqual(patch_geometry(device)["cell_extent_um"], [40, 60])
        device["patch_geometry"]["allowed_orientations"].append("rotated_90")
        self.assertTrue(validate_device(device))

    def test_geometry_mismatch_or_missing_fields_rejected(self):
        for key, value in [("occupied_bounds_um", [0, 0, 20, 30]), ("cell_extent_um", [20, 30]),
                            ("suggested_anchor_step_um", [0, 10]), ("cell_extent_um", [True, 60]),
                            ("occupied_bounds_um", [0, 0, float("inf"), 50])]:
            d = preinitialized_device()
            d["patch_geometry"][key] = value
            self.assertTrue(validate_device(d), key)
        d = preinitialized_device()
        del d["patch_geometry"]
        self.assertTrue(validate_device(d))

    def test_legacy_entry_cannot_be_relabelled_current(self):
        d = grouped_device()
        d["entry_mode"] = "preinitialized"
        self.assertTrue(validate_device(d))
        d = preinitialized_device()
        d["grouped_profile"]["initialization_zone"] = grouped_device()["grouped_profile"]["initialization_zone"]
        self.assertTrue(validate_device(d))

    def test_readout_capacity_and_global_mz_preserved(self):
        d = preinitialized_device()
        receiver = group_layout(d, "ancilla_readout", offset_um=[100, 0])
        events = [{"atom_id": s, "bank_id": "mz0", "site_id": s, "position_um": v["position_um"],
                   "t_start_us": 100, "t_end_us": 200, "earliest_ready_us": 100, "result_id": f"call/{s}",
                   "result_ready_us": 205, "basis": "Z"} for s, v in receiver["slots"].items()]
        self.assertEqual(validate_readout_batch(d, events), [])
        self.assertTrue(validate_readout_batch(preinitialized_device(readout_capacity=4), events))
        with self.assertRaises(DeviceModelError):
            group_layout(d, "ancilla_readout", offset_um=[0, 60])


class InitialStateTests(unittest.TestCase):
    def setUp(self):
        self.device = preinitialized_device()
        self.patches = {"L0": {"aod_group": "data", "basis": "Z", "value": 0},
                        "L1": {"aod_group": "data", "basis": "Z", "value": 1}}
        self.placements = {"L0": {"anchor_um": [0, 0], "orientation": "x_vertical_z_horizontal"},
                           "L1": {"anchor_um": [80, 60], "orientation": "x_vertical_z_horizontal"}}
        self.ref = {"artifact_id": "test-placement", "producer": "test-fixture", "fixture": True}

    def build(self):
        return build_preinitialized_state(self.device, self.patches, self.placements, placement_ref=self.ref)

    def test_input_binding_has_34_distinct_atoms_and_no_startup_cost(self):
        state = self.build()
        self.assertEqual(validate_preinitialized_state(state, self.device), [])
        self.assertEqual(len(state["atoms"]), 34)
        self.assertEqual(len({a["atom_id"] for a in state["atoms"]}), 34)
        self.assertEqual(len({a["qubit_id"] for a in state["atoms"]}), 34)
        self.assertEqual(state["t_start_us"], 0)
        self.assertEqual(state["startup_actions"], [])
        self.assertEqual(state["startup_duration_us"], 0)
        self.assertEqual(state["ready_magic_tokens"], [])
        self.assertEqual(state["results"], {})
        self.assertEqual(state["aod_rows"], [])
        self.assertEqual(state["aod_columns"], [])

    def test_encoded_data_not_falsely_labelled_product_zero(self):
        state = self.build()
        for atom in state["atoms"]:
            if atom["local_id"].startswith("d"):
                self.assertEqual(atom["initial_state"]["kind"], "encoded_member")
                self.assertNotIn("value", atom["initial_state"])
            else:
                self.assertEqual(atom["initial_state"], {"kind": "physical_basis", "basis": "Z", "value": 0})
        self.assertEqual(state["patches"]["L1"]["initial_logical_state"]["value"], 1)

    def test_placement_changes_actually_change_t0_atoms(self):
        first = self.build()
        self.placements["L1"]["anchor_um"] = [160, 180]
        second = self.build()
        p1 = next(a["position_um"] for a in first["atoms"] if a["qubit_id"] == "L1/d0")
        p2 = next(a["position_um"] for a in second["atoms"] if a["qubit_id"] == "L1/d0")
        self.assertEqual(p1, [80, 60])
        self.assertEqual(p2, [160, 180])
        self.assertNotEqual(first["placement_binding_sha256"], second["placement_binding_sha256"])
        self.assertNotEqual(first["artifact_id"], second["artifact_id"])

    def test_cell_edges_may_touch_but_interior_overlap_fails(self):
        self.placements["L1"]["anchor_um"] = [40, 0]
        self.assertEqual(validate_preinitialized_state(self.build(), self.device), [])
        self.placements["L1"]["anchor_um"] = [39, 0]
        with self.assertRaises(DeviceModelError) as caught:
            self.build()
        self.assertEqual(caught.exception.errors[0]["code"], "PATCH_FOOTPRINT_OVERLAP")

    def test_outside_ez_and_malformed_anchor_fail(self):
        for point in ([0, -1], [0, 1000], [True, 0], [0], [float("nan"), 0]):
            self.placements["L1"]["anchor_um"] = point
            with self.assertRaises(DeviceModelError):
                self.build()

    def test_unknown_orientation_not_silently_rotated(self):
        self.placements["L1"]["orientation"] = "rotated_90"
        with self.assertRaises(DeviceModelError):
            self.build()

    def test_complete_explicit_state_and_placement_required(self):
        for bad in ({}, {"aod_group": "data"}, {"aod_group": "data", "basis": "Z", "value": True},
                    {"aod_group": "data", "basis": "T", "value": 0},
                    {"aod_group": "data", "basis": "Z", "value": 0, "encoded": False}):
            self.patches["L0"] = bad
            with self.assertRaises(DeviceModelError):
                self.build()
        self.setUp()
        del self.placements["L1"]
        with self.assertRaises(DeviceModelError):
            self.build()

    def test_magic_carrier_group_is_not_ready_magic_inventory(self):
        self.patches["L1"]["aod_group"] = "magic"
        state = self.build()
        self.assertFalse(state["patches"]["L1"]["magic_resource_ready"])
        self.assertEqual(state["ready_magic_tokens"], [])

    def test_nonzero_time_startup_moves_and_results_rejected(self):
        state = self.build()
        for key, bad in [("t_start_us", 100), ("startup_duration_us", 500),
                         ("startup_actions", [{"kind": "move"}]), ("results", {"m0": 0}),
                         ("ready_magic_tokens", ["free-T"]), ("hardware_executed", True)]:
            changed = deepcopy(state)
            changed[key] = bad
            self.assertTrue(validate_preinitialized_state(changed, self.device), key)

    def test_position_identity_or_carrier_edits_are_not_new_placement(self):
        for key, value in [("position_um", [10, 10]), ("atom_id", "different"), ("carrier", "AOD")]:
            state = self.build()
            state["atoms"][0][key] = value
            self.assertTrue(validate_preinitialized_state(state, self.device))

    def test_wrong_device_hash_or_initial_declaration_detected(self):
        state = self.build()
        device = deepcopy(self.device)
        device["timings_us"]["measure"] = 200
        self.assertTrue(validate_preinitialized_state(state, device))
        state["entry_spec"]["patches"]["L0"]["value"] = 1
        self.assertTrue(validate_preinitialized_state(state, self.device))

    def test_json_roundtrip_no_mutation_or_shared_state(self):
        inputs = deepcopy((self.patches, self.placements, self.ref))
        first, second = self.build(), self.build()
        self.assertEqual(inputs, (self.patches, self.placements, self.ref))
        self.assertEqual(validate_preinitialized_state(json.loads(json.dumps(first)), self.device), [])
        first["atoms"][0]["position_um"][0] = 777
        self.assertNotEqual(first["atoms"][0]["position_um"], second["atoms"][0]["position_um"])

    def test_legacy_device_and_unsupported_state_fields_fail_closed(self):
        with self.assertRaises(DeviceModelError):
            build_preinitialized_state(grouped_device(), self.patches, self.placements, placement_ref=self.ref)
        for bad in (None, [], {}, {"entry_spec": {}}):
            self.assertTrue(validate_preinitialized_state(bad, self.device))
        state = self.build()
        state["factory_accepted"] = True
        self.assertTrue(validate_preinitialized_state(state, self.device))

    def test_published_fixture_matches_device_and_current_builder(self):
        root = Path(__file__).resolve().parents[2] / "configs/device"
        self.assertEqual(json.loads((root / "preinitialized_device.json").read_text(encoding="utf-8")), self.device)
        state = json.loads((root / "preinitialized_state_fixture.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_preinitialized_state(state, self.device), [])
        self.assertTrue(state["provenance"]["fixture"])


if __name__ == "__main__":
    unittest.main()
