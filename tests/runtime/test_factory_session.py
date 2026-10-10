import unittest

from na_pipeline.qec import build_factory15to1_protocol
from na_pipeline.runtime import FactoryExecution, RuntimeContractError, LogicalListScheduler
import test_resource_pool as pool_fixture


class FactorySessionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = pool_fixture.PoolTests(); self.fixture.setUp()
        self.protocol = build_factory15to1_protocol(data_block_id="w0", request_id="test-request", epoch=0)
        self.controller = FactoryExecution(self.protocol, self.fixture.pool, self.fixture.session, owner="T0")

    def test_real_recipe_starts_without_tokens_and_retains_all_spectators(self):
        graph = self.controller.next_graph()
        self.assertEqual(graph["protocol_binding"]["stage_id"], "initialize")
        self.assertEqual(len(self.controller.pool.qubit_to_atom), 205)
        self.assertEqual(len(self.protocol["qubits"]), 137)
        self.assertIsNone(self.controller.token)
        with self.assertRaises(RuntimeContractError) as caught: self.controller.advance_lifecycle()
        self.assertEqual(caught.exception.code, "FACTORY_NOT_LIFECYCLE")

    def test_full_recipe_checkpoint_does_not_mint_token_or_reset_epoch(self):
        self.controller.next_graph()
        restored = FactoryExecution.restore(self.fixture.session.device, self.controller.checkpoint())
        self.assertEqual(restored.snapshot(), self.controller.snapshot())
        self.assertEqual(restored.next_graph(), self.controller.next_graph())
        self.assertEqual(restored.pool.next_epoch, 1)
        with self.assertRaises(RuntimeContractError) as caught:
            FactoryExecution(self.protocol, restored.pool, restored.session, owner="T1")
        self.assertEqual(caught.exception.code, "FACTORY_EPOCH")

    def test_unexecuted_or_replaced_stage_is_rejected(self):
        graph = self.controller.next_graph()
        with self.assertRaises(RuntimeContractError) as caught:
            self.controller.commit_stage({"physical_dags": [dict(graph, nodes=[])]}, {})
        self.assertEqual(caught.exception.code, "FACTORY_STAGE_DAG")
        self.assertFalse(self.controller.receipts)
        self.assertIsNone(self.controller.accepted)

    def test_prefetched_raw_magic_requires_same_epoch_committed_producer(self):
        self.controller.stage_id='rotate_05'
        with self.assertRaises(RuntimeContractError) as caught:self.controller.next_graph()
        self.assertEqual(caught.exception.code,'FACTORY_PREPARED_INPUT_MISSING')
        self.controller.receipts=[{'stage_id':'finish_04','epoch':99,'prepared_magic_output':{'raw_input_index':5}}]
        with self.assertRaises(RuntimeContractError) as caught:self.controller.next_graph()
        self.assertEqual(caught.exception.code,'FACTORY_PREPARED_INPUT_MISSING')

    def test_adaptive_logical_node_cannot_complete_from_one_stage_or_empty_token(self):
        node = {"id": "logical/T0", "operation": "T", "patch_operands": {"block": "w0"},
                "source_ids": ["test:logical-source"], "reads": [], "writes": [], "condition": None}
        scheduler = LogicalListScheduler({"entry_mode": "preinitialized", "nodes": [node], "edges": []}, {})
        protocol = dict(self.protocol, logical_binding={"logical_node_id": node["id"]})
        scheduler.begin_protocol(node["id"], protocol, self.controller.lease)
        self.assertIsNone(scheduler.states[node["id"]]["reserved_end_us"])
        with self.assertRaises(RuntimeContractError) as caught:
            scheduler.complete(node["id"], {"node_id": node["id"], "completed_us": 0, "event_trace_ref": "fake", "physical_plan_ref": "fake"})
        self.assertEqual(caught.exception.code, "ADAPTIVE_COMPLETION_REQUIRED")
        with self.assertRaises(RuntimeContractError) as caught:
            scheduler.complete_protocol(node["id"], self.controller.snapshot())
        self.assertEqual(caught.exception.code, "PROTOCOL_NOT_CONSUMED")
        self.assertFalse(scheduler.snapshot()["complete"])

    def test_retry_boundary_fixture_requires_cleanup_and_fresh_epoch(self):
        # This exercises scheduler receipt guards only; it is not a fabricated
        # successful physical factory run and produces no accepted token.
        from copy import deepcopy
        node = {"id": "logical/T0", "operation": "T", "patch_operands": {"block": "w0"},
                "source_ids": ["test:retry-boundary"], "reads": [], "writes": [], "condition": None}
        scheduler = LogicalListScheduler({"entry_mode": "preinitialized", "nodes": [node], "edges": []}, {})
        protocol = dict(self.protocol, logical_binding={"logical_node_id": node["id"]})
        scheduler.begin_protocol(node["id"], protocol, self.controller.lease)
        rejected = self.controller.snapshot(); rejected["terminal"] = "rejected"
        next_protocol = dict(protocol, artifact_id="fixture-next-protocol", epoch=1)
        lease = dict(self.controller.lease, epoch=1)
        with self.assertRaises(RuntimeContractError) as caught:
            scheduler.retry_protocol(node["id"], next_protocol, lease, rejected, ledger_ref={"fixture": True})
        self.assertEqual(caught.exception.code, "PROTOCOL_RETRY_BEFORE_CLEANUP")
        rejected["pool"]["active_leases"] = {}
        stale = dict(next_protocol, epoch=0)
        with self.assertRaises(RuntimeContractError) as caught:
            scheduler.retry_protocol(node["id"], stale, lease, rejected, ledger_ref={"fixture": True})
        self.assertEqual(caught.exception.code, "PROTOCOL_RETRY_BINDING")
        scheduler.retry_protocol(node["id"], next_protocol, lease, rejected, ledger_ref={"fixture": True})
        self.assertEqual(scheduler.states[node["id"]]["status"], "running")
        self.assertEqual(scheduler.states[node["id"]]["epoch"], 1)
        self.assertFalse(scheduler.snapshot()["complete"])


if __name__ == "__main__": unittest.main()
