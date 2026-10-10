"""Cross-window factory witnesses, derived from every verified physical stage.

No R3 decision helper or R5 acceptance predicate is called. The original frozen
protocol is source input; this module checks its selected execution and lifecycle.
"""
from hashlib import sha256
import json

from .checker import _hash


def _cleanup(audit,atom,events,qubits,live_qubits):
    mapping={a['qubit_id']:a['atom_id'] for a in atom['initial_state']['atoms']};required={mapping[q] for q in qubits};live={mapping[q] for q in live_qubits};last={};resets={}
    for action in sorted(atom['actions'],key=lambda a:(a['t_end_us'],a['id'])):
        event=events[action['id']]
        if event['status']=='skipped':continue
        touched=set(action['atoms'])
        if action['kind']=='gate' and action['payload'].get('name')=='CZ':touched={a for pair in action['payload']['pairs'] for a in pair}
        if action['kind'] in ('reset','measure') and touched&live:audit.fail('STREAM_LIVE_DATA_DESTROYED','Protocol destroys existing live information carriers',action_id=action['id'])
        if action['kind'] not in ('gate','measure','reset'):continue
        for aid in touched&required:last[aid]=action
    for q in qubits:
        a=last.get(mapping[q])
        if a is None or a['kind']!='reset' or a['payload'].get('state')!=0 or a['payload'].get('params',{}).get('basis','Z')!='Z':
            audit.fail('STREAM_TERMINAL_RESET_MISSING','Every reusable carrier needs its own actually completed final Z0 reset',qubit_id=q)
        else:resets[q]={'action_id':a['id'],'end_us':a['t_end_us']}
    return resets


def _lease(stream,audit,epoch,nid,operation,resources,begin,end,cleanup=None,protocol_id=None):
    if epoch!=stream.index.get_meta('next_epoch'):audit.fail('STREAM_EPOCH_REPLAY','Pool epoch is not the next fresh epoch',epoch=epoch)
    stream.index.put_meta('next_epoch',epoch+1)
    value={'epoch':epoch,'node_id':nid,'operation':operation,'resources':sorted(resources),'start_us':begin,'end_us':end,'cleanup':cleanup,'protocol_id':protocol_id}
    stream.index.db.execute('INSERT INTO leases VALUES(?,?)',(epoch,json.dumps(value,ensure_ascii=False)))


def inspect_phase_cleanup(stream,audit,dag,atom,body,nid):
    req=stream.bundle['resource_requirements'];scratch=req['shared_phase_scratch'];target=dag['logical_binding']['patch_bindings']['block']
    if set(dag['required_leases']) == {target}:
        # Current neutral-atom S-SE is a complete one-patch instrument.
        # Independent source projection was already checked against its spec.
        expected_qubits={target+'/'+p+str(i) for p,n in (('d',9),('x',4),('z',4)) for i in range(n)}
        if ({q['id'] for q in dag['qubits']} != expected_qubits
                or stream.index.get_meta('active_factory') is not None
                or not any(o.get('metadata',{}).get('protocol') == 'surface17-neutral-s-se/1' for o in dag['nodes'])):
            audit.fail('STREAM_S_SE_BINDING','Scratch-free S must be the complete current single-patch S-SE source')
        aux=sorted(q for q in expected_qubits if q.rsplit('/',1)[-1][0] in 'xz')
        _cleanup(audit,atom,body['events'],aux,[target+'/d'+str(i) for i in range(9)])
        audit.metrics['single_patch_s_se_no_shared_scratch']=True
        return
    expected={scratch['phase_aux'],scratch['bridge'],scratch['exclusive_mutex'],target}
    if set(dag['required_leases'])!=expected or stream.index.get_meta('active_factory') is not None:audit.fail('STREAM_PHASE_POOL_CONFLICT','S/SDG must hold the shared Y/probe/mutex without an active factory')
    qids=[q for q in req['physical_qubit_ids'] if q.startswith(scratch['phase_aux']+'/') or q==scratch['bridge']];live=[target+'/d'+str(i) for i in range(9)]
    cleanup=_cleanup(audit,atom,body['events'],qids,live)
    _lease(stream,audit,dag['logical_binding']['epoch'],nid,dag['operation'],expected,body['start_us'],body['end_us'],cleanup)


