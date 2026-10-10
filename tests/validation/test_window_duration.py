"""Leading feedback latency belongs to the committed window, not action span."""
from copy import deepcopy
import unittest

from na_pipeline.validation.checker import Audit, _timing
from na_pipeline.validation.geometry import check_geometry
from test_validation import fixture, action


class WindowDurationTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.device = fixture([])
        self.plan.update(time_basis='absolute_session', session_binding={
            'time_origin_us':100., 'execution_context':{'time_us':100.}})
        self.plan['initial_state']['time_us'] = 100.
        action(self.plan, 'classical', [], 101., 102., {
            'operation':'copy', 'reads':['input'], 'writes':['output'],
            'result_id':'output', 'result_ready_us':102.})
        self.plan['stats'] = {'t_start_us':100., 't_end_us':102., 'duration_us':2.,
                              'action_count':1, 'atom_count':0}
        self.results = {'input':{'ready_us':100., 'action_id':'prior-readout'}}

    def inspect(self, plan=None):
        audit = Audit()
        _timing(audit, self.plan if plan is None else plan, self.device, external_results=self.results)
        check_geometry(audit, self.plan if plan is None else plan, self.device)
        return audit

    def test_feedback_wait_is_counted_without_modifying_actions(self):
        before = deepcopy(self.plan)
        audit = self.inspect()
        self.assertEqual(audit.failures, [])
        self.assertEqual(audit.metrics['makespan_us'], 1.)
        self.assertEqual(audit.metrics['leading_idle_us'], 1.)
        self.assertEqual(audit.metrics['window_duration_us'], 2.)
        self.assertEqual(self.plan, before)

    def test_changed_stats_still_fail(self):
        for key, value in [('duration_us',1.), ('duration_us',3.),
                           ('t_start_us',101.), ('t_end_us',103.)]:
            with self.subTest(key=key, value=value):
                plan = deepcopy(self.plan); plan['stats'][key] = value
                self.assertIn('PLAN_STATS', {f['code'] for f in self.inspect(plan).failures})

    def test_inconsistent_origin_still_fails(self):
        for target in ['initial_state', 'execution_context', 'binding']:
            with self.subTest(target=target):
                plan = deepcopy(self.plan)
                if target == 'initial_state': plan['initial_state']['time_us'] = 99.
                elif target == 'execution_context': plan['session_binding']['execution_context']['time_us'] = 99.
                else: plan['session_binding']['time_origin_us'] = 101.5
                self.assertIn('PLAN_TIME_ORIGIN', {f['code'] for f in self.inspect(plan).failures})

    def test_early_feedback_is_not_accepted(self):
        plan = deepcopy(self.plan); plan['actions'][0]['t_start_us'] = 100.
        self.assertIn('EARLY_RESULT_READ', {f['code'] for f in self.inspect(plan).failures})

    def test_unbound_action_span_check_is_preserved(self):
        plan = deepcopy(self.plan); del plan['session_binding']; del plan['time_basis']
        self.assertIn('PLAN_STATS', {f['code'] for f in self.inspect(plan).failures})


if __name__ == '__main__': unittest.main()
