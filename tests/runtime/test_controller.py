"""Controller fixtures qualify ownership and timing, not Surface-17/Enola."""

from copy import deepcopy
import unittest

from na_pipeline.device import default_device
from na_pipeline.runtime import LogicalBlockController, RuntimeContractError, make_scenario, run
from na_pipeline.runtime.engine import digest
from test_runtime import plan, action, measurement

PROFILE = {"code": "fixture", "distance": 1, "orientation": "fixture", "convention": "fixture"}


def primitive(operation, *, params=None):
    roles = ["control", "target"] if operation == "logical_cx" else ["block"]
    qubits = [{"id": role+"/"+slot, "block_id": role} for role in roles for slot in ("d0", "x0")]
    return {"qubits": qubits, "strategy_contract": {"operation": {"name": operation, "params": params or {}, "code_profile": PROFILE},
            "formal_bindings": {"physical_qubits": [{"physical_qubit_id": role+"/"+slot, "formal_block": role, "local_role": slot}
                                                     for role in roles for slot in ("d0", "x0")]},
            "exit": {"layout_profile_id": "fixture-home"}}}


class FixtureLibrary:
    def __init__(self, device):
        self.device, self.cache = device, {}
        self.stats = dict(strategy_compile_count=0, placement_search_count=0, routing_search_count=0, cache_hit_count=0, bind_count=0, composition_check_count=0)
        self.bad = None

    def get_or_compile(self, pp):
        key = digest(pp)
        if key in self.cache:
            self.stats["cache_hit_count"] += 1
            return deepcopy(self.cache[key])
        for k in ("strategy_compile_count", "placement_search_count", "routing_search_count"):
            self.stats[k] += 1
        op = pp["strategy_contract"]["operation"]["name"]
        points = [[0, 0], [50, 1020], [2, 0], [52, 1020]] if op == "logical_cx" else [[0, 0], [50, 1020]]
        ap, _ = plan(points)
        remap = {}
        for atom, q in zip(ap["initial_state"]["atoms"], pp["qubits"]):
            old = atom["atom_id"]; new = "formal:"+q["id"]; remap[old] = new
            atom.update(atom_id=new, qubit_id=q["id"])
        for trap in ap["initial_state"]["slm_traps"]:
            trap["occupant"] = remap[trap["occupant"]]
        if op == "logical_cx":
            ap["actions"] = [action("cz", "gate", [remap["a0"], remap["a2"]], 0, 1,
                                      {"name": "CZ", "broadcast": True, "zone_id": "storage_entanglement", "pairs": [[remap["a0"], remap["a2"]]]})]
        else:
            ap["actions"] = [measurement("m", "result", atom=remap["a1"])]
            if op == "prepare":
                ap["actions"].append(action("reset", "reset", [remap["a0"]], 0, 10, {"state": 0}))
        ap["source_map"] = {"source": [a["id"] for a in ap["actions"]]}
        body = {"physical_program": pp, "atom_program": ap, "strategy_contract": pp["strategy_contract"],
                "device_hash": digest(self.device), "backend_used": "fixture"}
        result = {"schema_version": "compiled-logical-strategy/0.1", "strategy_id": key, "strategy_hash": digest(body), "body": body}
        self.cache[key] = deepcopy(result)
        return result

    def bind(self, strategy, binding):
        self.stats["bind_count"] += 1
        self.stats["composition_check_count"] += 1
        prefix, start, mapping = binding["call_id"]+"/", binding["start_time_us"], binding["atom_bindings"]
        ap = deepcopy(strategy["body"]["atom_program"])
        ap["initial_state"] = deepcopy(binding["world_state"])
        for a in ap["actions"]:
            a["id"] = prefix+a["id"]
            a["atoms"] = [mapping[x] for x in a["atoms"]]
            a["t_start_us"] += start; a["t_end_us"] += start
            if "result_id" in a["payload"]:
                a["payload"]["result_id"] = prefix+a["payload"]["result_id"]
                a["payload"]["result_ready_us"] += start
            if "pairs" in a["payload"]:
                a["payload"]["pairs"] = [sorted([mapping[x] for x in pair]) for pair in a["payload"]["pairs"]]
        if self.bad == "search": self.stats["routing_search_count"] += 1
        if self.bad == "teleport": ap["initial_state"]["atoms"][0]["position_um"][0] += 1
        if self.bad == "reset_data": ap["actions"].append(action(prefix+"bad", "reset", [mapping[next(k for k in mapping if k.endswith("/d0"))]], start+100, start+110, {"state": 0}))
        if self.bad == "old_result": ap["actions"][0]["payload"]["result_id"] = "old/result"
        ap["source_map"] = {prefix+"source": [a["id"] for a in ap["actions"]]}
        return {"physical_program": deepcopy(strategy["body"]["physical_program"]), "atom_program": ap, "exit_state": {}, "binding_report": {"fixture": True}}


