"""R8 K01--K08 made executable plus T604 artifact mutation tests.

Knowledge cases remain untouched in R8. These are independent verifier tests.
"""
from copy import deepcopy
import gzip,json
from pathlib import Path
import unittest

from test_validation import fixture,action
from na_pipeline.validation import validate_strategy,validate_strategy_run
from na_pipeline.validation.checker import Audit,_hash
from na_pipeline.validation.geometry import check_geometry
from na_pipeline.validation.strategy_common import StrategyAudit
from na_pipeline.validation.strategy_capture import capture_closure
from na_pipeline.validation.strategy_groups import group_metrics,check_readout_capacity
from na_pipeline.validation.strategy_source import check_strategy_source
from na_pipeline.validation.strategy_enola import check_enola
from na_pipeline.validation.strategy_run import check_call_counters,check_bound_source


def grouped_pickup(plan,indices,start=0.):
    records=[]
    for i in indices:
        atom=plan['initial_state']['atoms'][i]
        records.append({'atom_id':atom['atom_id'],'from_trap_id':atom['trap_id'],'to_trap_id':f'ad{i}','row_id':f'r{i}','column_id':f'c{i}','position_um':atom['position_um']})
    return action(plan,'pickup',[f'a{i}' for i in indices],start,start+200,{'aod_group':'data','bindings':records})


