"""D05: real same-session nonzero-time binding with published-result guards."""
from copy import deepcopy
import unittest

from na_pipeline.backend import place_patches, compile_physical_dag, StrategyError
from na_pipeline.device import preinitialized_device
from na_pipeline.qec import build_patch_operation_spec
from na_pipeline.runtime import make_scenario, bind_physical_plan, RuntimeContractError
from na_pipeline.runtime.session import EventSession


class PlanBindingTests(unittest.TestCase):
    def setUp(self):
        self.device = preinitialized_device()
        self.world = place_patches({"block": {"aod_group": "data", "basis": "Z", "value": 0}}, [], self.device)["initial_state"]

    def first_window(self, value=1, delayed=False):
        session = EventSession(self.device, self.world, run_id="d05-test")
        snapshot = session.snapshot()
        dag = build_patch_operation_spec("SE")["physical_dag"]
        context = session.compilation_context(dag)
        relative = compile_physical_dag(dag, self.device, snapshot["world_state"], execution_context=context)
        bound = bind_physical_plan(relative, context)
        scenario = make_scenario(bound, value=value)
        bit = next(iter(relative["result_ready_offsets_us"]))
        if delayed:
            scenario["results"][bit]["ready_us"] = bound["stats"]["t_end_us"] + 100
        session.submit(bound, scenario, expected_revision=snapshot["revision"])
        if delayed: session.advance(bound["stats"]["t_end_us"])
        else: session.advance()
        return session, bit

    def conditional_plan(self, session, bit):
        dag = build_patch_operation_spec("X")["physical_dag"]
        # A labeled guard fixture surrounds a real R3 X physical graph. The
        # guard value itself comes exclusively from the running real session.
        dag["provenance"]["fixture"] = True
        dag["execution_guard"] = {"bit": bit, "equals": 1}
        dag["external_reads"] = [bit]
        return dag

    def test_nonzero_second_window_published_true_and_once(self):
        session, bit = self.first_window()
        completed_before = session.export_trace()["stats"]["completed_action_count"]
        dag = self.conditional_plan(session, bit)
        snapshot = session.snapshot(); context = session.compilation_context(dag)
        plan = compile_physical_dag(dag, self.device, snapshot["world_state"], execution_context=context)
        bound = bind_physical_plan(plan, context)
        self.assertGreater(bound["session_binding"]["time_origin_us"], 0)
        self.assertTrue(all(a["t_start_us"] >= snapshot["time_us"] for a in bound["actions"]))
        session.submit(bound, make_scenario(bound, value=1), expected_revision=snapshot["revision"])
        session.advance()
        self.assertEqual(session.export_trace()["stats"]["completed_action_count"], completed_before + len(bound["actions"]))
        with self.assertRaises(RuntimeContractError): bind_physical_plan({**plan, "atom_program": bound}, context)

    def test_false_guard_has_no_physical_actions(self):
        session, bit = self.first_window(value=0)
        dag = self.conditional_plan(session, bit)
        context = session.compilation_context(dag)
        self.assertEqual(context["graph_decisions"][dag["artifact_id"]]["decision"], "skip")
        with self.assertRaises(StrategyError) as caught:
            compile_physical_dag(dag, self.device, session.snapshot()["world_state"], execution_context=context)
        self.assertEqual(caught.exception.code, "PHYSICAL_DAG_GUARD_FALSE")

    def test_delayed_result_and_stale_world_rejected(self):
        session, bit = self.first_window(delayed=True)
        dag = self.conditional_plan(session, bit); snapshot = session.snapshot()
        self.assertNotIn(bit, snapshot["published_results"])
        with self.assertRaises(RuntimeContractError): session.compilation_context(dag)
        session.advance()
        snapshot = session.snapshot(); context = session.compilation_context(dag)
        plan = compile_physical_dag(dag, self.device, snapshot["world_state"], execution_context=context)
        bound = bind_physical_plan(plan, context)
        self.assertGreaterEqual(min(a["t_start_us"] for a in bound["actions"]), snapshot["published_results"][bit]["ready_us"]+1)
        changed = deepcopy(snapshot["world_state"])
        changed["atoms"][0]["reset_epoch"] += 1
        with self.assertRaises(StrategyError) as caught:
            compile_physical_dag(dag, self.device, changed, execution_context=context)
        self.assertEqual(caught.exception.code, "EXECUTION_CONTEXT_FRONTIER")

    def test_guarded_group_all_absolute_times_match_nonzero_window(self):
        from test_physical_dag import fixture_instance
        session, bit = self.first_window(delayed=True)
        session.advance()  # Publishes the delayed bit exactly at this frontier.
        dag = fixture_instance("SE", "block", "guarded-second-SE")
        dag["execution_guard"] = {"bit": bit, "equals": 1}
        dag["external_reads"] = [bit]
        context = session.compilation_context(dag)
        plan = compile_physical_dag(dag, self.device, session.snapshot()["world_state"], execution_context=context)
        atom = bind_physical_plan(plan, context)
        actions = {a["id"]: a for a in atom["actions"]}
        for group in atom["groups"]:
            for direction in ("outbound", "return"):
                t = group[direction]
                self.assertEqual(t["start_us"], actions[t["pickup_action_id"]]["t_start_us"])
                self.assertEqual(t["end_us"], actions[t["drop_action_id"]]["t_end_us"])
            for aid in group["measurement_action_ids"]:
                m = actions[aid]
                self.assertEqual(group["earliest_readout_us"][m["atoms"][0]], m["t_start_us"])
        self.assertEqual(plan["ready_decisions"][0]["time_us"], 1.)
        summary = next(iter(plan["node_summaries"].values()))
        self.assertEqual(summary["start_us"], 1.)
        session.submit(atom, make_scenario(atom, value=1), expected_revision=context["revision"])
        session.advance()
        self.assertEqual(len(session.snapshot()["published_results"]), 16)

    def test_postprocess_uses_actual_eight_published_bits_and_keeps_failure(self):
        for bits, status in (([0, 1, 0, 0, 0, 0, 0, 0], "success"), ([0]*8, "failed")):
            session = EventSession(self.device, self.world, run_id="postprocess-binding-"+status)
            measured = build_patch_operation_spec("SE")["physical_dag"]
            context = session.compilation_context(measured)
            plan = compile_physical_dag(measured, self.device, session.snapshot()["world_state"], execution_context=context)
            atom = bind_physical_plan(plan, context)
            scenario = make_scenario(atom, value=0)
            result_ids = [r for op in measured["nodes"] for r in op["writes"]]
            for bit, value in zip(result_ids, bits): scenario["results"][bit]["value"] = value
            session.submit(atom, scenario, expected_revision=context["revision"]); session.advance()
            post = build_patch_operation_spec("CLASSICAL_POSTPROCESS")["physical_dag"]
            mapping = dict(zip(post["external_reads"], result_ids))
            def remap(x):
                if isinstance(x, str): return mapping.get(x, x)
                if isinstance(x, list): return [remap(v) for v in x]
                if isinstance(x, dict): return {k: remap(v) for k, v in x.items()}
                return x
            post = remap(post)
            # This is a labeled result-binding fixture, not a Shor phase-estimation run.
            post["provenance"]["fixture"] = True
            context = session.compilation_context(post)
            plan = compile_physical_dag(post, self.device, session.snapshot()["world_state"], execution_context=context)
            atom = bind_physical_plan(plan, context)
            self.assertEqual(atom["actions"][0]["payload"]["params"]["bits_msb_first"], result_ids)
            session.submit(atom, make_scenario(atom, value=0), expected_revision=context["revision"]); session.advance()
            report = session.snapshot()["published_results"]["report"]["value"]
            self.assertEqual(report["status"], status)
            self.assertEqual(report["factors"], [3, 5] if status == "success" else [])


if __name__ == "__main__": unittest.main()
