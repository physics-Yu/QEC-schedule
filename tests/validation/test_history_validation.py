"""Independent byte-chain, duplicate and malformed-history rejection fixtures."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import gzip,json,tempfile,unittest

from na_pipeline.validation import validate_session_history
from na_pipeline.validation.checker import _hash
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.dag_history import reconstruct_history,inspect_history_checkpoints


class HistoryValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='history-fixture-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.chunks=[];self.bodies=[];self.world={'time_us':0.,'atoms':[{'atom_id':'a','qubit_id':'q','position_um':[0.,0.],'carrier':'SLM','trap_id':'s','aod_group':'data','row_id':None,'column_id':None}],'slm_traps':[],'aod_rows':[],'aod_columns':[]}
        previous=None
        for i in range(2):
            begin=float(i);end=begin+1;aid=f'window:{i}/a';action={'id':aid,'kind':'classical' if i==0 else 'gate','atoms':[] if i==0 else ['a'],'t_start_us':begin,'t_end_us':end,'payload':{'writes':['m']} if i==0 else {'name':'X'},'condition':None,'depends_on':[]}
            event={**{k:v for k,v in action.items() if k!='id'},'action_id':aid,'status':'completed','state_after':{} if i==0 else {'a':self.world['atoms'][0]}}
            results={'m':{'action_id':aid,'ready_us':1.,'value':0,'origin':'fake'}} if i==0 else {}
            body={'schema_version':'event-session-chunk/0.1','run_id':'history-fixture','sequence':i,'runtime_source_hashes':{'session.py':'fixturehash'},'start_us':begin,'end_us':end,'actions':{aid:action},'events':{aid:event},'results':results,'submitted_plans':[{'plan_hash':_hash(action),'action_ids':[aid],'sequence':i,'submitted_us':begin}],
                  'final_state':{**deepcopy(self.world),'time_us':end},'illumination_counts':{'a':0},'quantum_state_simulated':False,'hardware_executed':False,'sampled':False,'previous_chain_sha256':previous}
            record=self.write_body(body,previous);self.chunks.append(record);self.bodies.append(body);previous=record['chain_sha256']
        self.trace={'schema_version':'event-session-trace/0.2','run_id':'history-fixture','provenance':{'runtime_source_hashes':{'session.py':'fixturehash'}},'history_chunks':self.chunks,'events':[],'results':{},'submitted_plans':[],'retained_events_may_also_appear_in_chunks':True,'final_state':deepcopy(self.bodies[-1]['final_state']),'illumination_counts':{'a':0},'complete_submitted_prefix':True,'stats':{'action_count':2,'completed_action_count':2,'result_count':1,'t_end_us':2.}}

    def write_body(self,body,previous):
        path=self.root/f"{body['sequence']:03}.json.gz";raw=gzip.compress(json.dumps(body,sort_keys=True).encode('utf-8'),mtime=0);path.write_bytes(raw)
        record={'path':str(path),'byte_sha256':sha256(raw).hexdigest(),'size_bytes':len(raw),'previous_chain_sha256':previous,'action_count':len(body['actions']),'result_count':len(body['results']),'plan_count':len(body['submitted_plans']),'start_us':body['start_us'],'end_us':body['end_us']}
        record['chain_sha256']=_hash({k:v for k,v in record.items() if k!='path'})
        return record

    def report(self,trace=None,**kw):return validate_session_history(self.trace if trace is None else trace,fixture=True,**kw)
    def codes(self,trace=None,**kw):return {f['code'] for f in self.report(trace,**kw)['failures']}

    def test_full_history_and_identical_retained_producer_dedup(self):
        self.trace['events']=[deepcopy(next(iter(self.bodies[0]['events'].values())))];self.trace['results']=deepcopy(self.bodies[0]['results'])
        report=self.report();self.assertTrue(report['passed'],report['failures']);self.assertFalse(report['full_program_passed'])
        self.assertEqual((report['metrics']['history_events'],report['metrics']['retained_events_deduplicated'],report['metrics']['retained_results_deduplicated']),(2,1,1))

    def test_missing_file(self):
        (self.root/'000.json.gz').unlink();self.assertIn('HISTORY_CHUNK_UNREADABLE',self.codes())

    def test_changed_bytes(self):
        (self.root/'000.json.gz').write_bytes(b'changed');self.assertIn('HISTORY_CHUNK_BYTES',self.codes())

    def test_reordered_chunks(self):
        self.trace['history_chunks']=list(reversed(self.chunks));self.assertIn('HISTORY_CHAIN',self.codes())

    def test_same_retained_id_different_event_rejected(self):
        e=deepcopy(next(iter(self.bodies[0]['events'].values())));e['payload']['writes']=[];self.trace['events']=[e]
        self.assertIn('HISTORY_RETAINED_RECORD_CONFLICT',self.codes())

    def test_same_retained_id_different_result_rejected(self):
        self.trace['results']=deepcopy(self.bodies[0]['results']);self.trace['results']['m']['value']=1
        self.assertIn('HISTORY_RETAINED_RECORD_CONFLICT',self.codes())

    def test_suffix_only_totals_do_not_qualify_history(self):
        self.trace['stats'].update(action_count=0,completed_action_count=0,result_count=0)
        self.assertIn('HISTORY_CUMULATIVE_COUNTS',self.codes())

    def test_rehashed_manifest_cannot_hide_incorrect_sequence_or_count(self):
        r=self.trace['history_chunks'][1];r['action_count']=3;r['chain_sha256']=_hash({k:v for k,v in r.items() if k not in ('path','chain_sha256')})
        self.assertIn('HISTORY_MANIFEST_COUNTS',self.codes())

    def test_exact_byte_relocation_from_windows_manifest(self):
        for record in self.trace['history_chunks']:record['path']='C:\\old-host\\history\\'+Path(record['path']).name
        report=self.report(archive_root=self.root);self.assertTrue(report['passed'],report['failures'])

    def test_runtime_identity_must_match_every_chunk(self):
        self.trace['provenance']['runtime_source_hashes']['session.py']='different';self.assertIn('HISTORY_RUNTIME_CHANGED',self.codes())

    def test_final_world_cannot_teleport_after_retirement(self):
        self.trace['final_state']['atoms'][0]['position_um']=[50.,50.];self.assertIn('HISTORY_FINAL_STATE',self.codes())

    def test_chunk_actions_must_match_original_executed_windows(self):
        audit=DAGAudit('fixture',{},fixture=True);history=reconstruct_history(audit,self.trace);actions=[deepcopy(a) for b in self.bodies for a in b['actions'].values()];actions[1]['payload']['name']='Z'
        inspect_history_checkpoints(audit,history,actions,self.world);self.assertIn('HISTORY_ORIGINAL_ACTION_CHANGED',{f['code'] for f in audit.failures})

    def test_real_runtime_archive_records_are_consumed_without_its_verifier(self):
        import sys
        runtime_tests=Path(__file__).resolve().parents[1]/'runtime'
        sys.path.insert(0,str(runtime_tests))
        try:import test_session as fixtures
        finally:sys.path.pop(0)
        from na_pipeline.runtime import make_scenario
        f=fixtures.SessionTests();f.setUp();session=f.session
        first=fixtures.window(session,[fixtures.action('source','classical',[],0,1,{'operation':'fake','writes':['m'],'result_ready_us':1}),fixtures.action('expired','gate',['atom:P/d1'],0,1,{'name':'Z'})])
        session.submit(first,make_scenario(first,value=1));session.advance();session.retire_committed(self.root/'real-000.json.gz',keep_result_ids=['m'])
        next_window=fixtures.window(session,[fixtures.action('feedback','gate',['atom:P/d0'],2,3,{'name':'X','reads':['m']},{'bit':'m','equals':1})])
        next_window['actions'][0]['depends_on']=['source'];session.submit(next_window,make_scenario(next_window));session.advance()
        report=validate_session_history(session.export_trace(),fixture=True)
        self.assertTrue(report['passed'],report['failures']);self.assertEqual(report['metrics']['history_events'],3);self.assertEqual(report['metrics']['retained_events_deduplicated'],1)


if __name__=='__main__':unittest.main()
