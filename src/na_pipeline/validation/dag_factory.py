"""Audit a frozen first factory stage without compiling or executing it again."""
from collections import Counter
from copy import deepcopy

from .checker import _hash
from .dag_core import DAGAudit,inspect_graph
from .dag_entry import inspect_inventory_continuity
from .dag_physical import inspect_physical_plan
from .dag_session import inspect_window_binding
from .dag_resources import inspect_protocol_completion
from .strategy_groups import check_group_source,group_metrics

PIN='2944dbf4e163e8d2eeeec607add0d9139edce689'
SCHEDULER_SHA='e5a77fb3980c4425f9aea5796d1fd28339359a14516fd4c9a5df25a26023d1e4'
ROUTER_SHA='a75e92353a74b6f3597a33b214d358b0782de2fa60400362c5e1967646cecb82'


def candidate_motion_witness(candidate,route_actions,pulse):
    """Follow every pre-pulse leg for this mover; detours are not direct moves."""
    mover=candidate['mover'];segments=[]
    for action in route_actions:
        if action['kind']!='move':continue
        own=[t for t in action['payload']['trajectories'] if t['atom_id']==mover]
        if len(own)>1:return {'passed':False,'reason':'duplicate_mover_trajectory','action_id':action['id']}
        if not own:continue
        if action['t_start_us']<pulse['t_end_us'] and action['t_end_us']>pulse['t_start_us']:
            return {'passed':False,'reason':'motion_overlaps_pulse','action_id':action['id']}
        if action['t_end_us']<=pulse['t_start_us']:segments.append((action,own[0]))
    segments.sort(key=lambda pair:(pair[0]['t_start_us'],pair[0]['t_end_us'],pair[0]['id']))
    point=candidate['from_um'];last_end=None;legs=[]
    for action,trajectory in segments:
        if trajectory['from_um']!=point:return {'passed':False,'reason':'discontinuous_path','action_id':action['id'],'expected_from_um':point,'actual_from_um':trajectory['from_um']}
        if last_end is not None and action['t_start_us']<last_end:return {'passed':False,'reason':'overlapping_legs','action_id':action['id']}
        legs.append({'action_id':action['id'],'from_um':trajectory['from_um'],'to_um':trajectory['to_um'],'start_us':action['t_start_us'],'end_us':action['t_end_us']})
        point=trajectory['to_um'];last_end=action['t_end_us']
    if point!=candidate['to_um']:return {'passed':False,'reason':'missing_motion' if not legs else 'wrong_endpoint','actual_to_um':point,'expected_to_um':candidate['to_um'],'legs':legs}
    return {'passed':True,'classification':'zero_displacement' if not legs else 'single_segment' if len(legs)==1 else 'continuous_multisegment','mover':mover,'from_um':candidate['from_um'],'to_um':point,'pulse_action_id':pulse['id'],'legs':legs}


