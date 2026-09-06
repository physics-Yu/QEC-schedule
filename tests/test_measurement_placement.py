"""R4 deterministic measurement placement tests."""
from pathlib import Path
import unittest

from qec_schedule.compiler import MeasureRequest
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.planner import PlacementError, SpatialPlanner
from qec_schedule.qec import create_code


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class MeasurementPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = load_hardware_config(CONFIG)
        code = create_code()
        state = build_initial_state(code, config)
        plan = GateLowerer().lower(code.syndrome_round(), state)
        cls.state = state
        cls.requests = tuple(request for request in plan.requests if isinstance(request, MeasureRequest))

    def test_eight_measurements_are_packed_inside_imaging_fov(self):
        placements = SpatialPlanner().plan_measurement(self.requests, self.state)
        self.assertEqual(len(placements), 8)
        geometry = self.state.zones_by_id["measurement"].measurement_geometry
        self.assertTrue(all(geometry.field_of_view.contains(placement.position) for placement in placements))
        self.assertGreaterEqual(min(left.position.distance_to(right.position)
                                    for index, left in enumerate(placements)
                                    for right in placements[index + 1:]),
                                geometry.min_atom_spacing)

    def test_measurement_capacity_is_a_batch_constraint(self):
        geometry = self.state.zones_by_id["measurement"].measurement_geometry
        limited = type(geometry)(geometry.bounds, geometry.imaging_bounds,
                                 geometry.min_atom_spacing, 4, geometry.field_of_view)
        zones = tuple(type(zone)(zone.id, zone.kind, zone.bounds, zone.capacity,
                                 zone.allowed_operations, zone.sites, zone.pair_slots,
                                 zone.entangling_geometry, limited if zone.id == "measurement"
                                 else zone.measurement_geometry)
                      for zone in self.state.zones)
        from dataclasses import replace
        state = replace(self.state, zones=zones)
        with self.assertRaisesRegex(PlacementError, "ZONE_CAPACITY"):
            SpatialPlanner().plan_measurement(self.requests, state)


if __name__ == "__main__":
    unittest.main()
