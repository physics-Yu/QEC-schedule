"""Whole-array readout, explicit unbounded capacity, and logical site parity."""
from collections import Counter
from copy import deepcopy
import unittest

from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.backend.enola_kernel import digest
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state, validate_device
from na_pipeline.runtime import EventSession, bind_physical_plan, make_scenario, run
from na_pipeline.validation import validate_physical_plan


def world(device, patches=('block',)):
    return build_preinitialized_state(device, {p:{'aod_group':'data','basis':'Z','value':0} for p in patches},
        {p:{'anchor_um':[100*i,900],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(patches)},
        placement_ref={'artifact_id':'readout-test','producer':'R0-author-test','fixture':True})


class LogicalReadoutTests(unittest.TestCase):
    def compile(self, name='MEASURE_Z', capacity=None):
        device=canonical_surface17_device(readout_capacity=capacity)
        compiler=LogicalComponentCompiler(device)
        plan=compiler.compile_dags(compiler.instantiate(name),world(device),cache=False)
        atom=plan['atom_program'];trace=run(atom,make_scenario(atom,value=0),device)
        report=validate_physical_plan(plan,device,trace=trace)
        self.assertTrue(report['passed'],report)
        return device,plan,trace

    def test_nine_Z_readouts_one_common_window_one_array_trip(self):
        device,plan,trace=self.compile()
        self.assertIsNone(device['rigid_readout']['max_parallel_readouts'])
        actions=plan['atom_program']['actions'];readouts=[a for a in actions if a['kind']=='measure']
        self.assertEqual(len(readouts),9)
        self.assertEqual(len({(a['t_start_us'],a['t_end_us']) for a in readouts}),1)
        self.assertEqual(len(plan['measurement_placements']),1)
        self.assertEqual([len(a['atoms']) for a in actions if a['kind']=='pickup'],[9,9])
        self.assertFalse(any(a['kind']=='gate' for a in actions))
        self.assertEqual(Counter(a['measurement_count'] for a in trace['final_state']['atoms']),{1:9,0:8})
        before={a['atom_id']:a['position_um'] for a in plan['atom_program']['initial_state']['atoms']}
        self.assertEqual({a['atom_id']:a['position_um'] for a in trace['final_state']['atoms']},before)

    def test_two_patches_eighteen_readouts_are_not_capped_at_nine(self):
        device=canonical_surface17_device();compiler=LogicalComponentCompiler(device)
        formal=compiler.describe('MEASURE_Z')['formal_qubits']
        dags=[compiler.instantiate('MEASURE_Z',namespace=p,qubit_bindings={q['id']:p+'/'+q['local_id'] for q in formal}) for p in ('A','B')]
        plan=compiler.compile_dags(dags,world(device,('A','B')),cache=False)
        atom=plan['atom_program'];trace=run(atom,make_scenario(atom),device)
        self.assertTrue(validate_physical_plan(plan,device,trace=trace)['passed'])
        measured=[a for a in atom['actions'] if a['kind']=='measure']
        self.assertEqual(len(measured),18)
        self.assertEqual(len({a['t_start_us'] for a in measured}),1)
        self.assertEqual([len(a['atoms']) for a in atom['actions'] if a['kind']=='pickup'],[18,18])

    def test_finite_limit_uses_two_exposures_without_another_transport(self):
        _,plan,_=self.compile(capacity=8)
        actions=plan['atom_program']['actions'];reads=[a for a in actions if a['kind']=='measure']
        self.assertEqual(sorted(Counter(a['t_start_us'] for a in reads).values()),[1,8])
        self.assertEqual([len(a['atoms']) for a in actions if a['kind']=='pickup'],[9,9])
        first=min(a['t_start_us'] for a in reads);last=max(a['t_end_us'] for a in reads)
        self.assertFalse(any(a['kind'] in ('pickup','move','drop') and first <= a['t_start_us'] < last for a in actions))

    def test_H_then_Z_uses_current_code_sites_for_nonuniform_fake_bits(self):
        for chosen,expected in [('atom:block/d3',1),('atom:block/d1',0)]:
            device=canonical_surface17_device();compiler=LogicalComponentCompiler(device)
            session=EventSession(device,world(device),run_id='logical-readout-'+chosen)
            for name in ['H','MEASURE_Z']:
                dag=compiler.instantiate(name,namespace=name)
                context=session.compilation_context(dag)
                plan=compiler.compile_dags(dag,session.snapshot()['world_state'],execution_context=context)
                atom=bind_physical_plan(plan,context);scenario=make_scenario(atom,value=0)
                for a in atom['actions']:
                    if a['kind']=='measure' and a['atoms']==[chosen]:scenario['results'][a['payload']['result_id']]['value']=1
                session.submit(atom,scenario);session.advance()
            result=dag['component_binding']['logical_result_ports']['value']
            self.assertEqual(session.results[result]['value'],expected)

    def test_capacity_constraints_are_explicit_and_still_enforced(self):
        device,plan,_=self.compile();wrong=deepcopy(device)
        wrong['rigid_readout']['max_parallel_readouts']=8
        atom=deepcopy(plan['atom_program']);atom['input_hashes']['device']=digest(wrong)
        with self.assertRaisesRegex(ValueError,'READOUT_PROFILE_CONFLICT'):
            run(atom,make_scenario(atom),wrong)
        for bad in [0,-1,True,'unlimited']:
            invalid=deepcopy(device);invalid['rigid_readout']['max_parallel_readouts']=bad
            self.assertTrue(validate_device(invalid))


if __name__=='__main__':unittest.main()
