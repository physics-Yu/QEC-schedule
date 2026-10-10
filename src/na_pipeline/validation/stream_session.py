"""One-window independent verification with exact on-disk global identities.

No producer acceptance flags, runtime replay, compilation, or all-history list.
The index is an evidence index belonging to this exact verification run.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json,sqlite3,time
from pathlib import Path

from .checker import Audit,EPS,_hash,_contract,_timing,_resources
from .dag_core import DAGAudit,inspect_graph
from .dag_entry import inspect_mz_receiver
from .dag_session import inspect_window_binding,inspect_instance_source
from .geometry import check_geometry
from .strategy_capture import capture_closure
from .strategy_groups import check_readout_capacity,check_group_source,group_metrics
from .strategy_source import check_strategy_source
from .trace import check_trace
from .stream_io import CertifiedIndex,read_json_bound,StreamBudgetExceeded


def _write(path,value):
    raw=(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8');path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=raw:raise ValueError('Refusing to overwrite immutable stream evidence: '+str(path))
    path.write_bytes(raw);return sha256(raw).hexdigest()


def _world(initial):
    world={k:deepcopy(initial[k]) for k in ('atoms','slm_traps','aod_rows','aod_columns')};world['time_us']=initial.get('time_us',initial.get('t_start_us',0.))
    for atom in world['atoms']:
        atom.setdefault('reset_epoch',0);atom.setdefault('measurement_count',0);atom.setdefault('preparation_status','unspecified')
    return world


class StreamingSessionValidator:
    def __init__(self,device,initial_state,logical_dag,physical_bundle,output_root,*,budget,fixture=False,resume=False):
        required={'max_expanded_file_bytes','max_window_actions','max_index_bytes','sqlite_cache_mib'}
        if set(budget)!=required or any(type(v) is not int or v<=0 for v in budget.values()):raise ValueError('Explicit finite integer streaming budgets required')
        self.device=device;self.logical=logical_dag;self.bundle=physical_bundle;self.initial=initial_state;self.fixture=fixture;self.budget=budget
        self.out=Path(output_root);self.out.mkdir(parents=True,exist_ok=True)
        sources={p.name:sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
        self.identity={'device':_hash(device),'initial_state':_hash(initial_state),'logical_dag':_hash(logical_dag),'physical_bundle':_hash(physical_bundle),'verifier_sources':sources,'budget':budget,'fixture':fixture}
        self.index=CertifiedIndex(self.out/'index.sqlite3',budget['sqlite_cache_mib']);prior=self.index.get_meta('identity')
        if prior is not None and (not resume or prior!=self.identity):raise ValueError('Stream output exists or identity changed; use a new result root')
        if prior is None:
            self.index.put_meta('identity',self.identity);self.index.put_meta('world',_world(initial_state));self.index.put_meta('illumination',{a['atom_id']:0 for a in initial_state['atoms']});self.index.put_meta('sequence',0);self.index.put_meta('chain',None);self.index.put_meta('report_chain',None);self.index.put_meta('needs',[]);self.index.put_meta('next_epoch',0);self.index.db.commit()
        self.world=self.index.get_meta('world');self.illumination=self.index.get_meta('illumination');self.sequence=self.index.get_meta('sequence');self.chain=self.index.get_meta('chain');self.report_chain=self.index.get_meta('report_chain')
        audit=DAGAudit('stream_logical_structure',{},fixture=fixture);self.graph=inspect_graph(audit,logical_dag['nodes'],logical_dag['edges'])
        if audit.failures or self.graph is None:raise ValueError('Invalid source LogicalDAG: '+str(audit.failures[:3]))
        self.last_report=None

    def close(self):self.index.close()

    def _read(self,path,digest):return read_json_bound(path,digest,self.budget['max_expanded_file_bytes'])

    def consume_files(self,chunk_record,chunk_path,window_path,window_sha256,*,compiled_path=None,compiled_sha256=None,protocol=None):
        """Read exactly one chunk and window; an optional frozen relative plan is shared by old fixtures."""
        try:
            if Path(chunk_path).stat().st_size!=chunk_record['size_bytes']:raise ValueError('Chunk compressed size changed')
            body,chunk_bytes=self._read(chunk_path,chunk_record['byte_sha256']);window,window_bytes=self._read(window_path,window_sha256)
            if compiled_path is not None:
                original,extra_bytes=self._read(compiled_path,compiled_sha256);window['physical_plan']=original['physical_plan'];window_bytes+=extra_bytes;del original
            return self._consume_checked(chunk_record,body,window,input_bytes={'chunk':chunk_record['byte_sha256'],'window':window_sha256,'compiled':compiled_sha256},expanded_bytes=chunk_bytes+window_bytes,protocol=protocol)
        except (OSError,ValueError,EOFError) as exc:
            audit=DAGAudit('stream_window',{},fixture=self.fixture);audit.fail('STREAM_BUDGET_EXHAUSTED' if isinstance(exc,StreamBudgetExceeded) else 'STREAM_INPUT_READ',str(exc));return self._failed(audit)

    def _failed(self,audit):
        report=audit.report();report['status']='budget_exhausted_incomplete' if any('BUDGET' in x['code'] for x in audit.failures) else 'failed_incomplete';report['last_verified_chunk_count']=self.sequence
        _write(self.out/'failed'/f'{self.sequence:07}-{_hash(report)[:16]}.json',report);self.last_report=report;return report

    def _consume_checked(self,record,body,window,*,input_bytes,expanded_bytes=0,protocol=None):
        audit=DAGAudit('stream_window',{'input_bytes':input_bytes,'history_record':record},fixture=self.fixture);started=time.perf_counter();plan=window['physical_plan'];atom=window['atom_program'];own_results=body['results'];events=body['events'];actions=atom['actions']
        if len(actions)>self.budget['max_window_actions'] or self.index.bytes()>self.budget['max_index_bytes']:
            audit.fail('STREAM_BUDGET_EXHAUSTED','Action or disk budget reached; no history is truncated');return self._failed(audit)
        self.index.db.execute('BEGIN IMMEDIATE')
        try:
            audit.check('chunk_identity_chain_and_coverage',lambda:self._chunk(audit,record,body,window))
            external_results={};external_actions={}
            local_ids={a['id'] for a in actions};own_writers=set(own_results)
            reads={r for a in actions for r in a['payload'].get('reads',[])}|{a['condition']['bit'] for a in actions if a['condition']}
            reads|={r for d in plan['physical_dags'] for r in d['external_reads']}
            reads|={d['execution_guard']['bit'] for d in plan['physical_dags'] if d['execution_guard']}
            for rid in reads-own_writers:
                value=self.index.result(rid)
                if value is None:audit.fail('STREAM_EXTERNAL_RESULT_MISSING','Cross-window read has no previously verified producer',result_id=rid)
                else:external_results[rid]=value
            for dep in {d for a in actions for d in a['depends_on']}-local_ids:
                value=self.index.action(dep)
                if value is None or value['status'] not in ('completed','skipped'):audit.fail('STREAM_EXTERNAL_DEPENDENCY_MISSING','Cross-window dependency was not previously verified',action_id=dep)
                else:external_actions[dep]=value
            audit.check('prior_world_to_actual_window',lambda:self._entry(audit,atom))
            audit.check('runtime_guard_and_exact_time_binding',lambda:inspect_window_binding(audit,plan,atom,atom['session_binding']['execution_context'],external_results,body['run_id']))
            geometry=audit.check('independent_window_geometry_trace',lambda:self._physical(audit,body,window,external_actions,external_results))
            audit.check('complete_source_projection',lambda:self._source(audit,plan,atom,body,protocol))
            if geometry is None:audit.need('STREAM_GEOMETRY_INCOMPLETE','Window geometry did not complete')
            if audit.failures:
                self.index.db.rollback();return self._failed(audit)
            for action in actions:
                aid=action['id'];event=events[aid]
                self.index.db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?)',(aid,_hash(action),_hash(event),action['t_end_us'],event['status'],self.sequence))
            for rid,value in own_results.items():self.index.db.execute('INSERT INTO results VALUES(?,?,?,?)',(rid,_hash(value),json.dumps(value,ensure_ascii=False,allow_nan=False),self.sequence))
            for op in plan['source']['operations']:self.index.db.execute('INSERT INTO sources VALUES(?,?,?)',(op['id'],_hash(op),self.sequence))
            if self.index.bytes()>self.budget['max_index_bytes']:raise StreamBudgetExceeded('Index storage budget exceeded; transaction not certified')
            audit.metrics.update(chunk_sequence=self.sequence,action_count=len(actions),result_count=len(own_results),expanded_input_bytes=expanded_bytes,external_results_loaded=len(external_results),external_dependencies_loaded=len(external_actions),wall_seconds=time.perf_counter()-started)
            report=audit.report();report_path=f'segments/{self.sequence:07}.json';report_hash=_write(self.out/report_path,report)
            segment={'sequence':self.sequence,'input_bytes':input_bytes,'history_chain_sha256':record['chain_sha256'],'report':report_path,'report_byte_sha256':report_hash,'previous_report_chain_sha256':self.report_chain,'start_us':body['start_us'],'end_us':body['end_us'],'action_count':len(actions),'result_count':len(own_results),'scoped_pass':report['scoped_pass'],'passed':report['passed']}
            segment_hash=_hash(segment);self.index.db.execute('INSERT INTO segments VALUES(?,?,?)',(self.sequence,json.dumps(segment,ensure_ascii=False),segment_hash))
            needs=self.index.get_meta('needs',[])
            for item in audit.unverified:
                if not any(x['code']==item['code'] for x in needs):needs.append(item)
            self.index.put_meta('needs',needs);self.index.put_meta('world',body['final_state']);self.index.put_meta('illumination',body['illumination_counts']);self.index.put_meta('sequence',self.sequence+1);self.index.put_meta('chain',record['chain_sha256']);self.index.put_meta('report_chain',segment_hash)
            self.index.put_meta('max_expanded_input_bytes',max(expanded_bytes,self.index.get_meta('max_expanded_input_bytes',0)));self.index.db.commit()
            self.world=deepcopy(body['final_state']);self.illumination=dict(body['illumination_counts']);self.sequence+=1;self.chain=record['chain_sha256'];self.report_chain=segment_hash;self.last_report=report
            return report
        except (KeyError,TypeError,ValueError,IndexError,sqlite3.IntegrityError) as exc:
            self.index.db.rollback();audit.fail('STREAM_BUDGET_EXHAUSTED' if isinstance(exc,StreamBudgetExceeded) else 'STREAM_INVALID_OR_REPLAYED_RECORD',str(exc));return self._failed(audit)

    def _chunk(self,audit,record,body,window):
        if record['chain_sha256']!=_hash({k:v for k,v in record.items() if k not in ('path','chain_sha256')}) or record['previous_chain_sha256']!=self.chain or body['previous_chain_sha256']!=self.chain:
            audit.fail('STREAM_HISTORY_CHAIN','Chunk does not extend the previously certified byte chain')
        if body['sequence']!=self.sequence or body['schema_version']!='event-session-chunk/0.1' or body['start_us']!=self.world['time_us'] or body['end_us']<body['start_us'] or record['start_us']!=body['start_us'] or record['end_us']!=body['end_us'] or body['final_state']['time_us']!=body['end_us']:
            audit.fail('STREAM_CHUNK_FRONTIER','Chunk sequence/time does not extend the certified physical frontier')
        identity=self.index.get_meta('runtime_identity')
        current={'run_id':body['run_id'],'runtime_source_hashes':body['runtime_source_hashes']}
        if identity is not None and identity!=current:audit.fail('STREAM_RUNTIME_IDENTITY','Run/runtime changed across chunks')
        self.index.put_meta('runtime_identity',current)
        if any(body[k] is not False for k in ('sampled','quantum_state_simulated','hardware_executed')):audit.fail('STREAM_SCOPE_LABEL','Execution labels changed')
        atom=window['atom_program'];actions={a['id']:a for a in atom['actions']};events=body['events'];plans=body['submitted_plans']
        if (atom['initial_state'].get('time_us')!=body['start_us'] or
                atom['session_binding']['time_origin_us']!=body['start_us'] or
                atom['session_binding']['execution_context']['time_us']!=body['start_us']):
            audit.fail('STREAM_WINDOW_TIME_ORIGIN','Bound window must start at the independently certified history frontier')
        if len(actions)!=len(atom['actions']) or actions!=body['actions'] or set(actions)!=set(events) or len(plans)!=1 or plans[0]['plan_hash']!=_hash(atom) or plans[0]['scenario_hash']!=_hash(window['scenario']) or set(plans[0]['action_ids'])!=set(actions):
            audit.fail('STREAM_ORIGINAL_WINDOW_COVERAGE','Chunk is not exactly the complete original bound window and scenario')
        if (record['action_count'],record['result_count'],record['plan_count'])!=(len(actions),len(body['results']),len(plans)):audit.fail('STREAM_CHUNK_COUNTS','Byte manifest counts differ from stored records')
        for action in actions.values():
            if action['t_start_us']<body['start_us'] or action['t_end_us']>body['end_us']:audit.fail('STREAM_ACTION_OUTSIDE_FRONTIER','Committed chunk is not a complete nonoverlapping window',action_id=action['id'])
        for kind,ids in (('action',actions),('result',body['results'])):
            namespaces=set()
            for identity in ids:
                namespace=identity.split('/',1)[0] if kind=='action' and identity.startswith(('window:','strategy-instance:')) else identity.rsplit('/r0/',1)[0] if kind=='result' and '/r0/' in identity else None
                if namespace:namespaces.add(namespace)
            for namespace in namespaces:self.index.db.execute('INSERT INTO namespaces VALUES(?,?,?)',(kind,namespace,self.sequence))
        for rid,value in body['results'].items():
            if value['action_id'] not in actions or value['ready_us']>body['end_us']:audit.fail('STREAM_RESULT_NOT_COMMITTED','Chunk contains an absent or not-ready producer',result_id=rid)
            if value.get('derivation')=='scenario':
                expected=window['scenario']['results'][rid]
                if value['value']!=expected['value'] or 'ready_us' in expected and value['ready_us']!=expected['ready_us']:audit.fail('STREAM_FAKE_RESULT_CHANGED','Actual fake bit differs from the exact original scenario',result_id=rid)

    def _entry(self,audit,atom):
        entry=atom['initial_state'];prior={a['atom_id']:a for a in self.world['atoms']};actual={a['atom_id']:a for a in entry['atoms']}
        fields=('qubit_id','position_um','carrier','trap_id','aod_group','row_id','column_id','reset_epoch','measurement_count')
        if set(actual)!=set(prior) or any(any(value.get(k,0 if k in ('reset_epoch','measurement_count') else None)!=prior[aid].get(k,0 if k in ('reset_epoch','measurement_count') else None) for k in fields) for aid,value in actual.items() if aid in prior):audit.fail('STREAM_WORLD_DISCONTINUITY','Window resets, teleports, replaces or drops a previously certified carrier')
        old={t['trap_id']:t for t in self.world['slm_traps']};new={t['trap_id']:t for t in entry['slm_traps']}
        if not set(old)<=set(new) or any(new[k]!=v for k,v in old.items()) or any(t['occupant'] is not None for k,t in new.items() if k not in old):audit.fail('STREAM_STATIC_WORLD_CHANGED','Existing sites changed or a new site supplied a carrier')
        if entry['aod_rows']!=self.world['aod_rows'] or entry['aod_columns']!=self.world['aod_columns']:audit.fail('STREAM_AOD_FRONTIER','Initial shared axes changed across windows')

    def _physical(self,audit,body,window,external_actions,external_results):
        atom=window['atom_program'];events=list(body['events'].values());start=min(a['t_start_us'] for a in atom['actions']);end=body['end_us'];counts=Counter(e['status'] for e in events)
        delta={aid:count-self.illumination.get(aid,0) for aid,count in body['illumination_counts'].items()}
        trace={'schema_version':'EventTrace/0.2.0-draft','artifact_id':body['run_id']+'/stream/'+str(self.sequence),'provenance':{'owner':'R6','normalization':'one unchanged original window/events; independently checked cumulative illumination delta'},'execution_kind':'fake_event_run','quantum_state_simulated':False,'hardware_executed':False,'loss_enabled':False,'sampled':False,'measurement_origin':'fake','atom_program_ref':atom['artifact_id'],'device_ref':self.device['artifact_id'],'events':events,'results':body['results'],'final_state':body['final_state'],'illumination_counts':delta,'stats':{'t_start_us':start,'t_end_us':end,'duration_us':end-start,'action_count':len(atom['actions']),'atom_count':len(self.world['atoms']),'result_count':len(body['results']),'executed_action_count':counts['completed'],'skipped_action_count':counts['skipped']}}
        low=Audit();low.guard('contract',_contract,atom,self.device,trace,None);low.guard('timing',_timing,atom,self.device,external_actions,external_results);low.guard('resources',_resources,atom)
        geometry=low.guard('geometry',check_geometry,atom,self.device);low.guard('trace',check_trace,atom,self.device,trace,geometry,external_results,end)
        audit.failures.extend(low.failures);audit.unverified.extend(low.unverified);audit.metrics.update(low.metrics)
        capture_closure(audit,atom,self.device)
        if geometry is not None:check_readout_capacity(audit,atom,self.device,geometry);inspect_mz_receiver(audit,atom['actions'],geometry,self.device)
        return geometry

    def _source(self,audit,plan,atom,body,protocol):
        compiled={o['id']:o for o in plan['source']['operations']};seen=set()
        for dag in plan['physical_dags']:
            graph=inspect_graph(audit,dag['nodes'],dag['edges'],external_results=dag['external_reads'])
            if graph is None:continue
            for op in dag['nodes']:
                expected={**op,'after':sorted(set(op['after'])|graph.predecessors[op['id']])};actual=deepcopy(compiled.get(op['id'],{}));actual['after']=sorted(actual.get('after',[]))
                if actual!=expected or op['id'] in seen:audit.fail('STREAM_PHYSICAL_SOURCE_CHANGED','Window projection omitted, changed or duplicated a physical operation',source_id=op['id'])
                seen.add(op['id'])
            if dag['operation']=='FACTORY_STAGE':
                from .stream_factory import inspect_factory_window
                inspect_factory_window(self,audit,dag,plan,atom,body,protocol)
            else:
                nid=dag['logical_binding']['logical_node_id'];node=self.graph.nodes[nid];inspect_instance_source(audit,dag,self.bundle,node)
                if self.index.node(nid) is not None:audit.fail('STREAM_LOGICAL_REPLAY','A logical node was physically executed twice',node_id=nid)
                ids={a for op in dag['nodes'] for a in atom['source_map'][op['id']]};own=[a for a in atom['actions'] if a['id'] in ids]
                end=max([a['t_end_us'] for a in own]+[r['ready_us'] for r in body['results'].values() if r['action_id'] in ids]);begin=min(a['t_start_us'] for a in own)
                self.index.put_node(nid,{'status':'completed','start_us':begin,'end_us':end,'action_ids_sha256':_hash(sorted(ids)),'action_count':len(ids),'chunk':self.sequence,'operation':node['operation']})
                if node['operation'] in ('S','SDG'):
                    from .stream_factory import inspect_phase_cleanup
                    inspect_phase_cleanup(self,audit,dag,atom,body,nid)
        if seen!=set(compiled):audit.fail('STREAM_SOURCE_COVERAGE','Physical source set differs from the complete window DAGs')
        check_strategy_source(audit,{'qubits':[{'id':a['qubit_id']} for a in self.world['atoms']]},atom,plan['source']['operations'])
        groups=[g for d in plan['physical_dags'] for g in d['groups']]
        if groups:
            physical={'qubits':[q for d in plan['physical_dags'] for q in d['qubits']],'strategy_contract':{'operation':{'name':'stream_window'},'groups':groups}}
            check_group_source(audit,physical,plan['source']['operations']);group_metrics(audit,atom,physical,{'results':body['results']})

    def finish(self,trace,logical_schedule,*,decision_root=None,factory_ledgers=(),scope='streamed_session_component'):
        from .stream_finish import finish_stream
        return finish_stream(self,trace,logical_schedule,decision_root=decision_root,factory_ledgers=factory_ledgers,scope=scope)
