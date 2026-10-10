"""Independent R5 chunk-byte/chain verification and exact history reconstruction.

This bounded-artifact adapter materializes the complete supplied history. It is
not yet the streaming verifier required for an arbitrarily large Shor run.
"""
from copy import deepcopy
from hashlib import sha256
import gzip,json,zlib
from math import isfinite
from pathlib import Path,PureWindowsPath,PurePosixPath

from .checker import _hash
from .dag_core import DAGAudit


def _unique_object(pairs):
    value={}
    for key,item in pairs:
        if key in value: raise ValueError('Duplicate JSON key: '+key)
        value[key]=item
    return value


def _path(record,archive_root):
    original=record['path']
    if archive_root is None:return Path(original)
    name=(PureWindowsPath(original) if '\\' in original else PurePosixPath(original)).name
    if name in ('','.','..') or '/' in name or '\\' in name:raise ValueError('Invalid relocated chunk name')
    root=Path(archive_root).resolve();path=(root/name).resolve()
    if not path.is_relative_to(root):raise ValueError('Archive path escaped the explicit root')
    return path


def reconstruct_history(audit,trace,*,archive_root=None):
    """Return a checked 0.1 view plus immutable original action/checkpoint data.

    Identical retained records in the active suffix are deduplicated. Repeated
    archived records or divergent suffix records are rejected, never overwritten.
    """
    if trace['schema_version']!='event-session-trace/0.2' or not trace['history_chunks']:
        audit.fail('HISTORY_SCHEMA','Chunked trace requires nonempty event-session-trace/0.2 history');return None
    chunks=trace['history_chunks'];events={};results={};actions={};plans=[];plan_ids=set();previous=None;end=0.;files=[];checkpoints=[];action_namespaces=set();result_namespaces=set();paths=set()
    failed_before=len(audit.failures)
    def add_unique(target,entries,label,allow_retained=False):
        for identity,value in entries.items():
            if identity in target:
                if not allow_retained:audit.fail('HISTORY_DUPLICATE_ARCHIVED_RECORD','A supposedly new chunk repeats a prior record',record_type=label,identity=identity)
                elif target[identity]!=value:audit.fail('HISTORY_RETAINED_RECORD_CONFLICT','Active retained record disagrees with its original archived record',record_type=label,identity=identity)
            else:target[identity]=value
    def add_plans(entries):
        for plan in entries:
            identity=plan['plan_hash']
            if identity in plan_ids:audit.fail('HISTORY_PLAN_REPLAY','A physical plan appears in multiple history segments',plan_hash=identity)
            plan_ids.add(identity);plans.append(plan)
    for index,record in enumerate(chunks):
        expected_chain=_hash({k:v for k,v in record.items() if k not in ('path','chain_sha256')})
        if record['previous_chain_sha256']!=previous or record['chain_sha256']!=expected_chain:
            audit.fail('HISTORY_CHAIN','Chunk manifest chain is changed or out of order',chunk=index)
        try:
            path=_path(record,archive_root);raw=path.read_bytes()
            if path in paths:audit.fail('HISTORY_PATH_REUSE','Different chunks refer to the same file',chunk=index)
            paths.add(path)
            actual_hash=sha256(raw).hexdigest()
            if actual_hash!=record['byte_sha256'] or len(raw)!=record['size_bytes']:
                audit.fail('HISTORY_CHUNK_BYTES','Chunk byte digest/size differs from the immutable manifest',chunk=index);return None
            body=json.loads(gzip.decompress(raw),object_pairs_hook=_unique_object)
        except (OSError,ValueError,EOFError,zlib.error) as exc:
            audit.fail('HISTORY_CHUNK_UNREADABLE','A required history chunk is missing or invalid',chunk=index,error=str(exc));return None
        if body['schema_version']!='event-session-chunk/0.1' or body['sequence']!=index or body['run_id']!=trace['run_id'] or body['previous_chain_sha256']!=previous:
            audit.fail('HISTORY_CHUNK_IDENTITY','Chunk body does not belong to this run, sequence, or predecessor',chunk=index)
        if body['runtime_source_hashes']!=trace['provenance']['runtime_source_hashes']:
            audit.fail('HISTORY_RUNTIME_CHANGED','Archived history and active suffix use different runtime identities',chunk=index)
        if any(body[key] is not False for key in ('sampled','quantum_state_simulated','hardware_executed')):
            audit.fail('HISTORY_EXECUTION_SCOPE','Chunk changed fake/no-state/no-hardware labels',chunk=index)
        if not all(type(t) in (int,float) and isfinite(t) for t in (body['start_us'],body['end_us'])) or body['start_us']!=end or body['end_us']<end or body['end_us']!=record['end_us'] or body['start_us']!=record['start_us'] or body['final_state']['time_us']!=body['end_us']:
            audit.fail('HISTORY_CHUNK_TIME','Chunk frontier is discontinuous or disagrees with its physical world',chunk=index)
        own=body['actions'];own_events=body['events'];own_results=body['results'];ids=set(own)
        if record['action_count']!=len(own) or record['result_count']!=len(own_results) or record['plan_count']!=len(body['submitted_plans']):
            audit.fail('HISTORY_MANIFEST_COUNTS','Chunk manifest totals differ from the actual stored records',chunk=index)
        expected_ids=[aid for p in body['submitted_plans'] for aid in p['action_ids']]
        if len(expected_ids)!=len(set(expected_ids)) or set(expected_ids)!=ids or ids!=set(own_events):audit.fail('HISTORY_CHUNK_COVERAGE','Actions, actual terminal events and submitted-plan coverage differ',chunk=index)
        local_namespaces=set();local_result_namespaces=set()
        for aid,action in own.items():
            event=own_events.get(aid)
            if action['id']!=aid or event is None or event['action_id']!=aid or event['status'] not in ('completed','skipped'):
                audit.fail('HISTORY_ACTION_IDENTITY','Stored action/event identity or completion changed',action_id=aid);continue
            if any(event.get(k)!=v for k,v in action.items() if k!='id'):audit.fail('HISTORY_ACTION_EVENT_CONFLICT','Archived event changed its original action',action_id=aid)
            if not body['start_us']<=action['t_start_us']<=action['t_end_us']<=body['end_us']:audit.fail('HISTORY_ACTION_OUTSIDE_CHUNK','Chunk contains work outside its committed time window',action_id=aid)
            namespace=aid.split('/',1)[0]
            if namespace.startswith(('window:','strategy-instance:')):
                if namespace in action_namespaces:audit.fail('HISTORY_CLOSED_INSTANCE_REUSED','A retired physical instance reappeared in a later chunk',action_id=aid)
                local_namespaces.add(namespace)
        for rid,result in own_results.items():
            if result['action_id'] not in ids or result['ready_us']>body['end_us']:audit.fail('HISTORY_RESULT_PRODUCER','Chunk result lacks its own committed ready producer',result_id=rid)
            if '/r0/' in rid:
                namespace=rid.rsplit('/r0/',1)[0]
                if namespace in result_namespaces:audit.fail('HISTORY_CLOSED_RESULT_INSTANCE_REUSED','A retired result instance was used by a new chunk',result_id=rid)
                local_result_namespaces.add(namespace)
        action_namespaces|=local_namespaces;result_namespaces|=local_result_namespaces
        add_unique(actions,own,'action');add_unique(events,own_events,'event');add_unique(results,own_results,'result');add_plans(body['submitted_plans'])
        checkpoints.append({'end_us':body['end_us'],'final_state':body['final_state'],'illumination_counts':body['illumination_counts']})
        files.append({'path':str(path),'byte_sha256':actual_hash,'chain_sha256':record['chain_sha256'],'size_bytes':len(raw)})
        end=body['end_us'];previous=record['chain_sha256']
    suffix_events={e['action_id']:e for e in trace['events']}
    if len(suffix_events)!=len(trace['events']):audit.fail('HISTORY_SUFFIX_DUPLICATE','Active suffix repeats an event identity')
    suffix_ids={a for p in trace['submitted_plans'] for a in p['action_ids']}
    if suffix_ids&set(actions):audit.fail('HISTORY_SUFFIX_PLAN_REPLAY','A retired action was submitted again in the live suffix')
    for aid,event in suffix_events.items():
        if aid not in events and (aid not in suffix_ids or event['t_start_us']<end or aid.split('/',1)[0] in action_namespaces):audit.fail('HISTORY_SUFFIX_EVENT','New suffix event has no new plan or uses a retired instance/time',action_id=aid)
    for rid,record in trace['results'].items():
        if rid not in results and (record['action_id'] not in suffix_ids or '/r0/' in rid and rid.rsplit('/r0/',1)[0] in result_namespaces):audit.fail('HISTORY_SUFFIX_RESULT','New suffix result has no new producer or uses a retired instance',result_id=rid)
    retained_events=len(set(events)&set(suffix_events));retained_results=len(set(results)&set(trace['results']))
    add_unique(events,suffix_events,'event',True);add_unique(results,trace['results'],'result',True);add_plans(trace['submitted_plans'])
    stats=trace['stats'];all_action_ids={a for p in plans for a in p['action_ids']}
    if stats['action_count']!=len(all_action_ids) or stats['completed_action_count']!=len(events) or stats['result_count']!=len(results):audit.fail('HISTORY_CUMULATIVE_COUNTS','Session totals do not equal deduplicated complete history plus live suffix')
    if trace['final_state']['time_us']<end or stats['t_end_us']!=trace['final_state']['time_us']:audit.fail('HISTORY_SUFFIX_FRONTIER','Active suffix frontier precedes a committed chunk')
    if not trace['submitted_plans'] and (trace['final_state']!=checkpoints[-1]['final_state'] or trace['illumination_counts']!=checkpoints[-1]['illumination_counts']):audit.fail('HISTORY_FINAL_STATE','Without new plans, active world or illumination counts differ from the final archived state')
    if trace['complete_submitted_prefix'] and set(events)!=all_action_ids:audit.fail('HISTORY_COMPLETE_EVENT_COVERAGE','Claimed complete prefix omits actions from the full archived history')
    audit.metrics.update(history_chunk_count=len(chunks),history_files=files,history_chain_sha256=previous,history_events=len(events),history_results=len(results),history_plans=len(plans),retained_events_deduplicated=retained_events,retained_results_deduplicated=retained_results,history_storage_model='complete supplied history materialized; large-Shor streaming validation not qualified')
    if len(audit.failures)!=failed_before:return None
    view={**trace,'schema_version':'event-session-trace/0.1','events':list(events.values()),'results':results,'submitted_plans':plans}
    return {'trace':view,'archived_actions':actions,'checkpoints':checkpoints}


