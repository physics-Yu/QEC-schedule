"""Small explicit fixtures exercise runtime invariants, never full-chain claims."""

from copy import deepcopy
import unittest

from na_pipeline.device import default_device
from na_pipeline.runtime import run, make_scenario, RuntimeContractError


def plan(points):
    device = default_device()
    atoms, traps = [], []
    for i, xy in enumerate(points):
        aid, tid = f"a{i}", f"slm{i}"
        zone = "measurement" if xy[1] >= 1020 else "storage_entanglement"
        atoms.append(dict(atom_id=aid, qubit_id=f"q{i}", position_um=list(xy), carrier="SLM",
                          trap_id=tid, aod_group="data", row_id=None, column_id=None))
        traps.append(dict(trap_id=tid, position_um=list(xy), zone_id=zone, occupant=aid))
    return {"schema_version": "AtomProgram/0.2.0-draft", "artifact_id": "runtime-fixture",
            "provenance": {"fixture": True}, "device_ref": device["artifact_id"],
            "execution_kind": "compile_plan", "quantum_state_simulated": False,
            "hardware_executed": False, "loss_enabled": False, "complete": True,
            "initial_state": {"atoms": atoms, "slm_traps": traps, "aod_rows": [], "aod_columns": []},
            "actions": [], "source_map": {}, "stats": {}}, device


def action(aid, kind, atoms, t0, t1, payload=None, depends=(), condition=None, resources=()):
    return {"id": aid, "kind": kind, "atoms": atoms, "t_start_us": t0, "t_end_us": t1,
            "payload": payload or {}, "source_ids": ["fixture:"+aid], "depends_on": list(depends),
            "resources": list(resources), "condition": condition}


def measurement(aid="m0", result="round0/m", atom="a0", t0=0):
    return action(aid, "measure", [atom], t0, t0+100,
                  {"basis": "Z", "result_id": result, "result_ready_us": t0+105, "origin": "fake"})


def feedback_plan():
    p, d = plan([[0, 1020], [20, 0]])
    p["actions"] = [measurement(), action("feedback", "gate", ["a1"], 106, 107, {"name": "X", "params": {}},
                                              depends=["m0"], condition={"bit": "round0/m", "equals": 1})]
    return p, d


class RejectionMixin:
    def rejected(self, code, program, scenario, device):
        with self.assertRaises(RuntimeContractError) as caught:
            run(program, scenario, device)
        self.assertEqual(caught.exception.code, code, caught.exception.to_dict())
        return caught.exception


