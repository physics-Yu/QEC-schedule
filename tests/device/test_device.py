"""Model contract checks, including counterexamples invisible to atom paths."""

import copy
import json
import random
import unittest
from pathlib import Path

from na_pipeline.device import (
    DeviceModelError, broadcast_pairs, default_device, move_duration_us,
    position_in_zone, validate_aod_transition, validate_device,
)


class DeviceSpecTests(unittest.TestCase):
    def setUp(self):
        self.device = default_device()

    def test_default_json_roundtrip_and_independent_instances(self):
        self.assertEqual(validate_device(json.loads(json.dumps(self.device, allow_nan=False))), [])
        self.device["timings_us"]["measure"] = 900
        self.device["aod_groups"]["data"]["resource_id"] = "modified"
        self.assertEqual(default_device()["timings_us"]["measure"], 100)
        self.assertEqual(default_device()["aod_groups"]["data"]["resource_id"], "aod:data")

    def test_duration_and_latency_must_be_positive_finite_numbers(self):
        for key in self.device["timings_us"]:
            for bad in [None, 0, -1, True, "1", float("nan"), float("inf")]:
                with self.subTest(key=key, value=bad):
                    dev = default_device()
                    dev["timings_us"][key] = bad
                    self.assertTrue(validate_device(dev))

    def test_zero_measure_error_is_actionable(self):
        self.device["timings_us"]["measure"] = 0
        self.assertIn({"code": "NON_POSITIVE_PARAMETER", "path": "/timings_us/measure",
                       "message": "Operation durations and latencies must be positive."}, validate_device(self.device))

    def test_invalid_nested_shapes_do_not_throw(self):
        for key in self.device:
            for bad in (None, [], False):
                with self.subTest(key=key, bad=bad):
                    dev = default_device()
                    dev[key] = bad
                    errors = validate_device(dev)
                    if dev[key] is not self.device[key]:
                        self.assertTrue(errors)
        for bad in (None, [], 2, True, "device"):
            self.assertTrue(validate_device(bad))

    def test_missing_fields_and_unknown_fields_fail_closed(self):
        for key in self.device:
            dev = default_device()
            del dev[key]
            self.assertTrue(validate_device(dev), key)
        self.device["movement"]["teleport"] = True
        self.assertIn("UNSUPPORTED_FIELD", {e["code"] for e in validate_device(self.device)})

    def test_reject_evidence_and_unsupported_model_flags(self):
        paths = [("hardware_executed",), ("quantum_state_simulated",), ("loss_enabled",),
                 ("concurrency", "global_motion_lock"), ("concurrency", "global_measure_lock"),
                 ("illumination", "per_event_log_required"), ("geometry", "extra_pair_center_exclusion")]
        for path in paths:
            dev = default_device()
            parent = dev if len(path) == 1 else dev[path[0]]
            parent[path[-1]] = True
            self.assertTrue(validate_device(dev), path)
        for section, key, value in [("movement", "model", "teleport"), ("geometry", "pair_metric", "manhattan"),
                                    ("operations", "reset_target", 1), ("measurement", "basis", "Y")]:
            dev = default_device()
            dev[section][key] = value
            self.assertTrue(validate_device(dev))

    def test_no_fixed_aod_capacity_or_crossing_opt_out(self):
        for key, bad in [("max_rows", 100), ("max_columns", 100), ("non_crossing", False),
                         ("shared_rows", False), ("shared_columns", False)]:
            dev = default_device()
            dev["aod_groups"]["data"][key] = bad
            self.assertTrue(validate_device(dev), key)

    def test_additional_independent_aod_requires_sources_and_unique_resource(self):
        self.device["aod_groups"]["magic2"] = copy.deepcopy(self.device["aod_groups"]["magic"])
        self.assertTrue(validate_device(self.device))
        self.device["aod_groups"]["magic2"]["resource_id"] = "aod:magic2"
        self.device["parameter_provenance"]["/aod_groups/magic2"] = copy.deepcopy(
            self.device["parameter_provenance"]["/aod_groups/magic"])
        self.assertEqual(validate_device(self.device), [])

    def test_all_operating_parameters_need_scoped_sources(self):
        for path in list(self.device["parameter_provenance"]):
            dev = default_device()
            del dev["parameter_provenance"][path]
            self.assertTrue(validate_device(dev), path)
        for field, bad in [("source_refs", []), ("scope", ""), ("calibrated", True), ("kind", "hardware_calibration")]:
            dev = default_device()
            dev["parameter_provenance"]["/timings_us/cz"][field] = bad
            self.assertTrue(validate_device(dev), field)

    def test_unknown_physics_is_not_zero_and_reference_is_conditional(self):
        self.assertIsNone(self.device["physics"]["t2star_us"])
        self.assertFalse(self.device["physics"]["coherence_reference"]["used_for_noise"])
        self.assertTrue(self.device["physics"]["coherence_reference"]["conditions"])
        self.device["physics"]["gate_error_rate"] = 0
        self.assertTrue(validate_device(self.device))

    def test_native_gate_boundary(self):
        self.device["operations"]["native_1q_gates"] = ["H", "RZ"]
        self.assertEqual(validate_device(self.device), [])
        self.device["operations"]["native_1q_gates"].append("CX")
        self.assertTrue(validate_device(self.device))

    def test_geometry_and_ranges(self):
        for key in ["initial_spacing_um", "gate_pair_distance_um", "distance_tolerance_um"]:
            dev = default_device()
            dev["geometry"][key] = 0
            self.assertTrue(validate_device(dev))
        for bounds in ([10, 0], [0, 0], [0], [True, 10], ["0", 10]):
            dev = default_device()
            dev["zones"]["measurement"]["y_range_um"] = bounds
            self.assertTrue(validate_device(dev), bounds)
        self.device["geometry"]["distance_tolerance_um"] = 2
        self.assertTrue(validate_device(self.device))

    def test_validator_does_not_mutate(self):
        saved = copy.deepcopy(self.device)
        validate_device(self.device)
        self.assertEqual(self.device, saved)

    def test_published_examples(self):
        root = Path(__file__).resolve().parents[2]
        valid = json.loads((root / "configs/device/default_device.json").read_text(encoding="utf-8"))
        invalid = json.loads((root / "configs/device/rejected_zero_measure.json").read_text(encoding="utf-8"))
        self.assertEqual(valid, default_device())
        self.assertEqual(validate_device(valid), [])
        self.assertTrue(validate_device(invalid))


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.device = default_device()

    def test_parallel_axes_duration_is_maximum_not_sum_or_euclidean(self):
        self.assertEqual(move_duration_us(self.device, [0, 0], [3, 4]), 4)
        self.assertEqual(move_duration_us(self.device, [3, 4], [0, 0]), 4)
        self.assertEqual(move_duration_us(self.device, [0, 0], [0, 0]), 0)
        self.device["movement"]["speed_um_per_us"] = 2
        self.assertEqual(move_duration_us(self.device, [0, 0], [3, 4]), 2)

    def test_invalid_point_or_device_is_not_substituted(self):
        for point in ([1], [True, 0], [0, float("nan")], None):
            with self.assertRaises(DeviceModelError):
                move_duration_us(self.device, point, [0, 0])
        with self.assertRaises(DeviceModelError):
            move_duration_us({}, [0, 0], [1, 0])

    def test_closed_zone_boundaries_and_unbounded_x(self):
        self.assertTrue(position_in_zone(self.device, "storage_entanglement", [-1e8, 0]))
        self.assertTrue(position_in_zone(self.device, "storage_entanglement", [1e8, 1000]))
        self.assertFalse(position_in_zone(self.device, "storage_entanglement", [0, 1010]))
        self.assertTrue(position_in_zone(self.device, "measurement", [0, 1020]))
        self.assertFalse(position_in_zone(self.device, "measurement", [0, 1040.01]))
        with self.assertRaises(DeviceModelError):
            position_in_zone(self.device, "unknown", [0, 0])

    def test_broadcast_includes_extra_pairs_and_idle_atoms(self):
        result = broadcast_pairs(self.device, {
            "a": [0, 10], "b": [2, 10], "c": [20, 10], "d": [22, 10],
            "idle": [70, 10], "outside": [0, 1020],
        })
        self.assertEqual(result["pairs"], [["a", "b"], ["c", "d"]])
        self.assertEqual(result["illuminated_atoms"], ["a", "b", "c", "d", "idle"])
        # Consumer increments once per illuminated atom, regardless of pair count.
        counts = dict.fromkeys(result["illuminated_atoms"], 1)
        self.assertEqual(counts["idle"], 1)

    def test_all_edges_are_retained_without_matching_or_exclusion(self):
        result = broadcast_pairs(self.device, {"a": [0, 0], "b": [2, 0], "c": [4, 0]})
        self.assertEqual(result["pairs"], [["a", "b"], ["b", "c"]])
        self.assertEqual(result["illuminated_atoms"].count("b"), 1)
        self.assertEqual(broadcast_pairs(self.device, {})["pairs"], [])

    def test_pairing_euclidean_distance_and_numeric_tolerance(self):
        self.assertEqual(broadcast_pairs(self.device, {"a": [0, 0], "b": [1.2, 1.6]})["pairs"], [["a", "b"]])
        self.assertEqual(broadcast_pairs(self.device, {"a": [0, 0], "b": [2.00001, 0]})["pairs"], [])
        self.assertEqual(broadcast_pairs(self.device, {"a": [0, 0], "b": [2.0000005, 0]})["pairs"], [["a", "b"]])

    def test_geometric_result_does_not_depend_on_atom_input_order(self):
        points = {"a": [0, 5], "b": [2, 5], "c": [50, 5]}
        self.assertEqual(broadcast_pairs(self.device, points), broadcast_pairs(self.device, dict(reversed(list(points.items())))))


