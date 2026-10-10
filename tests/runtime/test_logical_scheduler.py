from copy import deepcopy
import json
from pathlib import Path
import unittest
import random

from na_pipeline.runtime.calendar import ResourceCalendar
from na_pipeline.runtime.logical_scheduler import LogicalListScheduler
from na_pipeline.runtime import RuntimeContractError


def interval(resource, a, b, **extra):
    return dict(resource_id=resource, start_us=a, end_us=b, units=1, **extra)


class CalendarTests(unittest.TestCase):
    def test_endpoint_search_jumps_large_busy_window(self):
        c = ResourceCalendar()
        c.reserve("one", [interval("beam", 0, 1_000_000)], 0)
        self.assertEqual(c.earliest_start([interval("beam", 5, 10)], 0), 999995)
        self.assertLessEqual(c.stats["candidate_points_checked"], 2)

    def test_capacity_and_exact_joint_pulse(self):
        c = ResourceCalendar({"mz": 2})
        c.reserve("one", [interval("mz", 0, 10)], 0)
        self.assertEqual(c.earliest_start([interval("mz", 0, 10)], 0), 0)
        c.reserve("two", [interval("mz", 0, 10)], 0)
        self.assertEqual(c.earliest_start([interval("mz", 0, 10)], 0), 10)
        b = ResourceCalendar()
        b.reserve("pulse1", [interval("laser", 0, 1, share_key="joint-cz")], 5)
        self.assertEqual(b.earliest_start([interval("laser", 0, 1, share_key="joint-cz")], 4.5), 5)
        self.assertTrue(b.conflicts([interval("laser", 0, 2, share_key="joint-cz")], 5))

    def test_multiple_offsets_and_feasible_domain(self):
        c = ResourceCalendar()
        c.reserve("one", [interval("a", 0, 5), interval("b", 5, 20)], 0)
        self.assertEqual(c.earliest_start([interval("a", 0, 2), interval("b", 4, 6)], 0), 16)
        with self.assertRaises(RuntimeContractError):
            c.earliest_start([interval("a", 0, 2)], 0, feasible_start_intervals=[{"start_us": 1, "end_us": 2}])

    def test_snapshot_and_retirement_do_not_reuse_owner(self):
        c = ResourceCalendar()
        c.reserve("one", [interval("a", 0, 5)], 0)
        d = ResourceCalendar.restore(c.snapshot())
        self.assertEqual(d.snapshot(), c.snapshot())
        d.advance_floor(5)
        self.assertEqual(d.earliest_start([interval("a", 0, 2)], 5), 5)
        with self.assertRaises(RuntimeContractError): d.reserve("one", [], 5)

    def test_capacity_sweep_matches_independent_midpoint_oracle(self):
        rng = random.Random(391)
        for _ in range(40):
            c = ResourceCalendar({"beam": 3}); old = []
            for index in range(12):
                a = rng.randrange(12); b = a+rng.randrange(1, 4)
                lease = interval("beam", a, b, share_key="pulse" if rng.randrange(3) == 0 else None)
                try: c.reserve("owner"+str(index), [lease], 0)
                except RuntimeContractError: continue
                old.append(lease)
            proposed = [interval("beam", (a := rng.randrange(12)), a+rng.randrange(1, 4), share_key="pulse" if rng.randrange(3) == 0 else None) for i in range(15)]
            points = sorted({t for i in old+proposed for t in (i["start_us"], i["end_us"])})
            expected = []
            for a, b in zip(points, points[1:]):
                at = (a+b)/2
                if not any(i["start_us"] <= at < i["end_us"] for i in proposed): continue
                signatures = set(); load = 0
                for i in old+proposed:
                    if not i["start_us"] <= at < i["end_us"]: continue
                    key = (i["share_key"], i["start_us"], i["end_us"]) if i.get("share_key") else None
                    if key is not None and key in signatures: continue
                    if key is not None: signatures.add(key)
                    load += 1
                if load > 3: expected.append((a, b, load))
            actual = [(r["start_us"], r["end_us"], r["load"]) for r in c.conflicts(proposed, 0)]
            self.assertEqual(actual, expected)

    def test_many_nonoverlapping_intervals_use_linear_number_of_sweep_events(self):
        c = ResourceCalendar()
        profile = [interval("beam", 2*i, 2*i+1) for i in range(2000)]
        self.assertFalse(c.conflicts(profile, 0))
        self.assertLessEqual(c.stats["event_sweep_steps"], 2*len(profile))


