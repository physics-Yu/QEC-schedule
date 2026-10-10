"""Full source contracts + real joint cleanup; ready-boundary tests are fixtures."""
from copy import deepcopy
from pathlib import Path
import unittest,tempfile
from na_pipeline.device import canonical_surface17_device,build_preinitialized_state
from na_pipeline.qec.factory_fleet import factory_fleet_requirements
from na_pipeline.qec import build_factory_physical_dag,validate_physical_dag
from na_pipeline.runtime import FactoryFleet,EventSession,resource_inventory,make_scenario,bind_physical_plan,RuntimeContractError
from na_pipeline.backend import LogicalComponentCompiler


def fleet_world():
    logical={'patches':[{'patch_id':p,'initial_state':{'logical_basis':'Z','logical_value':0}} for p in ('data0','data1')]}
    req=factory_fleet_requirements(logical,['F0','F1']);device=canonical_surface17_device()
    patches={p:{k:r[k] for k in ('aod_group','basis','value')} for p,r in req['patches'].items()}
    positions={p:{'anchor_um':[i*100.,900.],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(patches)}
    ref={'artifact_id':'fixture:two-independent-factories','producer':'test','fixture':True}
    inventory=resource_inventory(req,{'F0:join_probe':[1600.,980.],'F1:join_probe':[1610.,980.]},placement_ref=ref)
    world=build_preinitialized_state(device,patches,positions,placement_ref=ref,resource_inventory=inventory)
    return req,device,world


class FactoryFleetTests(unittest.TestCase):
    def setUp(self):
        req,self.device,world=fleet_world();self.session=EventSession(self.device,world,run_id='fixture:fleet')
        self.fleet=FactoryFleet(self.session,req)

    def demand(self,key,target='data0',**kwargs):
        return self.fleet.request(key,target,encoded_state_ref='fixture:encoded-entry',logical_frame='identity',**kwargs)

    def ready_fixture(self):
        # Controller boundary fixture only; never a claim of actual production.
        self.fleet.start_idle()
        for c in self.fleet.lines.values():
            c.accepted=True;c.stage_id='ready';c.graph=None
            c.receipts=[{'stage_id':'convert_output','epoch':c.protocol['epoch'],'fixture':True,'evidence_kind':'interface_fixture','action_ids':[]}]
        self.fleet.publish_ready()

    def test_two_independent_producers_hold_no_data_and_have_complete_sources(self):
        started=self.fleet.start_idle();self.assertEqual(len(started),2)
        self.assertEqual(len(self.fleet.pool.qubit_to_atom),274)
        self.assertEqual(self.fleet.pool.requirements['counts']['factory_atoms'],240)
        owners=list(self.fleet.pool.active.values())
        self.assertFalse(set(owners[0]['resources'])&set(owners[1]['resources']))
        self.assertTrue(all(l['target_patch'] is None for l in owners))
        self.assertEqual(len(self.fleet.frontier()),2)
        for c in self.fleet.lines.values():
            self.assertEqual(len(c.protocol['qubits']),120)
            for sid,stage in c.protocol['stages'].items():
                if stage['kind']!='physical' or sid.startswith('consume'):continue
                graph=build_factory_physical_dag(c.protocol,sid);validate_physical_dag(graph)
                self.assertFalse(any(q.startswith('data') or q.startswith('unbound_data') for n in graph['nodes'] for q in n['qubits']))
        self.assertEqual(self.fleet.inventory(),[])

    def test_priority_t_tdg_and_same_carrier_single_claim(self):
        self.ready_fixture();self.demand('first','data0');self.demand('urgent','data1',gate='TDG',priority=3)
        assigned=self.fleet.assign_ready()
        self.assertEqual([r['request_id'] for r in assigned],['urgent','first'])
        self.assertEqual(len({r['token_id'] for r in assigned}),2)
        self.assertEqual(len(self.fleet.inventory()),0)
        self.assertEqual(self.fleet.assign_ready(),[])
        self.assertEqual(self.fleet.start_idle(),[])
        for r in self.fleet.requests.values():
            c=self.fleet.lines[r['factory_id']];graph=c.next_graph()
            self.assertEqual(c.token['output_atom_ids'],c.output_atoms)
            self.assertEqual(c.consumer_protocol['data_block_id'],r['target_patch'])
            self.assertEqual(c.consumer_protocol['request_gate'],r['gate'])
            self.assertFalse(any(n['kind'] in ('measure','reset') and any(q.startswith(r['target_patch']+'/d') for q in n['qubits']) for n in graph['nodes']))
            branch=c.consumer_protocol['stages']['consume']['branch']
            self.assertEqual(branch['zero' if r['gate']=='TDG' else 'one'],'consume_correction')

    def test_busy_data_does_not_consume_second_token_and_buffer_is_bounded(self):
        self.ready_fixture();self.demand('a');self.demand('b')
        self.assertEqual(len(self.fleet.assign_ready()),1)
        self.assertEqual(len(self.fleet.inventory()),1)
        self.assertEqual(self.fleet.requests['b']['status'],'pending')
        self.assertEqual(self.fleet.start_idle(),[])

    def test_false_or_future_condition_never_claims_output(self):
        from test_session import window,action
        self.ready_fixture();self.demand('guarded',condition={'bit':'guard','equals':1})
        self.assertEqual(self.fleet.assign_ready(),[])
        atom=window(self.session,[action('fixture-result','classical',[],0,1,{'operation':'fake','writes':['guard'],'result_ready_us':1})])
        self.session.submit(atom,make_scenario(atom,value=0));self.session.advance()
        self.assertEqual(self.fleet.assign_ready(),[])
        self.assertEqual(self.fleet.requests['guarded']['status'],'skipped')
        self.assertEqual(len(self.fleet.inventory()),2)

    def test_checkpoint_preserves_shared_pool_epochs_and_single_token_claim(self):
        self.ready_fixture();self.demand('a');self.fleet.assign_ready()
        restored=FactoryFleet.restore(self.device,self.fleet.checkpoint())
        self.assertEqual(restored.snapshot(),self.fleet.snapshot())
        self.assertTrue(all(c.pool is restored.pool for c in restored.lines.values()))
        self.assertEqual(restored.assign_ready(),[])
        broken=self.fleet.checkpoint();broken['body']['pool']['factory_epochs']['F0']+=1
        with self.assertRaises(RuntimeContractError):FactoryFleet.restore(self.device,broken)

    def test_logical_ready_requests_attach_to_distinct_producer_and_consumer_identities(self):
        from na_pipeline.runtime import LogicalListScheduler
        nodes=[{'id':'logical-'+str(i),'operation':g,'patch_operands':{'block':'data'+str(i)},
                'source_ids':['algorithm:'+str(i)],'reads':[],'writes':[],'condition':None} for i,g in enumerate(('T','TDG'))]
        logical={'entry_mode':'preinitialized','nodes':nodes,'edges':[]}
        scheduler=LogicalListScheduler(logical,{})
        self.fleet.logical_scheduler=scheduler;self.ready_fixture()
        self.assertEqual(len(self.fleet.enqueue_logical_ready({'data0':'identity','data1':'identity'})),2)
        self.fleet.assign_ready()
        self.assertTrue(all(s['status']=='running' for s in scheduler.states.values()))
        for row in self.fleet.requests.values():
            c=self.fleet.lines[row['factory_id']];node=row['logical_source'];state=scheduler.states[node['id']]
            self.assertEqual(state['producer_protocol'],c.protocol['artifact_id'])
            self.assertEqual(state['adaptive_protocol'],c.consumer_protocol['artifact_id'])
            self.assertNotEqual(state['producer_protocol'],state['adaptive_protocol'])
            graph=c.next_graph();self.assertEqual(graph['fleet_logical_source'],node)
            self.assertTrue(all(node['id'] in op['source_ids'] for op in graph['nodes']))
            receipt={'protocol_id':c.consumer_protocol['artifact_id'],'epoch':c.protocol['epoch'],'stage_id':'consume','action_ids':[],
                     'evidence_kind':'scheduler_identity_fixture'}
            scheduler.record_protocol_stage(node['id'],{'resource_intervals':[]},receipt,origin_us=0)
        restored=FactoryFleet.restore(self.device,self.fleet.checkpoint(),logical_dag=logical)
        self.assertEqual(restored.logical_scheduler.snapshot(),scheduler.snapshot())
        self.assertEqual(restored.assign_ready(),[])

    def test_layout_is_replicated_without_aliasing_live_atoms(self):
        from na_pipeline.runtime import place_factory_lines
        plan=place_factory_lines(self.fleet.pool.requirements,{'F0':[500.,900.],'F1':[1300.,900.]})
        self.assertEqual(len(plan['patch_placements']),14)
        self.assertEqual(plan['patch_placements']['F1:W4']['anchor_um'],[1700.,900.])
        self.assertFalse(plan['copies_runtime_state'])

    def test_stock_backpressure_does_not_block_unrelated_data_work(self):
        from na_pipeline.runtime import FactoryDataInterface
        self.ready_fixture()
        self.assertEqual(self.fleet.available_data_patches(),['data0','data1'])
        compiler=LogicalComponentCompiler(self.device)
        spec=compiler.describe('X')
        graph=compiler.instantiate('X',qubit_bindings={q['id']:'data1/'+q['local_id'] for q in spec['formal_qubits']},namespace='data-work')
        def prepare(dags,session):
            ctx=session.compilation_context(dags);plan=compiler.compile_dags(dags,session.snapshot()['world_state'],execution_context=ctx,cache=False)
            return {'context':ctx,'physical_plan':plan,'atom_program':bind_physical_plan(plan,ctx)}
        batch=self.fleet.compile_frontier(prepare,additional_dags=[graph]);self.assertEqual(batch['work'],[])
        call=batch['prepared'];atom=call['atom_program']
        self.session.submit(atom,make_scenario(atom),expected_revision=call['context']['revision']);self.session.advance()
        self.fleet.commit([],call['physical_plan'],atom,allow_other_work=True)
        self.assertEqual(len(self.fleet.inventory()),2)

    def test_real_consumer_suffix_completes_while_peer_inventory_remains_live(self):
        # Only the producer-ready boundary is a fixture. Consumer actions,
        # measured branch, cleanup and logical completion execute for real in
        # the fake EventSession; this is not a production qualification.
        from na_pipeline.runtime import LogicalListScheduler,LogicalGateLibrary
        root=Path(__file__).resolve().parents[2]/'artifacts/demos/joint-factory-repaired-20261008'
        if not root.exists():self.skipTest('Frozen qualified component package not installed')
        node={'id':'consume-live-data','operation':'T','patch_operands':{'block':'data0'},
              'source_ids':['fixture:requested-T'],'reads':[],'writes':[],'condition':None}
        scheduler=LogicalListScheduler({'entry_mode':'preinitialized','nodes':[node],'edges':[]},{})
        self.fleet.logical_scheduler=scheduler;self.ready_fixture()
        self.fleet.enqueue_logical_ready({'data0':'identity'});self.fleet.assign_ready()
        row=self.fleet.requests[node['id']];fid=row['factory_id']
        with tempfile.TemporaryDirectory() as directory:
            library=LogicalGateLibrary(self.device,connection_directory=Path(directory)/'modules')
            for name in ('factory.consume','factory.consume_cleanup'):library.import_component(name,root/name)
            for _ in range(2):
                batch=self.fleet.compile_frontier(lambda dags,session:library.prepare_dags(library.component_for(dags),session,dags))
                call=batch['prepared'];atom=call['atom_program']
                self.session.submit(atom,make_scenario(atom,value=0),expected_revision=call['context']['revision']);self.session.advance()
                self.fleet.commit(batch['work'],call['physical_plan'],atom)
        self.assertEqual(row['status'],'completed')
        self.assertEqual(scheduler.states[node['id']]['status'],'completed')
        self.assertIsNone(self.fleet.lines[fid])
        self.assertEqual(len(self.fleet.inventory()),1)
        self.assertEqual(len(self.fleet.pool.active),1)

    def test_real_shared_cleanup_frontier_releases_only_own_lines_then_restarts(self):
        self.fleet.start_idle()
        for f in self.fleet.lines:self.fleet.abort_production(f)
        compiler=LogicalComponentCompiler(self.device)
        def prepare(dags,session):
            context=session.compilation_context(dags)
            plan=compiler.compile_dags(dags,session.snapshot()['world_state'],execution_context=context,cache=False)
            return {'physical_plan':plan,'atom_program':bind_physical_plan(plan,context),'context':context}
        batch=self.fleet.compile_frontier(prepare);call=batch['prepared'];atom=call['atom_program']
        self.assertEqual(len(atom['actions']),240)
        self.assertEqual(len({a['t_start_us'] for a in atom['actions']}),1)
        self.session.submit(atom,make_scenario(atom),expected_revision=call['context']['revision']);self.session.advance()
        receipts=self.fleet.commit(batch['work'],call['physical_plan'],atom)
        self.assertEqual([len(r['action_ids']) for r in receipts],[120,120])
        self.assertFalse(self.fleet.pool.active)
        self.assertTrue(all(c is None for c in self.fleet.lines.values()))
        self.assertEqual([r['epoch'] for r in self.fleet.start_idle()],[1,1])
        self.assertTrue(all(a.get('reset_epoch',0)==0 for a in self.session.snapshot()['world_state']['atoms'] if a['qubit_id'].startswith('data')))


if __name__=='__main__':unittest.main()