class ReviewKnowledgeCases(unittest.TestCase):
    def audit(self): return StrategyAudit('fixture_component',{})

    def test_K01_unsafe_projection_drops_H(self):
        p,d=fixture([[0.,0.],[2.,0.]])
        ops=[]
        for i,(name,qubits) in enumerate([('CZ',['q0','q1']),('H',['q1']),('CZ',['q0','q1'])]):
            ops.append({'id':f'g{i}','kind':'gate','qubits':qubits,'params':{'name':name},'reads':[],'writes':[],'after':[f'g{i-1}'] if i else [],'source_ids':[f'g{i}'],'condition':None})
        for i in (0,2):
            a=action(p,'gate',['a0','a1'],i,i+1,{'name':'CZ','physical_op_id':f'g{i}','physical_op_ids':[f'g{i}'],'pairs':[['a0','a1']],'writes':[],'reads':[]})
            a['source_ids']=[f'g{i}']; p['source_map'][f'g{i}']=[a['id']]
        physical={'qubits':[{'id':'q0'},{'id':'q1'}]}; audit=self.audit()
        check_strategy_source(audit,physical,p,ops)
        self.assertIn('STRATEGY_SOURCE_OMITTED',{f['code'] for f in audit.failures})

    def test_K02_capture_omits_spectator(self):
        p,d=fixture([[0.,0.],[10.,10.],[0.,10.]])
        grouped_pickup(p,[0,1]); audit=self.audit(); capture_closure(audit,p,d)
        self.assertIn('CAPTURE_CARTESIAN_CLOSURE',{f['code'] for f in audit.failures})

    def test_K03_distinct_rows_cannot_merge(self):
        p,d=fixture([[0.,0.],[10.,10.]])
        grouped_pickup(p,[0,1])
        action(p,'move',['a0','a1'],200,300,{'aod_group':'data','interpolation':'linear','trajectories':[{'atom_id':'a0','from_um':[0.,0.],'to_um':[0.,100.],'row_id':'r0','column_id':'c0'},{'atom_id':'a1','from_um':[10.,10.],'to_um':[10.,100.],'row_id':'r1','column_id':'c1'}]})
        audit=Audit(); check_geometry(audit,p,d)
        self.assertIn('AXIS_CROSSING',{f['code'] for f in audit.failures})

    def test_K07_project_linear_axis_time(self):
        p,d=fixture([[0.,0.]])
        grouped_pickup(p,[0])
        movement=action(p,'move',['a0'],200,240,{'aod_group':'data','interpolation':'linear','trajectories':[{'atom_id':'a0','from_um':[0.,0.],'to_um':[30.,40.],'row_id':'r0','column_id':'c0'}]})
        minimum=max(30.,40.)/d['movement']['speed_um_per_us']
        self.assertEqual(minimum,40.)
        audit=Audit(); check_geometry(audit,p,d); self.assertEqual(audit.failures,[])
        movement['t_end_us']=239.; audit=Audit(); check_geometry(audit,p,d)
        self.assertIn('MOVE_SPEED',{f['code'] for f in audit.failures})

    def test_K08_legal_parallel_translation(self):
        p,d=fixture([[0.,0.],[10.,10.]])
        grouped_pickup(p,[0,1])
        action(p,'move',['a0','a1'],200,300,{'aod_group':'data','interpolation':'linear','trajectories':[{'atom_id':'a0','from_um':[0.,0.],'to_um':[0.,100.],'row_id':'r0','column_id':'c0'},{'atom_id':'a1','from_um':[10.,10.],'to_um':[10.,110.],'row_id':'r1','column_id':'c1'}]})
        audit=Audit(); check_geometry(audit,p,d); self.assertEqual(audit.failures,[])
        capture=self.audit(); capture_closure(capture,p,d); self.assertEqual(capture.failures,[])

    def test_empty_crosspoint_sweep_hits_spectator(self):
        p,d=fixture([[0.,0.],[10.,10.],[0.,15.]])
        grouped_pickup(p,[0,1])
        action(p,'move',['a0','a1'],200,210,{'aod_group':'data','interpolation':'linear','trajectories':[{'atom_id':'a0','from_um':[0.,0.],'to_um':[0.,10.],'row_id':'r0','column_id':'c0'},{'atom_id':'a1','from_um':[10.,10.],'to_um':[10.,20.],'row_id':'r1','column_id':'c1'}]})
        audit=self.audit(); capture_closure(audit,p,d)
        self.assertIn('CARTESIAN_SWEEP_CAPTURE',{f['code'] for f in audit.failures})

    def test_existing_active_axes_expand_next_capture(self):
        p,d=fixture([[0.,0.],[10.,10.],[0.,10.]])
        grouped_pickup(p,[0]); grouped_pickup(p,[1],start=200.)
        audit=self.audit(); capture_closure(audit,p,d)
        self.assertIn('CAPTURE_CARTESIAN_CLOSURE',{f['code'] for f in audit.failures})

    def test_empty_active_axes_are_not_omitted(self):
        p,d=fixture([[10.,0.],[0.,10.]])
        p['initial_state']['aod_rows']=[{'aod_group':'data','row_id':'empty-r','y_um':10.}]
        p['initial_state']['aod_columns']=[{'aod_group':'data','column_id':'empty-c','x_um':0.}]
        grouped_pickup(p,[0]); audit=self.audit(); capture_closure(audit,p,d)
        self.assertIn('CAPTURE_CARTESIAN_CLOSURE',{f['code'] for f in audit.failures})

    def test_move_cannot_cross_an_empty_active_row(self):
        p,d=fixture([[0.,0.]])
        p['initial_state']['aod_rows']=[{'aod_group':'data','row_id':'empty-r','y_um':10.}]
        grouped_pickup(p,[0])
        action(p,'move',['a0'],200,220,{'aod_group':'data','interpolation':'linear','trajectories':[{'atom_id':'a0','from_um':[0.,0.],'to_um':[0.,20.],'row_id':'r0','column_id':'c0'}]})
        audit=self.audit(); capture_closure(audit,p,d)
        self.assertIn('ACTIVE_AXIS_ORDER',{f['code'] for f in audit.failures})

    def test_minimal_rejections_are_executable(self):
        self.assertEqual(validate_strategy({}, {})['failures'][0]['code'],'STRATEGY_INPUT_MISSING')
        self.assertEqual(validate_strategy_run({}, {})['failures'][0]['code'],'STRATEGY_RUN_INPUT_MISSING')

    def test_counted_composition_retries_are_legal(self):
        counters={k:0 for k in ('strategy_compile_count','placement_search_count','routing_search_count','cache_hit_count','bind_count','composition_check_count')}
        call={'call_id':'retry-fixture','library_stats_before':counters,'library_stats_after':{**counters,'bind_count':2,'composition_check_count':3},'composition_retries':[{'code':'RESOURCE_LEASE_CONFLICT','from_us':0.,'to_us':10.},{'code':'JOINT_CAPTURE','from_us':10.,'to_us':20.}],'binding':{'start_time_us':20.}}
        audit=self.audit(); check_call_counters(audit,call,True); self.assertEqual(audit.failures,[])
        call['library_stats_after']['composition_check_count']=1
        audit=self.audit(); check_call_counters(audit,call,True)
        self.assertIn('BIND_COMPOSITION_COUNT',{f['code'] for f in audit.failures})


class RealStrategyMutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[2]/'knowledge/roles/R6/evidence/T604/inputs.json.gz'
        cls.bundle=json.loads(gzip.decompress(path.read_bytes()))
        cls.device=cls.bundle['device']; cls.evidence=cls.bundle['enola_evidence']
        cls.strategies=list(cls.bundle['strategies'].values())
        cls.syndrome=next(s for s in cls.strategies if s['body']['strategy_contract']['operation']['name']=='syndrome_round')
        cls.prepare=next(s for s in cls.strategies if s['body']['strategy_contract']['operation']['name']=='prepare')

    def test_actual_complete_syndrome_strategy(self):
        report=validate_strategy(self.syndrome,self.device,enola_evidence=self.evidence)
        self.assertTrue(report['passed'],report['failures'][:4])
        self.assertEqual(report['metrics']['groups'][0]['readout_start_span_us'],0)

    def test_observed_source_paths_are_portable_but_hashes_remain_exact(self):
        for prefix,separator in [('C:\\producer\\src\\','\\'),('/home/producer/src/','/')]:
            evidence=deepcopy(self.evidence)
            observations=list(evidence.get('observations',{}).values())
            if evidence.get('observation'):observations.append(evidence['observation'])
            for observation in observations:
                observation['project_source_hashes']={prefix+p.replace('\\','/').rsplit('/',1)[-1]:h
                    for p,h in observation['project_source_hashes'].items()}
            report=validate_strategy(self.syndrome,self.device,enola_evidence=evidence)
            self.assertTrue(report['passed'],report['failures'])
            for observation in observations:
                name=next(iter(observation['project_source_hashes']))
                observation['project_source_hashes'][name]='0'*64
            rejected=validate_strategy(self.syndrome,self.device,enola_evidence=evidence)
            self.assertIn('COMPILER_OBSERVATION_IDENTITY',{f['code'] for f in rejected['failures']})

    def test_K04_basis_not_ready_at_readout(self):
        body=deepcopy(self.syndrome['body']); p=body['physical_program']; a=body['atom_program']; member=p['strategy_contract']['groups'][0]['members'][0]
        gate=next(x for x in a['actions'] if x['id'] in a['source_map'][member['basis_change_op_id']] and x['kind']=='gate')
        read=next(x for x in a['actions'] if x['kind']=='measure' and x['payload']['result_id']==member['result_id'])
        gate['t_end_us']=read['t_start_us']+10
        audit=StrategyAudit('mutant',{}); group_metrics(audit,a,p)
        self.assertIn('GROUP_READOUT_TOO_EARLY',{f['code'] for f in audit.failures})

    def test_K05_partial_patch_transport(self):
        body=deepcopy(self.prepare['body']); p,a=body['physical_program'],body['atom_program']
        data={atom['atom_id'] for atom in a['initial_state']['atoms'] if '/d' in atom['qubit_id']}
        for x in a['actions']:
            if x['kind']=='move' and x['payload'].get('purpose')=='patch_initialization_transport':
                x['atoms']=[aid for aid in x['atoms'] if aid in data]; x['payload']['trajectories']=[t for t in x['payload']['trajectories'] if t['atom_id'] in data]
        audit=StrategyAudit('mutant',{}); group_metrics(audit,a,p)
        self.assertIn('INITIALIZATION_TRANSPORT_OMITTED',{f['code'] for f in audit.failures})

    def test_K06_unrelated_kernel_result(self):
        s=deepcopy(self.syndrome)
        pulse=next(a for a in s['body']['atom_program']['actions'] if a['payload'].get('name')=='CZ'); pulse['payload']['enola_decision_hash']='unrelated'
        audit=StrategyAudit('mutant',{}); check_enola(audit,s,self.evidence,None)
        self.assertIn('ENOLA_OUTPUT_UNUSED',{f['code'] for f in audit.failures})

    def test_shared_CZ_wrong_source_pair(self):
        s=deepcopy(self.syndrome); a=s['body']['atom_program']; p=s['body']['physical_program']
        pulse=next(x for x in a['actions'] if len(x['payload'].get('pair_sources',[]))>1)
        pulse['payload']['pair_sources'][0]['physical_op_id']='wrong-instance'
        from na_pipeline.qec import iter_physical_ops
        audit=StrategyAudit('mutant',{}); check_strategy_source(audit,p,a,list(iter_physical_ops(p)))
        self.assertIn('SHARED_CZ_SOURCE',{f['code'] for f in audit.failures})

    def test_capacity_cannot_be_fixed_by_statistics(self):
        p=self.syndrome['body']['atom_program']; d=deepcopy(self.device); d['grouped_profile']['readout']['bank_capacity']=4
        low=Audit(); geometry=check_geometry(low,p,d)
        audit=StrategyAudit('mutant',{}); check_readout_capacity(audit,p,d,geometry)
        self.assertIn('READOUT_CAPACITY_EXCEEDED',{f['code'] for f in audit.failures})

    def test_observation_absence_not_full_pass(self):
        r=validate_strategy(self.syndrome,self.device)
        self.assertFalse(r['passed']); self.assertIn('ENOLA_OBSERVATION_MISSING',{x['code'] for x in r['unverified']})

    def test_strategy_body_change_invalidates_hash(self):
        s=deepcopy(self.syndrome); s['body']['strategy_contract']['operation']['encoding']['orientation']='mirrored'
        r=validate_strategy(s,self.device,enola_evidence=self.evidence)
        self.assertIn('STRATEGY_BODY_HASH',{f['code'] for f in r['failures']})

    def test_fake_values_cannot_be_cached(self):
        s=deepcopy(self.syndrome); s['body']['results']={'slot':{'value':1,'origin':'fake'}}; s['strategy_hash']=_hash(s['body'])
        r=validate_strategy(s,self.device,enola_evidence=self.evidence)
        self.assertIn('STRATEGY_CACHED_INSTANCE_STATE',{f['code'] for f in r['failures']})

    def test_cache_key_cannot_ignore_profile(self):
        s=deepcopy(self.syndrome); s['body']['cache_key']='0'*64; s['strategy_hash']=_hash(s['body'])
        r=validate_strategy(s,self.device,enola_evidence=self.evidence)
        self.assertIn('STRATEGY_CACHE_KEY',{f['code'] for f in r['failures']})

    def test_bank_rename_does_not_remove_physical_site_conflict(self):
        p=deepcopy(self.syndrome['body']['atom_program']); low=Audit(); geometry=check_geometry(low,p,self.device)
        a,b=[a for a in p['actions'] if a['kind']=='measure'][:2]
        b['payload']['bank_id']='different-bank'
        geometry['snapshots'][(b['id'],'before')][b['atoms'][0]]['position_um']=geometry['snapshots'][(a['id'],'before')][a['atoms'][0]]['position_um'][:]
        audit=StrategyAudit('fixture_site_collision',{}); check_readout_capacity(audit,p,self.device,geometry)
        self.assertIn('READOUT_SITE_CONFLICT',{f['code'] for f in audit.failures})

    def test_epoch_reuse_is_rejected(self):
        b=self.bundle; run=deepcopy(b['run']); run['instances'][1]['binding']['epoch']=run['instances'][0]['binding']['epoch']
        r=validate_strategy_run(run,b['device'],strategies=b['strategies'],enola_evidence=b['enola_evidence'])
        self.assertIn('CALL_EPOCH_REUSED',{f['code'] for f in r['failures']})

    def test_repeated_call_search_counter_rejected(self):
        b=self.bundle; run=deepcopy(b['run']); run['instances'][3]['library_stats_after']['routing_search_count']+=1
        r=validate_strategy_run(run,b['device'],strategies=b['strategies'],enola_evidence=b['enola_evidence'])
        self.assertIn('REUSE_RECOMPILED',{f['code'] for f in r['failures']})

    def test_missing_project_search_observation_is_unverified(self):
        b=self.bundle; evidence=deepcopy(b['enola_evidence']); next(iter(evidence['binding_observations'].values())).pop('project_search_counts')
        r=validate_strategy_run(b['run'],b['device'],strategies=b['strategies'],enola_evidence=evidence)
        self.assertFalse(r['passed']); self.assertIn('BIND_PROJECT_SEARCH_OBSERVATION_MISSING',{u['code'] for u in r['unverified']})

    def test_route_prechecks_cannot_disappear_from_counter(self):
        s=deepcopy(self.syndrome); s['body']['atom_program']['stats']['routing_search_count']-=1
        audit=StrategyAudit('mutant',{}); check_enola(audit,s,self.evidence,None)
        self.assertIn('ROUTING_SEARCH_COUNTER_MISMATCH',{f['code'] for f in audit.failures})

    def test_distinct_fake_bits_stay_instance_local(self):
        from na_pipeline.runtime import run as execute,make_scenario
        from na_pipeline.validation.strategy import inspect_strategy_plan
        plan=self.bundle['run']['atom_program']; scenario=make_scenario(plan,value=0)
        for index,value in enumerate(scenario['results'].values()): value['value']=index%2
        trace=execute(plan,scenario,self.device)
        self.assertEqual({r:v['value'] for r,v in trace['results'].items()},{r:v['value'] for r,v in scenario['results'].items()})
        self.assertGreater(trace['stats']['skipped_action_count'],0)
        audit=StrategyAudit('mixed_fake_plan',{}); inspect_strategy_plan(audit,plan,self.device,trace=trace)
        self.assertEqual(audit.failures,[]); self.assertEqual(audit.unverified,[])

    def test_result_writer_cannot_point_to_another_call(self):
        from na_pipeline.validation.trace import check_trace
        b=self.bundle; trace=deepcopy(b['run']['event_trace']); results=list(trace['results'].values())
        results[0]['action_id']=results[-1]['action_id']
        audit=Audit(); check_trace(audit,b['run']['atom_program'],b['device'],trace,None)
        self.assertIn('RESULT_INSTANCE',{f['code'] for f in audit.failures})

    def test_bound_source_cannot_rewrite_immutable_semantics(self):
        from na_pipeline.qec import iter_physical_ops
        instance=self.bundle['run']['instances'][0]; strategy=self.bundle['strategies'][instance['strategy_id']]
        ops=list(iter_physical_ops(instance['physical_program']))
        next(op for op in ops if op['kind']=='gate')['params']['name']='Z'
        audit=StrategyAudit('mutant',{}); check_bound_source(audit,instance,strategy,ops)
        self.assertIn('CALL_SOURCE_SEMANTICS_CHANGED',{f['code'] for f in audit.failures})

    def test_actual_controller_run(self):
        b=self.bundle; r=validate_strategy_run(b['run'],b['device'],strategies=b['strategies'],enola_evidence=b['enola_evidence'])
        self.assertTrue(r['passed'],(r['failures'][:4],r['unverified'][:4]))
        self.assertEqual(r['metrics']['cycle_duration_us'],b['run']['event_trace']['stats']['duration_us'])
        self.assertEqual(len(r['metrics']['call_cycle_duration_us']),11)


if __name__=='__main__': unittest.main()
