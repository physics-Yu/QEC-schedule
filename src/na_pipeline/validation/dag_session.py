"""Independent absolute-window, causal logical schedule and continuous-trace audit."""
from copy import deepcopy
from collections import Counter
from .checker import _hash,EPS
from .dag_core import DAGAudit,inspect_graph,physical_parallel_witnesses
from .dag_entry import inspect_inventory_continuity
from .strategy import inspect_strategy_plan
from .strategy_source import check_strategy_source


def inspect_window_binding(audit,relative,bound,context,results,run_id):
    if relative['schema_version']!='physical-plan/0.1' or context['schema_version']!='execution-context/0.1': raise ValueError('Unsupported plan/context version')
    original=relative['atom_program']; origin=context['time_us']
    if original.get('complete') is not True or original.get('provenance',{}).get('requires_runtime_binding'):
        audit.fail('DEFERRED_PLAN_NOT_EXECUTABLE','A deferred source cannot be promoted to an executable window by changing complete')
    binding=bound['session_binding']
    if binding['physical_plan_sha256']!=_hash(relative) or binding['execution_context']!=context or binding['time_origin_us']!=origin or context['run_id']!=run_id:
        audit.fail('WINDOW_BINDING_IDENTITY','Bound window is detached from the exact relative plan and live context')
    if relative['input_hashes']['device']!=context['device_hash'] or relative['input_hashes']['world_state']!=context['world_state_hash']:
        audit.fail('WINDOW_BINDING_WORLD','Compilation and submission refer to different device/world snapshots')
    old={a['id']:a for a in original['actions']}; new={a['id']:a for a in bound['actions']}
    if len(new)!=len(bound['actions']) or set(new)!=set(old): audit.fail('WINDOW_ACTION_COPY','Shared action records must be translated once, with exact identity coverage')
    for aid,action in new.items():
        if aid not in old: continue
        expected=deepcopy(old[aid]); expected['t_start_us']+=origin; expected['t_end_us']+=origin
        for key in ('result_ready_us','earliest_ready_us'):
            if key in expected['payload']: expected['payload'][key]+=origin
        if action!=expected: audit.fail('WINDOW_TIME_OR_BODY_CHANGED','Absolute action differs from one exact translation of its relative source',action_id=aid)
    dags={d['artifact_id']:d for d in relative['physical_dags']}; decisions=context['graph_decisions']
    if set(dags)!=set(decisions): audit.fail('WINDOW_DAG_COVERAGE','Context does not cover exactly the submitted original DAGs')
    used=set()
    for key,decision in decisions.items():
        dag=dags[key]; guard=dag['execution_guard']; reads=set(dag['external_reads'])|({guard['bit']} if guard else set()); used|=reads
        if decision['physical_dag_sha256']!=_hash(dag) or decision['execution_guard']!=guard or decision['external_reads']!=dag['external_reads']:
            audit.fail('WINDOW_ORIGINAL_GUARD_CHANGED','Context changed the original DAG, external reads or guard',physical_dag=key)
        for rid in reads:
            recorded=context['published_results'].get(rid); actual=results.get(rid)
            if not actual or actual['ready_us']>origin:
                audit.fail('WINDOW_GUARD_NOT_READY','Window used a result that was not actually published at its frontier',result_id=rid); continue
            expected=deepcopy(actual); expected['producer_ref']={'run_id':run_id,'action_id':actual['action_id'],'event_trace_ref':run_id+'/trace/'+str(context['revision'])}
            if recorded!=expected or decision['result_refs'].get(rid)!=expected['producer_ref']:
                audit.fail('WINDOW_GUARD_RECORD_CHANGED','Context value/producer/ready/reference differs from actual executed history',result_id=rid)
        selected=not guard or guard['bit'] in results and results[guard['bit']]['value']==guard['equals']
        if decision['decision']!='execute' or not selected: audit.fail('WINDOW_FALSE_GUARD_EXECUTED','A false original logical guard produced physical actions',physical_dag=key)
    if used!=set(context['published_results']): audit.fail('WINDOW_GUARD_WITNESS_COVERAGE','External/guard results require exact complete witness coverage')


