from copy import deepcopy
from pathlib import Path
import gzip
import json
import uuid
import unittest
from unittest.mock import patch

from na_pipeline.backend import PhysicalStrategyLibrary, place_patches, StrategyError
from na_pipeline.device import preinitialized_device
from na_pipeline.qec import build_physical_dag_bundle, materialize_physical_node
from na_pipeline.runtime import EventSession, make_scenario, bind_physical_plan
from na_pipeline.validation.dag_observer import EnolaStageObserver
from na_pipeline.backend.observation import RawCompilerObserver
from na_pipeline.backend.enola_kernel import digest
from examples.atom.t405.reuse_workload import repeated_se_workload


class PhysicalStrategyTests(unittest.TestCase):
    def setUp(self):
        self.device = preinitialized_device()
        self.logical = repeated_se_workload()
        self.bundle = build_physical_dag_bundle(self.logical)
        self.world = place_patches({"P0": {"aod_group": "data", "basis": "Z", "value": 0}}, [], self.device)["initial_state"]

    def test_real_two_se_reuses_search_not_results_and_source_binding(self):
        import na_pipeline.backend.strategy_compile as module
        session = EventSession(self.device, self.world, run_id="actual-two-SE-cache")
        library = PhysicalStrategyLibrary(self.device)
        previous, strategies = None, []
        for i, node in enumerate(self.logical["nodes"]):
            dag = materialize_physical_node(self.bundle, node["id"])
            snapshot = session.snapshot(); context = session.compilation_context(dag)
            with EnolaStageObserver(Path("third_party/enola/upstream")) as observer, patch.object(module, "group_route", wraps=module.group_route) as route:
                strategy = library.get_or_compile(dag, snapshot["world_state"])
                plan = library.bind(strategy, dag, snapshot["world_state"], execution_context=context)
            strategies.append(strategy)
            if i:
                self.assertEqual(route.call_count, 0)
                self.assertEqual(observer.evidence()["call_counts"], {})
                self.assertEqual(library.stats["routing_search_count"], previous["routing_search_count"])
                self.assertEqual(library.stats["placement_search_count"], previous["placement_search_count"])
            else:
                self.assertGreater(route.call_count, 0)
                self.assertEqual(route.call_count, library.stats["routing_search_count"])
                self.assertGreater(observer.evidence()["call_counts"]["enola/scheduler/gate_scheduler.py:gate_scheduling"], 0)
            previous = library.stats
            atom = bind_physical_plan(plan, context)
            session.submit(atom, make_scenario(atom, value=i), expected_revision=context["revision"]); session.advance()
            self.assertEqual(plan["physical_dags"], [dag])
            self.assertEqual(plan["source"]["operations"], dag["nodes"])
        self.assertEqual(strategies[0], strategies[1])
        self.assertEqual(library.stats["strategy_compile_count"], 1)
        self.assertEqual(library.stats["cache_hit_count"], 1)
        self.assertEqual([r["value"] for r in session.snapshot()["published_results"].values()], [0]*8+[1]*8)
        body = strategies[0]["body"]
        self.assertNotIn("execution_context", body["template_plan"])
        self.assertNotIn("time_us", body["template_plan"]["atom_program"]["initial_state"])
        self.assertTrue(all(d["execution_guard"] is None for d in body["canonical_dags"]))

    def test_geometry_site_and_source_tampering_do_not_silently_hit(self):
        library = PhysicalStrategyLibrary(self.device)
        session = EventSession(self.device, self.world, run_id="cache-invalidations")
        dag = materialize_physical_node(self.bundle, self.logical["nodes"][0]["id"])
        snapshot = session.snapshot(); strategy = library.get_or_compile(dag, snapshot["world_state"])
        context = session.compilation_context(dag)
        changed = deepcopy(snapshot["world_state"])
        changed["atoms"][0]["position_um"][0] += 1
        with self.assertRaises(StrategyError): library.bind(strategy, dag, changed, execution_context=context)
        corrupt = deepcopy(strategy)
        corrupt["body"]["template_plan"]["atom_program"]["actions"][0]["t_end_us"] += 1
        with self.assertRaises(StrategyError) as caught: library.bind(corrupt, dag, snapshot["world_state"], execution_context=context)
        self.assertEqual(caught.exception.code, "STRATEGY_BODY_CORRUPTED")
        rotated = deepcopy(dag); rotated["nodes"][8]["params"]["name"] = "Z"
        with self.assertRaises(StrategyError) as caught: library.bind(strategy, rotated, snapshot["world_state"], execution_context=context)
        self.assertEqual(caught.exception.code, "PHYSICAL_STRATEGY_MISS")
        # Changing a newly declared empty site cannot silently move an immutable target.
        site = next(t for t in strategy["body"]["template_plan"]["atom_program"]["initial_state"]["slm_traps"] if t["occupant"] is None)
        changed = deepcopy(snapshot["world_state"]); wrong = deepcopy(site); wrong["position_um"][0] += 1; changed["slm_traps"].append(wrong)
        # get_or_compile must use a new static-site variant or explicitly reject it.
        with self.assertRaises(StrategyError) as caught: library.get_or_compile(dag, changed)
        self.assertEqual(caught.exception.code, "READOUT_BANK_BINDING_CHANGED")
        self.assertEqual(library.stats["static_site_variant_miss_count"], 1)
        translated = deepcopy(snapshot["world_state"])
        for atom in translated["atoms"]: atom["position_um"][0] += 60.
        for trap in translated["slm_traps"]: trap["position_um"][0] += 60.
        candidate = library.get_or_compile(dag, translated)
        self.assertNotEqual(candidate["strategy_id"], strategy["strategy_id"])
        self.assertEqual(library.stats["cache_hit_count"], 0)

    def test_outer_guard_is_fresh_and_does_not_enter_cached_body(self):
        for value in (0, 1):
            logical = deepcopy(self.logical)
            bit = logical["nodes"][0]["writes"][0]
            logical["nodes"][1]["reads"] = [bit]
            logical["nodes"][1]["condition"] = {"bit": bit, "equals": 1}
            logical["edges"].append({"source": logical["nodes"][0]["id"], "target": logical["nodes"][1]["id"], "kind": "classical_ready", "result_id": bit})
            bundle = build_physical_dag_bundle(logical)
            session = EventSession(self.device, self.world, run_id="guard-cache-"+str(value))
            library = PhysicalStrategyLibrary(self.device)
            first = materialize_physical_node(bundle, logical["nodes"][0]["id"])
            snapshot = session.snapshot(); context = session.compilation_context(first)
            strategy = library.get_or_compile(first, snapshot["world_state"])
            plan = library.bind(strategy, first, snapshot["world_state"], execution_context=context)
            atom = bind_physical_plan(plan, context)
            session.submit(atom, make_scenario(atom, value=value), expected_revision=context["revision"]); session.advance()
            second = materialize_physical_node(bundle, logical["nodes"][1]["id"])
            snapshot = session.snapshot(); context = session.compilation_context(second)
            hit = library.get_or_compile(second, snapshot["world_state"])
            self.assertEqual(hit["strategy_id"], strategy["strategy_id"])
            self.assertIsNone(hit["body"]["canonical_dags"][0]["execution_guard"])
            if value == 0:
                with self.assertRaises(StrategyError) as caught:
                    library.bind(hit, second, snapshot["world_state"], execution_context=context)
                self.assertEqual(caught.exception.code, "PHYSICAL_DAG_GUARD_FALSE")
            else:
                bound = library.bind(hit, second, snapshot["world_state"], execution_context=context)
                self.assertEqual(bound["physical_dags"][0]["execution_guard"], second["execution_guard"])
                atom = bind_physical_plan(bound, context)
                session.submit(atom, make_scenario(atom, value=0), expected_revision=context["revision"]); session.advance()
            self.assertEqual(library.stats["strategy_compile_count"], 1)

    def test_saved_strategy_restores_hot_without_results_and_emits_production_evidence(self):
        out = Path("examples/atom/t405")/("restore-author-"+uuid.uuid4().hex[:8])
        session = EventSession(self.device, self.world, run_id="restore-production-cache")
        library = PhysicalStrategyLibrary(self.device, evidence_dir=out/"compiler_evidence")
        first, second = [materialize_physical_node(self.bundle, n["id"]) for n in self.logical["nodes"]]
        snapshot = session.snapshot(); context = session.compilation_context(first)
        strategy = library.get_or_compile(first, snapshot["world_state"])
        compile_file = out/strategy["compilation_evidence_ref"]["path"]
        proof = json.loads(gzip.decompress(compile_file.read_bytes()))
        self.assertTrue(proof["raw_plan_mapping"]["project_routes"])
        self.assertTrue(any(r["function"] == "maximalis_solve_sort" for r in proof["raw_observation"]["records"]))
        plan = library.bind(strategy, first, snapshot["world_state"], execution_context=context)
        atom = bind_physical_plan(plan, context)
        session.submit(atom, make_scenario(atom, value=0), expected_revision=context["revision"]); session.advance()
        saved = json.loads(json.dumps(strategy))
        restored_session = EventSession.restore(self.device, session.checkpoint())
        restored = PhysicalStrategyLibrary(self.device, evidence_dir=out/"compiler_evidence")
        current = restored_session.snapshot()
        with RawCompilerObserver(Path.cwd()) as observer:
            receipts = restored.restore_strategies([saved], current["world_state"])
            hot = restored.get_or_compile(second, current["world_state"])
        self.assertEqual(observer.evidence()["call_counts"], {})
        self.assertFalse(receipts["runtime_state_imported"])
        self.assertEqual(restored.stats["strategy_compile_count"], 0)
        self.assertEqual(restored.stats["strategy_import_count"], 1)
        self.assertEqual(hot["strategy_id"], strategy["strategy_id"])
        context = restored_session.compilation_context(second)
        bound = restored.bind(hot, second, current["world_state"], execution_context=context)
        atom = bind_physical_plan(bound, context)
        restored_session.submit(atom, make_scenario(atom, value=1), expected_revision=context["revision"]); restored_session.advance()
        self.assertEqual([r["value"] for r in restored_session.snapshot()["published_results"].values()], [0]*8+[1]*8)
        bind_proof = json.loads(gzip.decompress((out/bound["strategy_binding"]["instance_evidence_ref"]["path"]).read_bytes()))
        self.assertEqual(bind_proof["raw_observation"]["call_counts"], {})
        dirty = deepcopy(saved); dirty["results"] = {"stale": 1}
        with self.assertRaises(StrategyError) as caught: restored.import_strategy(dirty, current["world_state"])
        self.assertEqual(caught.exception.code, "STRATEGY_DYNAMIC_STATE_IMPORT")
        stale = deepcopy(saved)
        name = next(iter(stale["body"]["identity"]["compiler_sources"]))
        stale["body"]["identity"]["compiler_sources"][name] = "0"*64
        stale["strategy_hash"] = digest(stale["body"]); stale["strategy_id"] = "physical-strategy:"+stale["strategy_hash"]
        with self.assertRaises(StrategyError) as caught: restored.import_strategy(stale, current["world_state"])
        self.assertEqual(caught.exception.code, "STRATEGY_IMPORT_INCOMPATIBLE")


if __name__ == "__main__": unittest.main()
