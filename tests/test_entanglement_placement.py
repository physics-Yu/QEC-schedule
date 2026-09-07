"""R4 deterministic entanglement placement tests."""
from dataclasses import replace
from pathlib import Path
import unittest

from qec_schedule.compiler import EntangleRequest
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.planner import PlacementError, SpatialPlanner
from qec_schedule.qec import create_code


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class EntanglementPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_hardware_config(CONFIG)
        cls.code = create_code()
        cls.state = build_initial_state(cls.code, cls.config)
        cls.plan = GateLowerer().lower(cls.code.syndrome_round(), cls.state)

    def test_six_ready_interactions_are_packed_into_dynamic_geometry(self):
        requests = [request for request in self.plan.requests
                    if isinstance(request, EntangleRequest) and request.metadata["slot"] == 0]
        zone = self.state.zones_by_id["entangling"]
        geometry = zone.entangling_geometry
        placements = SpatialPlanner().plan_entanglement(requests, self.state)
        self.assertEqual(len(placements), 6)
        positions = [position for placement in placements for position in placement.positions]
        self.assertTrue(all(geometry.bounds.contains(position) for position in positions))
        self.assertEqual({round(placement.position_a.distance_to(placement.position_b), 8)
                          for placement in placements}, {4.0})
        self.assertGreaterEqual(min(left.distance_to(right) for index, left in enumerate(positions)
                                    for right in positions[index + 1:]), geometry.min_atom_spacing)
        self.assertGreaterEqual(placements[1].position_a.x - placements[0].position_b.x,
                                geometry.inter_pair_guard_distance)

    def test_dynamic_planner_does_not_need_pair_slots(self):
        zones = tuple(replace(zone, pair_slots=()) if zone.id == "entangling" else zone
                      for zone in self.config.zones)
        config = replace(self.config, zones=zones)
        state = build_initial_state(self.code, config)
        requests = [request for request in self.plan.requests
                    if isinstance(request, EntangleRequest) and request.metadata["slot"] == 0]
        self.assertEqual(len(SpatialPlanner().plan_entanglement(requests, state)), 6)

    def test_placement_rejects_a_batch_larger_than_geometry(self):
        requests = [EntangleRequest(f"dummy-{index}", f"dummy-{index}",
                                    (f"dummy-a{index}", f"dummy-b{index}"), (),
                                    metadata={"slot": 0}) for index in range(7)]
        with self.assertRaisesRegex(PlacementError, "ZONE_CAPACITY"):
            SpatialPlanner().plan_entanglement(requests, self.state)


if __name__ == "__main__":
    unittest.main()