def controller(lifecycle="unprepared"):
    ap, device = plan([[0, 0], [50, 1020], [2, 0], [52, 1020]])
    for i, atom in enumerate(ap["initial_state"]["atoms"]):
        atom["qubit_id"] = f"L{i//2}/"+("d0" if i%2 == 0 else "x0")
    library = FixtureLibrary(device)
    c = LogicalBlockController(device, ap["initial_state"], run_id="fixture", strategy_library=library, primitive_builder=primitive, fixture=True)
    for i in (0, 1):
        c.register_block(f"L{i}", qubits={"d0": f"L{i}/d0", "x0": f"L{i}/x0"}, data_slots=["d0"], code_profile=PROFILE, layout_profile="fixture-home", lifecycle=lifecycle)
    return c, library


class ControllerTests(unittest.TestCase):
    def test_repeat_two_blocks_cx_and_continue(self):
        c, library = controller()
        for lid in ("L0", "L1"):
            c.queue_call("prepare", {"block": lid}, call_id=lid+"-prep", params={"state": "0"})
            for i in range(3): c.queue_call("syndrome_round", {"block": lid}, call_id=f"{lid}-r{i}")
        cx = c.queue_call("logical_cx", {"control": "L0", "target": "L1"}, call_id="cx")
        for lid in ("L0", "L1"): c.queue_call("syndrome_round", {"block": lid}, call_id=lid+"-after")
        self.assertEqual(library.stats["strategy_compile_count"], 3)
        self.assertEqual(library.stats["cache_hit_count"], 8)
        self.assertEqual(c.snapshot()["blocks"]["L0"]["lifecycle"], "unprepared")
        outcome = c.execute_pending(make_scenario(c.pending_program(), value=1))
        instances = outcome["instances"]
        self.assertEqual(instances[0]["start_us"], instances[4]["start_us"])
        self.assertEqual(cx["start_us"], 420)
        self.assertEqual(outcome["snapshot"]["blocks"]["L0"]["epoch"], 6)
        self.assertEqual(len(outcome["event_trace"]["results"]), 10)
        data = [a for a in outcome["snapshot"]["world_state"]["atoms"] if a["qubit_id"].endswith("d0")]
        self.assertTrue(all(a["reset_epoch"] == 1 for a in data))
        self.assertEqual(len({p["strategy_hash"] for p in instances if p["operation"] == "syndrome_round"}), 1)

    def test_missing_fake_rolls_back_batch_then_retry(self):
        c, _ = controller("live")
        c.queue_call("syndrome_round", {"block": "L0"}, call_id="r0")
        before = c.snapshot()
        scenario = make_scenario(c.pending_program()); scenario["results"].clear()
        with self.assertRaises(RuntimeContractError): c.execute_pending(scenario)
        self.assertEqual(c.snapshot(), before)
        c.execute_pending(make_scenario(c.pending_program()))
        self.assertEqual(c.result("r0/result")["value"], 0)
        with self.assertRaises(RuntimeContractError): c.result("r0/result", at_us=100)

    def test_failed_bind_has_no_runtime_mutation(self):
        for bad, code in (("teleport", "ENTRY_TELEPORT"), ("reset_data", "LIVE_DATA_DESTROYED"), ("old_result", "RESULT_NAMESPACE_REUSE"), ("search", "BIND_TRIGGERED_SEARCH")):
            c, lib = controller("live"); lib.bad = bad
            before = c.snapshot()
            with self.assertRaises(RuntimeContractError) as caught:
                c.queue_call("syndrome_round", {"block": "L0"}, call_id="bad")
            self.assertEqual(caught.exception.code, code)
            after = c.snapshot()
            before.pop("library_stats"); after.pop("library_stats")
            self.assertEqual(after, before)

    def test_call_identity_and_live_prepare_rejected(self):
        c, _ = controller("live")
        with self.assertRaises(RuntimeContractError): c.queue_call("prepare", {"block": "L0"}, call_id="p", params={"state": "0"})
        c.queue_call("syndrome_round", {"block": "L0"}, call_id="same")
        with self.assertRaises(RuntimeContractError): c.queue_call("syndrome_round", {"block": "L1"}, call_id="same")

    def test_surface17_registration_cannot_shrink_protected_data(self):
        ap, device = plan([[0, 0], [50, 1020]])
        c = LogicalBlockController(device, ap["initial_state"], run_id="bad", strategy_library=FixtureLibrary(device), fixture=True)
        with self.assertRaises(RuntimeContractError) as caught:
            c.register_block("L0", qubits={"d0": "q0", "x0": "q1"}, data_slots=["d0"],
                             code_profile={"code": "rotated_surface", "distance": 3}, layout_profile="home")
        self.assertEqual(caught.exception.code, "SURFACE17_BINDING")

    def test_delayed_ready_prevents_premature_next_call(self):
        c, _ = controller("live")
        c.queue_call("syndrome_round", {"block": "L0"}, call_id="first")
        c.queue_call("syndrome_round", {"block": "L0"}, call_id="second")
        s = make_scenario(c.pending_program(), overrides={"first/result": {"origin": "fake", "value": 0, "ready_us": 120}})
        with self.assertRaises(RuntimeContractError) as caught: c.execute_pending(s)
        self.assertEqual(caught.exception.code, "CALL_RESULT_NOT_READY")
        self.assertEqual(c.snapshot()["results"], {})

    def test_committed_batches_keep_epochs_results_and_atom_identity(self):
        c, _ = controller("live")
        for i in range(2):
            c.queue_call("syndrome_round", {"block": "L0"}, call_id=f"r{i}")
            c.execute_pending(make_scenario(c.pending_program(), value=i))
        state = c.snapshot()
        self.assertEqual(state["blocks"]["L0"]["epoch"], 2)
        self.assertEqual([c.result(f"r{i}/result")["value"] for i in range(2)], [0, 1])
        self.assertEqual(state["time_us"], 210)
        self.assertEqual(state["blocks"]["L1"]["ready_at_us"], 0)


