"""Read-only whole-pipeline acceptance using the independent streaming checker."""
from pathlib import Path
import argparse
from collections import Counter
import gzip
import hashlib
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from na_pipeline.validation.stream_session import StreamingSessionValidator
from na_pipeline.validation.stream_factory import inspect_factory_ledger
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.runtime.history import verify_chunks
from na_pipeline.runtime.pipeline import save_artifact
from na_pipeline.frontend.logical_dag import build_logical_dag
from na_pipeline.device import validate_preinitialized_state
from na_pipeline.backend.enola_kernel import digest


def read(path):
    path=Path(path);raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def checked_ref(ref,directory):
    path=Path(directory)/Path(ref['path']).name
    if hashlib.sha256(path.read_bytes()).hexdigest()!=ref['byte_sha256']:
        raise ValueError('ARTIFACT_REFERENCE_HASH: '+str(path))
    return path


def reuse_failures(stats,guard=None):
    """Separate static component binding from native compilation/search."""
    failed=[]
    if stats['strategy_compile_count'] or any(stats['module_stats'][k] for k in
            ('leaf_compile_count','placement_search_count','routing_search_count','frontier_search_count')):
        failed.append('SHOR_EXECUTION_RECOMPILED')
    if 'geometry_cache_hits' in stats:
        if (not guard or guard.get('policy')!='reuse_only' or guard.get('violation_count')!=0 or
                guard.get('native_compile_allowance')!=0 or guard.get('batch_search_allowance')!=0):
            failed.append('SHOR_COMPILATION_GUARD_MISSING')
    elif stats['recipe_build_count']:
        failed.append('SHOR_EXECUTION_RECOMPILED')
    return failed


