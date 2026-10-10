"""Finite Shor-15 logical/factory component catalogue; physical semantics reused.

Public contracts expose DAGs, resources, results and adaptive protocol stages.
No compile result, measurement, token, state or acceptance is created here.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from functools import lru_cache
import json

from .physical_dag import build_patch_operation_spec, physical_dag_from_program, build_factory_physical_dag, validate_physical_dag, _program
from .factory_primitives import Circuit, FORMALS
from .factory import build_factory15to1_protocol

VERSION='logical-component-catalog/0.1'

def _hash(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

@lru_cache(maxsize=2)
def _factory(gate='T'):
    return build_factory15to1_protocol(gate=gate)


@lru_cache(maxsize=1)
def _catalog():
    rows=[]
    def add(id,label,category,kind='physical',**kw):rows.append({'id':id,'label':label,'category':category,'kind':kind,**kw})
    for id,label in [('SE','SE · 完整综合征提取'),('H','H · 逻辑 Hadamard'),('X','X · 逻辑 Pauli'),('Z','Z · 逻辑 Pauli'),
                     ('CX','CX · 有向逻辑 CNOT'),('CZ','CZ · 逻辑受控 Z'),('S','S · 逻辑相位'),('SDG','S† · 逆逻辑相位'),
                     ('RESET_Z','逻辑复位 |0〉'),('MEASURE_Z','逻辑 Z 测量'),('MEASURE_X','逻辑 X 测量')]:
        add(id,label,'逻辑原语')
    for id,label,state in [('PREPARE_ZERO','编码零态制备','zero'),('PREPARE_PLUS','编码加态制备','plus'),
                           ('PREPARE_A','原始 A 态制备与编码','A'),('PREPARE_Y_PLUS','Y+ 辅助制备','Y+'),('PREPARE_Y_MINUS','Y− 辅助制备','Y-')]:
        add(id,label,'蒸馏基础',state=state)
    add('JOINT_ZZ','联合逻辑 ZZ 测量','蒸馏基础')
    add('READ_X_CLEANUP','逻辑 X 读出及辅助清理','蒸馏基础')
    add('READ_Z_CLEANUP','逻辑 Z 读出及辅助清理','蒸馏基础')
    for op in ('X','Z'):add('FEEDBACK_'+op,'条件逻辑 '+op+' 修正','反馈与经典')
    add('PARITY','测量结果奇偶 XOR','反馈与经典')
    add('ACCEPT','蒸馏接受判定 all_zero','反馈与经典')
    add('CLASSICAL_POSTPROCESS','Shor 经典后处理','反馈与经典')
    protocol=_factory()
    for stage,record in protocol['stages'].items():
        if record['kind']=='physical':add('factory.'+stage,'15→1 · '+stage,'蒸馏阶段',stage_id=stage,gate='T',purpose=record['purpose'])
    add('factory.consume_correction_tdg','15→1 · T† 条件 S† 修正','蒸馏阶段',stage_id='consume_correction',gate='TDG')
    for op in ('T','TDG'):
        add(op,op.replace('DG','†')+' · 完整自适应协议','非 Clifford 协议','adaptive',
            physical_stage_ids=['factory.consume_correction_tdg' if op=='TDG' and s=='consume_correction' else 'factory.'+s for s,r in protocol['stages'].items() if r['kind']=='physical'])
    for id,label in [('FACTORY_READY','候选接受与 READY 发布'),('RESERVE_DELIVERY','魔态预约与同载体交接'),
                     ('REJECT_RETRY','拒收、清理与新 epoch 重试')]:
        add(id,label,'非 Clifford 协议','lifecycle')
    return {'schema_version':VERSION,'components':rows,'code_profile':'Surface-17 d=3',
            'execution_kind':'compile_plan','quantum_state_simulated':False,'hardware_executed':False}


def component_catalog():
    return deepcopy(_catalog())


def _extra_dag(id, *, with_ports=False):
    c=Circuit();roles={'D':'block'};ports={}
    states={'PREPARE_ZERO':'zero','PREPARE_PLUS':'plus','PREPARE_A':'A','PREPARE_Y_PLUS':'Y+','PREPARE_Y_MINUS':'Y-'}
    if id in states:c.prepare('D',states[id],'prepare')
    elif id=='JOINT_ZZ':
        ports['value']=c.joint_zz('D','W4','joint');roles={'D':'left','W4':'right','join_probe':'bridge'}
    elif id.startswith('READ_'):ports['value']=c.read_logical('D',id.split('_')[1],'read')
    else:raise KeyError(id)
    dag=physical_dag_from_program(_program(c,roles,id),operation=id)
    ports={k:'physical/r0/'+v for k,v in ports.items()}
    if any(v not in dag['result_producers'] for v in ports.values()):raise ValueError('COMPONENT_PUBLIC_RESULT_MISSING')
    return (dag,ports) if with_ports else dag


def _result_ports(spec):
    id=spec['id']
    if id in ('JOINT_ZZ','READ_X_CLEANUP','READ_Z_CLEANUP'):return _extra_dag(id,with_ports=True)[1]
    if id=='PARITY':return {'value':'report'}
    if id=='ACCEPT':return {'accepted':'report'}
    if spec['patch_spec']:return deepcopy(spec['patch_spec']['public_results'])
    if id.startswith('factory.'):
        branch=spec['protocol']['stages'][spec['stage_id']].get('branch')
        return {'branch':branch['result_id']} if branch else {}
    return {}


def get_component_result_ports(component_id):
    """Logical result slots to formal IDs, without exposing mutable runtime values."""
    return _result_ports(get_component_spec(component_id))


def get_component_spec(component_id):
    row=next((r for r in component_catalog()['components'] if r['id']==component_id),None)
    if row is None:raise ValueError('UNKNOWN_LOGICAL_COMPONENT: '+component_id)
    dag=None;protocol=None;patch=None
    if row['kind'] in ('adaptive','lifecycle'):
        protocol=_factory(component_id if component_id in ('T','TDG') else 'T')
        if row['kind']=='adaptive':patch=build_patch_operation_spec(component_id)
    elif component_id.startswith('factory.'):
        protocol=_factory(row['gate'])
        dag=build_factory_physical_dag(protocol,row['stage_id'])
    elif component_id in ('PREPARE_ZERO','PREPARE_PLUS','PREPARE_A','PREPARE_Y_PLUS','PREPARE_Y_MINUS','JOINT_ZZ','READ_X_CLEANUP','READ_Z_CLEANUP'):
        dag=_extra_dag(component_id)
    elif component_id.startswith('FEEDBACK_'):
        patch=build_patch_operation_spec(component_id[-1]);dag=deepcopy(patch['physical_dag'])
        dag['external_reads']=['feedback_bit']
        for n in dag['nodes']:n['condition']={'bit':'feedback_bit','equals':1};n['reads']=['feedback_bit']
    elif component_id in ('PARITY','ACCEPT'):
        patch=build_patch_operation_spec('CLASSICAL_POSTPROCESS');dag=deepcopy(patch['physical_dag'])
        reads=['input[0]','input[1]','input[2]','input[3]'];op=dag['nodes'][0]
        op.update(params={'operation':'xor' if component_id=='PARITY' else 'all_zero'},reads=reads)
        dag['external_reads']=reads;dag['result_types']={'report':'bit'}
    else:
        op={'RESET_Z':'RESET','MEASURE_Z':'MEASURE','MEASURE_X':'MEASURE'}.get(component_id,component_id)
        params={'basis':'X' if component_id=='MEASURE_X' else 'Z'} if op=='MEASURE' else None
        patch=build_patch_operation_spec(op,params=params);dag=deepcopy(patch['physical_dag'])
    if dag is not None:validate_physical_dag(dag)
    qubits=protocol['qubits'] if row['kind']=='adaptive' else [] if dag is None else dag['qubits']
    result={**deepcopy(row),'schema_version':'LogicalComponentSpec/0.1','catalog_version':VERSION,
            'physical_dag':dag,'patch_spec':patch,'protocol':deepcopy(protocol),
            'formal_qubits':deepcopy(qubits),'external_results':[] if dag is None else list(dag['external_reads']),
            'public_results':{} if dag is None else deepcopy(dag['result_producers']),
            'preconditions':{'geometry':'actual caller world','encoded_inputs':'as declared by source protocol',
                             'runtime_results_and_tokens':'must come from live session; never cached'},
            'implementation':'existing_R3_full_physical_source_or_adaptive_factory_protocol'}
    result['spec_hash']=_hash(result)
    return result


def instantiate_component(component_id, *, qubit_bindings=None, namespace='component', result_bindings=None, protocol_binding=None):
    """Stable scheduler boundary: fresh identities, original semantics and dependencies."""
    spec=get_component_spec(component_id)
    ports=_result_ports(spec)
    if spec['physical_dag'] is None:
        if qubit_bindings is not None or result_bindings is not None:
            raise ValueError('ADAPTIVE_BINDING_REQUIRES_PROTOCOL_BINDING')
        binding=deepcopy(protocol_binding or {})
        if set(binding)-{'data_block_id','request_id','factory_id','epoch'}:
            raise ValueError('UNKNOWN_PROTOCOL_BINDING_FIELD')
        if spec['kind']=='lifecycle':
            if binding:raise ValueError('LIFECYCLE_USES_EXISTING_CONTROLLER')
            return {'schema_version':'LogicalLifecycleCommand/0.1','component_id':component_id,
                    'runtime_owner':'na_pipeline.runtime.FactoryExecution','requires_live_session':True,
                    'action':{'FACTORY_READY':'advance_lifecycle:ready','RESERVE_DELIVERY':'advance_lifecycle:reserve_delivery',
                              'REJECT_RETRY':'commit_reject_cleanup_then_create_next_epoch'}[component_id],
                    'physical_motion_created':False}
        protocol=build_factory15to1_protocol(gate=component_id,**binding) if binding else spec['protocol']
        return {'schema_version':'AdaptiveLogicalComponent/0.1','component_id':component_id,
                'spec_hash':spec['spec_hash'],'protocol':protocol,
                'runtime_owner':'na_pipeline.runtime.FactoryExecution','requires_live_session':True}
    if protocol_binding is not None:raise ValueError('PHYSICAL_COMPONENT_USES_QUBIT_BINDINGS')
    if not isinstance(namespace,str) or not namespace:raise ValueError('COMPONENT_NAMESPACE_REQUIRED')
    dag=deepcopy(spec['physical_dag']);bindings=qubit_bindings if qubit_bindings is not None else {q['id']:q['id'] for q in dag['qubits']}
    if set(bindings)!={q['id'] for q in dag['qubits']} or len(set(bindings.values()))!=len(bindings):
        raise ValueError('COMPONENT_QUBIT_BINDING_MUST_BE_COMPLETE_AND_INJECTIVE')
    block_targets={}
    for q in dag['qubits']:
        target=bindings[q['id']]
        if not isinstance(target,str) or not target:raise ValueError('INVALID_COMPONENT_QUBIT_ID')
        local=q.get('local_id',q['id'].rsplit('/',1)[-1])
        if local in FORMALS:
            if '/' not in target or target.rsplit('/',1)[-1]!=local:
                raise ValueError('COMPONENT_REQUIRES_CANONICAL_LOCAL_ROLES')
            block_targets.setdefault(q['block_id'],set()).add(target.rsplit('/',1)[0])
    if any(len(v)!=1 for v in block_targets.values()):raise ValueError('COMPONENT_PATCH_BINDING_SPLIT')
    block_map={k:next(iter(v)) for k,v in block_targets.items()}
    mapping={**bindings,**{o['id']:namespace+'/'+o['id'] for o in dag['nodes']},
             **{r:namespace+'/'+r for r in dag['result_producers']},
             **{g['group_id']:namespace+'/'+g['group_id'] for g in dag['groups']}}
    if result_bindings:
        normalized={ports.get(k,k):v for k,v in result_bindings.items()}
        if len(normalized)!=len(result_bindings):raise ValueError('DUPLICATE_COMPONENT_RESULT_BINDING')
        result_bindings=normalized
        if not set(result_bindings)<=set(dag['external_reads'])|set(dag['result_producers']):raise ValueError('UNKNOWN_COMPONENT_RESULT')
        if any(not isinstance(v,str) or not v for v in result_bindings.values()):raise ValueError('INVALID_COMPONENT_RESULT_ID')
        mapping.update(result_bindings)
    def remap(v):
        if isinstance(v,str):return mapping.get(v,v)
        if isinstance(v,list):return [remap(x) for x in v]
        if isinstance(v,dict):return {mapping.get(k,k):remap(x) for k,x in v.items()}
        return v
    dag=remap(dag);dag['artifact_id']=namespace+'/'+component_id
    for q in dag['qubits']:q['block_id']=block_map.get(q['block_id'],q['block_id'])
    for g in dag['groups']:
        if 'formal_block' in g:g['formal_block']=block_map.get(g['formal_block'],g['formal_block'])
    for s in dag.get('readout_services',[]):
        if 'block_id' in s:s['block_id']=block_map.get(s['block_id'],s['block_id'])
    dag['component_binding']={'component_id':component_id,'spec_hash':spec['spec_hash'],'qubit_bindings':bindings,'namespace':namespace,
                              'logical_result_ports':{k:mapping.get(v,v) for k,v in ports.items()}}
    validate_physical_dag(dag)
    return dag


def shor_component_requirements():
    from na_pipeline.frontend.logical_dag import build_logical_dag
    dag=build_logical_dag();mapping={'MEASURE':'MEASURE_Z','RESET':'RESET_Z'}
    counts=Counter(n['operation'] for n in dag['nodes'])
    refs={n['id']:mapping.get(n['operation'],n['operation']) for n in dag['nodes']}
    catalogue={r['id'] for r in component_catalog()['components']}
    if not set(refs.values())<=catalogue:raise ValueError('SHOR_COMPONENT_COVERAGE_MISSING')
    return {'schema_version':'ShorComponentCoverage/0.1','logical_dag_hash':_hash(dag),'logical_nodes':len(dag['nodes']),
            'operation_counts':dict(counts),'logical_node_components':refs,'source_coverage_count':len(dag['source_coverage']),
            'full_shor_executed':False,'algorithm_profile':'N15 a2 / eight-round semiclassical QPE / Clifford+T synthesis'}