class GroupTransferTests(unittest.TestCase):
    def test_atomic_group_transfer_and_capture_rejection(self):
        p, device = plan([[0, 0], [10, 0]])
        bindings = [dict(atom_id=f"a{i}", from_trap_id=f"slm{i}", to_trap_id=f"dynamic{i}", row_id="r0", column_id=f"c{i}", position_um=[10*i, 0]) for i in range(2)]
        p["actions"] = [action("pickup", "pickup", ["a0", "a1"], 0, 200, {"aod_group": "data", "bindings": bindings})]
        trace = run(p, make_scenario(p), device)
        self.assertTrue(all(a["carrier"] == "AOD" for a in trace["final_state"]["atoms"]))
        self.assertEqual(len(trace["events"]), 1)
        p, device = plan([[0, 0], [10, 10], [10, 0]])
        bindings[1]["row_id"] = "r1"; bindings[1]["position_um"] = [10, 10]
        p["actions"] = [action("pickup", "pickup", ["a0", "a1"], 0, 200, {"aod_group": "data", "bindings": bindings})]
        with self.assertRaises(RuntimeContractError) as caught: run(p, make_scenario(p), device)
        self.assertEqual(caught.exception.code, "PICKUP_CAPTURE_CLOSURE")

    def test_full_patch_initialization_transports_all_17_before_reset(self):
        from na_pipeline.device import grouped_device, group_layout
        device = grouped_device()
        entry, home = (group_layout(device, name)["slots"] for name in ("patch_initialization", "patch_home"))
        atoms, traps, picks, drops, trajectories = [], [], [], [], []
        for slot, location in entry.items():
            aid, src, dst, dynamic = "a:"+slot, "init:"+slot, "home:"+slot, "dynamic:"+slot
            atoms.append(dict(atom_id=aid, qubit_id="q:"+slot, position_um=location["position_um"], carrier="SLM", trap_id=src, aod_group="data", row_id=None, column_id=None))
            traps.extend([dict(trap_id=src, position_um=location["position_um"], zone_id="initialization", occupant=aid),
                          dict(trap_id=dst, position_um=home[slot]["position_um"], zone_id="storage_entanglement", occupant=None)])
            common = dict(atom_id=aid, row_id=location["row_id"], column_id=location["column_id"])
            picks.append(dict(common, from_trap_id=src, to_trap_id=dynamic, position_um=location["position_um"]))
            drops.append(dict(common, from_trap_id=dynamic, to_trap_id=dst, position_um=home[slot]["position_um"]))
            trajectories.append(dict(common, from_um=location["position_um"], to_um=home[slot]["position_um"]))
        p, _ = plan([])
        p["device_ref"] = device["artifact_id"]
        p["initial_state"].update(atoms=atoms, slm_traps=traps)
        ids = [a["atom_id"] for a in atoms]
        common = {"aod_group": "data", "group_id": "init", "purpose": "patch_initialization_transport"}
        p["actions"] = [action("pick", "pickup", ids, 0, 200, dict(common, bindings=picks)),
                        action("move", "move", ids, 200, 300, dict(common, trajectories=trajectories, interpolation="linear")),
                        action("drop", "drop", ids, 300, 500, dict(common, bindings=drops))]
        p["actions"] += [action("reset-"+aid, "reset", [aid], 500, 510, {"state": 0}) for aid in ids]
        trace = run(p, make_scenario(p), device)
        self.assertEqual(len(trace["final_state"]["atoms"]), 17)
        self.assertTrue(all(a["reset_epoch"] == 1 and a["carrier"] == "SLM" for a in trace["final_state"]["atoms"]))
        self.assertEqual(trace["final_state"]["aod_rows"], [])
        self.assertEqual(trace["stats"]["duration_us"], 510)

    def test_readout_bank_capacity_and_independent_banks(self):
        from na_pipeline.device import grouped_device
        device = grouped_device(readout_capacity=1)
        p, _ = plan([[0, 1020], [10, 1020]])
        p["device_ref"] = device["artifact_id"]
        for atom, trap in zip(p["initial_state"]["atoms"], p["initial_state"]["slm_traps"]):
            atom["position_um"][1] = 90; trap["position_um"][1] = 90
        p["actions"] = [measurement("m0", "r0", "a0"), measurement("m1", "r1", "a1")]
        for i, node in enumerate(p["actions"]): node["payload"].update(bank_id="one", site_id=f"x{i}", earliest_ready_us=0)
        with self.assertRaises(RuntimeContractError) as caught: run(p, make_scenario(p), device)
        self.assertEqual(caught.exception.code, "READOUT_PROFILE_CONFLICT")
        p["actions"][1]["payload"]["bank_id"] = "two"
        self.assertEqual(len(run(p, make_scenario(p), device)["results"]), 2)

    def test_empty_aod_intersection_cannot_sweep_spectator(self):
        p, device = plan([[0, 0], [10, 10], [10, 5]])
        for i in (0, 1):
            p["initial_state"]["atoms"][i].update(carrier="AOD", trap_id=f"dynamic{i}", row_id=f"r{i}", column_id=f"c{i}")
            p["initial_state"]["slm_traps"][i]["occupant"] = None
        p["initial_state"]["aod_rows"] = [{"aod_group": "data", "row_id": f"r{i}", "y_um": 10*i} for i in (0, 1)]
        p["initial_state"]["aod_columns"] = [{"aod_group": "data", "column_id": f"c{i}", "x_um": 10*i} for i in (0, 1)]
        trajectories = [dict(atom_id=f"a{i}", row_id=f"r{i}", column_id=f"c{i}", from_um=[10*i, 10*i], to_um=[10*i, 10*i+10]) for i in (0, 1)]
        p["actions"] = [action("sweep", "move", ["a0", "a1"], 0, 10, {"aod_group": "data", "interpolation": "linear", "trajectories": trajectories})]
        with self.assertRaises(RuntimeContractError) as caught: run(p, make_scenario(p), device)
        self.assertEqual(caught.exception.code, "AOD_INTERSECTION_SWEEP")


if __name__ == "__main__": unittest.main()
