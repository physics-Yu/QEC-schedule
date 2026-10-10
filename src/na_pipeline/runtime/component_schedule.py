"""Reuse the actual compiled component's batch partition, independently of IDs."""
from copy import deepcopy
from na_pipeline.backend.enola_kernel import digest
from na_pipeline.backend.strategy_template import remap


def schedule_signature(dags):
    dags=dags if isinstance(dags,list) else [dags]
    operations=[o for d in dags for o in d['nodes']]
    qubits=list(dict.fromkeys(q for o in operations for q in o['qubits']))
    mapping={q:f'q:{i}' for i,q in enumerate(qubits)}
    mapping.update({o['id']:f'op:{i}' for i,o in enumerate(operations)})
    written=list(dict.fromkeys(r for o in operations for r in o['writes']))
    external=list(dict.fromkeys(r for o in operations for r in o['reads'] if r not in written))
    mapping.update({r:f'result:{i}' for i,r in enumerate(written)})
    mapping.update({r:f'input:{i}' for i,r in enumerate(external)})
    for i,g in enumerate(g for d in dags for g in d['groups']):mapping[g['group_id']]=f'group:{i}'
    declarations={q['id']:q for d in dags for q in d['qubits']}
    core={'schema_version':'OpaqueComponentScheduleKey/0.1','operations':remap([
        {k:deepcopy(o[k]) for k in ('id','kind','qubits','params','after','reads','writes','condition')} for o in operations],mapping),
        'qubits':[{'port':mapping[q],'role':declarations[q]['role'],'aod_group':declarations[q]['aod_group']} for q in qubits],
        'edges':remap([e for d in dags for e in d['edges']],mapping)}
    return digest(core),core,operations


def extract_schedule(plan):
    key,core,operations=schedule_signature(plan['physical_dags'])
    positions={o['id']:i for i,o in enumerate(operations)}
    required={i for i,o in enumerate(operations) if o['kind']=='gate' and len(o['qubits'])==2}
    batches=[]
    for action in sorted(plan['atom_program']['actions'],key=lambda a:(a['t_start_us'],a['t_end_us'])):
        if action['kind']=='gate' and action['payload'].get('name')=='CZ':
            ids=list(dict.fromkeys(positions[p] for p in action['payload']['physical_op_ids']))
            if not set(ids)<=required:raise ValueError('SCHEDULE_SOURCE_CZ_BINDING')
            batches.append(ids)
    flattened=[i for b in batches for i in b]
    if len(flattened)!=len(required) or set(flattened)!=required:raise ValueError('SCHEDULE_COMPLETE_COUPLING_COVERAGE')
    return key,{'schema_version':'OpaqueComponentSchedule/0.1','signature':key,'source':core,
                'batches':batches,'original_plan_hash':digest(plan),'original_operations':len(operations),
                'cached_measurements_results_state':False}
