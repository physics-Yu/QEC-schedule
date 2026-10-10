"""Current SE pulse depth, AOD reset, and shared-template integration."""
from copy import deepcopy
import unittest
from na_pipeline.qec import get_component_spec
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state
from na_pipeline.backend import LogicalComponentCompiler, compile_physical_dag
from na_pipeline.runtime import run, make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan, validate_physical_dag_source


class SEParallelTests(unittest.TestCase):
    def world(self, device, shift=0.):
        return build_preinitialized_state(device, {'block': {'aod_group': 'data', 'basis': 'Z', 'value': 0}},
            {'block': {'anchor_um': [shift, 900.], 'orientation': 'x_vertical_z_horizontal'}},
            placement_ref={'artifact_id': 'se-parallel-test', 'producer': 'R0', 'fixture': True})

    def audited(self, name='SE', *, direct=False, transfer_us=100., shift=0.):
        device = canonical_surface17_device(transfer_us=transfer_us)
        world = self.world(device, shift); dag = get_component_spec(name)['physical_dag']
        frozen = deepcopy(dag)
        if direct:
            plan = compile_physical_dag(dag, device, world)
        else:
            compiler = LogicalComponentCompiler(device)
            compiler.build_dependencies(dag, world)
            before = compiler.modules.stats
            plan = compiler.compose_recipe(dag, world)
            for key in ('leaf_compile_count', 'placement_search_count', 'routing_search_count'):
                self.assertEqual(compiler.modules.stats[key], before[key])
        self.assertEqual(dag, frozen)
        trace = run(plan['atom_program'], make_scenario(plan['atom_program']), device)
        report = validate_physical_plan(plan, device, trace=trace)
        self.assertTrue(report['passed'], {k: report[k] for k in ('failures', 'unverified')})
        return dag, plan, trace

    def test_SE_five_CZ_pulses_in_module_and_direct_paths(self):
        for direct in (False, True):
            dag, plan, trace = self.audited(direct=direct)
            self.assertTrue(validate_physical_dag_source(dag)['passed'])
            actions = plan['atom_program']['actions']
            pulses = [a for a in actions if a['payload'].get('name') == 'CZ']
            self.assertEqual([len(a['payload']['pairs']) for a in pulses], [6, 3, 6, 3, 6])
            ops = {o['id']: o for o in dag['nodes']}
            layers = [{ops[s]['metadata']['syndrome_layer'] for s in a['payload']['physical_op_ids']} for a in pulses]
            self.assertEqual(layers, [{0}, {1}, {1, 2}, {2}, {3}])
            self.assertLessEqual(plan['atom_program']['stats']['duration_us'], 1889.)
            self.assertEqual(sum(a['kind'] == 'pickup' for a in actions), 7)
            self.assertEqual(sum(a['kind'] == 'drop' for a in actions), 7)
            self.assertEqual({a['t_end_us']-a['t_start_us'] for a in actions if a['kind'] in ('pickup', 'drop')}, {100.})

    def test_service_reset_stays_in_AOD_without_an_extra_transfer(self):
        _, plan, trace = self.audited()
        atoms = {a['atom_id']: a['carrier'] for a in plan['atom_program']['initial_state']['atoms']}
        events = []
        for a in plan['atom_program']['actions']:
            events.extend([(a['t_start_us'], 1, a), (a['t_end_us'], 0, a)])
        held_resets = []
        for _, endpoint, a in sorted(events, key=lambda v: (v[0], v[1], v[2]['id'])):
            if endpoint == 0 and a['kind'] in ('pickup', 'drop'):
                for q in a['atoms']: atoms[q] = 'AOD' if a['kind'] == 'pickup' else 'SLM'
            if endpoint == 1 and a['kind'] == 'reset' and any(atoms[q] == 'AOD' for q in a['atoms']):
                self.assertTrue(all(atoms[q] == 'AOD' for q in a['atoms']))
                self.assertFalse(a['payload']['reset_transport_required']); held_resets.append(a)
        self.assertEqual(len(held_resets), 8)
        self.assertEqual(len({(a['t_start_us'], a['t_end_us']) for a in held_resets}), 1)
        self.assertTrue(all(c == 'SLM' for c in atoms.values()))

    def test_translation_and_original_transfer_setting(self):
        for shift in (-100., 300.):
            _, plan, _ = self.audited(shift=shift, transfer_us=200.)
            self.assertEqual(len([a for a in plan['atom_program']['actions'] if a['payload'].get('name') == 'CZ']), 5)
            self.assertLessEqual(plan['atom_program']['stats']['duration_us'], 3289.)

    def test_S_and_SDG_preserve_the_half_cycle_fold(self):
        for name in ('S', 'SDG'):
            dag, plan, _ = self.audited(name)
            self.assertTrue(validate_physical_dag_source(dag)['passed'])
            byid = {a['id']: a for a in plan['atom_program']['actions']}
            fold = [o for o in dag['nodes'] if o.get('metadata', {}).get('se_stage') == 'half_cycle_fold']
            early = [o for o in dag['nodes'] if o.get('metadata', {}).get('syndrome_layer') in (0, 1)]
            late = [o for o in dag['nodes'] if o.get('metadata', {}).get('syndrome_layer') in (2, 3)]
            def interval(ops):
                xs = [byid[i] for o in ops for i in plan['atom_program']['source_map'][o['id']]]
                return min(a['t_start_us'] for a in xs), max(a['t_end_us'] for a in xs)
            self.assertLessEqual(interval(early)[1], interval(fold)[0])
            self.assertLessEqual(interval(fold)[1], interval(late)[0])


if __name__ == '__main__': unittest.main()
