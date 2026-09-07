import unittest
from dataclasses import replace
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.qec import create_code
from qec_schedule.lowering import LegacyGateLowerer
from qec_schedule.scheduler.engine import Scheduler, build_tasks
from qec_schedule.scheduler import Pool, TaskState


class SchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_hardware_config('configs/hardware_default.yaml')
        cls.code = create_code()
        cls.state = build_initial_state(cls.code, cls.config)
        cls.plan = LegacyGateLowerer(cls.config.timing).lower(cls.code.syndrome_round(), cls.state)
        cls.trace = Scheduler(cls.config).run(cls.plan, cls.state)

    def test_tasks_and_all_actions_complete(self):
        tasks, catalog = build_tasks(self.plan)
        self.assertEqual(len(tasks), 216)
        self.assertEqual(sum(t.pool == Pool.MOVE for t in tasks), len(catalog.requests))
        self.assertTrue(all(t.status == TaskState.WAITING for t in tasks))
        self.assertEqual({a['id'] for a in self.trace['actions']}, {a.id for a in self.plan.actions})
        self.assertTrue(all(a['start_time'] is not None for a in self.trace['actions']))

    def test_dependency_and_exclusive_atom_intervals(self):
        records = {a['id']: a for a in self.trace['actions']}
        for a in records.values():
            for parent in a['dependencies']:
                self.assertLessEqual(records[parent]['end_time'], a['start_time'] + 1e-8)
        for atom in self.state.atoms:
            actions = sorted((a for a in records.values() if atom.atom_id in a['atoms']), key=lambda a: a['start_time'])
            for left, right in zip(actions, actions[1:]):
                self.assertLessEqual(left['end_time'], right['start_time'] + 1e-8)

    def test_deterministic_and_home_return(self):
        self.assertEqual(self.trace, Scheduler(self.config).run(self.plan, self.state))
        self.assertEqual(self.trace['initial_state']['atoms'], self.trace['final_state']['atoms'])

    def test_unknown_or_zero_device_capacity(self):
        with self.assertRaises(ValueError):
            Scheduler(self.config, device_capacities={'typo': 1})
        with self.assertRaises(ValueError):
            Scheduler(self.config, device_capacities={'device/aod': 0}).run(self.plan, self.state)

    def test_deadlock_has_diagnostic(self):
        zones = tuple(replace(z, capacity=1) if z.kind == 'ENTANGLING' else z for z in self.config.zones)
        config = replace(self.config, zones=zones)
        state = replace(self.state, zones=zones)
        with self.assertRaisesRegex(RuntimeError, 'deadlock'):
            Scheduler(config).run(self.plan, state)
