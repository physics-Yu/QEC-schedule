"""Release already archived action objects; never clone an execution state."""
import gzip
import json
from .history import verify_chunks
from .engine import digest
from .errors import fail


def compact_archived_frontier(session, keep_result_ids):
    if session.queue or session.pending_results or session.state.active or session.failure or session.plans:
        fail('COMPACTION_NOT_ARCHIVED','Only an entirely retired, committed frontier can be compacted')
    keep=set(keep_result_ids)
    if not keep<=session.results.keys():fail('COMPACTION_RESULT_MISSING','Requested live result is absent')
    archived=set()
    for chunk in verify_chunks(session.history_chunks):
        with gzip.open(chunk['path'],'rt',encoding='utf8') as stream:body=json.load(stream)
        if body['run_id']!=session.run_id:fail('COMPACTION_RUN_MISMATCH','History belongs to another run')
        if set(body['actions'])-body['events'].keys():fail('COMPACTION_EVENT_MISSING','Archived action lacks its event')
        if any(e['status'] not in ('completed','skipped') for e in body['events'].values()):
            fail('COMPACTION_HISTORY_NOT_COMPLETE','Archived action is not terminal')
        archived.update(body['actions'])
    if not session.actions.keys()<=archived:fail('COMPACTION_UNARCHIVED_ACTION','A live action lacks immutable history')
    live={session.results[r]['action_id'] for r in keep}
    if not live<=session.actions.keys():fail('COMPACTION_PRODUCER_MISSING','Required result producer is missing')
    before=digest(session.state.export(session.now_us))
    receipt={'schema_version':'ArchivedFrontierCompaction/0.1','run_id':session.run_id,'time_us':session.now_us,
             'before_actions':len(session.actions),'after_actions':len(live),'kept_results':len(keep),
             'history_chain_sha256':session.history_chunks[-1]['chain_sha256'],
             'runtime_replayed':False,'tokens_or_epochs_changed':False,'world_sha256':before}
    session.results={r:session.results[r] for r in keep}
    session.producers={r:session.producers[r] for r in keep}
    session.configured={r:v for r,v in session.configured.items() if r in keep}
    for field in ('actions','events','completed'):
        value=getattr(session,field);setattr(session,field,{a:value[a] for a in live})
    if before!=digest(session.state.export(session.now_us)):fail('COMPACTION_WORLD_CHANGED','Compaction changed the physical state')
    return receipt
