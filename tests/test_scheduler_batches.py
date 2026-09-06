from dataclasses import replace
import unittest
from examples.demo_aod_movement import ten_translations
from qec_schedule.hardware import Atom, Bounds, HardwareConfig, HardwareState, TrapSite, Zone, ActionTiming
from qec_schedule.lowering.experimental_ir import ExperimentalPlan
from qec_schedule.scheduler.engine import Scheduler
from qec_schedule.trace import metrics


class BatchTests(unittest.TestCase):
    def test_ten_transport_atoms_share_one_custody(self):
        requests = ten_translations(ActionTiming())
        source = Zone('demo_source', 'STORAGE', Bounds(0, 0, 30, 9), 10, frozenset({'LOCAL_1Q'}),
                      tuple(TrapSite(r.pickup.sources[0].site, r.pickup.sources[0].position) for r in requests))
        target = Zone('demo_target', 'STORAGE', Bounds(0, 11, 30, 20), 10, frozenset({'LOCAL_1Q'}),
                      tuple(TrapSite(r.dropoff.targets[0].site, r.dropoff.targets[0].position) for r in requests))
        config = HardwareConfig((source, target), 1)
        atoms = tuple(Atom(r.atom, f'q{i}', 'DATA', r.pickup.sources[0].position, source.id,
                           r.pickup.sources[0].site) for i, r in enumerate(requests))
        state = HardwareState(atoms, config.zones)
        plan = ExperimentalPlan(tuple(a for r in requests for a in (r.pickup, r.move, r.dropoff)),
                                {r.id: (r.dropoff.id,) for r in requests}, tuple(r.reservation for r in requests),
                                {r.atom: r.pickup.sources[0] for r in requests},
                                {r.atom: r.dropoff.targets[0] for r in requests})
        trace = Scheduler(config).run(plan, state)
        result = metrics(trace)
        self.assertEqual(result['movement_epochs'], 1)
        self.assertEqual(trace['duration'], 12)
        self.assertEqual(len(trace['resource_spans']), 1)
        self.assertEqual(result['resource_utilization']['device/aod'], 1)
        limited = replace(config, aod=replace(config.aod, max_x_tones=1))
        serial = Scheduler(limited).run(plan, state)
        self.assertEqual(metrics(serial)['movement_epochs'], 10)
        self.assertEqual(serial['duration'], 120)

