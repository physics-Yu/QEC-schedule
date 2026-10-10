"""R8 timing/state counterexamples executed as explicit verifier fixtures."""
from copy import deepcopy
import gzip,json
from pathlib import Path
import unittest

from na_pipeline.validation.checker import _hash
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.dag_resources import validate_resource_world,validate_resource_pool,inspect_protocol_completion


def event(action,*,status='completed'):
    return {**deepcopy({k:v for k,v in action.items() if k!='id'}),'action_id':action['id'],'status':status,'result_ids':action['payload'].get('writes',[])}


def action(identity,kind,atoms,begin,end,payload=None,condition=None):
    return {'id':identity,'kind':kind,'atoms':atoms,'t_start_us':float(begin),'t_end_us':float(end),'payload':payload or {},'condition':condition,'depends_on':[]}


class ResourceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=Path(__file__).resolve().parents[2]/'examples/atom/t405/resource-world-server-v1/world.json.gz'
        b=json.loads(gzip.decompress(p.read_bytes()));cls.requirements=b['requirements'];cls.initial=b['initial_state']

    def make_pool_fixture(self):
        req=deepcopy(self.requirements); initial=deepcopy(self.initial); target='w2'
        resources=[target if r=='operand:block' else r for r in req['lease_rules']['S_SDG']['exclusive']]
        mapping={a['qubit_id']:a['atom_id'] for a in initial['atoms']}
        resetq={q for q in mapping if q.startswith('factory0:Y/') or q=='factory0:join_probe'}
        actions=[action('last-target-Z','gate',[mapping[target+'/d0']],99,100,{'name':'Z'})]
        actions += [action('reset:'+q,'reset',[mapping[q]],100,110,{'state':0,'params':{'basis':'Z'}}) for q in sorted(resetq)]
        program={'actions':actions,'fixture':True}; h=_hash(program)
        lease={'owner':'S0','operation':'S','target_patch':target,'resources':resources,'epoch':0,'acquired_us':0.,'session_run_id':'fixture-only','entry_revision':0,'entry_plan_count':0,'requirements_hash':_hash(req),'ready_magic_token':None}
        release={'event':'release','owner':'S0','epoch':0,'released_us':110.,'cleanup_action_ids':[a['id'] for a in actions[1:]],'reset_qubit_ids':sorted(resetq),'released_state':{'kind':'physical_basis','basis':'Z','value':0,'encoding_status':'not_asserted_encoded'},'committed_plan_hashes':[h]}
        pool={'schema_version':'finite-resource-pool/0.1','requirements_hash':_hash(req),'qubit_to_atom':mapping,'active_leases':{},'next_epoch':1,'history':[{'event':'acquire',**lease},release],'initial_ready_magic_tokens':[]}
        trace={'run_id':'fixture-only','submitted_plans':[{'plan_hash':h,'submitted_us':0.,'action_ids':[a['id'] for a in actions]}],'events':[event(a) for a in actions],'results':{},'final_state':{'atoms':deepcopy(initial['atoms']),'time_us':110.}}
        return req,initial,pool,[program],trace

    def test_real_205_initial_world_only(self):
        r=validate_resource_world(self.requirements,self.initial)
        self.assertTrue(r['passed'],r['failures']);self.assertFalse(r['full_program_passed']);self.assertEqual(r['metrics']['world_carriers'],205)

    def test_borrowed_extra_Y_or_missing_probe_rejected(self):
        req=deepcopy(self.requirements);req['shared_phase_scratch']['phase_aux']='invented:Y'
        initial=deepcopy(self.initial);initial['atoms']=[a for a in initial['atoms'] if a['qubit_id']!='factory0:join_probe']
        r=validate_resource_world(req,initial,fixture=True)
        self.assertTrue({'RESOURCE_WORLD_INCOMPLETE','RESOURCE_PHASE_ALIAS'}<={f['code'] for f in r['failures']})

    def test_valid_release_is_only_a_fixture_component(self):
        r=validate_resource_pool(*self.make_pool_fixture(),fixture=True)
        self.assertTrue(r['passed'],r['failures']);self.assertFalse(r['full_program_passed']);self.assertEqual(r['metrics']['released_leases'],1)

    def test_N03_last_data_Z_is_not_Y_cleanup_completion(self):
        b=self.make_pool_fixture();b[2]['history'][1]['released_us']=100.
        r=validate_resource_pool(*b,fixture=True)
        self.assertIn('PROTOCOL_EARLY_RELEASE',{f['code'] for f in r['failures']})

    def test_N04_physical_reset_is_not_encoded_zero(self):
        b=self.make_pool_fixture();b[2]['history'][1]['released_state']={'kind':'encoded','logical_basis':'Z','value':0}
        r=validate_resource_pool(*b,fixture=True)
        self.assertIn('POOL_RESET_NOT_ENCODED',{f['code'] for f in r['failures']})

    def test_missing_terminal_and_cross_epoch_reset(self):
        b=self.make_pool_fixture();b[4]['events'].pop();b[2]['history'][0]['acquired_us']=1.
        r=validate_resource_pool(*b,fixture=True)
        self.assertIn('PROTOCOL_TERMINAL_PENDING',{f['code'] for f in r['failures']})

    def test_all_results_ready_before_release(self):
        read=action('read','measure',['a'],0,10,{'writes':['m']}); correction=action('z','gate',['d'],11,12,{'name':'Z','reads':['m']},{'bit':'m','equals':1})
        trace={'events':[event(read),event(correction)],'results':{'m':{'action_id':'read','value':1,'ready_us':20.}}}
        a=DAGAudit('fixture',{},fixture=True);inspect_protocol_completion(a,[{'actions':[read,correction]}],trace,12.)
        self.assertTrue({'PROTOCOL_RESULT_PENDING','PROTOCOL_READ_NOT_READY'}<={f['code'] for f in a.failures})

    def test_unselected_correction_need_not_execute(self):
        read=action('read','measure',['a'],0,10,{'writes':['m']}); correction=action('z','gate',['d'],11,12,{'name':'Z','reads':['m']},{'bit':'m','equals':1})
        trace={'events':[event(read),event(correction,status='skipped')],'results':{'m':{'action_id':'read','value':0,'ready_us':10.}}}
        a=DAGAudit('fixture',{},fixture=True);inspect_protocol_completion(a,[{'actions':[read,correction]}],trace,12.)
        self.assertEqual(a.failures,[])

    def test_overlap_S_T_shared_mutex(self):
        b=self.make_pool_fixture();lease=deepcopy(b[2]['history'][0]);lease.update(owner='T1',epoch=1,operation='T',resources=[lease['target_patch'] if r=='operand:block' else r for r in b[0]['lease_rules']['T_TDG']['exclusive']])
        b[2]['history'].insert(1,lease);b[2]['next_epoch']=2;b[2]['active_leases']={'T1':{k:v for k,v in lease.items() if k!='event'}}
        r=validate_resource_pool(*b,fixture=True)
        self.assertIn('POOL_OVERLAPPING_LEASE',{f['code'] for f in r['failures']})

    def test_live_data_reset_not_a_pool_cleanup(self):
        b=self.make_pool_fixture();a=action('bad-live-reset','reset',['atom:w2/d0'],100,110,{'state':0});b[3][0]['actions'].append(a);b[4]['events'].append(event(a));h=_hash(b[3][0]);b[2]['history'][1]['committed_plan_hashes']=[h];b[4]['submitted_plans'][0].update(plan_hash=h,action_ids=[a['id'] for a in b[3][0]['actions']])
        r=validate_resource_pool(*b,fixture=True)
        self.assertIn('POOL_LIVE_DATA_DESTROYED',{f['code'] for f in r['failures']})

    def test_later_reset_cannot_reuse_old_clean_receipt(self):
        b=self.make_pool_fixture();a=action('later-reset','reset',['atom:factory0:Y/d0'],110,112,{'state':1,'params':{'basis':'Z'}})
        b[3][0]['actions'].append(a);b[4]['events'].append(event(a));h=_hash(b[3][0]);b[2]['history'][1].update(committed_plan_hashes=[h],released_us=112.)
        b[4]['submitted_plans'][0].update(plan_hash=h,action_ids=[a['id'] for a in b[3][0]['actions']]);b[4]['final_state']['time_us']=112.
        r=validate_resource_pool(*b,fixture=True)
        self.assertIn('POOL_RESET_NOT_FINAL',{f['code'] for f in r['failures']})


if __name__=='__main__': unittest.main()
