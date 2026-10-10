"""Independent R3 PhysicalDAG and R4 joint-window checks for T605."""
from collections import Counter
from copy import deepcopy
from .checker import _hash,EPS
from .dag_core import DAGAudit,inspect_graph
from .dag_coupling import inspect_css_coupling
from .dag_entry import inspect_mz_receiver
from .semantic_qec import REFERENCE
from .semantic_common import conjugate,multiply
from .strategy import inspect_strategy_plan
from .strategy_source import check_strategy_source


def inspect_physical_dag(audit,dag):
    if dag['schema_version']!='PhysicalDAG/0.1.0' or dag['entry_mode']!='preinitialized': raise ValueError('Unsupported PhysicalDAG entry/schema')
    graph=inspect_graph(audit,dag['nodes'],dag['edges'],external_results=dag['external_reads'])
    if graph is None: return
    if set(dag['roots'])!={n for n,p in graph.predecessors.items() if not p} or set(dag['terminals'])!={n for n,p in graph.successors.items() if not p}:
        audit.fail('PHYSICAL_DAG_FRONTIER','Declared roots/terminals differ from actual graph')
    if dag['result_producers']!=graph.writers or set(dag['source_map'])!=set(graph.nodes): audit.fail('PHYSICAL_DAG_SOURCE_COVERAGE','Physical source/result maps differ from all DAG nodes')
    qubits={q['id'] for q in dag['qubits']}; last={}
    for op in dag['nodes']:
        if not set(op['qubits'])<=qubits or len(set(op['qubits']))!=len(op['qubits']): audit.fail('PHYSICAL_DAG_QUBIT','Physical DAG contains unbound/aliased operands',source_id=op['id'])
        if not op['source_ids']: audit.fail('PHYSICAL_DAG_ORIGIN','Physical source origin is missing',source_id=op['id'])
        for dep in op['after']:
            if dep not in graph.predecessors[op['id']]: audit.fail('PHYSICAL_DAG_EDGE_OMITTED','Typed graph omits an original operation dependency',source_id=op['id'],predecessor=dep)
        for q in op['qubits']:
            if q in last and not graph.precedes(last[q],op['id']): audit.fail('PHYSICAL_DAG_QUBIT_ORDER','Source qubit order is not represented by DAG reachability',source_id=op['id'],qubit_id=q)
            last[q]=op['id']
    if dag['operation']=='SE': inspect_se(audit,dag,graph)
    elif dag['operation'] in ('S','SDG') and len(dag['qubits'])==17:
        from .neutral_clifford import inspect_s_se
        inspect_s_se(audit,dag,graph)
    elif dag['operation'] in ('CX','CZ','H','X','Z'):
        roles=('control','target') if dag['operation']=='CX' else ('left','right') if dag['operation']=='CZ' else ('block',)
        rolemap=dict(zip(roles,('control','target')))
        if all(op['kind'] in ('gate', 'permute') and not op['condition'] for op in dag['nodes']):
            gates=[{'name':op['params'].get('name', 'PERMUTE'), 'destination_indices':op['params'].get('destination_indices'), 'qubits':[rolemap[q.split('/')[0]]+'/'+q.split('/')[-1] for q in op['qubits']]} for op in dag['nodes']]
            inspect_css_coupling(audit,gates,dag['operation'])
        else: audit.need('PHYSICAL_GATE_INSTRUMENT_UNVERIFIED','This Clifford proof does not cover measurement/conditional instruments')
    elif dag['operation'] not in ('CLASSICAL_POSTPROCESS',):
        audit.need('PHYSICAL_PROTOCOL_SEMANTICS_PENDING','Instrument/factory semantics need their separate complete protocol audit',operation=dag['operation'])
    return graph


