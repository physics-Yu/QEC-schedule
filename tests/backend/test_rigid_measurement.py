from copy import deepcopy
from itertools import combinations
import unittest

from na_pipeline.backend import compile_measurement_circuit, StrategyError
from na_pipeline.device import rigid_readout_device, build_preinitialized_state, validate_device, validate_readout_batch
from na_pipeline.runtime import run, make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan


class RigidMeasurementTests(unittest.TestCase):
    def world(self,device):
        return build_preinitialized_state(device,{'P':{'aod_group':'data','basis':'Z','value':0}},
               {'P':{'anchor_um':[0,900],'orientation':'x_vertical_z_horizontal'}},
               placement_ref={'artifact_id':'rigid-test','producer':'test','fixture':True})

    def circuit(self,qubits):
        return {'schema_version':'measurement-circuit/0.1','artifact_id':'rigid-test',
                'measurement':{'zone_id':'measurement','parallel_contiguous':True,'placement':'rigid_array_translation','return_to_source':True},
                'operations':[{'id':'m'+q,'kind':'measure','qubits':['P/'+q],'params':{'basis':'Z'},'writes':['bit:'+q],'source_ids':['source:'+q]} for q in qubits]}

    def compile(self,qubits):
        d=rigid_readout_device();initial=self.world(d)
        p=compile_measurement_circuit(self.circuit(qubits),d,initial)
        a=p['atom_program'];trace=run(a,make_scenario(a,value=1),d)
        return d,initial,p,trace

    def assert_rigid_and_returned(self,initial,plan,trace):
        a=plan['atom_program'];batch=plan['measurement_placements'][0]
        members=set(batch['captured_atoms'])
        self.assertEqual(len(batch['outbound']),1);self.assertEqual(len(batch['returned']),1)
        for move in (x for x in a['actions'] if x['kind']=='move'):
            self.assertEqual(set(move['atoms']),members)
            for left,right in combinations(move['payload']['trajectories'],2):
                for k in (0,1):
                    self.assertAlmostEqual(left['from_um'][k]-right['from_um'][k],left['to_um'][k]-right['to_um'][k])
        self.assertFalse(any(x['kind']=='reset' for x in a['actions']))
        final=trace['final_state']['atoms'];final={x['atom_id']:x for x in final} if isinstance(final,list) else final
        for atom in initial['atoms']:self.assertEqual(final[atom['atom_id']]['position_um'],atom['position_um'])

    def test_rectangular_array_one_parallel_in_out(self):
        d,i,p,t=self.compile(['d0','d1','d3','d4'])
        self.assert_rigid_and_returned(i,p,t)
        self.assertEqual(len(p['measurement_placements'][0]['captured_atoms']),4)
        self.assertTrue(validate_physical_plan(p,d,trace=t)['passed'])

    def test_capture_spectators_move_but_never_measure_them(self):
        d,i,p,t=self.compile(['d2','d5','d7'])
        self.assert_rigid_and_returned(i,p,t)
        b=p['measurement_placements'][0]
        self.assertEqual(set(b['spectator_atoms']),{'atom:P/d1','atom:P/d4','atom:P/d8'})
        measured=[a for a in p['atom_program']['actions'] if a['kind']=='measure']
        self.assertEqual({a['atoms'][0] for a in measured},{'atom:P/d2','atom:P/d5','atom:P/d7'})
        self.assertEqual(len({a['t_start_us'] for a in measured}),1)
        self.assertTrue(validate_physical_plan(p,d,trace=t)['passed'])

    def test_small_region_fails_without_squeezing_or_split(self):
        d=rigid_readout_device(y_range_um=(1020.,1040.))
        with self.assertRaises(StrategyError) as caught:
            compile_measurement_circuit(self.circuit(['d2','d5','d7']),d,self.world(d))
        self.assertEqual(caught.exception.code,'RIGID_ARRAY_DOES_NOT_FIT')

    def test_larger_region_does_not_invent_readout_capacity(self):
        d=rigid_readout_device()
        with self.assertRaises(StrategyError) as caught:
            compile_measurement_circuit(self.circuit(['d'+str(j) for j in range(9)]),d,self.world(d))
        self.assertEqual(caught.exception.code,'READOUT_CAPACITY_EXCEEDED')

    def test_forged_lattice_site_fails_runtime_and_independent_receiver(self):
        d,i,p,t=self.compile(['d0','d1','d3','d4'])
        broken=deepcopy(p);m=next(a for a in broken['atom_program']['actions'] if a['kind']=='measure')
        m['payload']['site_id']='grid:999:999'
        with self.assertRaises(Exception):run(broken['atom_program'],make_scenario(broken['atom_program'],value=1),d)
        report=validate_physical_plan(broken,d,trace=None)
        self.assertFalse(report['passed'])
        self.assertIn('RIGID_MZ_SITE_POSITION',{x['code'] for x in report['failures']})

    def test_profile_origin_and_grid_are_bound(self):
        d=rigid_readout_device();d['rigid_readout']['site_origin_um'][0]+=1
        self.assertTrue(validate_device(d))
        d=rigid_readout_device();d['rigid_readout']['site_pitch_um']=float('nan')
        self.assertTrue(validate_device(d))


if __name__=='__main__':unittest.main()
