"""Persistent frontier regressions; fixture classical sources are explicit."""
from copy import deepcopy
import unittest

from na_pipeline.device import preinitialized_device, build_preinitialized_state
from na_pipeline.runtime import EventSession, RuntimeContractError, make_scenario, bind_physical_plan
from na_pipeline.runtime.engine import digest


def action(aid, kind, atoms, start, end, payload, condition=None):
    return dict(id=aid, kind=kind, atoms=atoms, t_start_us=start, t_end_us=end,
                resources=[], depends_on=[], source_ids=["fixture:"+aid], payload=payload, condition=condition)


def window(session, actions):
    return dict(schema_version="AtomProgram/0.2.0-draft", artifact_id="fixture-window:"+digest(actions),
                provenance={"fixture": True}, execution_kind="compile_plan", complete=True,
                quantum_state_simulated=False, hardware_executed=False, loss_enabled=False,
                device_ref=session.device["artifact_id"], initial_state=session.snapshot()["world_state"],
                actions=actions, source_map={a["source_ids"][0]: [a["id"]] for a in actions})


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.device = preinitialized_device()
        self.world = build_preinitialized_state(self.device, {"P": {"aod_group": "data", "basis": "Z", "value": 0}},
            {"P": {"anchor_um": [0, 0], "orientation": "x_vertical_z_horizontal"}},
            placement_ref={"artifact_id": "fixture:placement", "producer": "R5-test", "fixture": True})
        self.session = EventSession(self.device, self.world, run_id="fixture-session")

    def reject(self, code, fn):
        with self.assertRaises(RuntimeContractError) as caught: fn()
        self.assertEqual(caught.exception.code, code, caught.exception.to_dict())

    def producer(self, value=1):
        p = window(self.session, [action("source", "classical", [], 0, 1,
            {"operation": "fake", "writes": ["m"], "result_ready_us": 2})])
        scenario = make_scenario(p, value=value, overrides={"m": {"value": value, "origin": "fake", "ready_us": 9}})
        self.session.submit(p, scenario)

    def test_delayed_publication_and_continuation_both_conditions(self):
        for value in (0, 1):
            self.setUp(); self.producer(value)
            self.assertFalse(self.session.results)
            self.session.advance(8)
            self.assertFalse(self.session.results)
            self.assertEqual(self.session.completed, {"source": 1})
            self.session.advance(9)
            p = window(self.session, [action("feedback", "gate", ["atom:P/d0"], 10, 11,
                {"name": "X", "params": {}}, {"bit": "m", "equals": 1})])
            self.session.submit(p, make_scenario(p)); self.session.advance()
            trace = self.session.export_trace()
            self.assertEqual(trace["events"][-1]["status"], "completed" if value else "skipped")
            self.assertEqual(trace["results"]["m"]["available_us"], 9)
            self.assertTrue(trace["complete_submitted_prefix"])
            self.assertFalse(trace["full_program_complete"])

    def test_checkpoint_preserves_pending_values_and_active_resources(self):
        self.producer()
        self.session.advance(.5)
        checkpoint = self.session.checkpoint()
        restored = EventSession.restore(self.device, checkpoint)
        self.assertEqual(restored.snapshot(), self.session.snapshot())
        self.session.advance(); restored.advance()
        self.assertEqual(restored.export_trace(), self.session.export_trace())
        bad = deepcopy(checkpoint); bad["body"]["configured"]["m"]["value"] = 0
        self.reject("SESSION_CHECKPOINT_HASH", lambda: EventSession.restore(self.device, bad))

    def test_inflight_other_atom_new_window_and_conflict(self):
        p = window(self.session, [action("long", "wait", ["atom:P/d0"], 0, 20, {})])
        self.session.submit(p, make_scenario(p)); self.session.advance(3)
        p = window(self.session, [action("short", "gate", ["atom:P/d1"], 3, 4, {"name": "X", "params": {}})])
        self.session.submit(p, make_scenario(p)); self.session.advance(4)
        self.assertIn("long", self.session.snapshot()["in_flight"])
        p = window(self.session, [action("collision", "gate", ["atom:P/d0"], 4, 5, {"name": "X", "params": {}})])
        self.session.submit(p, make_scenario(p))
        self.reject("RESOURCE_CONFLICT", self.session.advance)
        self.assertTrue(self.session.failure["prefix_preserved"])
        self.assertIn("short", self.session.completed)

    def test_missing_fake_and_early_feedback_are_explicit(self):
        p = window(self.session, [action("source", "classical", [], 0, 1, {"operation": "fake", "writes": ["m"], "result_ready_us": 1})])
        scenario = make_scenario(p); scenario["results"].clear()
        self.session.submit(p, scenario)
        self.reject("MISSING_FAKE_RESULT", self.session.advance)
        self.setUp(); self.producer(); self.session.advance(9)
        p = window(self.session, [action("read", "gate", ["atom:P/d0"], 9, 10, {"name": "X"}, {"bit": "m", "equals": 1})])
        self.session.submit(p, make_scenario(p))
        self.reject("FEEDBACK_TOO_EARLY", self.session.advance)

    def test_frontier_rejects_teleport_carrier_growth_line_reset_and_stale(self):
        p = window(self.session, [action("x", "gate", ["atom:P/d0"], 0, 1, {"name": "X"})])
        bad = deepcopy(p); bad["initial_state"]["atoms"][0]["position_um"][0] += 10
        self.reject("SESSION_ENTRY_MISMATCH", lambda: self.session.submit(bad, make_scenario(bad)))
        bad = deepcopy(p); bad["initial_state"]["atoms"].pop()
        self.reject("SESSION_CARRIER_SET", lambda: self.session.submit(bad, make_scenario(bad)))
        bad = deepcopy(p); bad["initial_state"]["aod_rows"].append({"aod_group": "data", "row_id": "x", "y_um": 0})
        self.reject("SESSION_ENTRY_LINES", lambda: self.session.submit(bad, make_scenario(bad)))
        self.session.advance(1)
        self.reject("STALE_SESSION_FRONTIER", lambda: self.session.submit(p, make_scenario(p), expected_revision=0))

    def test_context_uses_published_source_and_preserves_guard(self):
        self.producer(0)
        dag = {"artifact_id": "fixture-dag", "external_reads": ["m"], "execution_guard": {"bit": "m", "equals": 1}}
        self.reject("RESULT_NOT_READY", lambda: self.session.compilation_context(dag))
        self.session.advance(9)
        ctx = self.session.compilation_context(dag)
        self.assertEqual(ctx["graph_decisions"]["fixture-dag"]["decision"], "skip")
        self.assertEqual(ctx["published_results"]["m"]["producer_ref"]["action_id"], "source")
        self.assertEqual(ctx["graph_decisions"]["fixture-dag"]["execution_guard"], dag["execution_guard"])

    def test_time_binding_once_and_snapshot_hash(self):
        self.session.advance(17)
        dag = {"artifact_id": "fixture-dag"}; ctx = self.session.compilation_context(dag)
        p = window(self.session, [action("x", "gate", ["atom:P/d0"], 0, 1, {"name": "X", "params": {"angle": .5}})])
        plan = {"schema_version": "physical-plan/0.1", "atom_program": p,
                "input_hashes": {"device": ctx["device_hash"], "world_state": ctx["world_state_hash"], "physical_dags": [digest(dag)]}}
        absolute = bind_physical_plan(plan, ctx)
        self.assertEqual(absolute["actions"][0]["t_start_us"], 17)
        self.assertEqual(plan["atom_program"]["actions"][0]["t_start_us"], 0)
        self.reject("WINDOW_ALREADY_BOUND", lambda: bind_physical_plan(dict(plan, atom_program=absolute), ctx))
        self.session.submit(absolute, make_scenario(absolute)); self.session.advance()
        self.assertEqual(self.session.now_us, 18)
        self.reject("STALE_SESSION_FRONTIER", lambda: self.session.submit(absolute, make_scenario(absolute)))

    def test_r0_false_guard_context_tamper_rejected_with_same_frontier(self):
        self.producer(0); self.session.advance(9)
        dag = {"artifact_id": "fixture-dag", "external_reads": ["m"], "execution_guard": {"bit": "m", "equals": 1}}
        context = self.session.compilation_context(dag)
        p = window(self.session, [action("wrong-branch", "gate", ["atom:P/d0"], 2, 3, {"name": "X", "reads": ["m"]})])
        plan = {"schema_version": "physical-plan/0.1", "atom_program": p,
                "input_hashes": {"device": context["device_hash"], "world_state": context["world_state_hash"], "physical_dags": [digest(dag)]}}
        changed = deepcopy(context); changed["published_results"]["m"]["value"] = 1
        changed["graph_decisions"]["fixture-dag"]["decision"] = "execute"
        absolute = bind_physical_plan(plan, changed)
        before = self.session.snapshot()
        self.reject("SESSION_CONTEXT_RESULT", lambda: self.session.submit(absolute, make_scenario(absolute)))
        self.assertEqual(before, self.session.snapshot())
        self.assertNotIn("wrong-branch", self.session.actions)
        for field, value in (("action_id", "invented"), ("ready_us", 0), ("origin", "sampled")):
            bad = deepcopy(context); bad["published_results"]["m"][field] = value
            self.reject("SESSION_CONTEXT_RESULT", lambda: self.session.validate_context(bad))
        bad = deepcopy(context); bad["graph_decisions"]["fixture-dag"]["result_refs"]["m"]["action_id"] = "invented"
        self.reject("SESSION_CONTEXT_DECISION", lambda: self.session.validate_context(bad))
        bad = deepcopy(context); bad["graph_decisions"]["fixture-dag"]["execution_guard"]["equals"] = 0
        bad["graph_decisions"]["fixture-dag"]["decision"] = "execute"
        self.reject("SESSION_CONTEXT_NOT_ISSUED", lambda: self.session.validate_context(bad))

    def test_deferred_runtime_draft_cannot_bind(self):
        context = self.session.compilation_context({"artifact_id": "draft"})
        self.reject("WINDOW_RUNTIME_INPUTS_UNRESOLVED", lambda: bind_physical_plan(
            {"schema_version": "physical-plan/0.1", "atom_program": {"complete": False}}, context))

    def test_deferred_complete_flag_and_direct_production_submit_rejected(self):
        p = window(self.session, [action("bad", "gate", ["atom:P/d0"], 0, 1, {"name": "X"})])
        p["provenance"].update(backend_used="enola_ready_scheduler_and_constrained_router", requires_runtime_binding=True)
        p["complete"] = True
        self.reject("SESSION_RUNTIME_INPUTS_UNRESOLVED", lambda: self.session.submit(p, make_scenario(p)))
        del p["provenance"]["requires_runtime_binding"]
        self.reject("SESSION_BINDING_REQUIRED", lambda: self.session.submit(p, make_scenario(p)))
        self.assertNotIn("bad", self.session.actions)

    def test_postprocess_uses_published_bits_and_keeps_failure(self):
        for bits, expected in (([0, 1, 0, 0, 0, 0, 0, 0], [3, 5]), ([0]*8, [])):
            self.setUp(); names = [f"phase[{i}]" for i in range(8)]
            p = window(self.session, [action(f"source{i}", "classical", [], 0, 1,
                {"operation": "fake", "writes": [r], "result_ready_us": 1}) for i, r in enumerate(names)])
            self.session.submit(p, make_scenario(p, overrides=dict(zip(names, bits)))); self.session.advance()
            p = window(self.session, [action("postprocess", "classical", [], 2, 3,
                {"operation": "postprocess_phase", "reads": names, "writes": ["report"], "result_ready_us": 3,
                 "params": {"N": 15, "a": 2, "bits_msb_first": names}})])
            self.session.submit(p, make_scenario(p)); self.session.advance()
            record = self.session.results["report"]["value"]
            self.assertEqual(record["input_bits_msb_first"], bits)
            self.assertEqual(record["factors"], expected)
            self.assertEqual(record["status"], "success" if expected else "failed")


if __name__ == "__main__": unittest.main()
