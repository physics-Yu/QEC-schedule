"""Independent instances, continuous batch world and reuse qualification."""
from collections import defaultdict

from .checker import EPS,_hash
from .strategy_source import check_strategy_source
from .strategy_groups import check_group_source,group_metrics


def check_call_counters(audit,instance,seen_key):
    """Count all binding attempts, including rejected composition attempts."""
    cid=instance['call_id']; before=instance['library_stats_before']; after=instance['library_stats_after']
    delta={name:after[name]-before[name] for name in ('strategy_compile_count','placement_search_count','routing_search_count','cache_hit_count','bind_count','composition_check_count')}
    if any(type(v) is not int or v<0 for v in delta.values()): audit.fail('LIBRARY_COUNTER_REWIND','Library counters decreased or are not integers',call_id=cid)
    if seen_key and any(delta[name]!=0 for name in ('strategy_compile_count','placement_search_count','routing_search_count')):
        audit.fail('REUSE_RECOMPILED','Repeated immutable strategy invoked compile/search again',call_id=cid)
    retries=instance.get('composition_retries',[])
    # R4 counts every entry into bind as a composition check. A failed bind
    # has no bind_count increment; an R5 joint-geometry rejection does.
    attempts=1+len(retries)
    if delta['composition_check_count']!=attempts or not 1<=delta['bind_count']<=attempts:
        audit.fail('BIND_COMPOSITION_COUNT','Every binding attempt needs a separately counted composition check',call_id=cid,attempts=attempts)
    for index,retry in enumerate(retries):
        if not retry.get('code') or retry['to_us']<=retry['from_us'] or (index and abs(retries[index-1]['to_us']-retry['from_us'])>EPS):
            audit.fail('COMPOSITION_RETRY_HISTORY','Composition retry lacks a reason or a continuous advancing clock',call_id=cid)
    if retries and abs(retries[-1]['to_us']-instance['binding']['start_time_us'])>EPS:
        audit.fail('COMPOSITION_RETRY_HISTORY','Final retry time does not equal the actual binding start',call_id=cid)
    return delta


def check_bound_source(audit,instance,strategy,ops):
    """Compare bound semantics with the immutable source, not a mutable copy."""
    from na_pipeline.qec import iter_physical_ops
    cid=instance['call_id']; original=strategy['body']['physical_program']
    formal=list(iter_physical_ops(original)); bound={op['id']:op for op in ops}
    report=instance['binding_report']; opmap=report['source_bindings']; results=report['result_bindings']; qmap=instance['binding']['qubit_bindings']
    if set(opmap)!={op['id'] for op in formal} or set(opmap.values())!=set(bound) or len(bound)!=len(ops) or len(set(opmap.values()))!=len(opmap):
        audit.fail('CALL_SOURCE_BINDING_MAP','Source binding map must cover both full programs injectively',call_id=cid); return
    origins={**opmap,original['artifact_id']:instance['physical_program']['artifact_id'],original['body'][0]['id']:cid}
    for old in formal:
        new=bound[opmap[old['id']]]
        expected={'kind':old['kind'],'qubits':[qmap[q] for q in old['qubits']], 'params':old['params'],
                  'reads':[results[r] for r in old['reads']],'writes':[results[r] for r in old['writes']],
                  'after':[opmap[s] for s in old['after']], 'condition':None if old.get('condition') is None else {**old['condition'],'bit':results[old['condition']['bit']]}}
        if any(new.get(k)!=v for k,v in expected.items()) or new.get('metadata')!=old.get('metadata'):
            audit.fail('CALL_SOURCE_SEMANTICS_CHANGED','Binding changed immutable source gates/parameters/dependencies/results',call_id=cid,source_id=new['id'])
        if not {origins.get(s,s) for s in old['source_ids']}<=set(new['source_ids']):
            audit.fail('CALL_SOURCE_ORIGIN_CHANGED','Binding dropped immutable source provenance',call_id=cid,source_id=new['id'])


