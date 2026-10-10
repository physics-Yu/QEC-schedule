"""Read-only binding/tamper probes against R5's real archived five-window run."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from viewer import canonical
from viewer.bundle import load_bundle
from viewer.history import materialize_history
from viewer.session import read,session_projection


def main():
    source=ROOT/'examples/scenarios/T505-dag-session-chunked-v1'
    trace=read(source/'event-trace.json.gz')[0]
    windows=[read(p)[0] for p in sorted(source.glob('window-*.json.gz'))]
    original=canonical({'trace':trace,'windows':windows})
    full,chunks,receipts=materialize_history(trace,archive_root=source/'history')
    plan,_=session_projection(windows,full,history_chunks=chunks)
    assert len(full['events'])==2111 and len(full['results'])==64 and len(chunks)==5
    assert plan['actions']==[a for w in windows for a in w['atom_program']['actions']]
    assert len(trace['events'])==64 and not trace['submitted_plans']
    checks=[{'case':'all_five_chunks_and_retained_suffix_deduplicated','passed':True}]

    def reject(label,call,code):
        try:call()
        except ValueError as exc:
            assert code in str(exc),(label,str(exc))
            checks.append({'case':label,'passed':True,'rejection':str(exc)})
        else:raise AssertionError('Tamper accepted: '+label)

    changed=deepcopy(trace);changed['events'][0]['payload']['viewer_tamper']=True
    reject('retained_event_conflict',lambda:materialize_history(changed,archive_root=source/'history'),'DUPLICATE_CONFLICT')
    changed=deepcopy(trace);next(iter(changed['results'].values()))['value']=99
    reject('retained_result_conflict',lambda:materialize_history(changed,archive_root=source/'history'),'DUPLICATE_CONFLICT')
    changed=deepcopy(trace);changed['history_chunks'].reverse()
    reject('reordered_chunks',lambda:materialize_history(changed,archive_root=source/'history'),'CHAIN')
    changed=deepcopy(trace);changed['stats']['action_count']-=1
    reject('false_cumulative_count',lambda:materialize_history(changed,archive_root=source/'history'),'TOTAL_COUNT')
    reject('unverified_suffix_cannot_project',lambda:session_projection(windows,trace),'VERIFICATION_REQUIRED')
    changed_chunks=deepcopy(chunks)
    next(iter(changed_chunks[0]['actions'].values()))['t_end_us']+=1
    reject('chunk_actions_must_equal_original_windows',lambda:session_projection(windows,full,history_chunks=changed_chunks),'WINDOW_ACTION_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='r7-history-') as tmp:
        root=Path(tmp);history=root/'history';history.mkdir()
        for receipt in receipts.values():
            shutil.copyfile(receipt['path'],history/receipt['name'])
        first=history/next(iter(receipts.values()))['name'];raw=first.read_bytes()
        first.unlink()
        reject('missing_chunk',lambda:materialize_history(trace,archive_root=history),'MISSING_CHUNK')
        first.write_bytes(raw+b' ')
        reject('changed_compressed_bytes',lambda:materialize_history(trace,archive_root=history),'BYTES')
        first.write_bytes(raw)
        # Test nonempty active suffix by archiving only the first four chunks.
        suffix=deepcopy(trace);suffix['history_chunks']=suffix['history_chunks'][:-1]
        suffix['submitted_plans']=deepcopy(chunks[-1]['submitted_plans'])
        suffix['events']=list(chunks[-1]['events'].values())+deepcopy(trace['events'])
        suffix['results']={**chunks[-1]['results'],**trace['results']}
        merged,_,_=materialize_history(suffix,archive_root=history)
        assert merged['events']==full['events'] and merged['results']==full['results']
        checks.append({'case':'nonempty_active_suffix_plus_retained_records','passed':True})
        chunk_manifest={'schema_version':'r7-history-files/0.1','files':[
            {'path':'history/'+r['name'],'byte_sha256':r['byte_sha256']} for r in receipts.values()]}
        manifest={'schema_version':'r7-hierarchical-bundle/0.1','bundle_id':'r7-history-reader-check',
                  'kb_revision':'kb-0006','entry_mode':'preinitialized','fixture':True,'files':[]}
        for role,value in [('trace',trace),('chunk_manifest',chunk_manifest)]:
            p=root/(role+'.json');p.write_bytes(json.dumps(value).encode())
            manifest['files'].append({'role':role,'path':p.name,'byte_sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        path=root/'bundle.json';path.write_bytes(json.dumps(manifest).encode())
        _,values,receipt=load_bundle(path)
        assert values['trace']==trace and receipt['history']['merged_event_count']==2111
        assert receipt['full_program_passed'] is False
        checks.append({'case':'bundle_checks_every_chunk_preserves_original_trace','passed':True})
        first.unlink()
        reject('bundle_missing_chunk',lambda:load_bundle(path),'MISSING_CHUNK')
    assert canonical({'trace':trace,'windows':windows})==original
    checks.append({'case':'original_input_objects_unchanged','passed':True})
    result={'schema_version':'r7-history-view-checks/0.1','passed':True,'source':str(source),
            'original_input_canonical_sha256':original,'chunk_count':len(chunks),'checks':checks,
            'scope':'display binding and complete history bytes only; no physical or browser qualification'}
    output=ROOT/'scripts/outputs/T704/history-view-checks.json'
    output.write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'passed':True,'checks':len(checks),'output':str(output)},ensure_ascii=False))


if __name__=='__main__':main()
