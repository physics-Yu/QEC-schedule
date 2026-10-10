"""Interface/lease fixtures only: no distillation run or magic sampling claimed."""
import unittest
from copy import deepcopy
from na_pipeline.qec import build_factory15to1_protocol, build_factory_physical_dag, validate_physical_dag
from na_pipeline.runtime import FactoryExecution, FactoryDataInterface, data_surface_port, bind_consumer_suffix, RuntimeContractError
from na_pipeline.runtime.engine import digest
from test_resource_pool import PoolTests


class FactoryPortTests(unittest.TestCase):
    def setUp(self):
        fixture=PoolTests();fixture.setUp()
        self.session,self.pool=fixture.session,fixture.pool
        self.protocol=build_factory15to1_protocol(data_block_id='w0',request_id='producer-request',epoch=0)
        self.controller=FactoryExecution(self.protocol,self.pool,self.session,owner='factory-owner')
        self.api=FactoryDataInterface(self.controller)

    def rejected(self,code,fn):
        with self.assertRaises(RuntimeContractError) as caught:fn()
        self.assertEqual(caught.exception.code,code)

    def ready_boundary_fixture(self):
        # Explicit state-machine fixture, never returned as execution evidence.
        c=self.controller;c.stage_id='reserve_delivery';c.accepted=True
        c.receipts=[{'stage_id':'convert_output','epoch':0,'fixture':True,'evidence_kind':'interface_unit_fixture'}]
        c.token={'token_id':'fixture-token','status':'ready','epoch':0,'output_atom_ids':list(c.output_atoms),
                 'ready_us':0,'state':'A_plus_declared_protocol_quantum_untracked','sampled':False}

    def port(self,target='w3'):
        return data_surface_port(self.session,self.pool,target,encoded_state_ref='fixture:encoded-entry',logical_frame='identity')

    def test_data_port_uses_actual_site_mapping_and_full_patch(self):
        port=self.port();self.assertEqual(len(port['sites']),17)
        self.assertEqual({s['site_id'] for s in port['sites'].values()},{'w3/'+q for q in port['sites']})
        self.assertFalse(port['encoded_state_verified_by_quantum_simulation'])
        self.rejected('DATA_PORT_NOT_ALGORITHM',lambda:self.port('factory0:W4'))
        self.rejected('DATA_PORT_FRAME_UNSUPPORTED',lambda:data_surface_port(self.session,self.pool,'w3',encoded_state_ref='entry',logical_frame='H'))

    def test_no_free_token_or_uncommitted_producer_output(self):
        self.rejected('FACTORY_OUTPUT_NOT_READY',self.api.output_port)
        self.assertIsNone(self.controller.token)

    def test_request_uses_caller_target_without_allocating_or_starting_factory(self):
        state=self.pool.snapshot()
        protocol=FactoryDataInterface.request(self.session,self.pool,self.port('w4'),request_id='next-TDG',gate='TDG')
        self.assertEqual(protocol['data_block_id'],'w4')
        self.assertEqual(protocol['request_gate'],'TDG')
        self.assertEqual(protocol['epoch'],self.pool.next_epoch)
        self.assertEqual(self.pool.snapshot(),state)

    def test_consumer_protection_starts_at_binding_not_at_factory_start(self):
        from test_session import window,action
        from na_pipeline.runtime import make_scenario
        # The future consumer was legitimately reset before it was selected.
        atom=window(self.session,[action('earlier-data-reset','reset',['atom:w3/d0'],0,10,{'state':0})])
        self.session.submit(atom,make_scenario(atom));self.session.advance()
        self.ready_boundary_fixture()
        self.api.reserve(self.api.output_port(),self.port(),request_id='use-after-reset')
        qids=set(self.protocol['factory_qubit_ids'])
        atoms=[self.pool.qubit_to_atom[q] for q in qids]
        atom=window(self.session,[action('factory-cleanup','reset',atoms,10,20,{'state':0})])
        self.session.submit(atom,make_scenario(atom));self.session.advance()
        self.pool.release('factory-owner',self.session,cleanup_action_ids=['factory-cleanup'],reset_qubit_ids=qids)
        self.assertFalse(self.pool.active)

    def test_after_binding_data_reset_is_still_rejected_at_release(self):
        from test_session import window,action
        from na_pipeline.runtime import make_scenario
        self.ready_boundary_fixture();self.api.reserve(self.api.output_port(),self.port(),request_id='live')
        qids=set(self.protocol['factory_qubit_ids']);atoms=[self.pool.qubit_to_atom[q] for q in qids]
        atom=window(self.session,[action('bad-reset','reset',['atom:w3/d0'],0,10,{'state':0}),
                                  action('cleanup','reset',atoms,0,10,{'state':0})])
        self.session.submit(atom,make_scenario(atom));self.session.advance()
        self.rejected('POOL_LIVE_DATA_DESTROYED',lambda:self.pool.release('factory-owner',self.session,
                      cleanup_action_ids=['cleanup'],reset_qubit_ids=qids))

    def test_late_consumer_changes_only_suffix_preserves_producer_and_epoch(self):
        self.ready_boundary_fixture();producer_hash=digest(self.controller.protocol)
        receipts=deepcopy(self.controller.receipts);atom_ids=set(self.controller.output_atoms)
        link=self.api.reserve(self.api.output_port(),self.port('w3'),request_id='consumer-3')
        self.assertEqual(digest(self.controller.protocol),producer_hash)
        self.assertEqual(self.controller.receipts,receipts)
        self.assertEqual(set(self.controller.token['output_atom_ids']),atom_ids)
        self.assertEqual(self.pool.next_epoch,1)
        self.assertEqual(self.pool.active['factory-owner']['target_patch'],'w3')
        self.assertEqual(self.controller.token['status'],'reserved')
        self.assertFalse(link['production_recompiled'])
        dag=self.controller.next_graph();validate_physical_dag(dag)
        used={q for n in dag['nodes'] for q in n['qubits']}
        self.assertTrue(any(q.startswith('w3/') for q in used))
        self.assertFalse(any(q.startswith('w0/') for q in used))
        self.assertFalse(any(n['kind'] in ('measure','reset') and any(q.startswith('w3/d') for q in n['qubits']) for n in dag['nodes']))
        self.rejected('FACTORY_OUTPUT_NOT_READY',self.api.output_port)
        restored=FactoryExecution.restore(self.session.device,self.controller.checkpoint())
        self.assertEqual(restored.next_graph(),dag)
        self.assertEqual(restored.snapshot(),self.controller.snapshot())

    def test_stale_output_target_and_busy_target_do_not_partially_reserve(self):
        self.ready_boundary_fixture();output=self.api.output_port();target=self.port()
        wrong=deepcopy(output);wrong['epoch']=1
        self.rejected('FACTORY_STALE_OUTPUT_PORT',lambda:self.api.reserve(wrong,target,request_id='request'))
        wrong_target=deepcopy(target);wrong_target['sites']['d0']['atom_id']='invented'
        self.rejected('DATA_PORT_STALE',lambda:self.api.reserve(output,wrong_target,request_id='request'))
        self.pool.active['busy']={'resources':['w3']}
        self.rejected('POOL_RESOURCE_BUSY',lambda:self.api.reserve(output,target,request_id='request'))
        self.assertEqual(self.controller.token['status'],'ready')
        self.assertFalse(hasattr(self.controller,'consumer_protocol'))
        self.assertEqual(self.pool.active['factory-owner']['target_patch'],'w0')

    def test_original_logical_source_may_not_be_retargeted(self):
        p=deepcopy(self.protocol);p['logical_binding']={'logical_node_id':'algorithm-T-w0'}
        self.rejected('FACTORY_LOGICAL_REQUEST_CHANGED',lambda:bind_consumer_suffix(p,'w3',request_id='different-request'))

    def test_bound_shor_consumer_retains_protocol_and_scheduler_identity(self):
        from na_pipeline.runtime import LogicalListScheduler
        self.ready_boundary_fixture()
        node={'id':'T0','operation':'T','patch_operands':{'block':'w0'},'source_ids':['test:T0'],
              'reads':[],'writes':[],'condition':None}
        self.controller.protocol['logical_binding']={'logical_node_id':'T0','logical_source':node}
        protocol=deepcopy(self.controller.protocol)
        scheduler=LogicalListScheduler({'entry_mode':'preinitialized','nodes':[node],'edges':[]},{})
        scheduler.begin_protocol('T0',protocol,self.controller.lease)
        self.api.reserve(self.api.output_port(),self.port('w0'),request_id=protocol['request_id'])
        self.assertEqual(self.controller.consumer_protocol,protocol)
        self.assertEqual([r['event'] for r in self.pool.history],['acquire'])
        receipt={'protocol_id':self.controller.consumer_protocol['artifact_id'],'epoch':0,'stage_id':'consume','action_ids':[],
                 'evidence_kind':'identity_fixture_not_physical_execution'}
        scheduler.record_protocol_stage('T0',{'resource_intervals':[]},receipt,origin_us=0)
        event=self.controller.lifecycle[-1]
        self.assertEqual(event['event'],'reserve_and_handoff')
        self.assertEqual(event['delivery_kind'],'same_carrier_scheduling_handoff')
        self.assertFalse(event['physical_motion_claimed'])

    def test_T_and_TDG_suffixes_keep_correction_directions_and_source_templates(self):
        for gate in ('T','TDG'):
            p=build_factory15to1_protocol(data_block_id='old',gate=gate)
            bound=bind_consumer_suffix(p,'actual_data_7',request_id='use-7')
            for stage in ('consume','consume_correction','consume_cleanup'):
                tid=bound['stages'][stage]['template_id']
                self.assertEqual(bound['templates'][tid],p['templates'][tid])
                validate_physical_dag(build_factory_physical_dag(bound,stage))
            branch=bound['stages']['consume']['branch']
            self.assertEqual(branch['one' if gate=='T' else 'zero'],'consume_correction')
            self.assertNotIn('initialize',bound['stages'])


if __name__=='__main__':unittest.main()