def inspect_se(audit,dag,graph):
    ops=dag['nodes']; by_id=graph.nodes; formals=[q['id'] for q in dag['qubits']]
    if len(formals)!=17: audit.fail('SE_PATCH_SIZE','One SE must bind a complete Surface-17 patch'); return
    data={q for q in formals if q.rsplit('/',1)[1].startswith('d')}; aux=set(formals)-data
    readouts=[op for op in ops if op['kind']=='measure']; resets=[op for op in ops if op['kind']=='reset']
    if any(set(op['qubits'])&data for op in readouts+resets): audit.fail('SE_LIVE_DATA_DESTROYED','SE cannot reset or measure live data')
    if len(readouts)!=8 or {o['qubits'][0] for o in readouts}!=aux: audit.fail('SE_EIGHT_RESULTS','SE must read each of the eight auxiliary atoms exactly once')
    if Counter(q for op in resets for q in op['qubits'])!=Counter({q:2 for q in aux}): audit.fail('SE_AUXILIARY_RESET','Each auxiliary needs preparation and post-readout reset')
    gates=[o for o in ops if o['kind']=='gate']
    if any(o['condition'] for o in gates): audit.need('SE_CONDITIONAL_PROTOCOL','Conditional memory SE requires a separate decoder/protocol contract')
    group=dag['groups']
    if len(group)!=1 or len(group[0]['members'])!=8: audit.fail('SE_GROUP_COVERAGE','SE must declare one complete eight-auxiliary group'); return
    for member in group[0]['members']:
        local=member['local_id']; q=member['physical_qubit_id']; measure=by_id[member['measurement_op_id']]
        axis=local[0].upper(); index=int(local[1]); reference=[r for r in REFERENCE if r[0]==axis][index]
        bit=1<<formals.index(q); pauli=(0,bit,0)
        for gate in reversed(gates):
            name=gate['params']['name']; inverse={'S':'SDG','SDG':'S'}.get(name,name)
            pauli=conjugate(pauli,inverse,[formals.index(v) for v in gate['qubits']])
        support=sum(1<<formals.index(q.rsplit('/',1)[0]+f'/d{i}') for i in reference[1])
        expected=multiply((support,0,0) if axis=='X' else (0,support,0),(0,bit,0))
        if pauli!=expected: audit.fail('SE_STABILIZER_READOUT','Measured observable differs from the independently specified code stabilizer',qubit_id=q)
        if measure['qubits']!=[q] or measure['params'].get('basis')!='Z' or measure['writes']!=[member['result_id']]: audit.fail('SE_MEMBER_RESULT','Group member has an incorrect physical readout binding',qubit_id=q)
        local_gates=[g for g in gates if q in g['qubits']]
        if any(not graph.precedes(g['id'],measure['id']) for g in local_gates): audit.fail('SE_READOUT_DEPENDENCY','Readout is not after all couplings/basis changes',qubit_id=q)
        before=[r for r in resets if r['qubits']==[q] and graph.precedes(r['id'],measure['id'])]
        after=[r for r in resets if r['qubits']==[q] and graph.precedes(measure['id'],r['id'])]
        if len(before)!=1 or len(after)!=1 or any(not graph.precedes(before[0]['id'],g['id']) for g in local_gates): audit.fail('SE_PREPARE_RESET_ORDER','Auxiliary preparation/readout/service-reset order is incomplete',qubit_id=q)
    audit.metrics['se_stabilizer_observables_checked']=8


def validate_physical_dag_source(dag):
    audit=DAGAudit('physical_dag_source',{'physical_dag':dag},fixture=dag.get('provenance',{}).get('fixture',False))
    audit.interfaces={'R3-PHYSICAL-DAG-001':'0.1.0-draft'}
    audit.check('complete_physical_dag_and_operation_semantics',lambda:inspect_physical_dag(audit,dag))
    return audit.report()


def inspect_physical_plan(audit,plan,device,trace):
    if plan['schema_version']!='physical-plan/0.1': raise ValueError('Unsupported R4 physical plan')
    dags=plan['physical_dags']; original={}; compiled={o['id']:o for o in plan['source']['operations']}
    for dag in dags:
        graph=inspect_graph(audit,dag['nodes'],dag['edges'],external_results=dag['external_reads'])
        if graph is None: continue
        for op in dag['nodes']:
            if op['id'] in original: audit.fail('PHYSICAL_BATCH_ID_COLLISION','Independent node instances reused a source ID',source_id=op['id'])
            original[op['id']]=op
            expected=deepcopy(op); expected['after']=sorted(set(op['after'])|graph.predecessors[op['id']])
            actual=deepcopy(compiled.get(op['id'],{})); actual['after']=sorted(actual.get('after',[]))
            if actual!=expected: audit.fail('PHYSICAL_BATCH_SOURCE_CHANGED','Typed DAG projection dropped or changed a physical operation',source_id=op['id'])
        if dag['execution_guard'] is not None or dag['external_reads']: audit.need('PHYSICAL_EXTERNAL_RESULT_BINDING','Guard/external result resolution receipt has not been supplied')
    if set(compiled)!=set(original): audit.fail('PHYSICAL_BATCH_SOURCE_COVERAGE','Joint plan does not cover its complete original DAG batch')
    atom=plan['atom_program']; geometry=inspect_strategy_plan(audit,atom,device,trace=trace)
    check_strategy_source(audit,{'qubits':[{'id':q} for q in {q['id'] for d in dags for q in d['qubits']}]},atom,list(compiled.values()))
    if geometry is not None:
        inspect_mz_receiver(audit,atom['actions'],geometry,device)
        if {a['atom_id'] for a in plan['exit_state']['atoms']}!={a['atom_id'] for a in atom['initial_state']['atoms']}: audit.fail('PHYSICAL_WORLD_INVENTORY_CHANGED','No-loss compile introduced or removed a carrier')
    if any(a['payload'].get('purpose')=='patch_initialization_transport' for a in atom['actions']): audit.fail('INITIALIZATION_TRANSPORT_REINTRODUCED','Physical batch reintroduced startup preparation transport')
    return geometry


def validate_physical_plan(plan,device,*,trace=None):
    audit=DAGAudit('physical_window_geometry_and_source',{'physical_plan':plan,'device':device,'trace':trace},fixture=plan.get('atom_program',{}).get('provenance',{}).get('fixture',False))
    audit.interfaces={'R3-PHYSICAL-DAG-001':'0.1.0-draft','R4-HIERARCHICAL-IF-001':'0.1.0-draft'}
    audit.check('joint_source_geometry_resources_and_trace',lambda:inspect_physical_plan(audit,plan,device,trace))
    if trace is None: audit.need('PHYSICAL_TRACE_MISSING','Actual committed fake trace is required for execution qualification')
    return audit.report()
