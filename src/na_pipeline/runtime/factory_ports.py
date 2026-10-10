"""Actual data-patch ports and a same-session factory-output consumer boundary.

The producer protocol/history is immutable. Late binding creates only a
consumer suffix; it neither reruns production nor mints a second token.
"""
from copy import deepcopy
from na_pipeline.backend.strategy_template import remap
from na_pipeline.qec.surface17 import FORMALS
from na_pipeline.qec.factory import _name
from .engine import digest
from .errors import fail


def data_surface_port(session, pool, patch_id, *, encoded_state_ref, logical_frame):
    """Read current code sites; encoded_state_ref is a caller assertion, not a simulation."""
    if pool.requirements['patches'].get(patch_id,{}).get('role')!='algorithm':
        fail('DATA_PORT_NOT_ALGORITHM', 'Use an existing algorithm patch from the data region')
    if not isinstance(encoded_state_ref,str) or not encoded_state_ref:
        fail('DATA_PORT_ENCODED_CONTRACT', 'Scheduler must identify the encoded input contract')
    if logical_frame!='identity':
        fail('DATA_PORT_FRAME_UNSUPPORTED', 'Resolve the live logical frame before this physical consumer interface')
    snap=session.snapshot();world=snap['world_state']
    if snap['in_flight'] or session.queue or session.pending_results:
        fail('DATA_PORT_NOT_COMMITTED', 'Read a data port only at a committed event boundary')
    sites={a.get('site_id',a['qubit_id']):a for a in world['atoms']}
    selected={local:sites.get(patch_id+'/'+local) for local in FORMALS}
    if any(a is None for a in selected.values()):
        fail('DATA_PORT_INCOMPLETE', 'An intact Surface-17 port needs all nine data and eight syndrome sites')
    for a in selected.values():
        if a['carrier']!='SLM' or a['aod_group']!='data':
            fail('DATA_PORT_CARRIER', 'Consumer entry requires committed SLM sites in the data AOD group')
        trap=next((t for t in world['slm_traps'] if t['trap_id']==a['trap_id']),None)
        if trap is None or trap['zone_id']!='storage_entanglement' or trap['occupant']!=a['atom_id']:
            fail('DATA_PORT_ZONE', 'Consumer must occupy actual compute-zone traps')
    return {'schema_version':'DataSurfaceCodePort/0.1','patch_id':patch_id,'code':'surface17-d3',
        'run_id':session.run_id,'revision':session.revision,'world_hash':digest(world),
        'encoded_state_ref':encoded_state_ref,'encoded_state_verified_by_quantum_simulation':False,
        'logical_frame':logical_frame,'sites':{q:{'site_id':patch_id+'/'+q,'atom_id':a['atom_id'],
            'qubit_id':a['qubit_id'],'position_um':list(a['position_um'])} for q,a in selected.items()}}


