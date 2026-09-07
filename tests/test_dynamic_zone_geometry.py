"""R2 tests for dynamic working-region capabilities."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from qec_schedule.hardware import (Bounds, EntanglingGeometry, MeasurementGeometry,
                                   Zone, load_hardware_config)


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class DynamicZoneGeometryTests(unittest.TestCase):
    def test_default_geometry_is_uncapped_but_layout_capacity_remains_explicit(self):
        config = load_hardware_config(CONFIG)
        entangling = next(z for z in config.zones if z.id == "entangling")
        measurement = next(z for z in config.zones if z.id == "measurement")

        self.assertIsInstance(entangling.entangling_geometry, EntanglingGeometry)
        self.assertIsNone(entangling.entangling_geometry.max_parallel_pairs)
        self.assertIsNone(entangling.entangling_geometry.max_atoms)
        self.assertGreaterEqual(entangling.capacity, 12)
        self.assertIsInstance(measurement.measurement_geometry, MeasurementGeometry)
        self.assertIsNone(measurement.measurement_geometry.max_parallel_atoms)
        self.assertEqual(measurement.capacity, 8)
        self.assertEqual(measurement.measurement_geometry.field_of_view,
                         Bounds(2, 85, 43, 97))

    def test_entangling_and_measurement_zones_do_not_require_fixed_destinations(self):
        entangling = Zone(
            "dynamic-entangling", "ENTANGLING", Bounds(0, 0, 45, 25), 12,
            frozenset(("ENTANGLE",)), (), (),
            EntanglingGeometry(Bounds(0, 0, 45, 25), interaction_lanes=(12,),
                               pair_distance=4, inter_pair_guard_distance=3,
                               max_parallel_pairs=6, max_atoms=12),
        )
        measurement = Zone(
            "dynamic-measurement", "MEASUREMENT", Bounds(0, 30, 45, 55), 8,
            frozenset(("MEASURE",)), (), (), None,
            MeasurementGeometry(Bounds(0, 30, 45, 55), Bounds(1, 31, 44, 54),
                                min_atom_spacing=3, max_parallel_atoms=8),
        )

        self.assertEqual(entangling.pair_slots, ())
        self.assertEqual(entangling.sites, ())
        self.assertEqual(entangling.entangling_geometry.max_parallel_pairs, 6)
        self.assertEqual(measurement.sites, ())
        self.assertEqual(measurement.measurement_geometry.max_parallel_atoms, 8)

    def test_schema_rejects_geometry_that_does_not_match_its_zone(self):
        original = CONFIG.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hardware.yaml"
            path.write_text(original.replace("bounds: [0, 52, 45, 77]", "bounds: [0, 53, 45, 77]", 1),
                             encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "match"):
                load_hardware_config(path)

    def test_geometry_rejects_invalid_capacity_constraints(self):
        bounds = Bounds(0, 0, 10, 10)
        with self.assertRaises(ValueError):
            EntanglingGeometry(bounds, max_parallel_pairs=6, max_atoms=10)
        with self.assertRaises(ValueError):
            MeasurementGeometry(bounds, Bounds(0, 0, 11, 10))


if __name__ == "__main__":
    unittest.main()