def inspect_session_run(audit,bundle):
    device=bundle['device']; logical=bundle['logical_dag']; initial=bundle['initial_state']; windows=bundle['windows']; trace=bundle['event_trace']; schedule=bundle['logical_schedule']
    history=None
    if trace.get('schema_version')=='event-session-trace/0.2':
        from .dag_history import reconstruct_history
        history=audit.check('complete_archived_history_and_live_suffix',lambda:reconstruct_history(audit,trace,archive_root=bundle.get('archive_root')))
        if history is None:return
        trace=history['trace']
    if trace['schema_version']!='event-session-trace/0.1' or schedule['schema_version']!='LogicalSchedule/0.1': raise ValueError('Unsupported continuous trace or logical schedule')
    graph=inspect_graph(audit,logical['nodes'],logical['edges'])
    if graph is None: return
    if trace['complete_submitted_prefix'] is not True or trace['failure'] is not None: audit.need('SESSION_PREFIX_INCOMPLETE','Submitted physical prefix is not completely committed')
    if schedule['logical_dag_hash']!=_hash(logical): audit.fail('LOGICAL_SCHEDULE_INPUT','Logical schedule refers to another full DAG')
    atoms=deepcopy(initial['atoms']); traps={t['trap_id']:deepcopy(t) for t in initial['slm_traps']}; actions=[]; sources={}; plans_by_id={}; node_actions={}; node_sources={}; all_ops=[]
    for index,window in enumerate(windows):
        physical=window['physical_plan']; bound=window['atom_program']; context=bound['session_binding']['execution_context']
        inspect_window_binding(audit,physical,bound,context,trace['results'],trace['run_id'])
        if len(windows)!=len(trace['submitted_plans']): audit.fail('SESSION_SUBMISSION_COVERAGE','Stored windows differ from actual submitted-plan history')
        submitted=trace['submitted_plans'][index]
        if submitted['plan_hash']!=_hash(bound) or submitted['scenario_hash']!=_hash(window['scenario']) or set(submitted['action_ids'])!={a['id'] for a in bound['actions']}:
            audit.fail('SESSION_SUBMISSION_IDENTITY','Committed window hash/actions/scenario differ from its actual input',window=index)
        ids={a['id'] for a in actions}
        if ids&{a['id'] for a in bound['actions']}: audit.fail('SESSION_ACTION_REUSE','Physical action identity repeated across windows',window=index)
        actions.extend(bound['actions']); all_ops.extend(physical['source']['operations'])
        for sid,aids in bound['source_map'].items():
            if sid in sources: audit.fail('SESSION_SOURCE_REUSE','Two windows share a physical source instance',source_id=sid)
            sources[sid]=aids
        for trap in bound['initial_state']['slm_traps']:
            if trap['trap_id'] not in traps:
                if trap['occupant'] is not None: audit.fail('SESSION_NEW_OCCUPIED_SITE','A future static site declaration introduced an atom',window=index)
                traps[trap['trap_id']]=dict(deepcopy(trap),occupant=None)
            elif traps[trap['trap_id']]['position_um']!=trap['position_um']: audit.fail('SESSION_STATIC_SITE_MOVED','An existing SLM site moved between windows')
        for dag in physical['physical_dags']:
            nid=dag['logical_binding']['logical_node_id']
            inspect_instance_source(audit,dag,bundle['physical_bundle'],graph.nodes[nid])
            if nid in node_actions: audit.fail('LOGICAL_NODE_EXECUTED_TWICE','One logical node was submitted twice',node_id=nid)
            node_sources[nid]=[o['id'] for o in dag['nodes']]
            node_actions[nid]=sorted({a for o in dag['nodes'] for a in bound['source_map'][o['id']]})
        plans_by_id[bound['artifact_id']]=bound
        for rid,result in trace['results'].items():
            if result['action_id'] not in {a['id'] for a in bound['actions']}: continue
            if result.get('derivation')=='scenario':
                value=window['scenario']['results'][rid]
                if result['value']!=value['value'] or 'ready_us' in value and result['ready_us']!=value['ready_us']:
                    audit.fail('SESSION_SCENARIO_RESULT','Actual measurement differs from this instance scenario',result_id=rid)
    state={'atoms':atoms,'slm_traps':list(traps.values()),'aod_rows':deepcopy(initial['aod_rows']),'aod_columns':deepcopy(initial['aod_columns']),'time_us':0.}
    aggregate={'schema_version':'AtomProgram/0.2.0-draft','artifact_id':'R6-normalized-session:'+trace['run_id'],
               'provenance':{'owner':'R6','fixture':audit.fixture,'normalization':'union of original absolute actions and declared immutable empty SLM sites'},
               'execution_kind':'compile_plan','quantum_state_simulated':False,'hardware_executed':False,'loss_enabled':False,'complete':True,'device_ref':device['artifact_id'],
               'initial_state':state,'actions':actions,'source_map':sources,'stats':{}}
    # Public EventSession has a different envelope, but its event/result/state
    # records are checked unchanged. Stats are independently checked first.
    events=trace['events']; statuses=Counter(e['status'] for e in events)
    expected_stats={'atom_count':len(atoms),'action_count':len(actions),'completed_action_count':len(events),'result_count':len(trace['results'])}
    if any(trace['stats'].get(k)!=v for k,v in expected_stats.items()): audit.fail('SESSION_TRACE_COUNTS','Continuous trace summary differs from its actual event inventory')
    end=max([a['t_end_us'] for a in actions]+[r['ready_us'] for r in trace['results'].values()]); begin=min(a['t_start_us'] for a in actions)
    canonical={**deepcopy(trace),'schema_version':'EventTrace/0.2.0-draft','atom_program_ref':aggregate['artifact_id'],'device_ref':device['artifact_id'],
               'input_hashes':{'atom_program':_hash(aggregate),'device':_hash(device)},
               'stats':{'t_start_us':begin,'t_end_us':end,'duration_us':end-begin,'atom_count':len(atoms),'action_count':len(actions),'result_count':len(trace['results']),
                        'executed_action_count':statuses['completed'],'skipped_action_count':statuses['skipped']}}
    if trace['final_state']['time_us']<end: audit.fail('SESSION_FINAL_CLOCK','Final session clock precedes an actual action/result')
    canonical['final_state']['time_us']=end
    geometry=inspect_strategy_plan(audit,aggregate,device,trace=canonical)
    check_strategy_source(audit,{'qubits':[{'id':a['qubit_id']} for a in atoms]},aggregate,all_ops)
    inspect_inventory_continuity(audit,initial,[w['atom_program']['initial_state'] for w in windows]+[trace['final_state']])
    if history is not None:
        from .dag_history import inspect_history_checkpoints
        inspect_history_checkpoints(audit,history,actions,initial)
    if geometry is not None:
        for index,w in enumerate(windows):
            declared={a['atom_id']:a for a in w['atom_program']['initial_state']['atoms']}; seen=set()
            for action in w['atom_program']['actions']:
                for aid in action['atoms']:
                    if aid in seen: continue
                    seen.add(aid); actual=geometry['snapshots'][(action['id'],'before')][aid]
                    if any(actual.get(k)!=declared[aid].get(k) for k in ('qubit_id','position_um','carrier','trap_id','aod_group','row_id','column_id')):
                        audit.fail('SESSION_WINDOW_TELEPORT','Window entry differs from the independently reconstructed committed history',window=index,atom_id=aid)
    inspect_logical_schedule(audit,logical,graph,schedule,node_actions,actions,trace)
    physical_parallel_witnesses(audit,graph,node_actions,[dict(e,id=e['action_id']) for e in events],{n['id']:list(n['patch_operands'].values()) for n in logical['nodes']},node_sources=node_sources)
    audit.metrics.update(window_count=len(windows),logical_node_count=len(node_actions),session_clock_us=trace['final_state']['time_us'],physical_makespan_us=end-begin)


