import gzip
import json
from pathlib import Path
import tempfile
import unittest

import test_session as fixtures
from na_pipeline.runtime import EventSession, RuntimeContractError, make_scenario


class HistoryTests(unittest.TestCase):
    def test_compact_certified_history_keeps_feedback_and_replay_protection(self):
        from na_pipeline.runtime.session_compaction import compact_archived_frontier
        p=fixtures.window(self.session,[fixtures.action('source','classical',[],0,1,
            {'operation':'fake','writes':['m'],'result_ready_us':1}),
            fixtures.action('old-gate','gate',['atom:P/d1'],0,1,{'name':'Z'})])
        self.session.submit(p,make_scenario(p,value=1));self.session.advance()
        self.reject('COMPACTION_NOT_ARCHIVED',lambda:compact_archived_frontier(self.session,['m']))
        self.session.retire_committed(self.root/'000.json.gz',keep_result_ids=['m'],keep_action_ids=['source','old-gate'])
        world=self.session.snapshot()['world_state']
        proof=compact_archived_frontier(self.session,['m'])
        self.assertEqual(proof['after_actions'],1)
        self.assertEqual(self.session.snapshot()['world_state'],world)
        restored=EventSession.restore(self.session.device,self.session.checkpoint())
        feedback=fixtures.window(restored,[fixtures.action('next','gate',['atom:P/d0'],2,3,
            {'name':'X','reads':['m']},{'bit':'m','equals':1})])
        feedback['actions'][0]['depends_on']=['source']
        restored.submit(feedback,make_scenario(feedback));restored.advance()
        replay=fixtures.window(restored,[fixtures.action('old-gate','gate',['atom:P/d1'],4,5,{'name':'Z'})])
        self.reject('SESSION_ACTION_REUSE',lambda:restored.submit(replay,make_scenario(replay)))

    def setUp(self):
        f = fixtures.SessionTests(); f.setUp(); self.session = f.session
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def reject(self, code, fn):
        with self.assertRaises(RuntimeContractError) as caught: fn()
        self.assertEqual(caught.exception.code, code)

    def test_chunk_retirement_preserves_live_feedback_and_all_counts(self):
        p = fixtures.window(self.session, [fixtures.action("source", "classical", [], 0, 1,
            {"operation": "fake", "writes": ["m"], "result_ready_us": 1}),
            fixtures.action("expired", "gate", ["atom:P/d1"], 0, 1, {"name": "Z"})])
        self.session.submit(p, make_scenario(p, value=1)); self.session.advance()
        self.session.retire_committed(self.root/"000.json.gz", keep_result_ids=["m"])
        self.assertEqual(set(self.session.actions), {"source"})
        self.assertFalse(self.session.plans)
        p = fixtures.window(self.session, [fixtures.action("feedback", "gate", ["atom:P/d0"], 2, 3,
            {"name": "X", "reads": ["m"]}, {"bit": "m", "equals": 1})])
        p["actions"][0]["depends_on"] = ["source"]
        self.session.submit(p, make_scenario(p)); self.session.advance()
        self.session.retire_committed(self.root/"001.json.gz")
        self.assertFalse(self.session.actions)
        self.assertFalse(self.session.results)
        self.assertEqual(self.session.export_trace()["stats"]["action_count"], 3)
        self.assertEqual(self.session.export_trace()["stats"]["result_count"], 1)
        restored = EventSession.restore(self.session.device, self.session.checkpoint())
        self.assertEqual(restored.snapshot(), self.session.snapshot())
        events = [event for path in sorted(self.root.glob("*.gz")) for event in json.loads(gzip.decompress(path.read_bytes()))["events"].values()]
        self.assertEqual(len(events), 3)
        p = fixtures.window(restored, [fixtures.action("expired", "gate", ["atom:P/d1"], 3, 4, {"name": "X"})])
        self.reject("SESSION_ACTION_REUSE", lambda: restored.submit(p, make_scenario(p)))
        p["actions"][0] = fixtures.action("new-source", "classical", [], 3, 4, {"operation": "fake", "writes": ["m"], "result_ready_us": 4})
        self.reject("SESSION_RESULT_REUSE", lambda: restored.submit(p, make_scenario(p)))

    def test_cannot_retire_pending_publication_or_restore_missing_history(self):
        p = fixtures.window(self.session, [fixtures.action("m", "classical", [], 0, 1,
            {"operation": "fake", "writes": ["r"], "result_ready_us": 10})])
        self.session.submit(p, make_scenario(p)); self.session.advance(2)
        self.reject("HISTORY_PREFIX_NOT_QUIESCENT", lambda: self.session.retire_committed(self.root/"000.gz"))
        self.session.advance(); self.session.retire_committed(self.root/"000.gz")
        checkpoint = self.session.checkpoint()
        (self.root/"000.gz").write_bytes(b"changed")
        self.reject("HISTORY_CHUNK_INTEGRITY", lambda: EventSession.restore(self.session.device, checkpoint))


if __name__ == "__main__": unittest.main()
