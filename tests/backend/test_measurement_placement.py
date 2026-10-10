"""Measurement placement, source barriers, and actual parallel readout checks."""
from copy import deepcopy
from itertools import permutations
import random
import unittest

from na_pipeline.backend import compile_measurement_circuit, measurement_circuit_dag, StrategyError
from na_pipeline.backend.measurement_placement import minimum_cost_assignment, place_measurement_batch
from na_pipeline.device import preinitialized_device, build_preinitialized_state
from na_pipeline.runtime import make_scenario, run
from na_pipeline.validation.dag_physical import validate_physical_plan


def circuit(qubits=('d0','d1','d3','d4'), *, barrier=False):
    ops=[{'id':'m'+q, 'kind':'measure', 'qubits':['P/'+q], 'params':{'basis':'Z'},
          'writes':['bit:'+q], 'source_ids':['source:'+q]} for q in qubits]
    if barrier:
        ops.insert(2, {'id':'x', 'kind':'gate', 'qubits':['P/d8'], 'params':{'name':'X'}, 'source_ids':['source:x']})
    return {'schema_version':'measurement-circuit/0.1','artifact_id':'test',
            'measurement':{'zone_id':'measurement','parallel_contiguous':True,
                           'placement':'zac_style_min_cost_matching','return_to_source':True}, 'operations':ops}


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.device=preinitialized_device()
        self.state=build_preinitialized_state(self.device, {'P':{'aod_group':'data','basis':'Z','value':0}},
                    {'P':{'anchor_um':[0,900],'orientation':'x_vertical_z_horizontal'}},
                    placement_ref={'artifact_id':'test','producer':'test','fixture':True})

    def test_assignment_beats_greedy_and_matches_brute_force(self):
        costs=[[1.,2.],[1.1,100.]]
        self.assertEqual(minimum_cost_assignment(costs),[1,0])
        rng=random.Random(11)
        for n in range(1,5):
            for _ in range(12):
                matrix=[[rng.randrange(0,100)/7 for _ in range(n+1)] for _ in range(n)]
                got=minimum_cost_assignment(matrix)
                optimum=min(sum(matrix[i][j] for i,j in enumerate(p)) for p in permutations(range(n+1),n))
                self.assertAlmostEqual(sum(matrix[i][j] for i,j in enumerate(got)),optimum)

    def test_occupied_sites_excluded_and_insufficient_capacity_rejected(self):
        atoms=[{'atom_id':'a','qubit_id':'q','position_um':[0,0]}]
        sites=[{'trap_id':'near','position_um':[0,1],'occupant':'spectator','bank_id':'b','site_id':'0'},
               {'trap_id':'far','position_um':[0,5],'occupant':None,'bank_id':'b','site_id':'1'}]
        self.assertEqual(place_measurement_batch(atoms,sites,speed_um_per_us=1)['assignments'][0]['trap_id'],'far')
        with self.assertRaises(StrategyError):minimum_cost_assignment([[1],[2]])

    def test_contiguous_measurements_parallel_without_implicit_reset(self):
        c=circuit();before=deepcopy(c)
        plan=compile_measurement_circuit(c,self.device,self.state)
        atom=plan['atom_program'];trace=run(atom,make_scenario(atom,value=1),self.device)
        report=validate_physical_plan(plan,self.device,trace=trace)
        self.assertTrue(report['passed'],report)
        measurements=[a for a in atom['actions'] if a['kind']=='measure']
        self.assertEqual(len(measurements),4)
        self.assertEqual(len({a['t_start_us'] for a in measurements}),1)
        self.assertEqual(len({a['payload']['result_ready_us'] for a in measurements}),1)
        self.assertFalse(any(a['kind']=='reset' for a in atom['actions']))
        self.assertEqual(c,before)
        self.assertEqual(len({x['trap_id'] for x in plan['measurement_placements'][0]['assignments']}),4)

    def test_intervening_gate_separates_batches(self):
        c=circuit(barrier=True);dag=measurement_circuit_dag(c,self.state)
        byid={n['id']:n for n in dag['nodes']}
        self.assertEqual(set(byid['x']['after']),{'md0','md1'})
        self.assertEqual(byid['md3']['after'],['x'])
        plan=compile_measurement_circuit(c,self.device,self.state)
        batches=plan['measurement_placements'];self.assertEqual(len(batches),2)
        gate=next(a for a in plan['atom_program']['actions'] if a['kind']=='gate')
        self.assertGreaterEqual(gate['t_start_us'],batches[0]['measurement_end_us'])
        self.assertGreaterEqual(batches[1]['measurement_start_us'],gate['t_end_us'])

    def test_same_qubit_and_unsupported_basis_do_not_silently_parallelize(self):
        c=circuit();c['operations'][1]['qubits']=c['operations'][0]['qubits']
        with self.assertRaises(StrategyError) as caught:measurement_circuit_dag(c,self.state)
        self.assertEqual(caught.exception.code,'READOUT_QUBIT_ALIAS')
        c=circuit();c['operations'][0]['params']['basis']='X'
        with self.assertRaises(StrategyError) as caught:measurement_circuit_dag(c,self.state)
        self.assertEqual(caught.exception.code,'UNSUPPORTED_MEASUREMENT')

    def test_nine_measurements_do_not_invent_a_ninth_site(self):
        with self.assertRaises(StrategyError) as caught:
            compile_measurement_circuit(circuit(tuple('d'+str(i) for i in range(9))),self.device,self.state)
        self.assertEqual(caught.exception.code,'READOUT_CAPACITY_EXCEEDED')


if __name__=='__main__':unittest.main()