def inspect_instance_source(audit,dag,bundle,logical_node):
    nid=logical_node['id']; instance=bundle['instances'][nid]; spec=bundle['specifications'][instance['spec_ref']]
    if instance['spec_hash']!=spec['spec_hash'] or spec['spec_hash']!=_hash({k:v for k,v in spec.items() if k!='spec_hash'}): audit.fail('DAG_SPEC_IMMUTABILITY','Shared physical specification changed',node_id=nid)
    if dag['operation']!=logical_node['operation'] or dag['execution_guard']!=logical_node['condition'] or dag['logical_binding']['logical_source']!=logical_node:
        audit.fail('DAG_LOGICAL_PHYSICAL_BINDING','Physical graph changed the operation or original logical guard/source',node_id=nid)
    formal=spec['physical_dag']; actual={o['id']:o for o in dag['nodes']}; correspondence={r['formal_physical_op_id']:pid for pid,r in dag['source_map'].items()}
    if set(correspondence)!={o['id'] for o in formal['nodes']} or set(correspondence.values())!=set(actual): audit.fail('DAG_PHYSICAL_INSTANCE_COVERAGE','Physical graph is not a complete one-to-one instance of the immutable spec',node_id=nid); return
    roles=dag['logical_binding']['patch_bindings']
    qmap={q['id']:roles[q['block_id']] if q['block_id']=='bridge' else roles[q['block_id']]+'/'+q['local_id'] for q in formal['qubits']}
    rmap={x:y for o in formal['nodes'] for x,y in zip(o['writes'],actual[correspondence[o['id']]]['writes'])}
    for slot,formal_result in spec['public_results'].items():
        if rmap.get(formal_result)!=instance['public_result_bindings'][slot]: audit.fail('DAG_PUBLIC_RESULT_BINDING','Encoded result slot was bound to another physical producer',node_id=nid)
    for op in formal['nodes']:
        bound=actual[correspondence[op['id']]]
        condition=None if op['condition'] is None else {**op['condition'],'bit':rmap.get(op['condition']['bit'],op['condition']['bit'])}
        expected={'kind':op['kind'],'params':op['params'],'qubits':[qmap[q] for q in op['qubits']], 'reads':[rmap.get(r,r) for r in op['reads']], 'writes':[rmap[r] for r in op['writes']], 'after':[correspondence[d] for d in op['after']], 'condition':condition}
        if any(bound[k]!=v for k,v in expected.items()): audit.fail('DAG_PHYSICAL_INSTANCE_SEMANTICS','Binding changed a physical gate, parameter, dependency, result or condition',node_id=nid,source_id=bound['id'])


