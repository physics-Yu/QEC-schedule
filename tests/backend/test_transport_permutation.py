"""Carrier-preserving H transport, composition, and negative binding checks."""
from copy import deepcopy
import unittest

from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state
from na_pipeline.runtime import EventSession, bind_physical_plan, make_scenario, run
from na_pipeline.validation import validate_physical_plan, validate_physical_dag_source


class TransportPermutationTests(unittest.TestCase):
    def setUp(self):
        self.device = canonical_surface17_device()
        self.world = build_preinitialized_state(self.device, {'block': {'aod_group':'data', 'basis':'Z', 'value':0}},
            {'block': {'anchor_um':[0,900], 'orientation':'x_vertical_z_horizontal'}},
            placement_ref={'artifact_id':'transport-test', 'producer':'R0-author-test', 'fixture':True})
        self.compiler = LogicalComponentCompiler(self.device)

    def test_H_has_parallel_H_and_real_transport_without_entangling_gates(self):
        dag = self.compiler.instantiate('H', namespace='h')
        # Producer and consumer use separate Pauli algebra implementations.
        raw = self.compiler.describe('H')['physical_dag']
        self.assertTrue(validate_physical_dag_source(raw)['passed'])
        plan = self.compiler.compile_dags(dag, self.world, cache=False)
        atom = plan['atom_program']; trace = run(atom, make_scenario(atom), self.device)
        report = validate_physical_plan(plan, self.device, trace=trace)
        self.assertTrue(report['passed'], report)
        gates = [a for a in atom['actions'] if a['kind']=='gate']
        self.assertEqual(len(gates), 9)
        self.assertEqual({g['payload']['name'] for g in gates}, {'H'})
        self.assertEqual({g['t_start_us'] for g in gates}, {0.})
        final = {a['atom_id']:a for a in trace['final_state']['atoms']}
        before = {a['qubit_id']:a for a in self.world['atoms']}
        for i,j in enumerate([2,5,8,1,4,7,0,3,6]):
            a = final['atom:block/d'+str(i)]
            self.assertEqual(a['qubit_id'], 'block/d'+str(i))
            self.assertEqual(a['site_id'], 'block/d'+str(j))
            self.assertEqual(a['position_um'], before['block/d'+str(j)]['position_um'])

    def test_continuous_H_SE_H_measure_uses_new_bindings_and_cache_predictions(self):
        session = EventSession(self.device, self.world, run_id='transport-chain')
        for i, name in enumerate(['H','SE','H','MEASURE_Z']):
            dag = self.compiler.instantiate(name, namespace=f'{name}-{i}')
            world = session.snapshot()['world_state']
            context = session.compilation_context(dag)
            plan = self.compiler.compile_dags(dag, world, execution_context=context)
            mapping = {a.get('site_id',a['qubit_id']):a['atom_id'] for a in world['atoms']}
            # Fresh compilation after H must bind coupling operands by site,
            # retaining the original atom and physical-qubit identity.
            if name == 'SE':
                for a in plan['atom_program']['actions']:
                    for pair in a['payload'].get('pair_sources', []):
                        self.assertEqual(pair['atoms'], [mapping[q] for q in pair['qubits']])
            bound = bind_physical_plan(plan, context)
            session.submit(bound, make_scenario(bound, value=0)); session.advance()
            actual = {a['atom_id']:a for a in session.snapshot()['world_state']['atoms']}
            for predicted in plan['exit_state']['atoms']:
                self.assertEqual(actual[predicted['atom_id']].get('site_id'), predicted.get('site_id'))
                self.assertEqual(actual[predicted['atom_id']]['position_um'], predicted['position_um'])
        self.assertEqual(len(actual), 17)
        self.assertEqual({a['atom_id']:a['qubit_id'] for a in actual.values()},
                         {a['atom_id']:a['qubit_id'] for a in self.world['atoms']})

    def test_false_relabel_without_arrival_rejected_by_runtime_and_checker(self):
        dag = self.compiler.instantiate('H', namespace='h-negative')
        plan = self.compiler.compile_dags(dag, self.world, cache=False)
        wrong = deepcopy(plan)
        commit = next(a for a in wrong['atom_program']['actions'] if a['kind']=='rebind')
        b0,b1 = commit['payload']['site_bindings'][:2]
        b0['to_site_id'],b1['to_site_id'] = b1['to_site_id'],b0['to_site_id']
        with self.assertRaisesRegex(ValueError, 'SITE_BINDING_BEFORE_ARRIVAL'):
            run(wrong['atom_program'], make_scenario(wrong['atom_program']), self.device)
        report = validate_physical_plan(wrong, self.device)
        self.assertFalse(report['scoped_pass'])
        self.assertTrue(any(f['code']=='SITE_PERMUTATION_NOT_TRANSPORTED' for f in report['failures']))

    def test_checkpoint_mid_transport_preserves_site_homes(self):
        session = EventSession(self.device, self.world, run_id='transport-checkpoint')
        dag = self.compiler.instantiate('H', namespace='checkpoint-H')
        context = session.compilation_context(dag)
        plan = self.compiler.compile_dags(dag, session.snapshot()['world_state'], execution_context=context)
        bound = bind_physical_plan(plan, context)
        session.submit(bound, make_scenario(bound))
        motion = next(a for a in bound['actions'] if a['kind']=='move')
        session.advance(to_us=(motion['t_start_us']+motion['t_end_us'])/2)
        restored = EventSession.restore(self.device, session.checkpoint())
        restored.advance(); session.advance()
        self.assertEqual(restored.snapshot()['world_state'], session.snapshot()['world_state'])


if __name__ == '__main__': unittest.main()