def bind_consumer_suffix(producer_protocol, target_patch, *, request_id, gate=None):
    """Pure port/source binding: no compilation, scheduling, execution or readiness."""
    _name(target_patch,'target_patch');_name(request_id,'request_id')
    gate=gate or producer_protocol['request_gate']
    if gate not in ('T','TDG'):fail('FACTORY_CONSUMER_GATE','A_plus consumption supports T or TDG')
    old=producer_protocol['data_block_id']
    if target_patch in {q['block_id'] for q in producer_protocol['qubits'] if q['block_id']!=old}:
        fail('FACTORY_CONSUMER_ALIAS','Data consumer cannot alias a factory patch or probe')
    logical=producer_protocol.get('logical_binding')
    if logical and (target_patch!=old or request_id!=producer_protocol['request_id'] or gate!=producer_protocol['request_gate']):
        fail('FACTORY_LOGICAL_REQUEST_CHANGED','A source-bound T request cannot silently change its logical node or operand')
    if logical:
        # This request already names the exact consumer. Retain its source and
        # protocol identity; the reservation gets an instance ID, not the DAG.
        return deepcopy(producer_protocol)
    suffix=deepcopy(producer_protocol)
    if producer_protocol.get('production_mode') or gate!=producer_protocol['request_gate']:
        from na_pipeline.qec import build_factory15to1_protocol
        suffix=build_factory15to1_protocol(data_block_id=target_patch,request_id=request_id,gate=gate,
            epoch=producer_protocol['epoch'],factory_id=producer_protocol['factory_id'])
    sid=producer_protocol['artifact_id']+'-consumer-'+digest({'target':target_patch,'request':request_id,'gate':gate})[:16]
    original=suffix
    old=original['data_block_id']
    mapping={old:target_patch,original['artifact_id']:sid,
             **{old+'/'+q:target_patch+'/'+q for q in FORMALS}}
    kept=('consume','consume_correction','consume_cleanup','consumed')
    for stage_id in kept:
        stage=original['stages'][stage_id]
        if 'call_id' in stage:
            mapping[stage['call_id']]=sid+'.'+stage_id
            if 'branch' in stage:
                old_result=stage['branch']['result_id']
                mapping[old_result]=sid+'.'+stage_id+old_result[len(stage['call_id']):]
    suffix=remap(suffix,mapping)
    suffix['artifact_id']=sid;suffix['data_block_id']=target_patch;suffix['request_id']=request_id
    suffix['stages']={s:suffix['stages'][s] for s in kept}
    tids={s['template_id'] for s in suffix['stages'].values() if 'template_id' in s}
    suffix['templates']={t:suffix['templates'][t] for t in tids}
    suffix['entry']='consume';suffix['cleanup_stage_ids']=['consume_cleanup']
    suffix['raw_inputs']=[];suffix['acceptance_checks']=[]
    suffix.pop('data_input_contract',None)
    suffix['consumer_link']={'schema_version':'FactoryConsumerSourceBinding/0.1',
        'producer_protocol_id':producer_protocol['artifact_id'],'producer_protocol_hash':digest(producer_protocol),
        'output_block_id':producer_protocol['output']['block_id'],'target_patch':target_patch,
        'source_templates_unchanged':True,'production_recompiled':False,'ready_token_required':True}
    return suffix