def _encoded_calls(audit,run):
    program=run.get('encoded_program')
    if program is None:
        audit.need('ENCODED_PROGRAM_MISSING','Supply the original R2 EncodedLogicalProgram for end-to-end logical control qualification'); return
    if program['schema_version']!='EncodedLogicalProgram/0.1.0': audit.fail('ENCODED_PROGRAM_SCHEMA','Unsupported encoded logical program')
    mapping=run['encoded_call_map']; instances={i['call_id']:i for i in run['instances']}
    repeat_counts={n['id']:n['repeat'] for n in program['body']}; expected=set(); result_map=run.get('encoded_result_map',{})
    required_results=set()
    for node in program['body']:
        for index in range(node['repeat']):
            encoded_id=f"{node['id']}/r{index}"; expected.add(encoded_id)
            instance=instances[mapping[encoded_id]]
            if instance['operation']!=node['operation'] or instance['params']!=node['params'] or instance['operands']!=node['operands']:
                audit.fail('ENCODED_CALL_SEMANTICS','Logical operation/parameter/direction changed at controller boundary',call_id=instance['call_id'])
            if node.get('condition') is not None:
                audit.need('ENCODED_CONDITIONAL_CALL_UNSUPPORTED','Whole-call conditions have no qualified T303 primitive',call_id=instance['call_id'])
            deps=[f"{node['id']}/r{index-1}"] if index else [f'{d}/r{repeat_counts[d]-1}' for d in node['after']]
            if not {mapping[d] for d in deps}<=set(instance['after']): audit.fail('ENCODED_CALL_DEPENDENCY','An encoded call dependency was dropped',call_id=instance['call_id'])
            if not set(node['source_ids'])<=set(instance['source_ids']) or encoded_id not in instance['source_ids']:
                audit.fail('ENCODED_SOURCE_PROVENANCE','Encoded origin is absent from the call-to-physical chain',call_id=instance['call_id'])
            slots=instance['physical_program']['strategy_contract']['formal_bindings']['result_slots']
            by_slot={s['encoded_result_slot']:s['result_id'] for s in slots}
            for slot in node['writes']:
                key=f'{encoded_id}/{slot}'; required_results.add(key)
                if result_map.get(key)!=by_slot.get(slot) or result_map.get(key) not in run['event_trace']['results']:
                    audit.fail('ENCODED_RESULT_ALIAS','Encoded result slot is not bound to its actual per-call measurement',call_id=instance['call_id'],resource=key)
    if set(mapping)!=expected or set(mapping.values())!=set(instances) or len(mapping.values())!=len(set(mapping.values())):
        audit.fail('ENCODED_CALL_COVERAGE','Controller calls are not a one-to-one cover of the encoded program')
    if set(result_map)!=required_results: audit.fail('ENCODED_RESULT_COVERAGE','Encoded result mapping is incomplete or has extra slots')
    audit.metrics['encoded_calls']=len(expected); audit.metrics['encoded_result_slots']=len(required_results)


