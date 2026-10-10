"""Lightweight source checks only; full geometry/trace stays in the R7 job."""
from copy import deepcopy
from pathlib import Path
import gzip,json,unittest

from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.dag_factory import inspect_factory_stage_source,candidate_motion_witness
from na_pipeline.validation.checker import _hash


class FrozenFactorySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[2]/'scripts/outputs/T704/server/20261006T152602272401Z-r4-factory-first-stage-205/result/examples/atom/t405/factory-stage-v1/input.json.gz'
        with gzip.open(path,'rt',encoding='utf-8') as f:cls.source=json.load(f)

    def check(self,inputs):
        dag=inputs['physical_dag'];plan={'physical_dags':[dag],'input_hashes':{'physical_dags':[_hash(dag)]}}
        audit=DAGAudit('source_only_test',{},fixture=True);inspect_factory_stage_source(audit,inputs,plan);return audit

    def test_actual_initialize_template_plus_service_resets(self):
        audit=self.check(self.source)
        self.assertEqual(audit.failures,[]);self.assertEqual(audit.unverified,[])
        self.assertEqual((audit.metrics['template_source_operations'],audit.metrics['readout_service_resets']),(1168,144))

    def test_non_two_qubit_gate_cannot_be_discarded(self):
        b=deepcopy(self.source);ops=b['physical_dag']['nodes'];ops.remove(next(o for o in ops if o['kind']=='gate' and len(o['qubits'])==1))
        self.assertIn('FACTORY_TEMPLATE_OPERATION_CHANGED',{f['code'] for f in self.check(b).failures})

    def test_reset_cannot_be_relabelled_as_encoded_input(self):
        b=deepcopy(self.source);op=next(o for o in b['physical_dag']['nodes'] if o['kind']=='reset');op['kind']='gate';op['params']={'name':'I'}
        self.assertIn('FACTORY_TEMPLATE_OPERATION_CHANGED',{f['code'] for f in self.check(b).failures})

    def test_live_target_reset_and_missing_service_dependency(self):
        b=deepcopy(self.source);member=b['physical_dag']['groups'][0]['members'][0];reset=next(o for o in b['physical_dag']['nodes'] if o['id']==member['post_readout_reset_op_id']);reset['qubits']=['w2/d0'];reset['after']=[]
        self.assertTrue({'FACTORY_SERVICE_RESET','FACTORY_LIVE_DATA_DESTROYED'}<={f['code'] for f in self.check(b).failures})


class CandidateMotionTests(unittest.TestCase):
    def setUp(self):
        self.candidate={'mover':'a','from_um':[140.,20.],'to_um':[122.,20.]}
        self.pulse={'id':'pulse','t_start_us':450.,'t_end_us':451.}
        self.actions=[{'id':'first','kind':'move','t_start_us':222.,'t_end_us':227.,'payload':{'trajectories':[{'atom_id':'a','from_um':[140.,20.],'to_um':[145.,22.5]}]}},
                      {'id':'last','kind':'move','t_start_us':227.,'t_end_us':250.,'payload':{'trajectories':[{'atom_id':'a','from_um':[145.,22.5],'to_um':[122.,20.]}]}},
                      {'id':'return','kind':'move','t_start_us':651.,'t_end_us':680.,'payload':{'trajectories':[{'atom_id':'a','from_um':[122.,20.],'to_um':[140.,20.]}]}}]
    def check(self):return candidate_motion_witness(self.candidate,self.actions,self.pulse)
    def test_actual_detour_and_later_return(self):
        witness=self.check();self.assertTrue(witness['passed']);self.assertEqual(witness['classification'],'continuous_multisegment');self.assertEqual(len(witness['legs']),2)
    def test_missing_real_motion(self):
        self.actions=[];self.assertEqual(self.check()['reason'],'missing_motion')
    def test_deleted_first_leg_is_not_a_continuous_route(self):
        self.actions.pop(0);self.assertEqual(self.check()['reason'],'discontinuous_path')
    def test_wrong_endpoint_is_not_a_route_to_candidate(self):
        self.actions[1]['payload']['trajectories'][0]['to_um']=[124.,20.];self.assertEqual(self.check()['reason'],'wrong_endpoint')
    def test_overlapping_or_pulse_concurrent_motion(self):
        self.actions[1]['t_start_us']=225.;self.assertEqual(self.check()['reason'],'overlapping_legs')
        self.actions[1]['t_start_us']=449.;self.actions[1]['t_end_us']=452.;self.assertEqual(self.check()['reason'],'motion_overlaps_pulse')
    def test_explicit_zero_displacement_only(self):
        self.actions=[];self.candidate['to_um']=self.candidate['from_um'];self.assertTrue(self.check()['passed']);self.assertEqual(self.check()['classification'],'zero_displacement')


if __name__=='__main__': unittest.main()