def inspect_history_checkpoints(audit,history,actions,initial):
    """Bind archive action bodies and intermediate physical carriers to the run."""
    actual={a['id']:a for a in actions}
    for aid,action in history['archived_actions'].items():
        if actual.get(aid)!=action:audit.fail('HISTORY_ORIGINAL_ACTION_CHANGED','Archive differs from the original submitted window',action_id=aid)
    world={a['atom_id']:deepcopy(a) for a in initial['atoms']};events=sorted(history['trace']['events'],key=lambda e:(e['t_end_us'],e['action_id']));position=0
    for checkpoint in history['checkpoints']:
        while position<len(events) and events[position]['t_end_us']<=checkpoint['end_us']:
            world.update(events[position]['state_after']);position+=1
        archived={a['atom_id']:a for a in checkpoint['final_state']['atoms']}
        fields=('qubit_id','position_um','carrier','trap_id','aod_group','row_id','column_id')
        if set(archived)!=set(world) or any(any(a.get(k)!=world[aid].get(k) for k in fields) for aid,a in archived.items() if aid in world):audit.fail('HISTORY_WORLD_CHECKPOINT','Chunk world differs from the same committed physical action history',end_us=checkpoint['end_us'])


def validate_session_history(trace,*,archive_root=None,fixture=False):
    audit=DAGAudit('session_history_integrity',{'trace':trace},fixture=fixture);audit.interfaces={'R5-HISTORY-001':'0.1.0-draft'}
    audit.check('all_chunk_bytes_chain_and_suffix',lambda:reconstruct_history(audit,trace,archive_root=archive_root))
    return audit.report()