def inspect_factory_stage_source(audit,inputs,plan):
    dag=inputs['physical_dag']; protocol=inputs['protocol']; binding=dag['protocol_binding']
    if binding['stage_id']!='initialize' or protocol['entry']!='initialize':
        audit.need('FACTORY_STAGE_PROFILE_UNSUPPORTED','This adapter currently covers the complete initialize stage only'); return
    if plan['physical_dags']!=[dag] or plan['input_hashes']['physical_dags']!=[_hash(dag)]:
        audit.fail('FACTORY_STAGE_SOURCE_BINDING','Compiled stage differs from its exact input DAG')
    stage=protocol['stages']['initialize']; template=protocol['templates'][stage['template_id']]
    if any(item['kind']!='op' for item in template['body']):
        audit.need('FACTORY_TEMPLATE_EXPANSION_UNSUPPORTED','Nested initialization template requires an explicit additional source adapter'); return
    prefix=stage['call_id']+'/r0/'; source={op['id']:op for op in dag['nodes']}; used=set()
    written={rid for item in template['body'] for rid in item['op']['writes']}
    def result(rid): return prefix+rid if rid in written else rid
    for item in template['body']:
        op=item['op']; identity=prefix+op['id']; bound=source.get(identity);used.add(identity)
        condition=None if op['condition'] is None else {**op['condition'],'bit':result(op['condition']['bit'])}
        expected={'kind':op['kind'],'qubits':[protocol['bindings'][q] for q in op['qubits']],'params':op['params'],
                  'reads':[result(r) for r in op['reads']],'writes':[result(r) for r in op['writes']],'condition':condition}
        if bound is None or any(bound[k]!=v for k,v in expected.items()) or not {prefix+d for d in op['after']}<=set(bound['after']) or not set(op['source_ids'])<=set(bound['source_ids']):
            audit.fail('FACTORY_TEMPLATE_OPERATION_CHANGED','Stage dropped or changed an original gate/reset/read/condition/parameter',source_id=identity)
    service={member['post_readout_reset_op_id'] for group in dag['groups'] for member in group['members']}
    if set(source)-used!=service:
        audit.fail('FACTORY_SERVICE_SOURCE_COVERAGE','Only explicit readout-service resets may augment this complete template',extra=sorted(set(source)-used-service),missing=sorted(service-set(source)))
    for group in dag['groups']:
        for member in group['members']:
            reset=source[member['post_readout_reset_op_id']]
            if reset['kind']!='reset' or reset['qubits']!=[member['physical_qubit_id']] or reset['params'].get('basis')!='Z' or member['measurement_op_id'] not in reset['after']:
                audit.fail('FACTORY_SERVICE_RESET','Readout-service reset lost its member, basis, or measurement dependency',source_id=reset['id'])
    live=set(protocol['live_data_information_qubit_ids'])
    if live!={protocol['data_block_id']+'/d'+str(i) for i in range(9)}:
        audit.fail('FACTORY_LIVE_TARGET','Protocol live-information identity changed')
    if any(op['kind'] in ('measure','reset') and set(op['qubits'])&live for op in source.values()):
        audit.fail('FACTORY_LIVE_DATA_DESTROYED','Initialization stage destroys the live target data')
    audit.metrics.update(template_source_operations=len(used),readout_service_resets=len(service),physical_operations=len(source),source_kinds=dict(Counter(op['kind'] for op in source.values())))


def inspect_stage_enola(audit,plan,observation):
    enola=plan['enola']; source={op['id']:op for op in plan['source']['operations']}; atom=plan['atom_program']; actions={a['id']:a for a in atom['actions']}
    if observation['schema_version']!='R6EnolaStageObservation/0.1' or observation['fixture'] or not observation['source_unchanged']:
        audit.fail('ENOLA_OBSERVATION_IDENTITY','Frozen original-source observation is absent, mutated or a fixture')
    for kind,path,expected in (('scheduler','enola/scheduler/gate_scheduler.py',SCHEDULER_SHA),('router','enola/router/router_mis.py',ROUTER_SHA)):
        if enola[kind]['commit']!=PIN or enola[kind]['source_sha256']!=expected or observation['source_hashes'][path]!=expected:
            audit.fail('ENOLA_SOURCE_PIN','Original scheduler/router identity changed',stage=kind)
    observed=[r for r in observation['records'] if r['function']=='gate_scheduling']; receipts=enola['schedule_decisions']
    if len(observed)!=len(receipts): audit.fail('ENOLA_SCHEDULER_COUNT','Published scheduler decisions differ from original observed returns')
    for actual,receipt in zip(observed,receipts):
        if actual['input_sha256']!=_hash(actual['inputs']) or actual['output_sha256']!=_hash(actual['output']) or receipt['sha256']!=_hash({k:v for k,v in receipt.items() if k!='sha256'}):
            audit.fail('ENOLA_DECISION_DIGEST','Original input/output or published receipt was altered')
        ops=receipt['input_operations']; qubits=receipt['qubit_index']; layers=receipt['raw_layers']; pairs=[[qubits.index(q) for q in op['qubits']] for op in ops]
        if pairs!=receipt['pairs'] or actual['inputs']!={'n_qubit':len(qubits),'list_gate':pairs} or actual['output']!=layers:
            audit.fail('ENOLA_SCHEDULER_OUTPUT_UNUSED','Published selection differs from the observed original scheduler input/return')
        if sorted(i for layer in layers for i in layer)!=list(range(len(ops))) or receipt['layers']!=[[ops[i]['id'] for i in layer] for layer in layers]:
            audit.fail('ENOLA_SCHEDULER_GATE_COVERAGE','Original pair projection dropped/duplicated a gate or changed its identity')
        for op in ops:
            if op!=source.get(op['id']) or op['kind']!='gate' or op['params']['name'] not in ('CX','CZ') or not set(op['after'])<=set(receipt['completed_ids']):
                audit.fail('ENOLA_SCHEDULER_UNREADY_SOURCE','Pair projection changed an operation or included a non-ready gate',source_id=op['id'])
        for layer in layers:
            q=[q for i in layer for q in ops[i]['qubits']]
            if len(q)!=len(set(q)): audit.fail('ENOLA_SCHEDULER_SHARED_QUBIT','One scheduler layer aliases a qubit')
    routes=enola['route_decisions']; count=observation['call_counts'].get('enola/router/router_mis.py:maximalis_solve_sort',0)
    if count!=len(routes) or observation['call_counts'].get('enola/router/router_mis.py:compatible_2D',0)<=0:
        audit.fail('ENOLA_ROUTE_CALL_COUNT','Router decisions have no matching original function calls')
    for record in routes:
        selected=record['selected_indices']; candidates=record['candidates']; conflicts={tuple(sorted(edge)) for edge in record['conflicts']}
        if any(tuple(sorted((a,b))) in conflicts for i,a in enumerate(selected) for b in selected[i+1:]): audit.fail('ENOLA_ROUTE_CONFLICT','Selected candidate set contains a declared conflict')
        chosen=[candidates[i] for i in selected]
        if [c['op_id'] for c in chosen]!=record['selected_op_ids']: audit.fail('ENOLA_ROUTE_SELECTION','Router receipt detached selected candidates from physical sources')
        pulse=actions[record['pulse_action_id']]
        if not record['accepted'] or pulse['kind']!='gate' or pulse['payload'].get('name')!='CZ': audit.fail('ENOLA_ROUTE_NOT_EXECUTED','Accepted route has no actual CZ pulse')
        for candidate in chosen:
            sid=candidate['op_id']; pair=set(candidate['pair'])
            if sid not in source or record['pulse_action_id'] not in atom['source_map'][sid] or pair not in [set(p) for p in pulse['payload']['pairs']]:
                audit.fail('ENOLA_ROUTE_OUTPUT_UNUSED','Selected original source/pair does not contribute to the physical pulse',source_id=sid)
            witness=candidate_motion_witness(candidate,[actions[aid] for aid in record['action_ids']],pulse)
            if not witness['passed']:
                audit.fail('ENOLA_ROUTE_MOTION_UNUSED','Candidate does not have a continuous actual route to the pulse endpoint',source_id=sid,witness=witness)
    audit.metrics.update(original_scheduler_calls=len(observed),original_router_calls=count,original_compatible_calls=observation['call_counts'].get('enola/router/router_mis.py:compatible_2D',0),router_receipts_mapped_to_actual_actions=len(routes))
    audit.need('ENOLA_ROUTER_RETURN_OBSERVATION_MISSING','Frozen observer captured original router call counts and source hashes, but not compatible_2D/MIS inputs and returns. Declared conflict/selection/action consistency is checked; exact original return provenance remains unverified.')


