"""Read every immutable R5 chunk before making a display-only merged trace."""
from copy import deepcopy
import gzip
import hashlib
from pathlib import Path

from . import canonical, finite
from .bundle import decode


def materialize_history(trace, *, archive_root=None, chunk_paths=None):
    """Return projection, original chunks and byte receipts; never execute R5."""
    if trace.get('schema_version') == 'event-session-trace/0.1':
        if trace.get('history_chunks'):
            raise ValueError('VIEW_HISTORY_LEGACY_WITH_CHUNKS')
        return trace, [], {}
    if trace.get('schema_version') != 'event-session-trace/0.2':
        raise ValueError('VIEW_HISTORY_SCHEMA')
    records = trace.get('history_chunks')
    if not isinstance(records, list) or not records:
        raise ValueError('VIEW_HISTORY_CHUNKS_REQUIRED')
    if chunk_paths is not None and (archive_root is not None or len(chunk_paths) != len(records)):
        raise ValueError('VIEW_HISTORY_PATH_COVERAGE')
    previous, end = None, 0
    chunks, receipts, paths = [], {}, set()
    actions, events, results, plans = {}, {}, {}, {}

    def merge(target, key, value, *, retained=False):
        if key in target:
            if not retained or target[key] != value:
                raise ValueError('VIEW_HISTORY_DUPLICATE_CONFLICT: ' + str(key))
        else:
            target[key] = value

    for index, record in enumerate(records):
        expected = canonical({k:v for k,v in record.items() if k not in ('path','chain_sha256')})
        if record.get('previous_chain_sha256') != previous or record.get('chain_sha256') != expected:
            raise ValueError('VIEW_HISTORY_CHAIN')
        if chunk_paths is not None:
            path = Path(chunk_paths[index]).resolve()
        elif archive_root is not None:
            # Both producer platforms may appear in relocated manifests.
            root = Path(archive_root).resolve()
            name = record['path'].replace('\\','/').split('/')[-1]
            path = (root/name).resolve()
            if not path.is_relative_to(root):
                raise ValueError('VIEW_HISTORY_PATH_ESCAPE')
        else:
            path = Path(record['path']).resolve()
        if path in paths:
            raise ValueError('VIEW_HISTORY_DUPLICATE_PATH')
        paths.add(path)
        if not path.is_file():
            raise ValueError('VIEW_HISTORY_MISSING_CHUNK: ' + str(path))
        raw = path.read_bytes()
        if len(raw) != record['size_bytes'] or hashlib.sha256(raw).hexdigest() != record['byte_sha256']:
            raise ValueError('VIEW_HISTORY_BYTES')
        body = decode(gzip.decompress(raw))
        if (body.get('schema_version') != 'event-session-chunk/0.1'
                or body.get('sequence') != index or body.get('run_id') != trace['run_id']
                or body.get('runtime_source_hashes') != trace['provenance']['runtime_source_hashes']
                or body.get('previous_chain_sha256') != previous):
            raise ValueError('VIEW_HISTORY_IDENTITY')
        if any(body.get(k) is not False for k in ('sampled','hardware_executed','quantum_state_simulated')):
            raise ValueError('VIEW_HISTORY_EXECUTION_LABELS')
        if (body.get('start_us') != end or body.get('start_us') != record['start_us']
                or not finite(body.get('end_us')) or body['end_us'] < end or body['end_us'] != record['end_us']):
            raise ValueError('VIEW_HISTORY_TIME')
        for field, count in [('actions','action_count'),('results','result_count'),('submitted_plans','plan_count')]:
            if len(body[field]) != record[count]:
                raise ValueError('VIEW_HISTORY_COUNT: ' + field)
        ids = [aid for p in body['submitted_plans'] for aid in p['action_ids']]
        if len(ids) != len(set(ids)) or set(ids) != set(body['actions']) or set(ids) != set(body['events']):
            raise ValueError('VIEW_HISTORY_ACTION_COVERAGE')
        for aid, action in body['actions'].items():
            event = body['events'][aid]
            if action['id'] != aid or event['action_id'] != aid or event['status'] not in ('completed','skipped'):
                raise ValueError('VIEW_HISTORY_ACTION_IDENTITY')
            if action['t_start_us'] < end or action['t_end_us'] > body['end_us']:
                raise ValueError('VIEW_HISTORY_ACTION_TIME')
            merge(actions, aid, action); merge(events, aid, event)
        for rid, value in body['results'].items():
            if value['action_id'] not in body['actions'] or value['ready_us'] > body['end_us']:
                raise ValueError('VIEW_HISTORY_RESULT_PRODUCER_OR_TIME')
            merge(results, rid, value)
        for plan in body['submitted_plans']:
            merge(plans, plan['artifact_id'], plan)
        receipts[f'history_{index:03d}'] = {
            'path':str(path),'name':path.name,'byte_sha256':record['byte_sha256'],
            'canonical_sha256':canonical(body),'compressed':True,'chain_sha256':record['chain_sha256']}
        chunks.append(body)
        previous, end = record['chain_sha256'], body['end_us']
    for event in trace['events']:
        aid = event['action_id']
        if aid not in events and event['t_start_us'] < end:
            raise ValueError('VIEW_HISTORY_SUFFIX_TIME')
        merge(events, aid, event, retained=True)
    for rid, value in trace['results'].items():
        merge(results, rid, value, retained=True)
    for plan in trace['submitted_plans']:
        if plan['artifact_id'] not in plans and plan['submitted_us'] < end:
            raise ValueError('VIEW_HISTORY_SUFFIX_TIME')
        merge(plans, plan['artifact_id'], plan, retained=True)
    all_ids = [aid for p in plans.values() for aid in p['action_ids']]
    if len(all_ids) != len(set(all_ids)) or set(all_ids) != set(events):
        raise ValueError('VIEW_HISTORY_TOTAL_COVERAGE')
    stats = trace['stats']
    if (stats['action_count'] != len(events) or stats['result_count'] != len(results)
            or stats['completed_action_count'] != sum(e['status'] in ('completed','skipped') for e in events.values())
            or stats['t_start_us'] != 0 or stats['duration_us'] != stats['t_end_us'] or stats['t_end_us'] < end):
        raise ValueError('VIEW_HISTORY_TOTAL_COUNT_OR_TIME')
    if any(r['action_id'] not in events for r in results.values()):
        raise ValueError('VIEW_HISTORY_RESULT_PRODUCER')
    projection = deepcopy(trace)
    projection.update(events=sorted(events.values(),key=lambda e:(e['t_start_us'],e['action_id'])),
                      results=results,submitted_plans=list(plans.values()),display_projection_only=True)
    return projection, chunks, receipts
