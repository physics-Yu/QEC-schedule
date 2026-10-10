from copy import deepcopy
import unittest

from na_pipeline.backend import compile_physical
from na_pipeline.backend.reuse import ReuseContractError, check_frontier, route_template_key
from na_pipeline.device import default_device
from na_pipeline.qec import build_two_block_slice


class ReuseQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = default_device()
        program = build_two_block_slice()
        cls.template = next(iter(program["templates"].values()))
        cls.bindings = next(n["bindings"] for n in program["body"] if n["kind"] == "call" and n["template_id"] == cls.template["template_id"])
        cls.geometry = compile_physical(program, cls.device)["initial_state"]

    def key(self, **kw):
        values = {"template": self.template, "device": self.device,
                  "entry_geometry": self.geometry, "bindings": self.bindings, "policy_version": "r4-policy/1"}
        values.update(kw)
        return route_template_key(**values)

    def test_exact_immutable_content_has_same_key(self):
        self.assertEqual(self.key(), self.key(template=deepcopy(self.template), entry_geometry=deepcopy(self.geometry)))

    def test_changed_device_geometry_occupancy_and_policy_invalidate(self):
        baseline = self.key()
        device = deepcopy(self.device); device["timings_us"]["pickup"] += 1
        self.assertNotEqual(baseline, self.key(device=device))
        geometry = deepcopy(self.geometry); geometry["atoms"][-1]["position_um"][0] += 1
        self.assertNotEqual(baseline, self.key(entry_geometry=geometry))
        geometry = deepcopy(self.geometry); geometry["slm_traps"][-1]["occupant"] = "different-atom"
        self.assertNotEqual(baseline, self.key(entry_geometry=geometry))
        self.assertNotEqual(baseline, self.key(policy_version="r4-policy/2"))

    def test_axis_order_and_template_boundary_invalidate(self):
        baseline = self.key()
        geometry = deepcopy(self.geometry)
        geometry["aod_columns"] = [{"id": "c0", "position_um": 0}, {"id": "c1", "position_um": 10}]
        first = self.key(entry_geometry=geometry)
        geometry["aod_columns"][0]["position_um"] = 20
        self.assertNotEqual(first, self.key(entry_geometry=geometry))
        template = deepcopy(self.template); template["metadata"]["boundary"] = "changed-boundary"
        self.assertNotEqual(baseline, self.key(template=template))

    def test_same_scene_different_formal_bindings_is_not_same_route(self):
        bindings = deepcopy(self.bindings)
        first, second = list(bindings)[:2]
        bindings[first], bindings[second] = bindings[second], bindings[first]
        self.assertNotEqual(self.key(), self.key(bindings=bindings))
        bindings[first] = bindings[second]
        with self.assertRaises(ReuseContractError):
            self.key(bindings=bindings)

    def test_runtime_state_and_cached_acceptance_are_rejected(self):
        for key in ("results", "frames", "tokens", "epochs"):
            geometry = deepcopy(self.geometry); geometry[key] = {}
            with self.assertRaises(ReuseContractError):
                self.key(entry_geometry=geometry)
        template = deepcopy(self.template); template["metadata"]["validation_report"] = {"passed": True}
        with self.assertRaises(ReuseContractError):
            self.key(template=template)

    def test_each_frontier_identity_rejects_stale_and_fresh_is_not_execution(self):
        frontier = {"run_id": "run-a", "epoch": 2, "revision": 7, "time_us": 1024., "history_sha256": "0"*64}
        self.assertTrue(check_frontier(frontier, deepcopy(frontier))["fresh"])
        self.assertFalse(check_frontier(frontier, frontier)["execution_authorized"])
        for key, value in (("run_id", "run-b"), ("epoch", 3), ("revision", 8),
                           ("time_us", 1025.), ("history_sha256", "1"*64)):
            current = {**frontier, key: value}
            report = check_frontier(frontier, current)
            self.assertFalse(report["fresh"])
            self.assertEqual(report["changed_fields"], [key])


if __name__ == "__main__":
    unittest.main()
