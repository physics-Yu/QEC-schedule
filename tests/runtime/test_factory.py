"""T502 protocol fixtures: deliberately NOT a physical 15-to-1 factory."""

from copy import deepcopy
import unittest

from na_pipeline.runtime import FactoryLedger, RuntimeContractError, run, make_scenario
from na_pipeline.device import default_device
from test_runtime import plan, action, measurement


def boundary(kind, time_us, **fields):
    return {"id": fields.pop("id", kind), "kind": kind, "time_us": time_us, "after": fields.pop("after", []), **fields}


def specification():
    return {"schema_version": "FactorySpecification/0.1.0-draft", "fixture": True,
            "factory_id": "fixture-factory", "protocol_ref": "fixture/minimal-action-witnesses-NOT-15-to-1",
            "factory_atom_ids": ["a0", "a1"], "cleanup_atom_ids": ["a0", "a1"]}


def accepted_fixture(reset_live_after=False):
    p, device = plan([[0, 0], [50, 1020], [12, 0]])
    traps = p["initial_state"]["slm_traps"]
    traps.extend([{"trap_id": "delivery", "position_um": [10, 0], "zone_id": "storage_entanglement", "occupant": None},
                  {"trap_id": "output_readout", "position_um": [10, 1020], "zone_id": "measurement", "occupant": None}])
    binding = {"aod_group": "data", "row_id": "r0", "column_id": "c0"}

    def transfer(aid, kind, t0, t1, src, dst, xy):
        return action(aid, kind, ["a0"], t0, t1, dict(binding, from_trap_id=src, to_trap_id=dst, position_um=xy))

    def motion(aid, t0, t1, src, dst):
        return action(aid, "move", ["a0"], t0, t1, {"aod_group": "data", "interpolation": "linear", "trajectories": [dict(atom_id="a0", row_id="r0", column_id="c0", from_um=src, to_um=dst)]})

    p["actions"] = [action("prep", "gate", ["a0"], 0, 1, {"name": "H"}),
                    measurement("check", "attempt1/check", "a1"),
                    transfer("pick", "pickup", 106, 306, "slm0", "dynamic", [0, 0]),
                    motion("move", 306, 316, [0, 0], [10, 0]),
                    transfer("drop", "drop", 316, 516, "dynamic", "delivery", [10, 0]),
                    action("couple", "gate", ["a0", "a2"], 516, 517, {"name": "CZ", "broadcast": True, "zone_id": "storage_entanglement", "pairs": [["a0", "a2"]]}),
                    transfer("pick_readout", "pickup", 517, 717, "delivery", "dynamic", [10, 0]),
                    motion("move_readout", 717, 1737, [10, 0], [10, 1020]),
                    transfer("drop_readout", "drop", 1737, 1937, "dynamic", "output_readout", [10, 1020]),
                    measurement("out", "attempt1/consume", "a0", t0=1937),
                    action("correction", "gate", ["a2"], 2043, 2044, {"name": "X"}, condition={"bit": "attempt1/consume", "equals": 1}),
                    action("reset_out", "reset", ["a0"], 2044, 2054, {"state": 0}),
                    action("reset_check", "reset", ["a1"], 2044, 2054, {"state": 0})]
    if reset_live_after:
        p["actions"].append(action("algorithm_reset", "reset", ["a2"], 2054, 2064, {"state": 0}))
    for node in p["actions"]:
        if node["t_start_us"] >= 106:
            node["t_start_us"] += 1
            node["t_end_us"] += 1
            if "result_ready_us" in node["payload"]:
                node["payload"]["result_ready_us"] += 1
    p["actions"].append(action("phase_conversion", "gate", ["a0"], 106, 107, {"name": "S"}))
    trace = run(p, make_scenario(p, overrides={"attempt1/consume": 1}), device)
    events = [boundary("request", 0, request_id="T0", resource_kind="T", live_data_atom_ids=["a2"], live_block_atom_ids=["a2"]),
              boundary("begin", 0, request_id="T0", attempt_id="try1", epoch=0, candidate_id="candidate1", output_atom_ids=["a0"], output_data_atom_ids=["a0"], production_action_ids=["prep", "check"]),
              boundary("decide", 106, after=["prep", "check"], output_id="output1", acceptance_checks=[{"id": "fixture-check", "result_ids": ["attempt1/check"], "expected_parity": 0}]),
              boundary("make_ready", 107, request_id="T0", output_id="output1", phase_conversion_action_ids=["phase_conversion"]),
              boundary("reserve", 107, request_id="T0", output_id="output1"),
              boundary("deliver", 517, after=["pick", "move", "drop"], delivery_mode="transport", request_id="T0", output_id="output1", output_atom_ids=["a0"]),
              boundary("consume_begin", 517, request_id="T0", output_id="output1"),
              boundary("consume_finish", 2045, request_id="T0", output_id="output1", consumption_action_ids=["couple", "out", "correction"]),
              boundary("cleanup", 2055, attempt_id="try1", reset_action_ids=["reset_out", "reset_check"])]
    return p, trace, events


