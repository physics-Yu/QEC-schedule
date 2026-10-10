import unittest
from na_pipeline.qec import component_catalog,instantiate_component,get_component_spec,shor_component_requirements
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.device import canonical_surface17_device,build_preinitialized_state
from na_pipeline.runtime import run,make_scenario,EventSession,bind_physical_plan
from na_pipeline.validation.dag_physical import validate_physical_plan

class LogicalComponentTests(unittest.TestCase):
    def test_logical_result_ports_are_bound_for_scheduler(self):
        compiler=LogicalComponentCompiler(canonical_surface17_device())
        for id in ('JOINT_ZZ','READ_X_CLEANUP','READ_Z_CLEANUP','PARITY','ACCEPT','MEASURE_Z','SE'):
            ports=compiler.result_ports(id);spec=compiler.describe(id)
            self.assertTrue(ports)
            self.assertTrue(set(ports.values())<=set(spec['physical_dag']['result_producers']))
        dag=compiler.instantiate('MEASURE_Z',namespace='measure-A',result_bindings={'value':'logical-result-A'})
        self.assertEqual(dag['component_binding']['logical_result_ports']['value'],'logical-result-A')
        self.assertIn('logical-result-A',dag['result_producers'])
        with self.assertRaises(ValueError):compiler.instantiate('MEASURE_Z',result_bindings={'value':'a','physical/r0/value':'b'})

    def test_scheduler_reuses_SE_and_binds_actual_feedback(self):
        device=canonical_surface17_device()
        world=build_preinitialized_state(device,{'block':{'aod_group':'data','basis':'Z','value':0}},
             {'block':{'anchor_um':[0,900],'orientation':'x_vertical_z_horizontal'}},
             placement_ref={'artifact_id':'component-session','producer':'test','fixture':True})
        compiler=LogicalComponentCompiler(device);session=EventSession(device,world,run_id='component-binding-test')
        for i in range(2):
            dag=compiler.instantiate('SE',namespace=f'se-{i}')
            context=session.compilation_context(dag)
            plan=compiler.compile_dags(dag,session.snapshot()['world_state'],execution_context=context)
            atom=bind_physical_plan(plan,context);session.submit(atom,make_scenario(atom,value=i));session.advance()
        self.assertEqual(compiler.library.stats['strategy_compile_count'],1)
        self.assertEqual(compiler.library.stats['cache_hit_count'],1)
        for i in range(2):
            dag=compiler.instantiate('FEEDBACK_X',namespace=f'feedback-{i}',result_bindings={'feedback_bit':f'se-{i}/physical/r0/m_x0'})
            context=session.compilation_context(dag)
            plan=compiler.compile_dags(dag,session.snapshot()['world_state'],execution_context=context)
            atom=bind_physical_plan(plan,context);session.submit(atom,make_scenario(atom,value=0));session.advance()
            self.assertEqual({session.events[a['id']]['status'] for a in atom['actions']},{'completed' if i else 'skipped'})
        self.assertEqual(len(session.state.atoms),17)

    def test_catalogue_is_fresh_and_covers_source(self):
        a=component_catalog();a['components'].clear()
        self.assertEqual(len(component_catalog()['components']),70)
        coverage=shor_component_requirements()
        self.assertEqual(coverage['logical_nodes'],2102)
        self.assertEqual(len(coverage['logical_node_components']),2102)
        self.assertFalse(coverage['full_shor_executed'])

    def test_tdg_selects_inverse_consumption_correction(self):
        s=get_component_spec('TDG')
        self.assertIn('factory.consume_correction_tdg',s['physical_stage_ids'])
        self.assertNotIn('factory.consume_correction',s['physical_stage_ids'])
        self.assertEqual(s['protocol']['request_gate'],'TDG')
        self.assertEqual(len(s['formal_qubits']),137)
        self.assertEqual(s['patch_spec']['resource_requirements']['factory_patch_count'],7)
        bound=instantiate_component('TDG',protocol_binding={'data_block_id':'logical7','request_id':'T7','epoch':2,'factory_id':'factory2'})
        self.assertEqual(bound['protocol']['data_block_id'],'logical7')
        self.assertEqual(bound['protocol']['epoch'],2)
        with self.assertRaises(ValueError):instantiate_component('T',qubit_bindings={'x':'y'})
        self.assertFalse(instantiate_component('FACTORY_READY')['physical_motion_created'])

    def test_binding_rejects_alias_and_preserves_identities(self):
        q=get_component_spec('SE')['formal_qubits']
        with self.assertRaises(ValueError):instantiate_component('SE',qubit_bindings={x['id']:'same' for x in q})
        d=instantiate_component('SE',qubit_bindings={x['id']:'A/'+x['local_id'] for x in q},namespace='se-A')
        self.assertEqual(len(d['nodes']),56)
        self.assertTrue(all(n['id'].startswith('se-A/') for n in d['nodes']))
        self.assertTrue(all(q['id'].startswith('A/') for q in d['qubits']))
        self.assertTrue(all(q['block_id']=='A' for q in d['qubits']))
        self.assertEqual(d['groups'][0]['formal_block'],'A')
        with self.assertRaises(ValueError):instantiate_component('SE',qubit_bindings={x['id']:('B/' if x['local_id']=='d0' else 'A/')+x['local_id'] for x in q})

    def test_two_canonical_se_real_parallel_actions(self):
        device=canonical_surface17_device();qubits=get_component_spec('SE')['formal_qubits']
        dags=[instantiate_component('SE',qubit_bindings={q['id']:p+'/'+q['local_id'] for q in qubits},namespace='se-'+p) for p in ['A','B']]
        world=build_preinitialized_state(device,{p:{'aod_group':'data','basis':'Z','value':0} for p in ['A','B']},
             {'A':{'anchor_um':[0,900],'orientation':'x_vertical_z_horizontal'},'B':{'anchor_um':[100,900],'orientation':'x_vertical_z_horizontal'}},
             placement_ref={'artifact_id':'two-canonical-se','producer':'test','fixture':True})
        c=LogicalComponentCompiler(device,budget={'max_operations':1000,'max_wall_seconds':120})
        plan=c.compile_dags(dags,world);trace=run(plan['atom_program'],make_scenario(plan['atom_program'],value=0),device)
        report=validate_physical_plan(plan,device,trace=trace)
        self.assertTrue(report['passed'],report)
        gates=[a for a in plan['atom_program']['actions'] if a['kind']=='gate' and a['payload'].get('name')=='CZ']
        self.assertTrue(any(any('atom:A/' in v for pair in a['payload']['pairs'] for v in pair) and
                            any('atom:B/' in v for pair in a['payload']['pairs'] for v in pair) for a in gates))

if __name__=='__main__':unittest.main()