def inspect_logical_schedule(audit,logical,graph,schedule,node_actions,actions,trace):
    actual={a['id']:a for a in actions}; selected=set(); completed_at={}
    for nid,ids in node_actions.items():
        own={a for a in ids}; completed_at[nid]=max([actual[a]['t_end_us'] for a in own]+[r['ready_us'] for r in trace['results'].values() if r['action_id'] in own])
    for decision in schedule['decisions']:
        at=decision['time_us']; complete={n for n,t in completed_at.items() if t<=at and n in selected}; published={r for r,v in trace['results'].items() if v['ready_us']<=at}
        ready=set(graph.ready(complete,published))-selected
        if set(decision['ready_set'])!=ready: audit.fail('LOGICAL_ACTUAL_READY_SET','Logical decision is not based on actual physical completion/result readiness',time_us=at,expected=sorted(ready))
        for chosen in decision['selected']:
            nid=chosen['node_id']; ids=set(chosen['action_ids'])
            if nid not in ready or nid in selected or ids!=set(node_actions.get(nid,[])): audit.fail('LOGICAL_SELECTED_ACTION_BINDING','Chosen logical node is unready/repeated or detached from its physical actions',node_id=nid)
            elif abs(chosen['start_us']-min(actual[a]['t_start_us'] for a in ids))>EPS or abs(chosen['end_us']-completed_at[nid])>EPS:
                audit.fail('LOGICAL_ACTUAL_INTERVAL','Logical interval differs from its physical work and actual result availability',node_id=nid)
            selected.add(nid)
        for skipped in decision['skipped']:
            nid=skipped['node_id']; condition=graph.nodes[nid]['condition']
            if nid not in ready or not condition or trace['results'][condition['bit']]['value']==condition['equals']:
                audit.fail('LOGICAL_FALSE_SKIP','Logical skip has no actual ready false-condition evidence',node_id=nid)
            completed_at[nid]=at; selected.add(nid)
    if selected!=set(graph.nodes) or not schedule['complete']: audit.need('LOGICAL_PROGRAM_INCOMPLETE','Not every node of the supplied logical program was committed or correctly skipped')
    for rid,record in schedule['results'].items():
        if rid not in trace['results'] or any(record[k]!=trace['results'][rid][k] for k in ('value','origin','ready_us','action_id')):
            audit.fail('LOGICAL_RESULT_HISTORY','Logical result record differs from its actual physical producer',result_id=rid)


def validate_session_run(bundle):
    audit=DAGAudit('continuous_logical_physical_session',{'bundle':bundle},fixture=bundle.get('fixture',False))
    audit.interfaces={'R5-SESSION-BIND-001':'0.1.1','R5-DAG-IF-001':'0.1.0-draft'}
    if bundle.get('event_trace',{}).get('schema_version')=='event-session-trace/0.2':
        audit.interfaces['R5-HISTORY-001']='0.1.0-draft';audit.interfaces['R5-SESSION-BIND-001']='0.1.2'
    audit.check('all_windows_source_time_causality_and_geometry',lambda:inspect_session_run(audit,bundle))
    audit.need('COMPLETE_RESOURCE_WORLD_NOT_QUALIFIED','This component does not qualify the factory/scratch inventory, lifecycle or complete Shor program') if bundle.get('scope')=='complete_shor15' else None
    return audit.report()
