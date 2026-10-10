import random
import sys
import unittest

from na_pipeline.backend import place_patches, StrategyError
from na_pipeline.backend.enola_scheduler import EnolaReadyScheduler
from na_pipeline.device import preinitialized_device, validate_preinitialized_state


class PatchPlacementTests(unittest.TestCase):
    def setUp(self):
        self.device = preinitialized_device()
        self.patches = {f"L{i}": {"aod_group": "data", "basis": "Z", "value": 0} for i in range(6)}
        self.edges = [{"node_id": f"cx{i}", "patch_operands": [f"L{i}", f"L{(i+3)%6}"], "layer": i//3} for i in range(6)]

    def test_actual_original_call_drives_all_t0_atoms(self):
        observed = []
        def observer(frame, event, arg):
            if event == "return" and frame.f_code.co_name == "run" and frame.f_code.co_filename.replace("\\", "/").endswith("enola/placer/placer.py"):
                observed.append([list(p) for p in frame.f_locals["self"].best_mapping])
        before = random.getstate()
        sys.setprofile(observer)
        try:
            result = place_patches(self.patches, self.edges, self.device, seed=7, budget={"max_iterations": 100})
        finally:
            sys.setprofile(None)
        self.assertEqual(before, random.getstate())
        raw = result["enola"]["raw_output"]["best_mapping"]
        self.assertEqual(observed, [raw])
        self.assertLess(result["cost"]["candidate"], result["cost"]["baseline"])
        for i, p in enumerate(self.patches):
            self.assertEqual(result["placements"][p]["anchor_um"], [60*x for x in raw[i]])
        state = result["initial_state"]
        self.assertEqual(validate_preinitialized_state(state, self.device), [])
        self.assertEqual(len(state["atoms"]), 102)
        for a in state["atoms"]:
            anchor = result["placements"][a["patch_id"]]["anchor_um"]
            local = self.device["grouped_profile"]["layouts"]["patch_home"]["slots"][a["local_id"]]["position_um"]
            self.assertEqual(a["position_um"], [anchor[j]+local[j] for j in (0, 1)])
        self.assertEqual(state["startup_actions"], [])
        self.assertEqual(state["ready_magic_tokens"], [])
        self.assertEqual(result["interactions"], self.edges)

    def test_reproducible_and_budget_exhaustion_is_not_success(self):
        a = place_patches(self.patches, self.edges, self.device, seed=9, budget={"max_iterations": 10})
        b = place_patches(self.patches, self.edges, self.device, seed=9, budget={"max_iterations": 10})
        self.assertEqual(a["artifact_id"], b["artifact_id"])
        with self.assertRaises(StrategyError) as caught:
            place_patches(self.patches, self.edges, self.device, budget={"max_moves": 5})
        self.assertEqual(caught.exception.code, "PLACEMENT_BUDGET_EXHAUSTED")
        self.assertFalse(caught.exception.details["complete"])
        self.assertEqual(caught.exception.details["moves"], 5)

    def test_illegal_domain_and_missing_patch_are_rejected(self):
        with self.assertRaises(StrategyError):
            place_patches(self.patches, self.edges, self.device, grid_shape=[2, 2])
        self.edges[0]["patch_operands"][0] = "absent"
        with self.assertRaises(StrategyError):
            place_patches(self.patches, self.edges, self.device)

    def test_flat_domain_and_no_interactions_labeled(self):
        two = {k: self.patches[k] for k in ("L0", "L1")}
        result = place_patches(two, [{"node_id": "cx", "patch_operands": ["L0", "L1"], "layer": 0}], self.device, grid_shape=[2, 1])
        self.assertEqual(result["search"]["stop_reason"], "no_initial_uphill")
        result = place_patches(two, [], self.device)
        self.assertEqual(result["enola"]["called"], [])
        self.assertEqual(result["evidence_scope"]["backend_used"], "trivial_placement")

    def test_scheduler_preserves_direction_and_rejects_unready(self):
        def op(i, pair, after):
            return {"id": i, "kind": "gate", "params": {"name": "CX"}, "qubits": pair,
                    "reads": [], "writes": [], "condition": None, "source_ids": ["source:"+i], "after": after}
        nodes = [op("a", ["q1", "q0"], ["p"]), op("b", ["q2", "q3"], [])]
        s = EnolaReadyScheduler()
        with self.assertRaises(StrategyError):
            s.partition(nodes, [])
        layers = s.partition(nodes, ["p"])
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0], nodes)
        self.assertEqual(s.receipts[0]["input_operations"], nodes)


if __name__ == "__main__":
    unittest.main()
