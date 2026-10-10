"""Carrier continuity and full-width readout regression checks."""
from copy import deepcopy
import unittest

from na_pipeline.device import canonical_surface17_device, build_preinitialized_state, validate_device
from na_pipeline.qec import get_component_spec
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.runtime import make_scenario, run
from na_pipeline.validation.dag_physical import validate_physical_plan


class HeldCZTests(unittest.TestCase):
    def world(self, device, names, shift=0.):
        return build_preinitialized_state(device,{n:{'aod_group':'data','basis':'Z','value':0} for n in names},
            {n:{'anchor_um':[shift+100*i,900.],'orientation':'x_vertical_z_horizontal'} for i,n in enumerate(names)},
            placement_ref={'artifact_id':'held-cz-test','producer':'R0','fixture':True})

    def compile(self, name, device, world):
        compiler=LogicalComponentCompiler(device)
        dag=get_component_spec(name)['physical_dag']
        compiler.build_dependencies(dag,world)
        plan=compiler.compose_recipe(dag,world)
        trace=run(plan['atom_program'],make_scenario(plan['atom_program']),device)
        report=validate_physical_plan(plan,device,trace=trace)
        self.assertTrue(report['passed'],{k:report[k] for k in ('failures','unverified')})
        return plan,trace

    def test_nine_pairs_hold_AOD_through_CZ_and_drop_only_at_home(self):
        device=canonical_surface17_device();world=self.world(device,('control','target'))
        plan,trace=self.compile('CX',device,world);a=plan['atom_program']
        actions=a['actions'];self.assertEqual(sum(x['kind']=='pickup' for x in actions),1)
        self.assertEqual(sum(x['kind']=='drop' for x in actions),1)
        carrier={x['atom_id']:x['carrier'] for x in world['atoms']}
        for x in sorted(actions,key=lambda x:(x['t_start_us'],x['t_end_us'])):
            if x['kind']=='pickup':
                for q in x['atoms']:carrier[q]='AOD'
            elif x['kind']=='drop':
                for q in x['atoms']:carrier[q]='SLM'
            elif x['kind']=='gate' and x['payload']['name']=='CZ':
                self.assertEqual(len(x['payload']['pairs']),9)
                for p in x['payload']['pairs']:self.assertEqual({carrier[q] for q in p},{'AOD','SLM'})
                self.assertTrue(any(r.startswith('aod:data:row:') for r in x['resources']))
        self.assertTrue(all(v=='SLM' for v in carrier.values()))
        initial={x['atom_id']:x['position_um'] for x in world['atoms']}
        final=trace['final_state']['atoms'];final=final.values() if isinstance(final,dict) else final
        for x in final:self.assertEqual(x['position_um'],initial[x['atom_id']])
        self.assertLessEqual(a['stats']['duration_us'],417.)  # frozen pre-search baseline

    def test_measurement_strip_supports_negative_and_large_x(self):
        device=canonical_surface17_device();self.assertEqual(device['zones']['measurement']['x_range_um'],[None,None])
        for shift in (-10000.,10000.):
            plan,_=self.compile('MEASURE_Z',device,self.world(device,('block',),shift))
            placement=plan['measurement_placements'][0]
            self.assertEqual(placement['translation_um'][0],0.)
        bad=deepcopy(device);bad['zones']['measurement']['x_range_um']=[None,100.]
        self.assertTrue(validate_device(bad))


if __name__=='__main__':unittest.main()