def inspect_run(audit,run,device,strategies,evidence):
    from .strategy import validate_strategy,inspect_strategy_plan
    from na_pipeline.qec import iter_physical_ops
    audit.check('encoded_logical_source',lambda:_encoded_calls(audit,run))
    values=list(strategies.values()) if isinstance(strategies,dict) else list(strategies)
    by_hash={s['strategy_hash']:s for s in values}
    reports={}
    for key,strategy in by_hash.items():
        report=validate_strategy(strategy,device,enola_evidence=evidence)
        reports[key]=report
        for failure in report['failures']: audit.failures.append({**failure,'strategy_hash':key})
        for pending in report['unverified']: audit.unverified.append({**pending,'strategy_hash':key})
    audit.metrics['strategy_reports']={key:{'passed':r['passed'],'failure_count':len(r['failures']),'unverified':r['unverified']} for key,r in reports.items()}
    plan=run['atom_program']; trace=run['event_trace']
    geometry=inspect_strategy_plan(audit,plan,device,trace=trace)
    actual={a['id']:a for a in plan['actions']}; used_actions=set(); call_ids=set(); result_ids=set(); counts=[]; epochs=set()
    by_block=defaultdict(list); same_strategy=defaultdict(set); group_reports=[]; call_cycles={}; ready_by_call={}
    if run.get('execution_kind')!='fake_event_run' or run.get('sampled') is not False or run.get('hardware_executed') is not False or run.get('quantum_state_simulated') is not False:
        audit.fail('STRATEGY_RUN_EVIDENCE_LABEL','Controller evidence must remain fake and unsampled')
    for instance in run['instances']:
        cid=instance['call_id']; key=instance['strategy_hash']
        if cid in call_ids: audit.fail('CALL_ID_REUSED','A call identity appears twice',call_id=cid)
        call_ids.add(cid)
        if key not in by_hash:
            audit.fail('STRATEGY_BODY_NOT_FOUND','Instance references an unavailable strategy',call_id=cid); continue
        strategy=by_hash[key]; body=strategy['body']; binding=instance['binding']
        bound=instance['atom_program']; physical=instance['physical_program']
        result_bindings=instance['binding_report']['result_bindings']
        template_results={a['payload']['result_id'] for a in body['atom_program']['actions'] if a['kind']=='measure'}
        if set(result_bindings)!=template_results or len(set(result_bindings.values()))!=len(result_bindings):
            audit.fail('CALL_RESULT_BINDING_MAP','Result binding map must cover the immutable result slots injectively',call_id=cid)
        if instance.get('status')!='completed': audit.need('CALL_NOT_COMPLETED','Only actual completed calls qualify',call_id=cid)
        if binding['call_id']!=cid or binding['run_id']!=run['snapshot']['run_id']:
            audit.fail('CALL_BINDING_IDENTITY','Binding belongs to another call/run',call_id=cid)
        if instance['operation']!=body['strategy_contract']['operation']['name'] or instance['params']!=body['strategy_contract']['operation']['params']:
            audit.fail('CALL_OPERATION_CHANGED','Bound call changed strategy operation or logical parameters',call_id=cid)
        if binding.get('epoch') is None: audit.fail('CALL_EPOCH_MISSING','Instance must retain a runtime epoch',call_id=cid)
        epoch=binding.get('epoch')
        if type(epoch) is not int or epoch<0 or epoch in epochs: audit.fail('CALL_EPOCH_REUSED','Runtime call epoch is invalid or reused',call_id=cid)
        epochs.add(epoch)
        for artifact in (instance['physical_program'],instance['atom_program']):
            if any(artifact['provenance'].get(k)!=v for k,v in {'call_id':cid,'run_id':binding['run_id'],'epoch':epoch,'strategy_hash':key}.items()):
                audit.fail('CALL_PROVENANCE_BINDING','Instance artifact provenance belongs to another binding',call_id=cid)
        source_atoms={a['atom_id']:a for a in body['atom_program']['initial_state']['atoms']}
        amap=binding['atom_bindings']; qmap=binding['qubit_bindings']; offset=binding['offset_um']; start=binding['start_time_us']
        if set(amap)!=set(source_atoms) or len(set(amap.values()))!=len(amap) or len(set(qmap.values()))!=len(qmap):
            audit.fail('CALL_BINDING_ALIAS','Formal atoms/qubits were omitted or aliased',call_id=cid)
        bound_atoms={a['atom_id']:a for a in bound['initial_state']['atoms']}
        for aid,atom in source_atoms.items():
            mapped=bound_atoms[amap[aid]]
            expected=[atom['position_um'][i]+offset[i] for i in (0,1)]
            if mapped['qubit_id']!=qmap[atom['qubit_id']] or mapped['carrier']!=atom['carrier'] or any(abs(a-b)>EPS for a,b in zip(mapped['position_um'],expected)):
                audit.fail('CALL_ENTRY_MISMATCH','Current carrier/position does not satisfy strategy entry transform',call_id=cid,resource=amap[aid])
        relative=body['atom_program']['actions']
        own=bound['actions']
        if len(relative)!=len(own): audit.fail('CALL_ACTION_COUNT','Binding added/dropped actions or silently recompiled the strategy',call_id=cid)
        for template,action in zip(relative,own):
            aid=action['id']
            if aid in used_actions or aid not in actual or actual[aid]!=action:
                audit.fail('CALL_ACTION_CHAIN','Bound action is duplicated, absent or changed in the actual shared timeline',call_id=cid,action_id=aid)
            used_actions.add(aid)
            if action['kind']!=template['kind'] or any(abs(action[k]-(template[k]+start))>EPS for k in ('t_start_us','t_end_us')):
                audit.fail('CALL_STRATEGY_TIME_CHANGED','Binding changed the cached relative action sequence/time',call_id=cid,action_id=aid)
            expected_atoms=[amap[a] for a in template['atoms']]
            if template['kind']=='gate' and template['payload'].get('name')=='CZ':
                if not set(expected_atoms)<=set(action['atoms']): audit.fail('CALL_ATOM_BINDING','CZ binding lost an illuminated template atom',call_id=cid,action_id=aid)
            elif action['atoms']!=expected_atoms: audit.fail('CALL_ATOM_BINDING','Binding changed action atom identities/order',call_id=cid,action_id=aid)
            if not aid.startswith(cid+'/'): audit.fail('CALL_ACTION_NAMESPACE','Action lacks its unique call prefix',call_id=cid,action_id=aid)
            if action['kind']=='move':
                src={t['atom_id']:t for t in template['payload']['trajectories']}
                for tr in action['payload']['trajectories']:
                    old=next((q for q,m in amap.items() if m==tr['atom_id']),None)
                    if old not in src: audit.fail('CALL_TRAJECTORY_BINDING','Trajectory atom is outside strategy binding',call_id=cid); continue
                    for field in ('from_um','to_um'):
                        if any(abs(tr[field][i]-(src[old][field][i]+offset[i]))>EPS for i in (0,1)):
                            audit.fail('CALL_TRAJECTORY_CHANGED','Binding changed cached route rather than translating it',call_id=cid,action_id=aid)
            if action['kind']=='measure':
                rid=action['payload']['result_id']
                expected_result=result_bindings.get(template['payload']['result_id'])
                if rid in result_ids or not rid.startswith(cid+'/') or rid!=expected_result:
                    audit.fail('CALL_RESULT_NAMESPACE','Result is reused or belongs to another invocation',call_id=cid,resource=rid)
                result_ids.add(rid)
            if geometry is not None:
                # Each instance entry is compared with the actual global state
                # at its first physical use, not just its predicted exit dict.
                for aid in action['atoms']:
                    if not any(aid in earlier['atoms'] for earlier in own[:own.index(action)]):
                        before=geometry['snapshots'].get((action['id'],'before'),{}).get(aid)
                        declared=bound_atoms.get(aid)
                        if before and declared and any(before.get(k)!=declared.get(k) for k in ('qubit_id','carrier','trap_id','position_um','aod_group')):
                            audit.fail('CALL_WORLD_DISCONTINUITY','Actual shared history differs from the bound entry snapshot',call_id=cid,resource=aid)
        ops=list(iter_physical_ops(physical))
        check_bound_source(audit,instance,strategy,ops)
        check_strategy_source(audit,physical,bound,ops)
        check_group_source(audit,physical,ops)
        local_groups=group_metrics(audit,bound,physical,trace)
        ready=max([start,*(a['t_end_us'] for a in own),*(trace['results'][rid]['ready_us'] for rid in instance['result_ids'])])
        call_cycles[cid]=ready-start; ready_by_call[cid]=ready
        if abs(instance['start_us']-start)>EPS or abs(instance['end_us']-ready)>EPS:
            audit.fail('CALL_ACTUAL_INTERVAL','Call bounds differ from actual action/result availability',call_id=cid)
        group_reports.extend({**entry,'call_id':cid,'cycle_duration_us':ready-start} for entry in local_groups)
        seen_key=key in [c['strategy_hash'] for c in counts]
        delta=check_call_counters(audit,instance,seen_key)
        binding_observation=(evidence or {}).get('binding_observations',{}).get(cid)
        if binding_observation is None:
            audit.need('BIND_SEARCH_OBSERVATION_MISSING','Independent zero-search observation for this binding is absent',call_id=cid)
        elif binding_observation.get('record_count')!=0 or any(binding_observation.get('project_search_counts',{}).values()):
            audit.fail('BIND_RERAN_ENOLA','Instance binding unexpectedly executed the upstream search kernel',call_id=cid)
        elif 'project_search_counts' not in binding_observation or binding_observation.get('project_sources_unchanged') is not True:
            audit.need('BIND_PROJECT_SEARCH_OBSERVATION_MISSING','Project placement/routing search was not independently observed for this binding',call_id=cid)
        counts.append({'call_id':cid,'strategy_hash':key,'counter_delta':delta})
        for logical_id in instance['operands'].values():
            if by_block[logical_id] and start<ready_by_call[by_block[logical_id][-1]['call_id']]-EPS:
                audit.fail('CALL_BLOCK_NOT_READY','Next block call starts before its predecessor results are ready',call_id=cid,resource=logical_id)
            by_block[logical_id].append(instance)
            if instance['operation']=='syndrome_round': same_strategy[key].add(logical_id)
    if used_actions!=set(actual): audit.fail('RUN_EXTRA_ACTIONS','Shared run contains actions outside all declared call instances')
    if result_ids!=set(trace['results']): audit.fail('RUN_RESULT_COVERAGE','Trace results do not equal all actual measurement instances')
    for instance in run['instances']:
        if any(dep not in ready_by_call or instance['start_us']<ready_by_call[dep]-EPS for dep in instance['after']):
            audit.fail('CALL_PREDECESSOR_NOT_READY','A declared predecessor has not completed before the call',call_id=instance['call_id'])
    snapshot=run['snapshot']
    if snapshot['world_state']!=trace['final_state']: audit.fail('CONTROLLER_FINAL_WORLD','Controller world does not equal the actual trace final state')
    if snapshot['revision']==1:
        if snapshot['results']!=trace['results'] or snapshot['illumination_counts']!=trace['illumination_counts']:
            audit.fail('CONTROLLER_FINAL_RESULTS','First committed batch results/illumination differ from its actual trace')
        expected_history=_hash([{k:i[k] for k in ('call_id','strategy_hash','start_us','end_us')} for i in run['instances']])
        if snapshot['history_hash']!=expected_history: audit.fail('CONTROLLER_HISTORY_HASH','Committed call history differs from actual instances')
    else: audit.need('PRIOR_COMMITTED_HISTORY_MISSING','This run needs its earlier committed batches to verify accumulated state')
    for lid,records in by_block.items():
        block=snapshot['blocks'][lid]
        owned={r for i in records for r in i['result_ids']}
        if block['epoch']!=len(records) or set(block['frame']['result_ids'])!=owned or block['ready_at_us']!=max(i['end_us'] for i in records):
            audit.fail('BLOCK_INSTANCE_STATE','Block epoch/frame result references/ready time do not match its own calls',resource=lid)
    checks={'full_patch_prepare':any(i['operation']=='prepare' for i in run['instances']),
            'single_block_three_rounds':any(sum(i['operation']=='syndrome_round' for i in records)>=3 for records in by_block.values()),
            'two_blocks_same_strategy':any(len(blocks)>=2 for blocks in same_strategy.values()),
            'cx_then_same_local_reuse':False,
            'independent_blocks_legal_overlap':any(not set(a['operands'].values())&set(b['operands'].values()) and max(a['start_us'],b['start_us'])<min(a['end_us'],b['end_us']) for index,a in enumerate(run['instances']) for b in run['instances'][index+1:])}
    for cx in [i for i in run['instances'] if i['operation']=='logical_cx']:
        good=True
        for lid in cx['operands'].values():
            before={i['strategy_hash'] for i in by_block[lid] if i['operation']=='syndrome_round' and i['end_us']<=cx['start_us']}
            after={i['strategy_hash'] for i in by_block[lid] if i['operation']=='syndrome_round' and i['start_us']>=cx['end_us']}
            good &= bool(before&after)
        checks['cx_then_same_local_reuse'] |= good
    for name,passed in checks.items():
        if not passed: audit.need('T000_CASE_NOT_DEMONSTRATED',f'Required qualification case {name} was not demonstrated')
    audit.metrics['groups']=group_reports; audit.metrics['reuse_calls']=counts; audit.metrics['t000_cases']=checks
    audit.metrics['call_cycle_duration_us']=call_cycles
    audit.metrics['cycle_duration_us']=max(ready_by_call.values())-min(i['start_us'] for i in run['instances'])
