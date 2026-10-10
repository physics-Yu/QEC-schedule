from copy import deepcopy
import unittest
from unittest.mock import patch

from na_pipeline.backend import StrategyError, StrategyLibrary
from na_pipeline.backend.enola_kernel import EnolaKernel, capture_closure, check_group_segment, group_route
from na_pipeline.device import grouped_device
from na_pipeline.qec import build_logical_primitive
from na_pipeline.runtime import make_scenario, run


class StrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = grouped_device()
        cls.library = StrategyLibrary(cls.device)
        cls.prepare = cls.library.get_or_compile(build_logical_primitive("prepare", params={"state": "0"}))
        cls.syndrome = cls.library.get_or_compile(build_logical_primitive("syndrome_round"))
        cls.cx = cls.library.get_or_compile(build_logical_primitive("logical_cx"))

    def binding(self, strategy=None, *, call="call0", start=0):
        strategy = strategy or self.syndrome
        body = strategy["body"]
        return {"schema_version": "logical-call-binding/0.1", "call_id": call, "run_id": "tests", "epoch": 0,
                "start_time_us": start, "qubit_bindings": {q["id"]: q["id"] for q in body["physical_program"]["qubits"]},
                "atom_bindings": {a["atom_id"]: a["atom_id"] for a in body["entry"]["atoms"]},
                "offset_um": [0., 0.], "world_state": deepcopy(body["entry"]), "resource_leases": []}

    def test_real_enola_selection_controls_pulse_geometry(self):
        body = self.cx["body"]
        accepted = [r for r in body["enola_provenance"]["decisions"] if r["accepted"]]
        self.assertTrue(accepted)
        actions = {a["id"]: a for a in body["atom_program"]["actions"]}
        for receipt in accepted:
            pulse = actions[receipt["pulse_action_id"]]
            self.assertEqual(set(pulse["payload"]["physical_op_ids"]), set(receipt["selected_op_ids"]))
            self.assertEqual(pulse["payload"]["enola_decision_hash"], receipt["decision_hash"])
        self.assertEqual(sum(len(a["payload"]["pairs"]) for a in actions.values() if a["kind"] == "gate" and a["payload"]["name"] == "CZ"), 9)

    def test_full_initialization_and_readout_groups(self):
        p = self.prepare["body"]["atom_program"]
        group = next(g for g in p["groups"] if g["purpose"] == "patch_initialization_transport")
        moves = [a for a in p["actions"] if a["kind"] == "move" and a["payload"]["group_id"] == group["group_id"]]
        self.assertEqual(set(moves[0]["atoms"]), set(group["members"]))
        self.assertEqual(len(group["members"]), 17)
        s = self.syndrome["body"]["atom_program"]
        readout = s["groups"][0]
        self.assertEqual(len(readout["members"]), 8)
        self.assertEqual(readout["readout_start_span_us"], 0)
        self.assertTrue(all("/d" not in atom for a in s["actions"] if a["kind"] in {"measure", "reset"} for atom in a["atoms"]))
        resets = [a for a in s["actions"] if a["kind"] == "reset" and "service_reset" in a["payload"]["physical_op_id"]]
        self.assertLessEqual(max(a["t_end_us"] for a in resets), readout["return"]["start_us"])

    def test_repeat_cache_no_search_and_immutable_copy(self):
        before = self.library.stats
        strategy = self.library.get_or_compile(build_logical_primitive("syndrome_round"))
        self.assertEqual(strategy["strategy_hash"], self.syndrome["strategy_hash"])
        after = self.library.stats
        for key in ("strategy_compile_count", "placement_search_count", "routing_search_count"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["cache_hit_count"], before["cache_hit_count"]+1)
        strategy["body"]["atom_program"]["actions"].clear()
        self.assertTrue(self.library.get_or_compile(build_logical_primitive("syndrome_round"))["body"]["atom_program"]["actions"])

    def test_route_counter_covers_candidate_and_final_planning_calls(self):
        library = StrategyLibrary(self.device)
        physical = build_logical_primitive("syndrome_round")
        with patch("na_pipeline.backend.strategy_compile.group_route", wraps=group_route) as observed:
            strategy = library.get_or_compile(physical)
            self.assertEqual(library.stats["routing_search_count"], observed.call_count)
            self.assertEqual(strategy["body"]["atom_program"]["stats"]["routing_search_count"], observed.call_count)
            before = observed.call_count
            library.get_or_compile(physical)
            library.bind(strategy, self.binding(strategy))
            self.assertEqual(observed.call_count, before)

    def test_bound_runs_keep_results_separate_and_no_search(self):
        before = self.library.stats
        first = self.library.bind(self.syndrome, self.binding())
        zero = run(first["atom_program"], make_scenario(first["atom_program"], value=0), self.device)
        binding = self.binding(call="call1", start=zero["stats"]["t_end_us"])
        binding["world_state"] = zero["final_state"]
        second = self.library.bind(self.syndrome, binding)
        one = run(second["atom_program"], make_scenario(second["atom_program"], value=1), self.device)
        self.assertFalse(set(zero["results"]) & set(one["results"]))
        self.assertTrue(all(r["value"] == 1 for r in one["results"].values()))
        self.assertTrue(all(r["value"] == 0 for r in zero["results"].values()))
        for key in ("strategy_compile_count", "placement_search_count", "routing_search_count"):
            self.assertEqual(before[key], self.library.stats[key])

    def test_bad_carrier_entry_device_and_hash_rejected(self):
        b = self.binding(); b["world_state"]["atoms"][0]["carrier"] = "AOD"
        with self.assertRaises(StrategyError): self.library.bind(self.syndrome, b)
        b = self.binding(); b["world_state"]["atoms"][0]["position_um"][0] += 1
        with self.assertRaises(StrategyError): self.library.bind(self.syndrome, b)
        altered = deepcopy(self.syndrome); altered["body"]["device_hash"] = "wrong"
        with self.assertRaises(StrategyError): self.library.bind(altered, self.binding())
        d = deepcopy(self.device); d["timings_us"]["measure"] += 1
        with self.assertRaises(StrategyError): StrategyLibrary(d).bind(self.syndrome, self.binding())

    def test_empty_active_axis_is_not_ignored(self):
        b = self.binding()
        b["world_state"]["aod_rows"] = [{"aod_group": "data", "row_id": "external", "y_um": 300.}]
        with self.assertRaises(StrategyError) as caught: self.library.bind(self.syndrome, b)
        self.assertEqual(caught.exception.code, "ACTIVE_AOD_ENTRY_UNSUPPORTED")

    def test_same_body_translates_to_a_second_homologous_patch(self):
        b = self.binding(call="other")
        b["offset_um"] = [100., 0.]
        qmap = {q: "L1/"+q.rsplit("/", 1)[-1] for q in b["qubit_bindings"]}
        amap = {a: "other:"+a for a in b["atom_bindings"]}
        b["qubit_bindings"], b["atom_bindings"] = qmap, amap
        for atom in b["world_state"]["atoms"]:
            atom["atom_id"], atom["qubit_id"] = amap[atom["atom_id"]], qmap[atom["qubit_id"]]
            atom["trap_id"] = "other:"+atom["trap_id"]; atom["position_um"][0] += 100
        for trap in b["world_state"]["slm_traps"]:
            trap["trap_id"] = "other:"+trap["trap_id"]; trap["position_um"][0] += 100
            if trap["occupant"] is not None: trap["occupant"] = amap[trap["occupant"]]
        before = self.library.stats
        bound = self.library.bind(self.syndrome, b)
        trace = run(bound["atom_program"], make_scenario(bound["atom_program"]), self.device)
        self.assertEqual(len(trace["results"]), 8)
        self.assertEqual(bound["binding_report"]["strategy_hash"], self.syndrome["strategy_hash"])
        self.assertEqual(before["routing_search_count"], self.library.stats["routing_search_count"])

    def test_resource_lease_and_out_of_zone_translation_rejected(self):
        b = self.binding()
        atom = self.syndrome["body"]["atom_program"]["actions"][0]["atoms"][0]
        b["resource_leases"] = [{"resource_id": "atom:"+atom, "t_start_us": 0., "t_end_us": 1000.}]
        with self.assertRaises(StrategyError) as caught: self.library.bind(self.syndrome, b)
        self.assertEqual(caught.exception.code, "RESOURCE_LEASE_CONFLICT")
        b = self.binding(); b["offset_um"] = [0., 20.]
        with self.assertRaises(StrategyError) as caught: self.library.bind(self.syndrome, b)
        self.assertEqual(caught.exception.code, "LAYOUT_TRANSFORM_OUT_OF_ZONE")

    def test_capture_uses_device_geometric_tolerance(self):
        b = self.binding(self.prepare)
        p = [30.+5e-7, -100.]
        zone = self.device["grouped_profile"]["layouts"]["patch_initialization"]["zone_id"]
        b["world_state"]["atoms"].append({"atom_id": "near-intersection", "qubit_id": "extra", "position_um": p,
            "carrier": "SLM", "trap_id": "extra-trap", "aod_group": "magic", "row_id": None, "column_id": None})
        b["world_state"]["slm_traps"].append({"trap_id": "extra-trap", "position_um": p, "zone_id": zone, "occupant": "near-intersection"})
        with self.assertRaises(StrategyError) as caught: self.library.bind(self.prepare, b)
        self.assertEqual(caught.exception.code, "CAPTURE_CLOSURE_MISMATCH")

    def test_full_background_extra_pair_rejected(self):
        b = self.binding()
        for i, x in enumerate((900., 902.)):
            b["world_state"]["atoms"].append({"atom_id": f"extra{i}", "qubit_id": f"extraq{i}", "position_um": [x, 20.],
                 "carrier": "SLM", "trap_id": f"extrat{i}", "aod_group": "magic", "row_id": None, "column_id": None})
            b["world_state"]["slm_traps"].append({"trap_id": f"extrat{i}", "position_um": [x, 20.], "zone_id": "storage_entanglement", "occupant": f"extra{i}"})
        with self.assertRaises(StrategyError) as caught: self.library.bind(self.syndrome, b)
        self.assertEqual(caught.exception.code, "BROADCAST_WORLD_MISMATCH")

    def test_readout_capacity_four_cannot_fake_eight(self):
        library = StrategyLibrary(grouped_device(readout_capacity=4))
        with self.assertRaises(StrategyError) as caught: library.get_or_compile(build_logical_primitive("syndrome_round"))
        self.assertEqual(caught.exception.code, "READOUT_CAPACITY_EXCEEDED")
        self.assertEqual(library.stats["strategy_compile_count"], 0)
        self.assertEqual(library.stats["failed_compile_count"], 1)
        self.assertGreater(library.stats["routing_search_count"], 0)

    def test_missing_enola_has_no_fallback(self):
        with self.assertRaises(StrategyError) as caught: EnolaKernel("examples/atom/nonexistent-enola")
        self.assertEqual(caught.exception.code, "ENOLA_NOT_INSTALLED")

    def test_cartesian_capture_and_empty_intersection_sweep(self):
        atoms = [{"atom_id": "a", "position_um": [0., 0.], "carrier": "SLM"},
                 {"atom_id": "b", "position_um": [10., 10.], "carrier": "SLM"},
                 {"atom_id": "c", "position_um": [0., 10.], "carrier": "SLM"}]
        self.assertEqual(capture_closure(atoms, ["a", "b"])["captured_atoms"], ["a", "b", "c"])
        atoms[-1]["position_um"] = [5., 15.]
        self.assertEqual(check_group_segment(atoms, ["a", "b"], {"a": [5., 5.], "b": [15., 15.]}), "CARTESIAN_SWEEP_CAPTURE")
        self.assertEqual(check_group_segment(atoms[:2], ["a", "b"], {"a": [10., 0.], "b": [0., 10.]}), "AXIS_CROSSING")


if __name__ == "__main__": unittest.main()
