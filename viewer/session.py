"""Read-only display projection of original absolute-time R5 session windows."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

from . import canonical, check_model, group_projection
from .bundle import decode
from .history import materialize_history


def read(path):
    path=Path(path);raw=path.read_bytes();decoded=gzip.decompress(raw) if path.suffix=='.gz' else raw
    value=decode(decoded)
    return value,{'name':path.name,'path':str(path.resolve()),'byte_sha256':hashlib.sha256(raw).hexdigest(),'canonical_sha256':canonical(value),'compressed':path.suffix=='.gz'}


def session_projection(windows,trace,*,history_chunks=None):
    if trace.get('schema_version') not in {'event-session-trace/0.1','event-session-trace/0.2'} or trace.get('complete_submitted_prefix') is not True or trace.get('failure') is not None:
        raise ValueError('VIEW_SESSION_INCOMPLETE_PREFIX')
    if trace['schema_version']=='event-session-trace/0.2' and history_chunks is None:
        raise ValueError('VIEW_HISTORY_VERIFICATION_REQUIRED')
    if len(windows)!=len(trace.get('submitted_plans',[])) or not windows:raise ValueError('VIEW_SESSION_WINDOW_COVERAGE')
    projection=deepcopy(windows[0]['atom_program']);projection['artifact_id']='display-only:'+trace['artifact_id']
    projection['producer_version']='R7-session-display/0.1'
    projection['provenance']={'owner':'R7','display_projection':True,'backend_used':'original_R4_windows','fixture':False,'scope':'read-only concatenation of original absolute-time window actions; not an executable plan'}
    projection['actions']=[];projection['source_map']={};projection['input_hashes']={};projection['groups']=[]
    state={a['atom_id']:deepcopy(a) for a in projection['initial_state']['atoms']};events={e['action_id']:e for e in trace['events']}
    trap_declarations=[];trap_positions={};seen=set();previous_end=0
    for index,(window,submitted) in enumerate(zip(windows,trace['submitted_plans'],strict=True)):
        atom=window['atom_program'];check_model(atom)
        if canonical(atom)!=submitted['plan_hash'] or canonical(window['scenario'])!=submitted['scenario_hash'] or atom['artifact_id']!=submitted['artifact_id']:
            raise ValueError('VIEW_SESSION_SUBMITTED_HASH_MISMATCH')
        origin=atom['session_binding']['time_origin_us']
        if origin!=submitted['submitted_us'] or origin<previous_end:raise ValueError('VIEW_SESSION_WINDOW_TIME')
        current={a['atom_id']:a for a in atom['initial_state']['atoms']}
        if set(current)!=set(state):raise ValueError('VIEW_SESSION_CARRIER_SET_CHANGED')
        for ident,a in current.items():
            for key in ('qubit_id','position_um','carrier','trap_id','row_id','column_id','aod_group'):
                if a.get(key)!=state[ident].get(key):raise ValueError('VIEW_SESSION_ENTRY_DISCONTINUITY: '+ident+' '+key)
        ids=[a['id'] for a in atom['actions']]
        if len(ids)!=len(set(ids)) or seen.intersection(ids) or ids!=submitted['action_ids']:raise ValueError('VIEW_SESSION_DUPLICATE_OR_MISSING_ACTION')
        seen.update(ids)
        for trap in atom['initial_state'].get('slm_traps',[]):
            if trap['trap_id'] in trap_positions and trap_positions[trap['trap_id']]!=trap['position_um']:raise ValueError('VIEW_SESSION_TRAP_REDEFINED')
            trap_positions[trap['trap_id']]=trap['position_um']
        trap_declarations.append({'at_us':origin,'traps':deepcopy(atom['initial_state'].get('slm_traps',[]))})
        for a in sorted(atom['actions'],key=lambda a:(a['t_end_us'],a['t_start_us'])):
            if a['t_start_us']<origin:raise ValueError('VIEW_SESSION_PREORIGIN_ACTION')
            event=events.get(a['id'])
            if event is None:raise ValueError('VIEW_SESSION_EVENT_MISSING')
            if event['status']=='skipped':continue
            if a['kind']=='move':
                for t in a['payload']['trajectories']:
                    target=state[t['atom_id']];target['position_um']=t['to_um'];target['row_id']=t['row_id'];target['column_id']=t['column_id']
            if a['kind'] in ('pickup','drop'):
                p=a['payload']
                for b in p.get('bindings') or [{'atom_id':a['atoms'][0],**p}]:
                    target=state[b['atom_id']];pickup=a['kind']=='pickup'
                    target.update(carrier='AOD' if pickup else 'SLM',trap_id=b['to_trap_id'],row_id=b['row_id'] if pickup else None,column_id=b['column_id'] if pickup else None)
                    target['aod_group']=b.get('aod_group') or p.get('aod_group') or target['aod_group']
        previous_end=max((a['t_end_us'] for a in atom['actions']),default=origin)
        projection['actions'].extend(deepcopy(atom['actions']));projection['groups'].extend(deepcopy(atom.get('groups',[])))
        for source,actions in atom['source_map'].items():
            if source in projection['source_map']:raise ValueError('VIEW_SESSION_SOURCE_ALIAS')
            projection['source_map'][source]=deepcopy(actions)
    projection['stats']=deepcopy(trace['stats']);projection['window_refs']=[{'artifact_id':w['atom_program']['artifact_id'],'sha256':canonical(w['atom_program'])} for w in windows]
    check_model(projection,trace,trace_schema=trace['schema_version'])
    if history_chunks:
        by_id={a['id']:a for a in projection['actions']}
        for chunk in history_chunks:
            if any(by_id.get(aid)!=action for aid,action in chunk['actions'].items()):
                raise ValueError('VIEW_HISTORY_WINDOW_ACTION_MISMATCH')
    final=trace['final_state']['atoms'];final=list(final.values()) if isinstance(final,dict) else final
    if {a['atom_id'] for a in final}!=set(state) or len(final)!=len(state):raise ValueError('VIEW_SESSION_FINAL_CARRIER_COVERAGE')
    for a in final:
        for key in ('position_um','carrier','trap_id','row_id','column_id'):
            if a.get(key)!=state[a['atom_id']].get(key):raise ValueError('VIEW_SESSION_FINAL_STATE_MISMATCH')
    return projection,trap_declarations


def export_session_view(window_paths,trace_path,device_path,out,*,logical_path=None,schedule_path=None,report_path=None,report_receipt_path=None,archive_root=None):
    windows=[];receipts={}
    for i,path in enumerate(window_paths):
        value,receipt=read(path);windows.append(value);receipts[f'window_{i:03d}']=receipt
    trace,receipts['trace']=read(trace_path);device,receipts['device']=read(device_path)
    original_trace=trace
    trace,chunks,history_receipts=materialize_history(trace,archive_root=archive_root)
    receipts.update(history_receipts)
    projection,traps=session_projection(windows,trace,history_chunks=chunks)
    if any(w['atom_program']['device_ref']!=device['artifact_id'] for w in windows):raise ValueError('VIEW_SESSION_DEVICE_REFERENCE')
    calls=[];logical=None;schedule=None
    if (logical_path is None)!=(schedule_path is None):raise ValueError('VIEW_SESSION_LOGICAL_PAIR_REQUIRED')
    if logical_path is not None:
        logical,receipts['logical_dag']=read(logical_path);schedule,receipts['logical_schedule']=read(schedule_path)
        if schedule['logical_dag_hash']!=canonical(logical):raise ValueError('VIEW_SESSION_LOGICAL_HASH')
        by_id={n['id']:n for n in logical['nodes']}
        for nid,record in schedule['nodes'].items():
            node=by_id[nid]
            if record['status']=='skipped':continue
            if record['status']!='completed':raise ValueError('VIEW_SESSION_LOGICAL_NODE_INCOMPLETE')
            calls.append({'call_id':nid,'operation':node['operation'],'operands':node['patch_operands'],'source_ids':node['source_ids'],'start_us':record['start_us'],'end_us':record['completed_us'],'status':record['status'],'backend_used':'enola_ready_scheduler_and_constrained_router'})
    context={'schema_version':'r7-session-view/0.1','original_trace_schema':trace['schema_version'],'run_id':trace['run_id'],'window_count':len(windows),'windows':windows,'trap_declarations':traps,'display_projection_only':True,'full_program_complete':trace['full_program_complete']}
    payload={'viewer_version':'na-session-view/0.2','atom_program':projection,'trace':original_trace,'device':device,'receipts':receipts,'session_context':context,'logical_dag':logical,'logical_schedule':schedule,'mode':'fake_event_run','fixture':any(w['atom_program'].get('provenance',{}).get('fixture',False) for w in windows),'user_visual_acceptance':'pending','group_projection':group_projection(projection,trace)}
    if chunks:
        payload['display_trace']=trace
        context.update(history_chunks=chunks,history_chunk_count=len(chunks),history_bytes_and_chain_verified=True)
    if (report_path is None)!=(report_receipt_path is None):raise ValueError('VIEW_SESSION_REPORT_RECEIPT_REQUIRED')
    if report_path is not None:
        report,rr=read(report_path);report_receipt,br=read(report_receipt_path)
        root=Path(__file__).resolve().parents[1]
        if report.get('scope')!='continuous_logical_physical_session' or not report_receipt.get('inputs_unchanged') or not report_receipt.get('source_unchanged'):
            raise ValueError('VIEW_SESSION_REPORT_SCOPE_OR_STABILITY')
        for r in receipts.values():
            path=Path(r['path']);relative=path.relative_to(root).as_posix()
            if report_receipt.get('input_byte_sha256',{}).get(relative)!=r['byte_sha256']:raise ValueError('VIEW_SESSION_REPORT_INPUT_MISMATCH: '+relative)
        if report.get('passed')!=report_receipt.get('passed'):raise ValueError('VIEW_SESSION_REPORT_RECEIPT_DECISION_MISMATCH')
        for key,expected in [('action_count',len(projection['actions'])),('atom_count',len(projection['initial_state']['atoms'])),('result_count',len(trace['results']))]:
            if report.get('metrics',{}).get(key)!=expected:raise ValueError('VIEW_SESSION_REPORT_METRIC_MISMATCH')
        receipts['report']=rr;receipts['report_binding_receipt']=br;payload['report']=report
    if calls:payload['strategy_context']={'run_id':trace['run_id'],'calls':sorted(calls,key=lambda c:c['start_us']),'scope':'actual logical schedule, not strategy qualification'}
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    folder=Path(__file__).parent
    html=(folder/'viewer.html').read_text(encoding='utf-8').replace('/*__STYLE__*/',(folder/'viewer.css').read_text(encoding='utf-8')).replace('/*__SCRIPT__*/',(folder/'viewer.js').read_text(encoding='utf-8')).replace('__PAYLOAD__',encoded)
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(html.encode('utf-8'))
    result={'schema_version':'r7-session-view-receipt/0.1','path':str(out.resolve()),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'inputs':receipts,'window_count':len(windows),'action_count':len(projection['actions']),'atom_count':len(projection['initial_state']['atoms']),'full_shor_complete':False,'display_projection_only':True,'user_visual_acceptance':'pending','browser_verified':False}
    result.update(original_trace_schema=original_trace['schema_version'],history_chunk_count=len(chunks),history_bytes_and_chain_verified=bool(chunks))
    result['viewer_source_sha256']={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ('session.py','history.py','bundle.py','__init__.py','viewer.html','viewer.js','viewer.css')}
    out.with_suffix('.receipt.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    return result
