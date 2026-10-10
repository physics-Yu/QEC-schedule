"""Search-free reuse, actual exit binding and complete-world counterexamples."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.backend.compiled_modules import CompiledModuleLibrary
from na_pipeline.backend.enola_kernel import StrategyError
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state
from na_pipeline.runtime import EventSession, bind_physical_plan, make_scenario, run
from na_pipeline.validation.dag_physical import validate_physical_plan, validate_physical_dag_source


class CompiledModuleTests(unittest.TestCase):
    def setUp(self):
        self.device=canonical_surface17_device()
        self.front=LogicalComponentCompiler(self.device)
        self.world=self.world_at('block',0)

    def world_at(self,name,x):
        return build_preinitialized_state(self.device,{name:{'aod_group':'data','basis':'Z','value':0}},
            {name:{'anchor_um':[x,900.],'orientation':'x_vertical_z_horizontal'}},
            placement_ref={'artifact_id':'module-test','producer':'R0','fixture':True})

    def test_missing_dependencies_reject_instead_of_flattening(self):
        lib=CompiledModuleLibrary(self.device)
        with self.assertRaisesRegex(StrategyError,'MODULE_DEPENDENCY_MISSING'):
            lib.compose_recipe(self.front.instantiate('SE'),self.world)
        self.assertEqual(lib.stats['leaf_compile_count'],0)

    def test_ready_batch_alias_and_wrong_site_map_are_rejected(self):
        lib=CompiledModuleLibrary(self.device)
        with self.assertRaisesRegex(StrategyError,'JOINT_DAG_QUBIT_CONFLICT'):
            lib.compose_recipe([self.front.instantiate('H',namespace='a'),self.front.instantiate('H',namespace='b')],self.world,build_missing=True)
        self.assertEqual(lib.stats['leaf_compile_count'],0)
        dag=self.front.instantiate('H');lib.compose_recipe(dag,self.world,build_missing=True)
        world=deepcopy(self.world);world['atoms'][-1]['site_id']=world['atoms'][-2]['qubit_id']
        with self.assertRaisesRegex(StrategyError,'MODULE_DEPENDENCY_MISSING'):
            lib.compose_recipe(dag,world)

    def test_mismatched_after_and_typed_edges_rejected_before_search(self):
        from na_pipeline.qec import PhysicalDAGError
        lib=CompiledModuleLibrary(self.device);dag=self.front.instantiate('X')
        a,b=dag['nodes'][:2]
        dag['edges'].append({'source':a['id'],'target':b['id'],'kind':'protocol'})
        dag['roots'].remove(b['id']);dag['terminals'].remove(a['id'])
        with self.assertRaisesRegex(PhysicalDAGError,'PHYSICAL_AFTER_EDGE_MISMATCH'):
            lib.compose_recipe(dag,self.world,build_missing=True)
        self.assertEqual(lib.stats['leaf_compile_count'],0)

    def test_persistent_H_translation_and_renaming_do_not_search(self):
        with tempfile.TemporaryDirectory() as directory:
            dag=self.front.instantiate('H',namespace='first')
            lib=CompiledModuleLibrary(self.device,directory=directory)
            lib.compose_recipe(dag,self.world,build_missing=True)
            second=CompiledModuleLibrary(self.device,directory=directory)
            renamed=self.front.instantiate('H',namespace='next',qubit_bindings={f'block/{q}':f'other/{q}' for q in [f'd{i}' for i in range(9)]+[f'{p}{i}' for p in ('x','z') for i in range(4)]})
            with patch('na_pipeline.backend.compiled_modules.compile_physical_dag',side_effect=AssertionError('unexpected compile')):
                plan=second.compose_recipe(renamed,self.world_at('other',100.))
            atom=plan['atom_program'];trace=run(atom,make_scenario(atom),self.device)
            self.assertTrue(validate_physical_plan(plan,self.device,trace=trace)['passed'])
            self.assertEqual(second.stats['leaf_compile_count'],0)
            self.assertEqual(second.stats['routing_search_count'],0)
            self.assertEqual(second.stats['import_count'],2)

    def test_H_SE_readout_consumes_actual_site_mapping(self):
        lib=CompiledModuleLibrary(self.device)
        lib.compose_recipe(self.front.instantiate('SE',namespace='warm-se'),self.world,build_missing=True)
        session=EventSession(self.device,self.world,run_id='modular-h-se-read')
        for i,name in enumerate(('H','SE','MEASURE_Z')):
            dag=self.front.instantiate(name,namespace=f'op{i}')
            ctx=session.compilation_context(dag);world=session.snapshot()['world_state']
            plan=lib.compose_recipe(dag,world,execution_context=ctx,build_missing=name!='SE')
            relative=plan['atom_program']
            local_trace=run(relative,make_scenario(relative),self.device)
            self.assertTrue(validate_physical_plan(plan,self.device,trace=local_trace)['passed'])
            actual={a.get('site_id',a['qubit_id']):a['atom_id'] for a in world['atoms']}
            for action in plan['atom_program']['actions']:
                for pair in action['payload'].get('pair_sources',[]):
                    self.assertEqual(pair['atoms'],[actual[q] for q in pair['qubits']])
            atom=bind_physical_plan(plan,ctx);scenario=make_scenario(atom)
            if name=='MEASURE_Z':
                for action in atom['actions']:
                    if action['kind']=='measure':scenario['results'][action['payload']['result_id']]['value']=int(action['atoms']==['atom:block/d3'])
            session.submit(atom,scenario);session.advance()
        result=self.front.result_ports('MEASURE_Z')['value']
        self.assertEqual(session.results['op2/'+result]['value'],1)

    def test_repeated_Y_uses_fresh_feedback_and_no_new_search(self):
        lib=CompiledModuleLibrary(self.device);dag=self.front.instantiate('PREPARE_Y_PLUS')
        first=lib.compose_recipe(dag,self.world,build_missing=True);before=lib.stats
        with patch('na_pipeline.backend.compiled_modules.compile_physical_dag',side_effect=AssertionError('unexpected compile')):
            plan=lib.compose_recipe(dag,self.world)
        for key in ('leaf_compile_count','routing_search_count','placement_search_count'):
            self.assertEqual(lib.stats[key],before[key])
        atom=plan['atom_program'];scenario=make_scenario(atom,value=1)
        trace=run(atom,scenario,self.device)
        report=validate_physical_plan(plan,self.device,trace=trace)
        self.assertTrue(report['passed'],report)
        self.assertFalse(plan['module_composition']['cached_runtime_state'])

    def test_extra_atom_at_required_buffer_rejects_reuse_without_search(self):
        lib=CompiledModuleLibrary(self.device);dag=self.front.instantiate('H')
        original=lib.compose_recipe(dag,self.world,build_missing=True)
        move=next(a for a in original['atom_program']['actions'] if a['kind']=='move')
        position=move['payload']['trajectories'][0]['to_um']
        world=deepcopy(self.world)
        a=deepcopy(world['atoms'][0]);a.update(atom_id='extra',qubit_id='extra/q',site_id='extra/q',trap_id='slm:extra',position_um=position)
        world['atoms'].append(a);world['slm_traps'].append({'trap_id':'slm:extra','position_um':position,'zone_id':self.device['broadcast']['zone_id'],'occupant':'extra'})
        before=lib.stats['leaf_compile_count']
        with self.assertRaisesRegex(StrategyError,'MODULE_DEPENDENCY_MISSING'):
            lib.compose_recipe(dag,world)
        self.assertEqual(before,lib.stats['leaf_compile_count'])

    def test_MZ_translation_requires_explicit_connector_variant(self):
        lib=CompiledModuleLibrary(self.device);dag=self.front.instantiate('MEASURE_Z')
        lib.compose_recipe(dag,self.world,build_missing=True)
        with self.assertRaisesRegex(StrategyError,'MODULE_DEPENDENCY_MISSING'):
            lib.compose_recipe(dag,self.world_at('block',100.))
        self.assertEqual(lib.stats['connector_compile_count'],1)

    def test_CX_nine_pairs_and_CZ_native_source_are_preserved(self):
        from na_pipeline.qec import get_component_spec
        for name,roles in (('CX',('control','target')),('CZ',('left','right'))):
            dag=get_component_spec(name)['physical_dag']
            self.assertTrue(validate_physical_dag_source(dag)['passed'])
            world=build_preinitialized_state(self.device,{p:{'aod_group':'data','basis':'Z','value':0} for p in roles},
                {p:{'anchor_um':[100.*i,900.],'orientation':'canonical_rot90' if name=='CZ' and i==1 else 'x_vertical_z_horizontal'} for i,p in enumerate(roles)},
                placement_ref={'artifact_id':'pair','producer':'R0','fixture':True})
            lib=CompiledModuleLibrary(self.device);plan=lib.compose_recipe(dag,world,build_missing=True)
            gates=[a for a in plan['atom_program']['actions'] if a['kind']=='gate']
            pulses=[a for a in gates if a['payload']['name']=='CZ']
            self.assertEqual([len(a['payload']['pairs']) for a in pulses],[9])
            if name=='CZ':self.assertEqual(len(gates),1)

    def test_independent_local_gate_overlaps_readout_connector(self):
        roles = ('A', 'B')
        world = build_preinitialized_state(self.device,
            {p: {'aod_group':'data','basis':'Z','value':0} for p in roles},
            {p: {'anchor_um':[100.*i,900.],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(roles)},
            placement_ref={'artifact_id':'parallel-module-test','producer':'R0','fixture':True})
        specs = [self.front.instantiate(name, namespace=p,
            qubit_bindings={q['id']: q['id'].replace('block/', p+'/') for q in self.front.describe(name)['formal_qubits']})
            for p,name in (('A','X'),('B','MEASURE_Z'))]
        plan = self.front.build_dependencies(specs, world)
        instances = plan['module_composition']['instances']
        local = next(m for m in instances if m['kind']=='local_layer')
        readout = next(m for m in instances if m['kind']=='readout_connector')
        self.assertEqual(local['start_us'], 0.)
        self.assertEqual(readout['start_us'], 0.)
        self.assertFalse(readout['schedule_constraints'])
        self.assertLess(plan['atom_program']['stats']['duration_us'], sum(m['end_us']-m['start_us'] for m in instances))
        trace = run(plan['atom_program'], make_scenario(plan['atom_program']), self.device)
        self.assertTrue(validate_physical_plan(plan,self.device,trace=trace)['passed'])

    def test_same_array_stays_in_AOD_between_two_complete_CNOT_layers(self):
        from na_pipeline.qec.factory_primitives import Circuit
        from na_pipeline.qec.physical_dag import _program, physical_dag_from_program
        circuit=Circuit();circuit.transversal('A','B','first');circuit.transversal('A','B','second')
        dag=physical_dag_from_program(_program(circuit,{'A':'A','B':'B'},'double-CX'),operation='MODULE_FRAGMENT')
        world=build_preinitialized_state(self.device,
            {p:{'aod_group':'data','basis':'Z','value':0} for p in ('A','B')},
            {p:{'anchor_um':[100.*i,900.],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(('A','B'))},
            placement_ref={'artifact_id':'resident-test','producer':'R0','fixture':True})
        plan=self.front.build_dependencies(dag,world);atom=plan['atom_program']
        self.assertEqual(plan['aod_residency']['saved_transfer_us'],200.)
        self.assertEqual(len(plan['aod_residency']['merged_boundaries']),1)
        self.assertEqual(sum(a['kind']=='pickup' for a in atom['actions']),1)
        self.assertEqual(sum(a['kind']=='drop' for a in atom['actions']),1)
        self.assertEqual([len(a['payload']['pairs']) for a in atom['actions'] if a['payload'].get('name')=='CZ'],[9,9])
        self.assertEqual(sum(a['payload'].get('name')=='H' for a in atom['actions']),36)
        trace=run(atom,make_scenario(atom),self.device)
        self.assertTrue(validate_physical_plan(plan,self.device,trace=trace)['passed'])
        self.assertTrue(all(a['carrier']=='SLM' for a in plan['exit_state']['atoms']))
        # The immutable leaf library remains reusable without new routing.
        before=self.front.modules.stats
        with patch('na_pipeline.backend.compiled_modules.compile_physical_dag',side_effect=AssertionError('unexpected compile')):
            again=self.front.compose_recipe(dag,world)
        self.assertEqual(again['atom_program']['actions'],atom['actions'])
        self.assertEqual(before['routing_search_count'],self.front.modules.stats['routing_search_count'])

    def test_ready_CNOT_is_not_starved_by_independent_maintenance_SE(self):
        from na_pipeline.qec.factory_primitives import Circuit
        from na_pipeline.qec.physical_dag import _program, physical_dag_from_program
        from na_pipeline.backend.module_graph import module_graph
        circuit=Circuit();circuit.transversal('A','B','unlock')
        for p in ('A','B','C','D'):circuit.syndrome(p,'hold_'+p,rounds=1)
        dag=physical_dag_from_program(_program(circuit,{p:p for p in 'ABCD'},'unlock-SE'),operation='MODULE_FRAGMENT')
        graph=module_graph(dag)
        first=next(m for m in graph['modules'] if m['kind']=='entangling_layer')
        self.assertEqual(len(first['dag']['nodes']),9)
        self.assertTrue(all('/unlock_' in o['id'] for o in first['dag']['nodes']))
        self.assertEqual(set(graph['source_owner']),{o['id'] for o in dag['nodes']})

    def test_partial_CNOT_input_waits_for_SE_then_reads_nine_together(self):
        from na_pipeline.qec.factory_primitives import Circuit
        from na_pipeline.qec.physical_dag import _program, physical_dag_from_program
        from na_pipeline.backend.module_graph import module_graph
        c=Circuit();c.syndrome('M','prepare',rounds=1);c.transversal('D','M','inject');c.read_logical('M','Z','magic')
        dag=physical_dag_from_program(_program(c,{'D':'D','M':'M'},'SE-then-CNOT'),operation='MODULE_FRAGMENT')
        def sizes(graph,needle):
            return [sum(needle in o['id'] for o in m['dag']['nodes']) for m in graph['modules'] if any(needle in o['id'] for o in m['dag']['nodes'])]
        graph=module_graph(dag)
        self.assertEqual(sizes(graph,'/inject_'),[9])
        self.assertEqual(sizes(graph,'/magic_read_d'),[9])
        broken=deepcopy(dag)
        for o in broken['nodes']:o.get('metadata',{}).pop('logical_cohort',None)
        self.assertNotEqual(sizes(module_graph(broken),'/inject_'),[9])


if __name__=='__main__':unittest.main()