def _template(audit,dag,protocol):
    stage=protocol['stages'][dag['protocol_binding']['stage_id']];template=protocol['templates'][stage['template_id']];prefix=stage['call_id']+'/r0/';nodes={o['id']:o for o in dag['nodes']};used=set()
    if any(item['kind']!='op' for item in template['body']):audit.need('STREAM_FACTORY_NESTED_TEMPLATE','Original protocol contains a not-yet-supported nested source template');return
    writes={r for item in template['body'] for r in item['op']['writes']}
    remap=lambda rid:prefix+rid if rid in writes else rid
    for item in template['body']:
        op=item['op'];sid=prefix+op['id'];used.add(sid);actual=nodes.get(sid);cond=None if not op['condition'] else {**op['condition'],'bit':remap(op['condition']['bit'])}
        expected={'kind':op['kind'],'qubits':[protocol['bindings'][q] for q in op['qubits']],'params':op['params'],'reads':[remap(r) for r in op['reads']],'writes':[remap(r) for r in op['writes']],'condition':cond}
        if actual is None or any(actual[k]!=v for k,v in expected.items()) or not {prefix+d for d in op['after']}<=set(actual['after']) or not set(op['source_ids'])<=set(actual['source_ids']):audit.fail('STREAM_FACTORY_SOURCE_CHANGED','Executed factory stage differs from the complete original source template',source_id=sid)
    services={m['post_readout_reset_op_id'] for g in dag['groups'] for m in g['members']}
    if set(nodes)-used!=services-used:audit.fail('STREAM_FACTORY_SERVICE_COVERAGE','Factory stage omits original operations or adds unsupported source work')
    for group in dag['groups']:
        for member in group['members']:
            op=nodes[member['post_readout_reset_op_id']]
            if op['kind']!='reset' or op['qubits']!=[member['physical_qubit_id']] or member['measurement_op_id'] not in op['after']:audit.fail('STREAM_FACTORY_SERVICE_RESET','Readout cleanup reset lost its actual measurement dependency')