class AODTransitionTests(unittest.TestCase):
    def setUp(self):
        self.device = default_device()
        self.before = {"rows": {"r0": 0, "r1": 10}, "columns": {"c0": 0, "c1": 10}}

    def test_compatible_shared_axes_and_independent_aod(self):
        after = {"rows": {"r0": 3, "r1": 14}, "columns": {"c0": 2, "c1": 14}}
        for group in ("data", "magic"):
            self.assertEqual(validate_aod_transition(self.device, group, self.before, after, 4), [])

    def test_nonintersecting_atom_paths_still_cannot_swap_columns(self):
        # A: (0,0)->(10,0), B: (10,10)->(0,10): atom paths never intersect.
        after = {"rows": {"r0": 0, "r1": 10}, "columns": {"c0": 10, "c1": 0}}
        codes = {e["code"] for e in validate_aod_transition(self.device, "data", self.before, after, 10)}
        self.assertIn("LINE_CROSSING", codes)

    def test_collapsed_axes_cannot_share_coordinate(self):
        after = {"rows": {"r0": 5, "r1": 5}, "columns": {"c0": 0, "c1": 10}}
        codes = {e["code"] for e in validate_aod_transition(self.device, "data", self.before, after, 10)}
        self.assertIn("LINE_COLLISION", codes)

    def test_insufficient_time_is_not_a_valid_move(self):
        after = {"rows": {"r0": 0, "r1": 10}, "columns": {"c0": 0, "c1": 14}}
        self.assertEqual(validate_aod_transition(self.device, "data", self.before, after, 4), [])
        self.assertIn("SPEED_EXCEEDED", {e["code"] for e in validate_aod_transition(self.device, "data", self.before, after, 3.99)})

    def test_motion_cannot_rename_lines_or_omit_stationary_line(self):
        for columns in ({"c0": 1}, {"c0": 1, "new": 11}):
            after = {"rows": {"r0": 0, "r1": 10}, "columns": columns}
            self.assertIn("LINE_IDENTITY_CHANGED", {e["code"] for e in validate_aod_transition(self.device, "data", self.before, after, 10)})

    def test_empty_or_noop_motion_does_not_replace_wait(self):
        self.assertIn("NO_MOTION", {e["code"] for e in validate_aod_transition(self.device, "data", self.before, self.before, 10)})
        self.assertTrue(validate_aod_transition(self.device, "data", self.before, self.before, 0))

    def test_unknown_group_and_malformed_snapshots(self):
        for before, after, group, duration in [(None, {}, "data", 1), (self.before, [], "data", 1),
                                                (self.before, self.before, "unknown", 1),
                                                (self.before, self.before, "data", True),
                                                ({"rows": {}, "columns": {"c": "0"}}, self.before, "data", 1)]:
            self.assertTrue(validate_aod_transition(self.device, group, before, after, duration))

    def test_linear_endpoint_proof_matches_interior_order(self):
        rng = random.Random(101)
        # Random ordered endpoints: interpolate at interior times as a separate invariant check.
        for _ in range(30):
            start = sorted(rng.sample(range(-100, 100), 20))
            end = sorted(rng.sample(range(-100, 100), 20))
            before = {"rows": {}, "columns": {f"c{i}": x for i, x in enumerate(start)}}
            after = {"rows": {}, "columns": {f"c{i}": x for i, x in enumerate(end)}}
            self.assertEqual(validate_aod_transition(self.device, "data", before, after, 200), [])
            for t in (0.01, 0.2, 0.5, 0.85, 0.99):
                positions = [(1 - t) * a + t * b for a, b in zip(start, end)]
                self.assertTrue(all(a < b for a, b in zip(positions, positions[1:])))


if __name__ == "__main__":
    unittest.main()
