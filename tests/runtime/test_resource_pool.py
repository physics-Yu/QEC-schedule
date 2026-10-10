import unittest

from na_pipeline.device import preinitialized_device, build_preinitialized_state
from na_pipeline.qec import physical_resource_requirements
from na_pipeline.runtime import EventSession, FiniteResourcePool, resource_inventory, make_scenario, RuntimeContractError
from test_session import window, action


class PoolTests(unittest.TestCase):
    def setUp(self):
        logical = {"patches": [{"patch_id": "w"+str(i), "initial_state": {"logical_basis": "Z", "logical_value": 0}} for i in range(5)]}
        self.req = physical_resource_requirements(logical)
        d = preinitialized_device()
        patches = {p: {k: r[k] for k in ("aod_group", "basis", "value")} for p, r in self.req["patches"].items()}
        placements = {p: {"anchor_um": [60*(i//4), 60*(i%4)], "orientation": "x_vertical_z_horizontal"} for i, p in enumerate(patches)}
        ref = {"artifact_id": "fixture:pool-placement", "producer": "R5-test", "fixture": True}
        inventory = resource_inventory(self.req, {"factory0:join_probe": [240, 0]}, placement_ref=ref)
        world = build_preinitialized_state(d, patches, placements, placement_ref=ref, resource_inventory=inventory)
        self.session = EventSession(d, world, run_id="fixture:pool")
        self.pool = FiniteResourcePool(self.req, world)

    def rejected(self, code, fn):
        with self.assertRaises(RuntimeContractError) as caught: fn()
        self.assertEqual(caught.exception.code, code)

    def test_complete_world_identity_and_s_t_mutex(self):
        self.assertEqual(len(self.pool.qubit_to_atom), 205)
        self.assertEqual(self.pool.snapshot()["initial_ready_magic_tokens"], [])
        lease = self.pool.acquire("S0", "S", "w0", self.session)
        self.assertEqual(lease["ready_magic_token"], None)
        self.rejected("POOL_RESOURCE_BUSY", lambda: self.pool.acquire("T0", "T", "w1", self.session))
        self.rejected("POOL_LEASE_IDENTITY", lambda: self.pool.acquire("S0", "S", "w0", self.session))

    def test_cleanup_requires_actual_final_resets(self):
        self.pool.acquire("S0", "S", "w0", self.session)
        qids = [q for q in self.pool.qubit_to_atom if q.startswith("factory0:Y/") or q == "factory0:join_probe"]
        self.rejected("POOL_CLEANUP_NOT_EXECUTED", lambda: self.pool.release("S0", self.session, cleanup_action_ids=["invented"], reset_qubit_ids=qids))
        aids = [self.pool.qubit_to_atom[q] for q in qids]
        p = window(self.session, [action("cleanup", "reset", aids, 0, 10, {"state": 0})])
        self.session.submit(p, make_scenario(p)); self.session.advance()
        self.pool.release("S0", self.session, cleanup_action_ids=["cleanup"], reset_qubit_ids=qids)
        self.assertFalse(self.pool.active)
        self.assertEqual(self.pool.acquire("T0", "T", "w2", self.session)["epoch"], 1)

    def test_algorithm_only_world_rejected(self):
        world = self.session.snapshot()["world_state"]
        world["atoms"] = [a for a in world["atoms"] if a["aod_group"] == "data"]
        self.rejected("POOL_CARRIER_COVERAGE", lambda: FiniteResourcePool(self.req, world))

    def test_release_waits_all_terminals_and_results_after_cleanup(self):
        self.pool.acquire("S0", "S", "w0", self.session)
        qids = [q for q in self.pool.qubit_to_atom if q.startswith("factory0:Y/") or q == "factory0:join_probe"]
        p = window(self.session, [action("cleanup", "reset", [self.pool.qubit_to_atom[q] for q in qids], 0, 10, {"state": 0}),
            action("last-data-Z", "gate", ["atom:w0/d0"], 10, 11, {"name": "Z"}),
            action("late-terminal", "wait", ["atom:w0/d1"], 10, 15, {}),
            action("delayed-output", "classical", [], 10, 11, {"operation": "fake", "writes": ["r"], "result_ready_us": 20})])
        self.session.submit(p, make_scenario(p)); self.session.advance(11)
        release = lambda: self.pool.release("S0", self.session, cleanup_action_ids=["cleanup"], reset_qubit_ids=qids)
        self.rejected("POOL_PROTOCOL_NOT_COMPLETE", release)
        self.session.advance(15)
        self.rejected("POOL_PROTOCOL_RESULTS_PENDING", release)
        self.session.advance(20)
        receipt = release()
        self.assertEqual(receipt["released_state"]["encoding_status"], "not_asserted_encoded")


if __name__ == "__main__": unittest.main()