class LogicalSchedulerTests(unittest.TestCase):
    def fixture(self):
        data = json.loads((Path(__file__).resolve().parents[2]/"knowledge/roles/R5/dag-scheduler-example.json").read_text(encoding="utf-8"))
        return data, data.pop("summaries")

    def test_independent_SE_ready_selected_together_then_CX(self):
        dag, summaries = self.fixture()
        s = LogicalListScheduler(dag, summaries)
        batch = s.propose()
        self.assertEqual(set(batch["ready_set"]), {"se.A", "se.B"})
        self.assertEqual(len(batch["selected"]), 2)
        s.reserve(batch); s.advance(10)
        for nid in ("se.A", "se.B"):
            s.complete(nid, {"node_id": nid, "completed_us": 10, "physical_plan_ref": "fixture-plan", "event_trace_ref": "fixture-trace"})
        self.assertEqual(s.ready_set(), ["cx.AB"])
        # Quantum completion and later result publication are different clocks.
        with self.assertRaises(RuntimeContractError):
            s.publish_results("se.A", {"se.A/x0": {"value": 0, "origin": "fake", "ready_us": 12}}, event_trace_ref="fixture-trace")
        s.advance(12)
        s.publish_results("se.A", {"se.A/x0": {"value": 0, "origin": "fake", "ready_us": 12}}, event_trace_ref="fixture-trace")

    def test_shared_resource_defers_second_without_global_patch_barrier(self):
        dag, summaries = self.fixture()
        summaries["se.A"]["intervals"] = [interval("global", 0, 10)]
        summaries["se.B"]["intervals"] = [interval("global", 0, 10)]
        s = LogicalListScheduler(dag, summaries)
        batch = s.propose()
        self.assertEqual(len(batch["selected"]), 1)
        self.assertEqual(batch["rejected"][0]["earliest_start_us"], 10)

    def test_classical_ready_condition_and_skip(self):
        dag, summaries = self.fixture()
        node = dag["nodes"][-1]
        node.update(reads=["se.A/x0"], condition={"bit": "se.A/x0", "equals": 1})
        dag["edges"].append({"source": "se.A", "target": "cx.AB", "kind": "classical_ready", "result_id": "se.A/x0"})
        s = LogicalListScheduler(dag, summaries)
        s.reserve(s.propose()); s.advance(10)
        for nid in ("se.A", "se.B"):
            s.complete(nid, {"node_id": nid, "completed_us": 10, "physical_plan_ref": "p", "event_trace_ref": "t"})
        self.assertEqual(s.ready_set(), [])
        s.advance(12); s.publish_results("se.A", {"se.A/x0": {"value": 0, "origin": "fake", "ready_us": 12}}, event_trace_ref="t")
        skipped = s.propose(); self.assertEqual(skipped["skipped"][0]["node_id"], "cx.AB")
        s.reserve(skipped); self.assertEqual(s.states["cx.AB"]["status"], "skipped")

    def test_cycle_and_missing_producer_edges_rejected(self):
        dag, summaries = self.fixture()
        dag["edges"].append({"source": "cx.AB", "target": "se.A", "kind": "quantum"})
        with self.assertRaises(RuntimeContractError) as caught: LogicalListScheduler(dag, summaries)
        self.assertEqual(caught.exception.code, "DAG_CYCLE")
        dag, summaries = self.fixture()
        dag["nodes"][0]["reads"] = ["unknown"]
        with self.assertRaises(RuntimeContractError) as caught: LogicalListScheduler(dag, summaries)
        self.assertEqual(caught.exception.code, "DAG_MISSING_PRODUCER")

    def test_stale_or_modified_proposal_is_atomic(self):
        dag, summaries = self.fixture(); s = LogicalListScheduler(dag, summaries)
        batch = s.propose(); bad = deepcopy(batch); bad["selected"][0]["end_us"] = 1
        before = s.snapshot()
        with self.assertRaises(RuntimeContractError): s.reserve(bad)
        self.assertEqual(s.snapshot(), before)
        s.advance(1)
        with self.assertRaises(RuntimeContractError): s.reserve(batch)


if __name__ == "__main__": unittest.main()