def inspect_factory_window(stream,audit,dag,plan,atom,body,protocol):
    if protocol is None:audit.need('STREAM_ORIGINAL_FACTORY_PROTOCOL_REQUIRED','Every factory stage must be checked against its complete frozen original R3 protocol');return
    binding=dag['protocol_binding'];pid=binding['protocol_id'];sid=binding['stage_id'];epoch=binding['epoch'];nid=dag['logical_binding']['logical_node_id'];node=stream.graph.nodes[nid];request=node['resource_requests'][0];req=stream.bundle['resource_requirements']
    if protocol['artifact_id']!=pid or protocol['epoch']!=epoch or protocol['logical_binding']['logical_source']!=node or protocol['request_id']!='logical-'+sha256(request['request_id'].encode()).hexdigest() or protocol['request_gate']!=node['operation'] or protocol['data_block_id']!=node['patch_operands']['block'] or protocol['world_resource_ref']['sha256']!=_hash(req) or dag['world_resource_ref']!=protocol['world_resource_ref']:
        audit.fail('STREAM_FACTORY_REQUEST_BINDING','Factory stage changed source request/parent/target/epoch or world')
    active=stream.index.get_meta('active_factory')
    if active is None:
        if sid!=protocol['entry']:audit.fail('STREAM_FACTORY_PREFIX_OMITTED','Attempt starts after its required initialization')
        previous=stream.index.node(nid)
        if previous is not None and previous.get('status') not in ('rejected',):audit.fail('STREAM_FACTORY_PARENT_REPLAY','Parent was consumed or has an unfinished old attempt')
        _lease(stream,audit,epoch,nid,node['operation'],protocol['required_leases'],body['start_us'],None,protocol_id=pid)
        active={'protocol_id':pid,'protocol_hash':_hash(protocol),'epoch':epoch,'node_id':nid,'expected_stage':protocol['entry'],'start_us':body['start_us'],'stage_count':0,'accepted':None,'lifecycle_required':[]}
    if active['protocol_id']!=pid or active['protocol_hash']!=_hash(protocol) or active['epoch']!=epoch:audit.fail('STREAM_FACTORY_INTERLEAVING','Attempt changed protocol or lost the exclusive shared pool')
    expected=active['expected_stage']
    while protocol['stages'][expected]['kind']=='lifecycle':
        active['lifecycle_required'].append(expected);expected=protocol['stages'][expected]['next']
    if sid!=expected:audit.fail('STREAM_FACTORY_STAGE_SEQUENCE','Actual stage skipped or changed a ready-result-selected protocol transition',expected=expected,actual=sid)
    _template(audit,dag,protocol)
    mapping={a['qubit_id']:a['atom_id'] for a in atom['initial_state']['atoms']};live={mapping[q] for q in protocol['live_data_information_qubit_ids']}
    for event in body['events'].values():
        if event['status']=='completed' and event['kind'] in ('reset','measure') and set(event['atoms'])&live:audit.fail('STREAM_FACTORY_LIVE_DATA','Factory stage resets or measures live target data',action_id=event['action_id'])
    own_results=body['results'];stage=protocol['stages'][sid];branch=stage.get('branch');following=stage.get('next');branch_record=None
    if branch:
        rid=branch['result_id'];branch_record=own_results.get(rid) or stream.index.result(rid)
        if branch_record is None or type(branch_record['value']) is not int or branch_record['value'] not in (0,1) or branch_record['ready_us']>body['end_us']:audit.fail('STREAM_FACTORY_BRANCH_NOT_READY','Factory selected a branch without an actual ready producer',result_id=rid)
        else:following=branch['one'] if branch_record['value'] else branch['zero']
    if sid=='terminal_checks':
        passes=[]
        for check in protocol['acceptance_checks']:
            values=[own_results.get(r) or stream.index.result(r) for r in check['result_ids']]
            if any(v is None or v['ready_us']>body['end_us'] for v in values):audit.fail('STREAM_FACTORY_ACCEPTANCE_PRODUCER','Acceptance uses absent/future terminal parity input')
            else:passes.append(sum(v['value'] for v in values)%2==check['expected_parity'])
        active['accepted']=len(passes)==4 and all(passes)
        if (following=='convert_output')!=active['accepted']:audit.fail('STREAM_FACTORY_ACCEPTANCE_CHANGED','Accepted branch differs from the actual current four logical-X parity checks')
    if sid=='convert_output':
        output_data={mapping[q] for q in protocol['output']['qubit_ids'] if q.rsplit('/',1)[-1].startswith('d')}
        if active['accepted'] is not True or any(e['kind'] in ('reset','measure') and e['status']=='completed' and set(e['atoms'])&output_data for e in body['events'].values()):audit.fail('STREAM_FACTORY_CONVERSION','Ready conversion must preserve the same accepted W4 data carriers')
    cleanup=None
    if sid in protocol['cleanup_stage_ids']:cleanup=_cleanup(audit,atom,body['events'],protocol['factory_qubit_ids'],protocol['live_data_information_qubit_ids'])
    end=max([a['t_end_us'] for a in atom['actions']]+[r['ready_us'] for r in own_results.values()]);summary={'protocol_id':pid,'protocol_hash':_hash(protocol),'stage_id':sid,'node_id':nid,'epoch':epoch,'chunk':stream.sequence,'start_us':min(a['t_start_us'] for a in atom['actions']),'required_end_us':end,'boundary_end_us':body['end_us'],'atom_program_hash':_hash(atom),'physical_dag_hash':_hash(dag),'action_ids_sha256':_hash([a['id'] for a in atom['actions']]),'result_ids_sha256':_hash(sorted(dag['result_producers'])),'next_stage':following,'branch_result':branch_record,'cleanup':cleanup}
    stream.index.db.execute('INSERT INTO stages VALUES(?,?,?)',(pid,sid,json.dumps(summary,ensure_ascii=False)))
    active['expected_stage']=following;active['stage_count']+=1
    if following is not None and protocol['stages'][following]['kind']=='terminal':
        outcome=protocol['stages'][following]['outcome']
        if cleanup is None or len(cleanup)!=120:audit.fail('STREAM_FACTORY_TERMINAL_WITHOUT_CLEANUP','Attempt cannot end without all 120 actual final carrier resets')
        active.update(terminal=outcome,end_us=body['end_us']);stream.index.put_meta('completed_factory:'+pid,active);stream.index.put_meta('active_factory',None)
        stream.index.put_node(nid,{'status':'rejected' if outcome=='rejected' else 'factory_ledger_pending','start_us':active['start_us'],'end_us':body['end_us'],'protocol_id':pid,'epoch':epoch})
        lease=json.loads(stream.index.db.execute('SELECT body FROM leases WHERE epoch=?',(epoch,)).fetchone()[0]);lease.update(end_us=body['end_us'],cleanup=cleanup);stream.index.db.execute('UPDATE leases SET body=? WHERE epoch=?',(json.dumps(lease,ensure_ascii=False),epoch))
    else:stream.index.put_meta('active_factory',active)


