"""Lightweight action/interface check. Never claims continuous path qualification."""
from copy import deepcopy
from math import dist
from na_pipeline.validation.checker import Audit, _contract, _timing, _resources
from na_pipeline.validation.dag_core import DAGAudit, inspect_graph
from na_pipeline.validation.dag_physical import validate_physical_dag_source
from na_pipeline.validation.strategy_source import check_strategy_source
from na_pipeline.validation.trace import check_trace


def validate_demo_actions(plan, device, trace=None):
    atom=plan['atom_program']
    audit=DAGAudit('demo_source_timing_resources_and_AB_events',{'atom_program':atom,'trace':trace},fixture=False)
    basic=Audit()
    basic.guard('contract',_contract,atom,device,trace,None)
    basic.guard('timing',_timing,atom,device)
    basic.guard('resources',_resources,atom)
    audit.failures.extend(basic.failures)
    audit.unverified.extend(basic.unverified)
    projected={n['id']:n for n in plan['source']['operations']}
    source={}
    for dag in plan['physical_dags']:
        graph=inspect_graph(audit,dag['nodes'],dag['edges'],external_results=dag['external_reads'])
        for n in dag['nodes']:
            want=deepcopy(n);want['after']=sorted(set(n['after'])|graph.predecessors[n['id']])
            got=deepcopy(projected.get(n['id'],{}));got['after']=sorted(got.get('after',[]))
            if got!=want:audit.fail('DEMO_SOURCE_CHANGED','Compiled source differs from complete requested DAG',source_id=n['id'])
            if n['id'] in source:audit.fail('DEMO_SOURCE_ALIAS','Source identity reused')
            source[n['id']]=n
        if dag.get('logical_source'):
            # The algebra checker consumes formal operand names. Bind those
            # names from the requested operand order, not from gate contents.
            roles=('control','target') if dag['operation']=='CX' else ('left','right') if dag['operation']=='CZ' else ('block',)
            mapping=dict(zip(dag['logical_source']['patches'],roles,strict=True))
            for q in dag['qubits']:
                patch,local=q['id'].rsplit('/',1)
                mapping[q['id']]=mapping[patch]+'/'+local
            def formalize(value):
                if isinstance(value,str):return mapping.get(value,value)
                if isinstance(value,list):return [formalize(v) for v in value]
                if isinstance(value,dict):return {k:formalize(v) for k,v in value.items()}
                return value
            check=validate_physical_dag_source(formalize(dag))
            audit.failures.extend(check['failures']);audit.unverified.extend(check['unverified'])
    if source.keys()!=projected.keys():audit.fail('DEMO_SOURCE_COVERAGE','Compiled source coverage differs')
    physical={'qubits':[{'id':q} for q in {q['id'] for d in plan['physical_dags'] for q in d['qubits']}]}
    check_strategy_source(audit,physical,atom,list(projected.values()))
    if trace is not None:
        trace_audit=Audit()
        context=atom.get('session_binding',{}).get('execution_context',{})
        check_trace(trace_audit,atom,device,trace,None,
                    external_results=context.get('published_results',{}),boundary_time_us=trace['stats']['t_end_us'])
        audit.failures.extend(trace_audit.failures)
        audit.unverified.extend(v for v in trace_audit.unverified if v['code']!='GEOMETRY_UNAVAILABLE')
        events={e['action_id']:e for e in trace['events']}
        if len(events)!=len(trace['events']) or set(events)!={a['id'] for a in atom['actions']}:
            audit.fail('DEMO_EVENT_COVERAGE','Actual events must cover every compiled action exactly once')
        for a in atom['actions']:
            e=events.get(a['id'],{})
            for key in ('kind','atoms','resources','payload','depends_on','source_ids','condition','t_start_us','t_end_us'):
                if e.get(key)!=a.get(key):audit.fail('DEMO_EVENT_CHANGED','Actual event differs from compiled action',action_id=a['id'],field=key)
            if e.get('status') not in ('completed','skipped'):audit.fail('DEMO_EVENT_NOT_TERMINAL','Incomplete action')
            if e.get('status')=='completed' and a['kind']=='move':
                for tr in a['payload']['trajectories']:
                    if dist(e['state_before'][tr['atom_id']]['position_um'],tr['from_um'])>1e-8 or dist(e['state_after'][tr['atom_id']]['position_um'],tr['to_um'])>1e-8:
                        audit.fail('DEMO_AB_ENDPOINT','Recorded move endpoints differ from compiled A/B',action_id=a['id'])
    audit.metrics.update(action_count=len(atom['actions']),source_count=len(source))
    result=audit.report()
    result.update(qualification_scope='action source, timing, declared resources, event identity and A/B endpoints',
                  continuous_geometry_rechecked=False, hardware_executed=False,
                  factory_protocol_acceptance='checked separately from complete same-run ledger')
    return result
