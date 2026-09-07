from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from qec_schedule.hardware import AODController, ActionTiming, Bounds, Position, Translation, build_initial_state, load_hardware_config
from qec_schedule.lowering import (AODMovementEpoch, LegacyGateLowerer, MoveRequest,
                                    MovementPlanner, SiteRef, TransportCatalog)
from qec_schedule.qec import create_code
from examples.demo_aod_movement import inspect_frontiers, ten_translations

CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


def request(i, source, target, *, timing=None, dependencies=()):
    return MoveRequest.translation_request(f"t{i}", f"a{i}", SiteRef("source", f"s{i}", Position(*source)),
                                          SiteRef("target", f"t{i}", Position(*target)), timing or ActionTiming(), dependencies=dependencies)


class AODTests(unittest.TestCase):
    def setUp(self):
        self.config = load_hardware_config(CONFIG)
        self.controller = self.config.aod
        self.planner = MovementPlanner(self.controller)

    def test_ten_atoms_one_epoch_and_one_aod_lease(self):
        requests = ten_translations(self.config.timing)
        epochs = self.planner.plan(requests)
        self.assertEqual(len(epochs), 1)
        epoch = epochs[0]
        self.assertEqual(len(epoch.atoms), 10)
        self.assertEqual(epoch.duration, 12)
        self.assertEqual(epoch.to_dict()["tone_counts"], {"x":10, "y":1})
        resources = {r.resource:r.units for r in epoch.reservation.required_resources}
        self.assertEqual(resources.pop("device/aod"), 1)
        self.assertEqual(len(resources), 10)
        self.assertEqual(len(epoch.reservation.acquire_before), 10)
        self.assertEqual(len(epoch.reservation.release_after), 10)
        self.assertEqual(set(epoch.to_dict()["replaces_reservation_ids"]), {r.id for r in requests})
        self.assertEqual(epoch.to_dict(), json.loads(json.dumps(epoch.to_dict())))

    def test_different_vector_same_speed_and_opposite_directions(self):
        requests = (request(0, (1, 1), (1, 11)), request(1, (3, 1), (13, 1)), request(2, (5, 11), (5, 1)))
        self.assertEqual(len(self.planner.plan(requests)), 3)
        self.assertFalse(self.controller.legacy_compatible(r.translation for r in requests))
        with self.assertRaises(ValueError): AODMovementEpoch("bad", requests, self.controller)

    def test_tone_budget_counts_lines_not_atoms(self):
        restricted = replace(self.controller, max_x_tones=4)
        epochs = MovementPlanner(restricted).plan(ten_translations(self.config.timing))
        self.assertEqual([len(e.atoms) for e in epochs], [4, 4, 2])
        grid = tuple(request(3*x+y, (2*x+1, 2*y+1), (2*x+1, 2*y+11)) for x in range(3) for y in range(3))
        epochs = MovementPlanner(replace(self.controller, max_x_tones=3, max_y_tones=3)).plan(grid)
        self.assertEqual(len(epochs), 1)
        self.assertEqual(len(epochs[0].atoms), 9)  # NOT limited to 3 atoms.
        self.assertEqual(epochs[0].to_dict()["tone_counts"], {"x":3, "y":3})
        rows = tuple(request(i, (1, i+1), (11, i+1)) for i in range(5))
        self.assertEqual([len(e.atoms) for e in MovementPlanner(replace(self.controller, max_y_tones=2)).plan(rows)], [2, 2, 1])

    def test_field_of_view_and_invalid_controller(self):
        outside = request(0, (1, 1), (1, 100))
        self.assertEqual(self.controller.legacy_incompatibility((outside.translation,)), "outside AOD allowed region")
        with self.assertRaises(ValueError): self.planner.plan((outside,))
        self.assertTrue(self.controller.compatible((Translation("a", Position(0, 0), Position(100, 99)),)))
        for bad in (0, -1, True, 1.5):
            with self.assertRaises(ValueError): replace(self.controller, max_x_tones=bad)
        with self.assertRaises(ValueError): replace(self.controller, allowed_primitives=("STRETCH",))
        with self.assertRaises(ValueError): replace(self.controller, displacement_tolerance=-1)
        with self.assertRaises(ValueError): Translation("a", Position(1, 1), Position(1, 1))

    def test_absolute_tolerance_does_not_chain(self):
        controller = replace(self.controller, displacement_tolerance=1e-9)
        a = Translation("a", Position(1, 1), Position(1, 11))
        b = Translation("b", Position(2, 1), Position(2, 11+0.75e-9))
        c = Translation("c", Position(3, 1), Position(3, 11+1.5e-9))
        self.assertTrue(controller.legacy_compatible((a, b)))
        self.assertTrue(controller.legacy_compatible((b, c)))
        self.assertFalse(controller.legacy_compatible((a, b, c)))
        decimal = (request(0, (0.1, 1), (0.4, 1)), request(1, (0.2, 2), (0.5, 2)))
        self.assertEqual(len(self.planner.plan(decimal)), 1)

    def test_timing_mismatch_duplicate_atoms_and_empty_input(self):
        a = request(0, (1, 1), (1, 11))
        b = request(1, (2, 1), (2, 11), timing=ActionTiming(move_speed=2))
        self.assertEqual(len(self.planner.plan((a, b))), 2)
        with self.assertRaises(ValueError): self.planner.plan((a, a))
        same_atom = replace(b.translation, atom=a.atom)
        self.assertFalse(self.controller.legacy_compatible((a.translation, same_atom)))
        self.assertFalse(self.controller.legacy_compatible(()))
        self.assertEqual(self.planner.plan(()), ())

    def test_dependencies_must_be_completed_not_just_same_displacement(self):
        a = request(0, (1, 1), (1, 11))
        b = request(1, (2, 1), (2, 11), dependencies=(a.dropoff.id,))
        with self.assertRaises(ValueError): self.planner.plan((a, b))
        with self.assertRaises(ValueError): self.planner.plan((a, b), completed_actions=(a.dropoff.id,))
        self.assertEqual(len(self.planner.plan((b,), completed_actions=a.action_ids)), 1)
        with self.assertRaises(ValueError): AODMovementEpoch("bad", (a, b), self.controller)

    def test_catalog_partial_and_inflight_requests(self):
        code = create_code()
        plan = LegacyGateLowerer(self.config.timing).lower(code.syndrome_round(), build_initial_state(code, self.config))
        catalog = TransportCatalog(plan)
        self.assertEqual(len(catalog.requests), 112)
        self.assertEqual(len(catalog.transport_action_ids), 336)
        first = catalog.requests[0]
        actions = {a.id:a for a in plan.actions}
        done = set()
        def complete_ancestors(action_id):
            for parent in actions[action_id].dependencies: complete_ancestors(parent)
            done.add(action_id)
        for parent in first.dependencies: complete_ancestors(parent)
        self.assertIn(first, catalog.ready_requests(done))
        self.assertNotIn(first, catalog.ready_requests(done, in_flight=(first.id,)))
        done.add(first.pickup.id)
        with self.assertRaises(ValueError): catalog.ready_requests(done)
        self.assertNotIn(first, catalog.ready_requests(done, in_flight=(first.id,)))
        done.update(first.action_ids)
        self.assertNotIn(first, catalog.ready_requests(done))
        with self.assertRaises(ValueError): catalog.ready_requests(done, in_flight=(first.id,))
        with self.assertRaises(ValueError): catalog.ready_requests((first.dropoff.id,))
        with self.assertRaises(ValueError): catalog.ready_requests(("missing",))

    def test_full_plan_coverage_determinism_and_preserved_reservations(self):
        for rounds in (1, 3):
            code = create_code()
            plan = LegacyGateLowerer(self.config.timing).lower(code.syndrome_round(rounds=rounds), build_initial_state(code, self.config))
            before = plan.to_dict()
            catalog, frontiers = inspect_frontiers(plan, self.planner)
            covered = [i for f in frontiers for e in f["epochs"] for phase in e["phase_action_ids"].values() for i in phase]
            self.assertEqual(len(covered), len(set(covered)))
            self.assertEqual(set(covered), catalog.transport_action_ids)
            local = [a for f in frontiers for a in f["nontransport_actions"]]
            self.assertEqual(set(local) | set(covered), {a.id for a in plan.actions})
            self.assertEqual(plan.to_dict(), before)
            self.assertEqual(inspect_frontiers(plan, self.planner)[1], frontiers)
            leases = {r.id:r for r in plan.reservations}
            for request_ in catalog.requests:
                for lease_id in request_.additional_reservation_ids:
                    self.assertIn(lease_id, leases)
                    self.assertNotEqual(lease_id, request_.id)
            for frontier in frontiers:
                for epoch in frontier["epochs"]:
                    self.assertIsNone(epoch["start_time"])
                    self.assertEqual(sum(r["units"] for r in epoch["reservation"]["required_resources"] if r["resource"] == "device/aod"), 1)

    def test_config_loading_and_malformed_transport(self):
        original = CONFIG.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hardware.yaml"
            path.write_text(original.replace("max_x_tones: 20", "max_x_tones: 3"), encoding="utf-8")
            self.assertEqual(load_hardware_config(path).aod.max_x_tones, 3)
            for changed in (original.replace("max_y_tones: 20", "max_y_tones: true"),
                            original.replace("[TRANSLATE]", "[COMPRESS]"),
                            original.replace("max_x_tones: 20", "max_x_tonnes: 20")):
                path.write_text(changed, encoding="utf-8")
                with self.assertRaises(ValueError): load_hardware_config(path)
        a = request(0, (1, 1), (1, 11))
        with self.assertRaises(ValueError): replace(a, move=replace(a.move, dependencies=()))
        with self.assertRaises(ValueError): replace(a, reservation=replace(a.reservation, release_after=()))


if __name__ == "__main__": unittest.main()
