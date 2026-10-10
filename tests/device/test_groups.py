"""T102 local geometry/resource tests; fixtures do not certify Enola strategies."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from na_pipeline.device import (
    DeviceModelError, capture_closure, default_device, group_layout, grouped_device,
    move_duration_us, validate_aod_transition, validate_device,
    validate_group_transfer, validate_readout_batch,
)

ROOT = Path(__file__).resolve().parents[2]


def world(slots):
    return {f"a:{slot}": {"position_um": list(value["position_um"]), "carrier": "SLM"}
            for slot, value in slots.items()}


def bind(slots):
    return {slot: f"a:{slot}" for slot in slots}


def readings(device, *, bank="bank0", dx=0, start=447):
    slots = group_layout(device, "ancilla_readout", offset_um=[dx, 0])["slots"]
    return [{"atom_id": f"{bank}:{s}", "bank_id": bank, "site_id": s, "position_um": v["position_um"],
             "t_start_us": start, "t_end_us": start + 100, "earliest_ready_us": start - 7 + i,
             "result_id": f"result:{bank}:{s}", "result_ready_us": start + 105, "basis": "Z"}
            for i, (s, v) in enumerate(slots.items())]


class GroupProfileTests(unittest.TestCase):
    def test_old_default_bytes_and_parameters_are_unchanged(self):
        device = default_device()
        data = json.dumps(device, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(data).hexdigest(), "1c436306473c9938e7febf7abceb1ebceb28a52c7c5fc6d3e5aa02bf338ccf5f")
        self.assertEqual(validate_device(device), [])
        new = grouped_device()
        for key in ("timings_us", "movement", "geometry", "aod_groups"):
            self.assertEqual(new[key], device[key])

    def test_new_profile_independent_json_and_examples(self):
        new = grouped_device()
        self.assertEqual(validate_device(json.loads(json.dumps(new))), [])
        on_disk = json.loads((ROOT / "configs/device/grouped_device.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, new)
        new["grouped_profile"]["layouts"]["patch_home"]["slots"]["d0"]["position_um"][0] = 999
        self.assertEqual(grouped_device()["grouped_profile"]["layouts"]["patch_home"]["slots"]["d0"]["position_um"], [0, 0])

    def test_lower_capacity_is_a_valid_configuration(self):
        self.assertEqual(validate_device(grouped_device(readout_capacity=4)), [])
        for bad in (0, 9, -1, True, 8.0, None):
            with self.subTest(bad=bad), self.assertRaises(DeviceModelError):
                grouped_device(readout_capacity=bad)

    def test_sites_rows_columns_and_regions_are_validated(self):
        cases = [
            ("carrier", "AOD"), ("zone_id", "measurement"),
        ]
        for key, value in cases:
            d = grouped_device()
            d["grouped_profile"]["layouts"]["patch_home"][key] = value
            self.assertTrue(validate_device(d))
        for mutation in ("duplicate", "shared_row", "shared_column", "outside", "missing_site"):
            d = grouped_device()
            slots = d["grouped_profile"]["layouts"]["ancilla_readout"]["slots"]
            if mutation == "duplicate": slots["x1"]["position_um"] = list(slots["x0"]["position_um"])
            if mutation == "shared_row": slots["x1"]["position_um"][1] += 1
            if mutation == "shared_column": slots["z0"]["position_um"][0] += 1
            if mutation == "outside": slots["z0"]["position_um"][1] = 999
            if mutation == "missing_site": del slots["z3"]
            self.assertTrue(validate_device(d), mutation)

    def test_unknown_fields_models_and_calibration_claim_rejected(self):
        for section, key, value in [("capture", "selective_atom_mask", True), ("capture", "model", "per_atom_mask"),
                                     ("readout", "bank_capacity", 9), ("readout", "independent_banks", False),
                                     ("provenance", "calibrated", True), ("provenance", "kind", "hardware_calibration")]:
            d = grouped_device()
            d["grouped_profile"][section][key] = value
            self.assertTrue(validate_device(d))
        d = grouped_device()
        d["grouped_profile"]["ignored_limit"] = 8
        self.assertTrue(validate_device(d))

    def test_malformed_extension_returns_errors(self):
        for bad in (None, [], 1, False, "group"):
            d = grouped_device()
            d["grouped_profile"] = bad
            self.assertTrue(validate_device(d))
        d = grouped_device()
        d["grouped_profile"]["layouts"]["patch_home"]["slots"]["d0"]["position_um"] = [float("nan"), 0]
        self.assertTrue(validate_device(d))

    def test_layout_copy_translation_and_opt_in(self):
        d = grouped_device()
        local = group_layout(d, "patch_home")
        shifted = group_layout(d, "patch_home", offset_um=[100, 0])
        self.assertEqual(shifted["slots"]["d0"]["position_um"], [100, 0])
        local["slots"]["d0"]["position_um"][0] = 33
        self.assertEqual(group_layout(d, "patch_home")["slots"]["d0"]["position_um"], [0, 0])
        for device, layout, offset in [(default_device(), "patch_home", [0, 0]), (d, "unknown", [0, 0]), (d, "patch_home", [0, 1000])]:
            with self.assertRaises(DeviceModelError):
                group_layout(device, layout, offset_um=offset)


class GroupTransferTests(unittest.TestCase):
    def setUp(self):
        self.device = grouped_device()
        self.entry = group_layout(self.device, "patch_initialization")["slots"]
        self.home = group_layout(self.device, "patch_home")["slots"]
        self.mz = group_layout(self.device, "ancilla_readout")["slots"]

    def test_initialization_all_17_one_compatible_translation(self):
        self.assertEqual(len(self.entry), 17)
        atoms = world(self.entry)
        saved = deepcopy(atoms)
        self.assertEqual(validate_group_transfer(self.device, "patch_initialization_transport", atoms, bind(self.entry), target_layout_id="patch_home"), [])
        self.assertEqual(atoms, saved)
        durations = [move_duration_us(self.device, self.entry[s]["position_um"], self.home[s]["position_um"]) for s in self.entry]
        self.assertEqual(set(durations), {100})
        before = {"rows": {}, "columns": {}}
        after = {"rows": {}, "columns": {}}
        for s in self.entry:
            for key, axis, label in (("row_id", 1, "rows"), ("column_id", 0, "columns")):
                before[label][self.entry[s][key]] = self.entry[s]["position_um"][axis]
                after[label][self.home[s][key]] = self.home[s]["position_um"][axis]
        self.assertEqual(validate_aod_transition(self.device, "data", before, after, 100), [])
        self.assertTrue(validate_aod_transition(self.device, "data", before, after, 99))

    def test_eight_auxiliaries_forward_and_return_preserve_nine_data(self):
        atoms = world(self.home)
        bindings = bind(self.mz)
        self.assertEqual(validate_group_transfer(self.device, "maintenance_readout", atoms, bindings, target_layout_id="ancilla_readout"), [])
        self.assertEqual(capture_closure(self.device, atoms, [40, 50], [0, 10, 20, 30]), sorted(bindings.values()))
        for slot in self.mz:
            atoms[f"a:{slot}"]["position_um"] = list(self.mz[slot]["position_um"])
        self.assertEqual(validate_group_transfer(self.device, "maintenance_readout", atoms, bindings, target_layout_id="patch_home"), [])
        self.assertEqual({a for a in atoms if a.startswith("a:d")}, {f"a:d{i}" for i in range(9)})

    def test_capture_closure_includes_unlisted_crosspoint_atom(self):
        atoms = world(self.entry)
        atoms["spectator"] = {"position_um": [30, -100], "carrier": "SLM"}
        closure = capture_closure(self.device, atoms, [-100, -90, -80, -60, -50], [0, 10, 20, 30])
        self.assertEqual(len(closure), 18)
        errors = validate_group_transfer(self.device, "patch_initialization_transport", atoms, bind(self.entry), target_layout_id="patch_home")
        self.assertIn("CAPTURE_CLOSURE", {e["code"] for e in errors})

    def test_aod_atoms_are_not_recaptured_as_slm(self):
        atoms = world(self.entry)
        atoms["other_aod"] = {"position_um": [30, -100], "carrier": "AOD"}
        self.assertNotIn("other_aod", capture_closure(self.device, atoms, [-100], [30]))

    def test_target_occupation_is_not_hidden_by_group_binding(self):
        atoms = world(self.home)
        atoms["blocker"] = {"position_um": [0, 90], "carrier": "SLM"}
        errors = validate_group_transfer(self.device, "maintenance_readout", atoms, bind(self.mz), target_layout_id="ancilla_readout")
        self.assertIn("TARGET_OCCUPIED", {e["code"] for e in errors})

    def test_row_compression_and_shared_column_split_rejected(self):
        d = deepcopy(self.device)
        for i in range(4):
            slot = d["grouped_profile"]["layouts"]["ancilla_readout"]["slots"][f"z{i}"]
            slot.update(position_um=[40 + 10*i, 90], row_id="r4", column_id=f"c{i+4}")
        self.assertEqual(validate_device(d), [])
        errors = validate_group_transfer(d, "maintenance_readout", world(self.home), bind(self.mz), target_layout_id="ancilla_readout")
        self.assertTrue({"SHARED_AXIS_SPLIT", "LINE_CROSSING"} <= {e["code"] for e in errors})

    def test_reversing_columns_rejected(self):
        d = deepcopy(self.device)
        for v in d["grouped_profile"]["layouts"]["ancilla_readout"]["slots"].values():
            v["position_um"][0] = 30 - v["position_um"][0]
        self.assertEqual(validate_device(d), [])
        errors = validate_group_transfer(d, "maintenance_readout", world(self.home), bind(self.mz), target_layout_id="ancilla_readout")
        self.assertIn("LINE_CROSSING", {e["code"] for e in errors})

    def test_incomplete_binding_wrong_carrier_and_region(self):
        for mutation in ("missing", "aliased", "carrier", "region"):
            atoms, bindings = world(self.entry), bind(self.entry)
            if mutation == "missing": del bindings["d0"]
            if mutation == "aliased": bindings["d0"] = bindings["d1"]
            if mutation == "carrier": atoms["a:d0"]["carrier"] = "AOD"
            if mutation == "region": atoms["a:d0"]["position_um"] = [0, 999]
            self.assertTrue(validate_group_transfer(self.device, "patch_initialization_transport", atoms, bindings, target_layout_id="patch_home"))


class ReadoutTests(unittest.TestCase):
    def setUp(self):
        self.device = grouped_device()

    def test_eight_simultaneous_results_have_independent_ids(self):
        events = readings(self.device)
        self.assertEqual(validate_readout_batch(self.device, events), [])
        self.assertEqual(len({e["result_id"] for e in events}), 8)
        self.assertEqual(max(e["earliest_ready_us"] for e in events), events[0]["t_start_us"])
        self.assertEqual(max(e["t_start_us"] for e in events)-min(e["t_start_us"] for e in events), 0)

    def test_capacity_four_rejects_eight_and_accepts_explicit_two_batches(self):
        device = grouped_device(readout_capacity=4)
        events = readings(device)
        self.assertIn("READOUT_CAPACITY_EXCEEDED", {e["code"] for e in validate_readout_batch(device, events)})
        for event in events[4:]:
            for key in ("t_start_us", "t_end_us", "result_ready_us"):
                event[key] += 100
        self.assertEqual(validate_readout_batch(device, events), [])
        self.assertEqual(max(e["t_start_us"] for e in events)-min(e["t_start_us"] for e in events), 100)

    def test_independent_banks_overlap_without_global_barrier(self):
        events = readings(self.device, bank="A") + readings(self.device, bank="B", dx=100, start=470)
        self.assertEqual(validate_readout_batch(self.device, events), [])

    def test_renaming_bank_cannot_hide_physical_site_conflicts(self):
        events = readings(self.device, bank="A") + readings(self.device, bank="B")
        self.assertIn("READOUT_RESOURCE_CONFLICT", {e["code"] for e in validate_readout_batch(self.device, events)})

    def test_result_and_prerequisite_times_not_inferred_or_zeroed(self):
        for key, value, code in [("earliest_ready_us", 448, "READOUT_BEFORE_READY"),
                                  ("result_ready_us", 550, "RESULT_BEFORE_READY"),
                                  ("t_end_us", 447, "READOUT_DURATION"), ("basis", "X", "READOUT_BASIS")]:
            events = readings(self.device)
            events[0][key] = value
            self.assertIn(code, {e["code"] for e in validate_readout_batch(self.device, events)})

    def test_duplicate_result_atom_and_site_fail(self):
        for key in ("result_id", "atom_id", "site_id"):
            events = readings(self.device)
            events[1][key] = events[0][key]
            self.assertTrue(validate_readout_batch(self.device, events), key)

    def test_bank_site_geometry_not_only_capacity(self):
        events = readings(self.device)
        events[0]["position_um"][0] += 1
        self.assertIn("READOUT_BANK_GEOMETRY", {e["code"] for e in validate_readout_batch(self.device, events)})
        events = readings(self.device)
        events[0]["site_id"] = "unknown"
        self.assertIn("UNKNOWN_READOUT_SITE", {e["code"] for e in validate_readout_batch(self.device, events)})

    def test_malformed_batch_failures(self):
        for bad in (None, {}, [], [None], [{}]):
            self.assertTrue(validate_readout_batch(self.device, bad))
        for key, value in [("position_um", [True, 90]), ("t_start_us", float("nan")), ("result_id", None)]:
            events = readings(self.device)
            events[0][key] = value
            self.assertTrue(validate_readout_batch(self.device, events))

    def test_machine_readable_positive_and_capacity_examples(self):
        fixture = json.loads((ROOT / "configs/device/grouped_examples.json").read_text(encoding="utf-8"))
        self.assertTrue(fixture["fixture"])
        for name in ("initialization", "maintenance_outbound"):
            request = {k:v for k,v in fixture[name].items() if k != "expected_errors"}
            self.assertEqual(validate_group_transfer(self.device, **request), [])
        self.assertEqual(validate_readout_batch(self.device, fixture["readout"]["entries"]), [])
        self.assertTrue(validate_readout_batch(grouped_device(readout_capacity=4), fixture["capacity_insufficient"]["entries"]))


if __name__ == "__main__":
    unittest.main()