def audit_run(out, *, phase='execute', prefix=False):
    started=time.perf_counter();world=read(out/'world.json.gz');run=out/phase
    checker_hash=digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src/na_pipeline/validation').glob('*.py')})
    root=out/('validation-'+phase+'-'+checker_hash[:12]);root.mkdir(parents=True,exist_ok=True)
    bundle=read(run/'physical-bundle.json.gz')
    ledgers=[read(p) for p in sorted((run/'factory').glob('*.json.gz'))]
    protocols={l['protocol_ref']:l['protocol'] for l in ledgers}
    cp=read(run/'checkpoint.json.gz')['body']
    if cp.get('factory'):
        factory=cp['factory']['body']
        protocol=factory['protocol'];protocols[protocol['artifact_id']]=protocol
    index_paths=sorted((run/'window-index').glob('*.json'))
    validator=StreamingSessionValidator(world['device'],world['initial_state'],world['logical_dag'],bundle,root,
        budget={'max_expanded_file_bytes':512*1024**2,'max_window_actions':500000,
                'max_index_bytes':64*1024**3,'sqlite_cache_mib':128},resume=True)
    try:
        for i,path in enumerate(index_paths):
            if i<validator.sequence:continue
            item=read(path);window=checked_ref(item['window'],run/'windows')
            history=run/'history'/Path(item['history']['path']).name
            # Protocol bodies come from the exact committed ledger/checkpoint.
            # They are source inputs, not regenerated accepted results.
            data=read(window)
            factory_dags=[d for d in data['physical_plan']['physical_dags'] if d['operation']=='FACTORY_STAGE']
            protocol=None
            if factory_dags:
                binding=factory_dags[0]['protocol_binding']
                pid=binding.get('protocol_id',binding.get('protocol_ref'))
                protocol=protocols.get(pid)
                if protocol is None:raise ValueError('FROZEN_PROTOCOL_MISSING '+str(binding))
            del data
            report=validator.consume_files(item['history'],history,window,item['window']['byte_sha256'],protocol=protocol)
            if report['failures'] or not report['scoped_pass']:
                save_artifact(root/'first-failure.json',report)
                raise ValueError({'window':i,'failure_counts':dict(Counter(f['code'] for f in report['failures'])),'first_failures':report['failures'][:3],'unverified':report['unverified']})
            if i%25==0:print(json.dumps({'verified_windows':validator.sequence,'elapsed_seconds':round(time.perf_counter()-started,2)}),flush=True)
        if prefix:
            result={'status':'prefix_checked','verified_windows':validator.sequence,'full_program_passed':False}
            save_artifact(root/'prefix.json',result);return result
        trace=read(run/'event-trace.json.gz');schedule=read(run/'logical-schedule.json.gz');summary=read(run/'summary.json')
        audit=DAGAudit('basic_complete_shor_pipeline',{'world_hash':digest(world),'summary_hash':digest(summary)},fixture=False)
        for ledger in ledgers:
            audit.check('factory_ledger:'+ledger['protocol_ref'],lambda l=ledger:inspect_factory_ledger(validator,audit,l))
        validator.index.db.commit()
        nodes=world['logical_dag']['nodes'];states=schedule['nodes'];byid={n['id']:n for n in nodes}
        if digest(world['logical_dag'])!=digest(build_logical_dag()):audit.fail('SHOR_SOURCE_CHANGED','Complete original Shor DAG must be retained')
        if validate_preinitialized_state(world['initial_state'],world['device']):audit.fail('SHOR_WORLD_ENTRY','Complete canonical world is invalid')
        if len(world['initial_state']['atoms'])!=world['requirements']['physical_qubit_count']:audit.fail('SHOR_WORLD_SIZE','Finite inventory differs from required carriers')
        if not schedule['complete'] or set(states)!=set(byid):audit.fail('SHOR_NODE_COVERAGE','All original logical nodes must have a terminal status')
        if validator.sequence!=len(trace['history_chunks']) or validator.chain!=(trace['history_chunks'][-1]['chain_sha256'] if trace['history_chunks'] else None):audit.fail('SHOR_HISTORY_COVERAGE','Not every committed window was independently checked')
        if trace['failure'] is not None or not trace['complete_submitted_prefix']:audit.fail('SHOR_EVENT_INCOMPLETE','Event session did not reach a clean committed end')
        verified=verify_chunks(schedule.get('decision_chunks',[]),archive_root=run/'decisions')
        skip_witness={};decision_selected=set()
        for ref in verified:
            for decision in read(ref['path'])['decisions']:
                for value in decision.get('skipped',[]):
                    nid=value['node_id']
                    if nid in skip_witness:audit.fail('SHOR_DUPLICATE_SKIP','A source node was skipped twice',node_id=nid)
                    skip_witness[nid]=decision['time_us']
                for value in decision.get('selected',[]):
                    if 'stage_id' not in value:decision_selected.add(value['node_id'])
        ends={};starts={};counts=Counter();executed=Counter()
        for nid,state in states.items():
            status=state['status'];counts[status]+=1;node=byid[nid]
            if status=='skipped':
                at=skip_witness.get(nid);cond=node.get('condition');record=validator.index.result(cond['bit']) if cond else None
                if at is None or not record or record['ready_us']>at or record['value']==cond['equals']:
                    audit.fail('SHOR_UNJUSTIFIED_SKIP','Skip lacks a published false original condition',node_id=nid)
                ends[nid]=starts[nid]=at if at is not None else -1
                if validator.index.node(nid) is not None:audit.fail('SHOR_SKIPPED_EXECUTED','Skipped source was physically executed',node_id=nid)
            elif status=='completed':
                verified_node=validator.index.node(nid)
                if verified_node is None:audit.fail('SHOR_COMPLETION_WITHOUT_EVENTS','Logical completion lacks independently checked actions or factory consumption',node_id=nid);continue
                starts[nid]=verified_node['start_us'];ends[nid]=verified_node['end_us'];executed[node['operation']]+=1
                if state['completed_us']<ends[nid]:audit.fail('SHOR_EARLY_COMPLETION','Logical completion precedes physical/results boundary',node_id=nid)
            else:audit.fail('SHOR_NONTERMINAL_NODE','Original source remains unfinished',node_id=nid)
        for edge in world['logical_dag']['edges']:
            if edge['source'] in ends and edge['target'] in starts and ends[edge['source']]>starts[edge['target']]+1e-8:
                audit.fail('SHOR_SOURCE_CAUSALITY','A component precedes its original predecessor',source=edge['source'],target=edge['target'])
        for rid,record in schedule['results'].items():
            physical=validator.index.result(rid)
            if physical is None or any(physical[k]!=record[k] for k in ('value','ready_us','action_id','origin')):
                audit.fail('SHOR_CLASSICAL_OUTPUT','Logical result differs from verified physical output',result_id=rid)
        phase_bits=[validator.index.result('phase['+str(i)+']') for i in range(8)]
        if any(r is None for r in phase_bits):audit.fail('SHOR_EIGHT_READOUTS','Eight phase readouts were not produced')
        post=validator.index.result('postprocess/result')
        if post is None or post['value']!=summary['postprocess']:audit.fail('SHOR_POSTPROCESS','Final answer differs from the executed classical action')
        stats=read(out/'execution-stats.json')
        guard_path=run/'compilation-guard.json'
        for code in reuse_failures(stats,read(guard_path) if guard_path.exists() else None):
            audit.fail(code,'Final native compilation/search must be zero; new-interface runs require the fail-fast guard receipt')
        if validator.index.get_meta('active_factory') is not None:audit.fail('SHOR_FACTORY_ACTIVE','A factory attempt remains active')
        for need in validator.index.get_meta('needs',[]):audit.unverified.append(need)
        audit.metrics.update(logical_nodes=len(nodes),terminal_counts=dict(counts),executed_operation_counts=dict(executed),
            atoms=len(world['initial_state']['atoms']),verified_windows=validator.sequence,
            factory_attempts=len(ledgers),phase_bits=[r['value'] if r else None for r in phase_bits],
            postprocess=post['value'] if post else None,time_us=summary['time_us'],native_compile_calls_during_execution=0,
            wall_seconds=time.perf_counter()-started)
        result=audit.report();result.update(full_program_passed=result['passed'],
            execution_kind='complete_compile_schedule_fake_event_pipeline',sampled=False,quantum_state_simulated=False,
            hardware_executed=False,parallel_optimization_required=False,user_visual_acceptance='pending')
        save_artifact(out/'acceptance.json',result)
        if not result['passed']:raise ValueError({'failures':result['failures'],'unverified':result['unverified']})
        return result
    finally:validator.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--phase',default='execute');p.add_argument('--prefix',action='store_true');a=p.parse_args()
    result=audit_run(a.out,phase=a.phase,prefix=a.prefix)
    print(json.dumps({k:result[k] for k in ('passed','full_program_passed','metrics') if k in result},ensure_ascii=False))
