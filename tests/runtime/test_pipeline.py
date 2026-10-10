"""Explicit one-node fixture tests the new orchestration, not full Shor."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import gzip
import json
from types import SimpleNamespace

from na_pipeline.frontend import build_patch_dag_example, patch_interaction_graph, validate_logical_dag
from na_pipeline.qec import physical_resource_requirements
from na_pipeline.qec import materialize_factory_protocol, build_factory_physical_dag
from na_pipeline.device import preinitialized_device, build_preinitialized_state
from na_pipeline.runtime import HierarchicalPipeline, resource_inventory
from na_pipeline.runtime import make_scenario
import test_session as session_fixtures


class PipelineTests(unittest.TestCase):
    def world(self):
        dag = build_patch_dag_example()
        node = deepcopy(dag["nodes"][0]); node.update(id="fixture/X0", operation="X", params={}, reads=[], writes=[], source_ids=["fixture:X0"])
        second = deepcopy(node); second.update(id="fixture/X1", source_ids=["fixture:X1"])
        dag.update(nodes=[node, second], edges=[{"source": node["id"], "target": second["id"], "kind": "quantum", "patch_id": "P0"}], result_types={}, result_producers={})
        dag["provenance"]["fixture"] = True
        dag["provenance"]["purpose"] = "repeated_X_orchestrator_test_not_algorithm_source"
        dag["patch_interaction_graph"] = patch_interaction_graph(dag)
        self.assertEqual(validate_logical_dag(dag), [])
        requirements = physical_resource_requirements(dag)
        device = preinitialized_device()
        patches = {p: {k: r[k] for k in ("aod_group", "basis", "value")} for p, r in requirements["patches"].items()}
        positions = {p: {"anchor_um": [60*(i//4), 60*(i%4)], "orientation": "x_vertical_z_horizontal"} for i, p in enumerate(patches)}
        ref = {"artifact_id": "fixture:orchestrator-placement", "producer": "R5-test", "fixture": True}
        inventory = resource_inventory(requirements, {"factory0:join_probe": [300, 0]}, placement_ref=ref)
        initial = build_preinitialized_state(device, patches, positions, placement_ref=ref, resource_inventory=inventory)
        return {"logical_dag": dag, "requirements": requirements, "device": device, "initial_state": initial,
                "patch_placement": {"provenance": {"fixture": True}, "placements": positions}}

    def test_real_compile_reuse_execute_archive_and_restore_repeated_X_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            world = self.world()
            p = HierarchicalPipeline(world, Path(directory), phase_bits=[0]*8)
            self.assertFalse(p.status()["complete_source_path"])
            result = p.step()
            self.assertEqual(result["kind"], "logical_window")
            self.assertFalse(p.status()["complete_source_path"])
            result = p.step()
            self.assertTrue(p.status()["complete_source_path"])
            self.assertEqual(p.session.export_trace()["stats"]["action_count"], 6)
            self.assertEqual(p.compiler.stats["strategy_compile_count"], 1)
            self.assertEqual(p.compiler.stats["bind_count"], 2)
            self.assertEqual(p.compiler.stats["cache_hit_count"], 1)
            self.assertEqual(p.session.export_trace()["schema_version"], "event-session-trace/0.2")
            self.assertEqual(p.scheduler.snapshot()["schema_version"], "LogicalSchedule/0.2")
            self.assertFalse(p.session.actions)
            restored = HierarchicalPipeline.restore(world, directory, p.checkpoint())
            self.assertEqual(restored.scheduler.snapshot(), p.scheduler.snapshot())
            self.assertEqual(restored.session.export_trace(), p.session.export_trace())
            self.assertTrue(restored.status()["complete_source_path"])
            self.assertFalse(restored.status()["full_program_passed"])

    def test_attempt_scenarios_bind_physical_terminal_bits_with_fresh_epochs(self):
        # Source mapping test only: no fabricated acceptance or token receipts.
        root = Path(__file__).resolve().parents[2]
        world_path = root/"examples/atom/t405/resource-world-server-v1/world.json.gz"
        if not world_path.exists(): self.skipTest("actual R4 world artifact not present")
        world = json.loads(gzip.decompress(world_path.read_bytes()))
        config = json.loads((root/"examples/scenarios/T505-reject-then-accept.json").read_bytes())
        nid = next(iter(config["requests"]))
        with tempfile.TemporaryDirectory() as directory:
            p = HierarchicalPipeline(world, directory, phase_bits=[0, 1, 0, 0, 0, 0, 0, 0], factory_scenarios=config)
            namespaces = []
            for epoch, expected in ((0, [1, 0, 0, 0]), (1, [0, 0, 0, 0])):
                protocol = materialize_factory_protocol(p.bundle, nid, epoch=epoch)
                graph = build_factory_physical_dag(protocol, "terminal_checks")
                atom = {"artifact_id": "fixture:terminal-values", "actions": [{"kind": "measure", "payload": {"result_id": op["writes"][0]}}
                        for op in graph["nodes"] if op["kind"] == "measure"]}
                p.attempt_indices[nid] = epoch
                scenario = p._factory_scenario(SimpleNamespace(protocol=protocol, stage_id="terminal_checks"), atom)
                parities = [sum(scenario["results"][r]["value"] for r in c["result_ids"]) % 2 for c in protocol["acceptance_checks"]]
                self.assertEqual(parities, expected)
                self.assertNotIn(protocol["stages"]["terminal_checks"]["branch"]["result_id"], scenario["results"])
                namespaces.append(set(scenario["results"]))
            self.assertFalse(namespaces[0] & namespaces[1])

    def test_skipped_terminal_keeps_fixed_plan_calendar_boundary(self):
        f = session_fixtures.SessionTests(); f.setUp()
        atom = session_fixtures.window(f.session, [
            session_fixtures.action("source", "classical", [], 0, 1, {"operation": "fake", "writes": ["m"], "result_ready_us": 1}),
            session_fixtures.action("last-correction", "gate", ["atom:P/d0"], 2, 3, {"name": "Z"}, {"bit": "m", "equals": 1})])
        f.session.submit(atom, make_scenario(atom, value=0))
        HierarchicalPipeline._advance_window(SimpleNamespace(session=f.session), atom)
        self.assertEqual(f.session.events["last-correction"]["status"], "skipped")
        self.assertEqual(f.session.now_us, 3)
        self.assertEqual(f.session.completed["last-correction"], 2)


if __name__ == "__main__": unittest.main()