def validate_factory_initialize(inputs,plan,execution,observation):
    audit=DAGAudit('first_factory_initialize_in_205_world',{'input':inputs,'physical_plan':plan,'execution':execution,'observation':observation},fixture=False)
    audit.interfaces={'R1-PREINITIALIZED-IF-001':'0.2.0','R3-PHYSICAL-DAG-001':'0.2.0-draft','R4-HIERARCHICAL-IF-001':'0.1.0-draft','R5-SESSION-BIND-001':'0.1.1','R8-FACTORY-PHASE-001':'0.2.0'}
    atom=execution['atom_program']; trace=execution['event_trace']; initial=inputs['initial_state']; protocol=inputs['protocol']; pool=execution['resource_pool']
    audit.check('full_template_and_non_two_qubit_source',lambda:inspect_factory_stage_source(audit,inputs,plan))
    audit.check('exact_once_live_session_binding',lambda:inspect_window_binding(audit,plan,atom,inputs['execution_context'],trace['results'],trace['run_id']))
    def actual_submission():
        submitted=trace['submitted_plans']
        if len(submitted)!=1 or submitted[0]['plan_hash']!=_hash(atom) or submitted[0]['scenario_hash']!=_hash(execution['scenario']) or set(submitted[0]['action_ids'])!={a['id'] for a in atom['actions']}:
            audit.fail('FACTORY_STAGE_SUBMISSION','Trace is not the exact bound initialization plan/scenario')
        for rid,result in trace['results'].items():
            if result.get('derivation')=='scenario' and result['value']!=execution['scenario']['results'][rid]['value']: audit.fail('FACTORY_STAGE_SCENARIO','Committed fake result differs from this scenario',result_id=rid)
        if trace['failure'] is not None or trace['complete_submitted_prefix'] is not True: audit.fail('FACTORY_STAGE_PREFIX_INCOMPLETE','Factory stage did not finish its full submitted prefix')
    audit.check('actual_submission_and_fake_values',actual_submission)
    end=max([a['t_end_us'] for a in atom['actions']]+[r['ready_us'] for r in trace['results'].values()]);begin=min(a['t_start_us'] for a in atom['actions']);counts=Counter(e['status'] for e in trace['events'])
    canonical={**trace,'schema_version':'EventTrace/0.2.0-draft','atom_program_ref':atom['artifact_id'],'device_ref':inputs['device']['artifact_id'],'input_hashes':{'atom_program':_hash(atom),'device':_hash(inputs['device'])},
       'stats':{'t_start_us':begin,'t_end_us':end,'duration_us':end-begin,'atom_count':len(initial['atoms']),'action_count':len(atom['actions']),'result_count':len(trace['results']),'executed_action_count':counts['completed'],'skipped_action_count':counts['skipped']}}
    if trace['stats']['atom_count']!=len(initial['atoms']) or trace['stats']['action_count']!=len(atom['actions']) or trace['stats']['completed_action_count']!=len(trace['events']) or trace['stats']['result_count']!=len(trace['results']) or trace['final_state']['time_us']!=end:
        audit.fail('FACTORY_STAGE_TRACE_COUNTS','Original trace totals/frontier differ from committed actions/results')
    audit.check('global_geometry_sources_resources_trace',lambda:inspect_physical_plan(audit,{**plan,'atom_program':atom},inputs['device'],canonical))
    audit.check('all_actions_and_result_ready',lambda:inspect_protocol_completion(audit,[atom],trace,end))
    group_source={'qubits':inputs['physical_dag']['qubits'],'strategy_contract':{'operation':{'name':'factory_initialize'},'groups':inputs['physical_dag']['groups']}}
    audit.check('eight_auxiliary_source_groups',lambda:check_group_source(audit,group_source,plan['source']['operations']))
    audit.check('eight_auxiliary_actual_service',lambda:group_metrics(audit,atom,group_source,canonical))
    def inventory():
        inspect_inventory_continuity(audit,initial,[atom['initial_state'],trace['final_state']],required_qubit_ids=pool['qubit_to_atom'])
        mapping={a['qubit_id']:a['atom_id'] for a in initial['atoms']}
        if len(mapping)!=205 or Counter(a['aod_group'] for a in initial['atoms'])!={'data':85,'magic':120} or mapping!=pool['qubit_to_atom']: audit.fail('FACTORY_205_WORLD','Complete stable 205-carrier world is not preserved')
        if protocol['world_resource_ref']['sha256']!=pool['requirements_hash'] or inputs['physical_dag']['world_resource_ref']!=protocol['world_resource_ref'] or pool['requirements_hash']!=inputs['resource_pool']['requirements_hash']:
            audit.fail('FACTORY_REQUIREMENTS_IDENTITY','Stage, pool and protocol do not bind the same complete resource requirements')
        if pool['initial_ready_magic_tokens'] or initial['ready_magic_tokens'] or any(r['event']!='acquire' for r in pool['history']) or len(pool['active_leases'])!=1: audit.fail('FACTORY_INITIALIZE_FREE_READY_OR_RELEASE','First stage must retain its exclusive lease and cannot publish/release a ready resource')
        for lease in pool['active_leases'].values():
            if lease['ready_magic_token'] is not None or set(lease['resources'])!=set(protocol['required_leases']) or lease['target_patch']!=protocol['data_block_id'] or lease['epoch']!=protocol['epoch'] or lease['session_run_id']!=trace['run_id']: audit.fail('FACTORY_INITIALIZE_LEASE_BINDING','Stage changed its actual exclusive resource/epoch/live target')
        live={mapping[q] for q in protocol['live_data_information_qubit_ids']}
        if any(e['status']=='completed' and e['kind'] in ('measure','reset') and set(e['atoms'])&live for e in trace['events']): audit.fail('FACTORY_LIVE_DATA_EVENT','Committed stage destructively touched live data')
    audit.check('full_world_active_lease_live_data',inventory)
    audit.check('original_enola_source_scheduler_and_action_contribution',lambda:inspect_stage_enola(audit,plan,observation))
    audit.metrics.update(world_carriers=len(initial['atoms']),action_count=len(atom['actions']),result_count=len(trace['results']),readout_groups=len(inputs['physical_dag']['groups']),model_duration_us=end-begin,ready_magic_tokens=0,complete_factory_protocol=False,normalization='EventSession envelope adapted; unchanged original bound actions/events/results/state; original counts checked separately')
    return audit.report()