def inspect_factory_ledger(stream,audit,ledger):
    protocol=ledger['protocol'];pid=protocol['artifact_id'];finished=stream.index.get_meta('completed_factory:'+pid)
    if finished is None:audit.fail('STREAM_LEDGER_WITHOUT_ATTEMPT','Ledger has no independently verified complete physical attempt',protocol_id=pid);return
    stages={sid:json.loads(body) for sid,body in stream.index.db.execute('SELECT stage,body FROM stages WHERE protocol=?',(pid,))};receipts=ledger['stage_receipts'];decisions=ledger['stage_decisions']
    if ledger['protocol_hash']!=_hash(protocol) or ledger['protocol_ref']!=pid or ledger['epoch']!=finished['epoch'] or ledger['terminal']!=finished['terminal'] or len(receipts)!=len(stages) or len(decisions)!=len(receipts) or len({r['stage_id'] for r in receipts})!=len(receipts):audit.fail('STREAM_ATTEMPT_LEDGER_COVERAGE','Ledger omits, duplicates or rebinds an executed stage')
    for receipt,decision in zip(receipts,decisions):
        stage=stages.get(receipt['stage_id'])
        if stage is None:audit.fail('STREAM_LEDGER_UNEXECUTED_STAGE','Ledger contains an unexecuted branch stage');continue
        if receipt['protocol_id']!=pid or receipt['epoch']!=finished['epoch'] or receipt['complete'] is not True or receipt['evidence_kind']!='fake_event_run' or receipt['atom_program_hash']!=stage['atom_program_hash'] or receipt['physical_dag_hash']!=stage['physical_dag_hash'] or _hash(receipt['action_ids'])!=stage['action_ids_sha256'] or _hash(receipt['result_ids'])!=stage['result_ids_sha256'] or receipt['end_us']<stage['required_end_us'] or receipt['end_us']>stage['boundary_end_us']:audit.fail('STREAM_STAGE_RECEIPT','Stage receipt is detached from all actual actions/results/ready events',stage_id=receipt['stage_id'])
        if decision['protocol_id']!=pid or decision['epoch']!=finished['epoch'] or decision['from_stage']!=stage['stage_id'] or decision['next_stage']!=stage['next_stage'] or decision['decision_us']<stage['required_end_us']:audit.fail('STREAM_STAGE_DECISION','Adaptive branch changed the actual selected execution path')
    own_history=[r for r in ledger['pool']['history'] if r['owner']==ledger['owner']]
    if len(own_history)!=2 or [r['event'] for r in own_history]!=['acquire','release']:audit.fail('STREAM_ATTEMPT_LEASE_HISTORY','Attempt must have exactly one explicit acquisition and actual release');return
    acquire,release=own_history;cleanup_stage=stages.get('consume_cleanup' if finished['terminal']=='consumed' else 'reject_cleanup');last=cleanup_stage['cleanup'] if cleanup_stage else {}
    if acquire['epoch']!=finished['epoch'] or acquire['target_patch']!=protocol['data_block_id'] or set(acquire['resources'])!=set(protocol['required_leases']) or release['epoch']!=finished['epoch'] or release['released_us']<finished['end_us'] or set(release['reset_qubit_ids'])!=set(protocol['factory_qubit_ids']) or set(release['cleanup_action_ids'])!={r['action_id'] for r in last.values()}:audit.fail('STREAM_ATTEMPT_CLEANUP_RELEASE','Release lacks the same-epoch actual full factory cleanup')
    # After retirement this list legitimately contains only the retained suffix.
    # Whole-attempt evidence above comes from ALL independently indexed stages.
    hashes={s['atom_program_hash'] for s in stages.values()}
    if not set(release['committed_plan_hashes'])<=hashes or cleanup_stage is None or cleanup_stage['atom_program_hash'] not in release['committed_plan_hashes']:audit.fail('STREAM_RELEASE_PLAN_SUFFIX','Release suffix is not part of this complete verified attempt')
    if release['released_state']!={'kind':'physical_basis','basis':'Z','value':0,'encoding_status':'not_asserted_encoded'}:audit.fail('STREAM_RELEASE_STATE','Physical Z0 cleanup cannot assert encoding or ready magic')
    events=ledger['lifecycle'];token=ledger['token'];mapping={a['qubit_id']:a['atom_id'] for a in stream.initial['atoms']};expected_output=[mapping[q] for q in protocol['output']['qubit_ids']]
    if finished['terminal']=='rejected':
        if token is not None or any(e['event'] in ('ready','reserve_and_handoff','consume','consumption_executed','consumed') for e in events):audit.fail('STREAM_REJECTED_TOKEN','Rejected attempt minted or consumed a token')
    else:
        ready=[e for e in events if e['event']=='ready'];reserve=[e for e in events if e['event']=='reserve_and_handoff']
        if finished['accepted'] is not True or len(ready)!=1 or len(reserve)!=1 or 'convert_output' not in stages or 'consume' not in stages or token is None or token['status']!='consumed':audit.fail('STREAM_TOKEN_LIFECYCLE','Consumption requires one accepted conversion/ready/reservation and actual consume/cleanup')
        else:
            if ready[0]['ready_us']<stages['convert_output']['required_end_us'] or reserve[0]['time_us']<ready[0]['ready_us'] or reserve[0]['time_us']>stages['consume']['start_us'] or token['epoch']!=finished['epoch'] or token['output_atom_ids']!=expected_output or token['request_id']!=protocol['request_id'] or token['target_patch']!=protocol['data_block_id']:audit.fail('STREAM_TOKEN_IDENTITY_OR_TIME','Token/request/target/epoch/W4 carrier or ready/consume ordering changed')
            if reserve[0]['delivery_kind']!='same_carrier_scheduling_handoff' or reserve[0]['physical_motion_claimed'] is not False:audit.fail('STREAM_HANDOFF_CLAIM','Scheduling handoff alone cannot claim physical movement')
            stream.index.db.execute('INSERT INTO tokens VALUES(?,?)',(token['token_id'],json.dumps({'protocol_id':pid,'node_id':finished['node_id'],'epoch':finished['epoch'],'status':'consumed'},ensure_ascii=False)))
        stream.index.put_node(finished['node_id'],{'status':'completed','operation':protocol['request_gate'],'start_us':finished['start_us'],'end_us':finished['end_us'],'protocol_id':pid,'epoch':finished['epoch'],'ledger_hash':_hash(ledger)})