class RuntimeTests(RejectionMixin, unittest.TestCase):
    def test_nonzero_branch_and_zero_skip_keep_measurement(self):
        p, d = feedback_plan()
        zero, one = run(p, make_scenario(p), d), run(p, make_scenario(p, value=1), d)
        self.assertEqual([e["status"] for e in zero["events"]], ["completed", "skipped"])
        self.assertEqual([e["status"] for e in one["events"]], ["completed", "completed"])
        self.assertEqual(zero["results"]["round0/m"]["available_us"], 105)
        self.assertEqual(one["events"][1]["condition_reads"][0]["origin"], "fake")
        self.assertFalse(one["sampled"])

    def test_missing_result_is_not_implicit_zero(self):
        p, d = feedback_plan()
        s = make_scenario(p); s["results"].clear()
        self.rejected("MISSING_FAKE_RESULT", p, s, d)

    def test_future_result_cannot_drive_condition(self):
        p, d = feedback_plan()
        p["actions"][1].update(t_start_us=100, t_end_us=101)
        self.rejected("RESULT_NOT_READY", p, make_scenario(p, value=1), d)

    def test_feedback_latency_is_real_time(self):
        p, d = feedback_plan()
        p["actions"][1].update(t_start_us=105, t_end_us=106)
        self.rejected("FEEDBACK_TOO_EARLY", p, make_scenario(p), d)

    def test_scenario_delay_does_not_retime_the_plan(self):
        p, d = feedback_plan()
        s = make_scenario(p, overrides={"round0/m": {"value": 1, "origin": "fake", "ready_us": 120}})
        self.rejected("RESULT_NOT_READY", p, s, d)

    def test_plan_and_scenario_cannot_advance_readout(self):
        p, d = feedback_plan()
        p["actions"][0]["payload"]["result_ready_us"] = 100
        self.rejected("RESULT_READY_TOO_EARLY", p, make_scenario(p), d)
        p, d = feedback_plan()
        s = make_scenario(p, overrides={"round0/m": {"value": 0, "origin": "fake", "ready_us": 104}})
        self.rejected("RESULT_READY_TOO_EARLY", p, s, d)

    def test_measure_reset_preserves_atom_identity_and_instances(self):
        p, d = plan([[0, 1020]])
        p["actions"] = [measurement(), action("reset", "reset", ["a0"], 100, 110, {"state": 0}, ["m0"]),
                        measurement("m1", "round1/m", t0=110)]
        s = make_scenario(p, overrides={"round1/m": 1})
        before = deepcopy((p, s, d))
        trace = run(p, s, d)
        self.assertEqual(trace["stats"]["atom_count"], 1)
        atom = trace["final_state"]["atoms"][0]
        self.assertEqual((atom["atom_id"], atom["qubit_id"], atom["reset_epoch"], atom["measurement_count"]), ("a0", "q0", 1, 2))
        self.assertEqual([trace["results"][rid]["value"] for rid in ("round0/m", "round1/m")], [0, 1])
        self.assertEqual(trace["stats"]["duration_us"], 215)
        self.assertEqual((p, s, d), before)
        second = run(p, make_scenario(p, value=1), d)
        self.assertEqual(second["final_state"]["atoms"][0]["reset_epoch"], 1)
        self.assertEqual(second["results"]["round0/m"]["value"], 1)

    def test_duplicate_instance_result_rejected(self):
        p, d = plan([[0, 1020]])
        p["actions"] = [measurement(), measurement("m1", "round0/m", t0=120)]
        s = {"schema_version": "ScenarioInput/0.2.0-draft", "artifact_id": "s", "provenance": {}, "execution_kind": "scenario", "results": {}}
        self.rejected("DUPLICATE_RESULT_ID", p, s, d)

    def test_parallel_clock_and_resource_conflict(self):
        p, d = plan([[0, 0], [10, 0]])
        p["actions"] = [action(f"g{i}", "gate", [f"a{i}"], 0, 1, {"name": "H"}) for i in range(2)]
        trace = run(p, make_scenario(p), d)
        self.assertEqual(trace["stats"]["duration_us"], 1)
        p["actions"][1]["atoms"] = ["a0"]
        self.rejected("RESOURCE_CONFLICT", p, make_scenario(p), d)

    def test_dependency_time_cannot_be_overridden_by_scenario(self):
        p, d = feedback_plan()
        p["actions"][1].update(t_start_us=50, t_end_us=51)
        self.rejected("DEPENDENCY_NOT_COMPLETE", p, make_scenario(p), d)

    def test_disjoint_broadcasts_and_spectator_count(self):
        p, d = plan([[0, 0], [2, 0], [20, 0], [22, 0], [50, 0], [0, 1020]])
        p["actions"] = [action("cz", "gate", ["a0", "a1", "a2", "a3"], 0, 1,
                                {"name": "CZ", "broadcast": True, "zone_id": "storage_entanglement", "pairs": [["a0", "a1"], ["a2", "a3"]]})]
        trace = run(p, make_scenario(p), d)
        self.assertEqual(trace["illumination_counts"], dict(a0=1, a1=1, a2=1, a3=1, a4=1, a5=0))
        self.assertNotIn("illuminated_atoms", trace["events"][0])
        p["actions"][0]["payload"]["pairs"].pop()
        self.rejected("BROADCAST_PAIR_MISMATCH", p, make_scenario(p), d)

    def test_multibody_degree_rejected_without_dropping_edges(self):
        p, d = plan([[0, 0], [2, 0], [4, 0]])
        p["actions"] = [action("cz", "gate", ["a0", "a1", "a2"], 0, 1,
                                {"name": "CZ", "broadcast": True, "zone_id": "storage_entanglement", "pairs": [["a0", "a1"], ["a1", "a2"]]})]
        self.rejected("UNSUPPORTED_MULTIBODY_BROADCAST", p, make_scenario(p), d)
        self.assertEqual(len(p["actions"][0]["payload"]["pairs"]), 2)

    def test_spectator_cannot_run_another_gate_during_broadcast(self):
        p, d = plan([[0, 0], [2, 0], [20, 0]])
        p["actions"] = [action("cz", "gate", ["a0", "a1"], 0, 1,
                                {"name": "CZ", "broadcast": True, "zone_id": "storage_entanglement", "pairs": [["a0", "a1"]]}),
                        action("h", "gate", ["a2"], 0, 1, {"name": "H"})]
        self.rejected("RESOURCE_CONFLICT", p, make_scenario(p), d)

    def test_unexecuted_measurement_has_no_return(self):
        p, d = feedback_plan()
        m = measurement("m1", "unselected/m", t0=110)
        m["condition"] = {"bit": "round0/m", "equals": 1}
        p["actions"].append(m)
        s = make_scenario(p); del s["results"]["unselected/m"]
        trace = run(p, s, d)
        self.assertNotIn("unselected/m", trace["results"])
        self.assertEqual(trace["events"][-1]["status"], "skipped")

    def test_invalid_origin_loss_incomplete_or_schema_rejected(self):
        p, d = feedback_plan()
        for field, value, code in (("loss_enabled", True, "UNSUPPORTED_EVIDENCE"), ("complete", False, "INCOMPLETE_PLAN"), ("schema_version", "AtomProgram/unknown", "UNSUPPORTED_SCHEMA")):
            modified = deepcopy(p); modified[field] = value
            self.rejected(code, modified, make_scenario(p), d)
        s = make_scenario(p); s["results"]["round0/m"]["origin"] = "quantum"
        self.rejected("INVALID_FAKE_VALUE", p, s, d)

    def test_changed_device_hash_rejected_even_when_id_same(self):
        from hashlib import sha256
        import json
        p, d = feedback_plan()
        p["input_hashes"] = {"device": sha256(json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}
        d["timings_us"]["reset"] += 1
        self.rejected("DEVICE_HASH_MISMATCH", p, make_scenario(p), d)

    def test_explicit_wait_is_retained(self):
        p, d = plan([[0, 0]])
        p["actions"] = [action("wait", "wait", ["a0"], 0, 50)]
        trace = run(p, make_scenario(p), d)
        self.assertEqual((trace["stats"]["duration_us"], trace["events"][0]["kind"]), (50, "wait"))

    def test_classical_xor_has_explicit_cost_and_causality(self):
        p, d = plan([[0, 1020], [10, 1020]])
        p["actions"] = [measurement(), measurement("m1", "round0/n", "a1"),
                        action("xor", "classical", [], 106, 107, {"operation": "xor", "reads": ["round0/m", "round0/n"], "writes": ["parity"]})]
        trace = run(p, make_scenario(p, overrides={"round0/n": 1}), d)
        self.assertEqual(trace["results"]["parity"]["value"], 1)
        self.assertEqual(trace["results"]["parity"]["ready_us"], 107)
        self.assertEqual(trace["results"]["parity"]["derivation"], "xor")

    def test_all_zero_is_timed_computation_from_ready_fake_bits(self):
        p, d = plan([[0, 1020], [10, 1020]])
        p["actions"] = [measurement(), measurement("m1", "round0/n", "a1"),
                        action("accept", "classical", [], 106, 107, {"operation": "all_zero", "reads": ["round0/m", "round0/n"], "writes": ["accept"]})]
        zeros = run(p, make_scenario(p), d)
        nonzero = run(p, make_scenario(p, overrides={"round0/n": 1}), d)
        self.assertEqual((zeros["results"]["accept"]["value"], nonzero["results"]["accept"]["value"]), (1, 0))
        self.assertEqual(zeros["results"]["accept"]["ready_us"], 107)
        self.assertNotIn("accept", make_scenario(p)["results"])


class TransportTests(RejectionMixin, unittest.TestCase):
    # These cases use explicit R4-shaped fixtures, not production compiler output.
    def transport(self):
        p, d = plan([[0, 0]])
        p["initial_state"]["slm_traps"].append(dict(trap_id="readout", position_um=[0, 1020], zone_id="measurement", occupant=None))
        binding = {"aod_group": "data", "row_id": "r0", "column_id": "c0"}
        p["actions"] = [
            action("pick", "pickup", ["a0"], 0, 200, dict(binding, from_trap_id="slm0", to_trap_id="dynamic0", position_um=[0, 0])),
            action("move", "move", ["a0"], 200, 1220, {"aod_group": "data", "interpolation": "linear", "trajectories": [dict(atom_id="a0", row_id="r0", column_id="c0", from_um=[0, 0], to_um=[0, 1020])]}, ["pick"]),
            action("drop", "drop", ["a0"], 1220, 1420, dict(binding, from_trap_id="dynamic0", to_trap_id="readout", position_um=[0, 1020]), ["move"]),
            measurement(t0=1420)]
        return p, d

    def test_pickup_move_drop_measure_retains_id_and_frees_lines(self):
        p, d = self.transport()
        trace = run(p, make_scenario(p), d)
        atom = trace["final_state"]["atoms"][0]
        self.assertEqual((atom["atom_id"], atom["trap_id"], atom["carrier"], atom["position_um"]), ("a0", "readout", "SLM", [0, 1020]))
        self.assertEqual(trace["final_state"]["aod_rows"], [])
        self.assertEqual(trace["final_state"]["slm_traps"][0]["occupant"], None)

    def test_teleport_speed_and_unaligned_drop_rejected(self):
        for edit, code in (("from", "MOTION_BINDING"), ("speed", "SPEED_EXCEEDED"), ("drop", "TRANSFER_BINDING")):
            p, d = self.transport()
            if edit == "from": p["actions"][1]["payload"]["trajectories"][0]["from_um"] = [1, 0]
            if edit == "speed": p["actions"][1]["t_end_us"] = 1219
            if edit == "drop": p["actions"][2]["payload"]["position_um"] = [0, 1030]
            self.rejected(code, p, make_scenario(p), d)

    def shared(self):
        p, d = plan([[0, 0], [10, 0]])
        for i, atom in enumerate(p["initial_state"]["atoms"]):
            atom.update(carrier="AOD", trap_id=f"dynamic{i}", row_id="r0", column_id=f"c{i}")
            p["initial_state"]["slm_traps"][i]["occupant"] = None
        p["initial_state"]["aod_rows"] = [{"aod_group": "data", "row_id": "r0", "y_um": 0}]
        p["initial_state"]["aod_columns"] = [{"aod_group": "data", "column_id": f"c{i}", "x_um": 10*i} for i in range(2)]
        p["actions"] = [action("move", "move", ["a0", "a1"], 0, 10, {"aod_group": "data", "interpolation": "linear", "trajectories": [dict(atom_id=f"a{i}", row_id="r0", column_id=f"c{i}", from_um=[10*i, 0], to_um=[10*i, 10]) for i in range(2)]})]
        return p, d

    def test_all_atoms_on_shared_row_move(self):
        p, d = self.shared()
        trace = run(p, make_scenario(p), d)
        self.assertEqual([a["position_um"][1] for a in trace["final_state"]["atoms"]], [10, 10])
        p["actions"][0]["atoms"].pop()
        p["actions"][0]["payload"]["trajectories"].pop()
        self.rejected("SHARED_LINE_MOTION", p, make_scenario(p), d)

    def test_line_order_cannot_cross_even_without_point_collision(self):
        p, d = self.shared()
        p["initial_state"]["atoms"][1]["position_um"] = [10, 10]
        p["initial_state"]["atoms"][1]["row_id"] = "r1"
        p["initial_state"]["aod_rows"].append({"aod_group": "data", "row_id": "r1", "y_um": 10})
        trs = p["actions"][0]["payload"]["trajectories"]
        trs[0]["to_um"] = [10, 0]
        trs[1].update(row_id="r1", from_um=[10, 10], to_um=[0, 10])
        self.rejected("LINE_CROSSING", p, make_scenario(p), d)

    def test_motion_entering_broadcast_during_pulse_rejected(self):
        p, d = plan([[0, 0], [2, 0], [50, 1020]])
        a = p["initial_state"]["atoms"][2]
        a.update(carrier="AOD", trap_id="dynamic2", row_id="r2", column_id="c2")
        p["initial_state"]["slm_traps"][2]["occupant"] = None
        p["initial_state"]["aod_rows"] = [{"aod_group": "data", "row_id": "r2", "y_um": 1020}]
        p["initial_state"]["aod_columns"] = [{"aod_group": "data", "column_id": "c2", "x_um": 50}]
        motion = action("move", "move", ["a2"], 0, 40, {"aod_group": "data", "interpolation": "linear", "trajectories": [dict(atom_id="a2", row_id="r2", column_id="c2", from_um=[50, 1020], to_um=[50, 980])]})
        pulse = action("cz", "gate", ["a0", "a1"], 19, 21, {"name": "CZ", "broadcast": True, "zone_id": "storage_entanglement", "pairs": [["a0", "a1"]]})
        p["actions"] = [motion, pulse]
        self.rejected("BROADCAST_MOTION", p, make_scenario(p), d)
        pulse.update(t_start_us=1, t_end_us=2)
        trace = run(p, make_scenario(p), d)
        self.assertEqual(trace["illumination_counts"], {"a0": 1, "a1": 1, "a2": 0})

    def test_concurrent_independent_aods_allowed(self):
        p, d = self.shared()
        second = p["initial_state"]["atoms"][1]
        second.update(aod_group="magic", row_id="r1")
        p["initial_state"]["aod_columns"][1]["aod_group"] = "magic"
        p["initial_state"]["aod_rows"].append({"aod_group": "magic", "row_id": "r1", "y_um": 0})
        first_motion = p["actions"][0]
        tr = first_motion["payload"]["trajectories"].pop()
        first_motion["atoms"] = ["a0"]
        tr["row_id"] = "r1"
        p["actions"].append(action("magic_move", "move", ["a1"], 0, 10, {"aod_group": "magic", "interpolation": "linear", "trajectories": [tr]}))
        trace = run(p, make_scenario(p), d)
        self.assertEqual(trace["stats"]["duration_us"], 10)


if __name__ == "__main__":
    unittest.main()