def rejected_fixture():
    p, device = plan([[0, 0], [50, 1020], [12, 0]])
    p["actions"] = [action("prep1", "gate", ["a0"], 0, 1, {"name": "H"}), measurement("check1", "attempt1/check", "a1"),
                    action("reset0", "reset", ["a0"], 106, 116, {"state": 0}), action("reset1", "reset", ["a1"], 106, 116, {"state": 0}),
                    action("prep2", "gate", ["a0"], 116, 117, {"name": "H"}), measurement("check2", "attempt2/check", "a1", t0=116),
                    action("ready_wait", "wait", [], 222, 223)]
    trace = run(p, make_scenario(p, overrides={"attempt1/check": 1}), device)
    events = [boundary("request", 0, request_id="T0", resource_kind="T", live_data_atom_ids=["a2"], live_block_atom_ids=["a2"]),
              boundary("begin", 0, request_id="T0", attempt_id="try1", epoch=0, candidate_id="candidate1", output_atom_ids=["a0"], output_data_atom_ids=["a0"], production_action_ids=["prep1", "check1"]),
              boundary("decide", 106, output_id="output1", acceptance_checks=[{"id": "fixture-check", "result_ids": ["attempt1/check"], "expected_parity": 0}]),
              boundary("cleanup", 116, attempt_id="try1", reset_action_ids=["reset0", "reset1"]),
              boundary("begin", 116, id="begin2", request_id="T0", attempt_id="try2", epoch=1, candidate_id="candidate2", output_atom_ids=["a0"], output_data_atom_ids=["a0"], production_action_ids=["prep2", "check2"]),
              boundary("decide", 222, id="decide2", output_id="output2", acceptance_checks=[{"id": "fixture-check", "result_ids": ["attempt2/check"], "expected_parity": 0}])]
    return p, trace, events