class FactoryDataInterface:
    """Use a real FactoryExecution; callers cannot hand in a free magic token."""
    def __init__(self, controller):
        from .factory_session import FactoryExecution
        if not isinstance(controller,FactoryExecution):fail('FACTORY_CONTROLLER_REQUIRED','An execution-bound factory controller is required')
        self.controller=controller

    @staticmethod
    def request(session, pool, target_port, *, request_id, gate='T'):
        """Build an arbitrary-data request; no allocation or factory execution."""
        from na_pipeline.qec import build_factory15to1_protocol
        if pool.requirements.get('factories'):
            fail('FACTORY_FLEET_REQUEST_REQUIRED','Queue demand through FactoryFleet so a ready line is selected without fixing production to data')
        if target_port.get('schema_version')!='DataSurfaceCodePort/0.1':fail('DATA_PORT_SCHEMA','A live data port is required')
        actual=data_surface_port(session,pool,target_port['patch_id'],
            encoded_state_ref=target_port['encoded_state_ref'],logical_frame=target_port['logical_frame'])
        if target_port!=actual:fail('DATA_PORT_STALE','Target changed before request construction')
        protocol=build_factory15to1_protocol(data_block_id=target_port['patch_id'],request_id=request_id,
            gate=gate,epoch=pool.next_epoch,factory_id=pool.requirements['factory_id'])
        protocol['data_input_contract']=deepcopy(target_port)
        return protocol

    def output_port(self):
        c=self.controller
        if (c.stage_id!='reserve_delivery' or c.accepted is not True or not c.token or
                c.token['status']!='ready' or not c.receipts or c.receipts[-1]['stage_id']!='convert_output'):
            fail('FACTORY_OUTPUT_NOT_READY','Accepted checks and committed same-carrier conversion must publish a ready token first')
        if c.owner not in c.pool.active or c.pool.active[c.owner]['epoch']!=c.token['epoch']:
            fail('FACTORY_OUTPUT_LEASE','Ready output must remain owned in its original factory epoch')
        if (c.token['epoch']!=c.protocol['epoch'] or c.receipts[-1].get('epoch')!=c.protocol['epoch'] or
                c.pool.active[c.owner]['session_run_id']!=c.session.run_id or c.token['ready_us']>c.session.now_us or
                c.token['state']!='A_plus_declared_protocol_quantum_untracked'):
            fail('FACTORY_OUTPUT_STATE','Output requires same-session, same-epoch converted A_plus readiness')
        snap=c.session.snapshot();sites={a.get('site_id',a['qubit_id']):a for a in snap['world_state']['atoms']}
        actual=[sites[q]['atom_id'] for q in c.protocol['output']['qubit_ids']]
        if set(actual)!=set(c.output_atoms) or set(actual)!=set(c.token['output_atom_ids']):
            fail('FACTORY_OUTPUT_CARRIER_CHANGED','Same W4 carriers must survive conversion and delivery')
        return {'schema_version':'FactoryOutputPort/0.1','run_id':c.session.run_id,'revision':c.session.revision,
            'world_hash':digest(snap['world_state']),'owner':c.owner,'epoch':c.token['epoch'],
            'token_id':c.token['token_id'],'output_block_id':c.protocol['output']['block_id'],
            'atom_ids':actual,'state':c.token['state'],'ready_us':c.token['ready_us'],
            'conversion_receipt_hash':digest(c.receipts[-1]),'producer_protocol_hash':digest(c.protocol),
            'sampled':False,'physical_motion_claimed':False}

    def reserve(self, output_port, target_port, *, request_id, gate=None, logical_source=None):
        """Validate everything first, then atomically reserve this token/target."""
        c=self.controller
        if output_port!=self.output_port():fail('FACTORY_STALE_OUTPUT_PORT','Refresh a stale or altered output port')
        if target_port.get('schema_version')!='DataSurfaceCodePort/0.1':fail('DATA_PORT_SCHEMA','A live data-surface port is required')
        actual=data_surface_port(c.session,c.pool,target_port['patch_id'],
            encoded_state_ref=target_port['encoded_state_ref'],logical_frame=target_port['logical_frame'])
        if actual!=target_port:fail('DATA_PORT_STALE','Target site binding or runtime revision changed')
        suffix=bind_consumer_suffix(c.protocol,target_port['patch_id'],request_id=request_id,gate=gate)
        source_bound=bool(c.protocol.get('logical_binding'))
        if not source_bound:suffix['data_input_contract']=deepcopy(target_port)
        if logical_source is not None:
            if (logical_source.get('operation')!=suffix['request_gate'] or
                    logical_source.get('patch_operands',{}).get('block')!=target_port['patch_id']):
                fail('FACTORY_LOGICAL_REQUEST_CHANGED','Consumer source must retain its operation and target')
            if source_bound and logical_source!=c.protocol['logical_binding']['logical_source']:
                fail('FACTORY_LOGICAL_REQUEST_CHANGED','Cannot replace the existing logical source')
            if not source_bound:suffix['fleet_logical_source']=deepcopy(logical_source)
        if not {q['id'] for q in suffix['qubits']}<=c.pool.qubit_to_atom.keys():
            fail('FACTORY_CONSUMER_COVERAGE','Consumer declarations must resolve in the complete live world')
        c.pool.preview_target_binding(c.owner,target_port['patch_id'],c.session)
        link={'schema_version':'FactoryConsumerReservation/0.1','output_port':deepcopy(output_port),
            'data_port':deepcopy(target_port),'request_id':request_id,'consumer_protocol_hash':digest(suffix),
            'same_token':True,'same_epoch':True,'production_recompiled':False,'runtime_results_cached':False,
            'physical_motion_claimed':False}
        if c.lease['target_patch']!=target_port['patch_id']:
            c.lease=c.pool.bind_target(c.owner,target_port['patch_id'],c.session)
        c.consumer_protocol=suffix;c.consumer_binding=link
        c.live_atoms={target_port['sites']['d'+str(i)]['atom_id'] for i in range(9)}
        c.token.update(status='reserved',request_id=request_id,target_patch=target_port['patch_id'])
        c.lifecycle.append({'event':'reserve_and_handoff','time_us':c.session.now_us,'token':deepcopy(c.token),
            'delivery_kind':'same_carrier_scheduling_handoff',**deepcopy(link)})
        c.stage_id='consume';c.graph=None
        return deepcopy(link)