class FactoryTests(unittest.TestCase):
    def setup_ledger(self, prefix=0, rejected=False, reset_live_after=False):
        p, trace, events = rejected_fixture() if rejected else accepted_fixture(reset_live_after)
        ledger = FactoryLedger(p, trace, specification())
        for event in events[:prefix]:
            ledger.apply(event)
        return ledger, events

    def fail_atomic(self, ledger, event, code):
        before = ledger.snapshot()
        with self.assertRaises(RuntimeContractError) as caught:
            ledger.apply(event)
        self.assertEqual(caught.exception.code, code, caught.exception.to_dict())
        self.assertEqual(ledger.snapshot(), before)

    def test_accept_deliver_consume_cleanup_same_carrier(self):
        ledger, events = self.setup_ledger()
        for event in events:
            ledger.apply(event)
        snapshot = ledger.snapshot()
        self.assertFalse(snapshot["physical_factory_executed"])
        self.assertEqual(snapshot["state"]["phase"], "idle")
        self.assertEqual(snapshot["state"]["requests"]["T0"]["status"], "fulfilled")
        output = snapshot["state"]["outputs"]["output1"]
        self.assertEqual((output["status"], output["carrier_atom_ids"], output["epoch"]), ("consumed", ["a0"], 0))
        self.assertEqual(snapshot["state"]["requests"]["T0"]["live_identity"]["a2"]["reset_epoch"], 0)

    def test_reject_cleanup_retry_fresh_results(self):
        ledger, events = self.setup_ledger(rejected=True)
        for event in events:
            ledger.apply(event)
        state = ledger.snapshot()["state"]
        self.assertEqual((state["phase"], state["epoch"]), ("candidate", 1))
        self.assertFalse(state["attempts"]["try1"]["accepted"])
        self.assertTrue(state["attempts"]["try2"]["accepted"])
        self.assertNotIn("output1", state["outputs"])

    def test_ready_output_applies_backpressure(self):
        ledger, events = self.setup_ledger(4)
        new = dict(events[1], id="begin2", time_us=107, epoch=1)
        self.fail_atomic(ledger, new, "FACTORY_BACKPRESSURE")

    def test_fake_decision_cannot_read_future(self):
        ledger, events = self.setup_ledger(2)
        event = dict(events[2], time_us=100)
        self.fail_atomic(ledger, event, "FACTORY_RESULT_NOT_READY")

    def test_no_old_measurement_result_reuse_on_retry(self):
        ledger, events = self.setup_ledger(5, rejected=True)
        event = deepcopy(events[5]); event["acceptance_checks"][0]["result_ids"] = ["attempt1/check"]
        self.fail_atomic(ledger, event, "FACTORY_RESULT_REUSE")

    def test_old_epoch_cannot_start_retry(self):
        ledger, events = self.setup_ledger(4, rejected=True)
        self.fail_atomic(ledger, dict(events[4], epoch=0), "FACTORY_EPOCH")

    def test_token_cannot_be_reserved_or_consumed_twice(self):
        ledger, events = self.setup_ledger(8)
        self.fail_atomic(ledger, dict(events[4], id="reserve-again", time_us=2045), "FACTORY_OUTPUT_STATE")
        self.fail_atomic(ledger, dict(events[7], id="consume-again"), "FACTORY_OUTPUT_STATE")

    def test_wrong_live_data_request_and_output_carrier(self):
        ledger, events = self.setup_ledger(4)
        self.fail_atomic(ledger, dict(events[4], request_id="T-other"), "FACTORY_REQUEST_OUTPUT_MISMATCH")
        ledger.apply(events[4])
        self.fail_atomic(ledger, dict(events[5], output_atom_ids=["a1"]), "FACTORY_DELIVERY_CARRIER_MISMATCH")

    def test_cleanup_requires_every_physical_reset(self):
        ledger, events = self.setup_ledger(3, rejected=True)
        self.fail_atomic(ledger, dict(events[3], reset_action_ids=["reset0"]), "FACTORY_INCOMPLETE_CLEANUP")

    def test_cleanup_must_not_claim_live_data_reset(self):
        ledger, events = self.setup_ledger(8, reset_live_after=True)
        event = dict(events[8], time_us=2065, reset_action_ids=["reset_out", "reset_check", "algorithm_reset"])
        self.fail_atomic(ledger, event, "FACTORY_CLEANUP_LIVE_DATA")

    def test_historical_rewrite_and_future_commit_rejected(self):
        ledger, events = self.setup_ledger(4)
        self.fail_atomic(ledger, dict(events[4], time_us=105), "FACTORY_COMMITTED_BOUNDARY")
        self.fail_atomic(ledger, dict(events[4], time_us=9999), "FACTORY_COMMITTED_BOUNDARY")

    def test_consumption_requires_coupling_and_readout(self):
        ledger, events = self.setup_ledger(7)
        self.fail_atomic(ledger, dict(events[7], consumption_action_ids=["out"]), "FACTORY_CONSUMPTION_COUPLING")
        self.fail_atomic(ledger, dict(events[7], consumption_action_ids=["couple"]), "FACTORY_CONSUMPTION_READOUT")

    def test_physical_cross_coupling_before_submission_rejected(self):
        ledger, events = self.setup_ledger(6)
        # Let the physical coupling finish before submitting the output token.
        self.fail_atomic(ledger, dict(events[6], time_us=518), "FACTORY_EARLY_COUPLING")

    def test_acceptance_is_not_ready_before_phase_conversion(self):
        ledger, events = self.setup_ledger(3)
        self.assertEqual(ledger.snapshot()["state"]["phase"], "candidate")
        self.fail_atomic(ledger, dict(events[4], time_us=106), "FACTORY_OUTPUT_STATE")

    def test_scheduling_handoff_does_not_claim_physical_motion(self):
        ledger, events = self.setup_ledger(5)
        handoff = dict(events[5], time_us=107, after=[], delivery_mode="handoff")
        result = ledger.apply(handoff)
        self.assertEqual(result["state"]["outputs"]["output1"]["delivery_mode"], "handoff")

    def test_live_data_reset_is_forbidden_during_request(self):
        p, _, events = accepted_fixture()
        p["actions"].append(action("illegal_live_reset", "reset", ["a2"], 1, 11, {"state": 0}))
        trace = run(p, make_scenario(p), default_device())
        ledger = FactoryLedger(p, trace, specification())
        ledger.apply(events[0]); ledger.apply(events[1])
        self.fail_atomic(ledger, events[2], "FACTORY_LIVE_DATA_CHANGED")

    def test_output_syndrome_carrier_may_reset_but_identity_is_retained(self):
        p, _, events = accepted_fixture()
        p["actions"].append(action("syndrome_reset", "reset", ["a1"], 107, 117, {"state": 0}))
        trace = run(p, make_scenario(p), default_device())
        ledger = FactoryLedger(p, trace, specification())
        events[1]["output_atom_ids"] = ["a0", "a1"]
        events[5]["output_atom_ids"] = ["a0", "a1"]
        for event in events:
            ledger.apply(event)
        output = ledger.snapshot()["state"]["outputs"]["output1"]
        self.assertEqual(output["carrier_atom_ids"], ["a0", "a1"])
        self.assertEqual(output["data_atom_ids"], ["a0"])

    def test_nonfixture_use_is_closed_and_trace_hash_is_bound(self):
        p, trace, events = accepted_fixture()
        spec = specification(); spec["fixture"] = False
        with self.assertRaises(RuntimeContractError) as caught:
            FactoryLedger(p, trace, spec)
        self.assertEqual(caught.exception.code, "FACTORY_PROTOCOL_NOT_INTEGRATED")
        p["artifact_id"] += "-other"
        with self.assertRaises(RuntimeContractError) as caught:
            FactoryLedger(p, trace, specification())
        self.assertEqual(caught.exception.code, "FACTORY_TRACE_BINDING")


if __name__ == "__main__":
    unittest.main()
