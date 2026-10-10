"""R2 LogicalDAG/0.1.0 source-preservation adapter; no R2 verdict calls."""
from collections import Counter
from .checker import _hash
from .dag_core import DAGAudit,inspect_graph
from .dag_source import inspect_source_projection


ARITIES={**{op:('block',) for op in ('SE','H','X','Z','S','SDG','T','TDG','MEASURE','RESET')},'CX':('control','target'),'CZ':('left','right'),'CLASSICAL_POSTPROCESS':()}


def inspect_logical(audit,dag):
    if dag['schema_version']!='LogicalDAG/0.1.0': raise ValueError('Unsupported LogicalDAG schema')
    if dag['entry_mode']!='preinitialized' or dag['entry']['startup_transport_required'] or dag['entry']['initialization_zone'] is not None:
        audit.fail('LOGICAL_ENTRY_MODE','Logical graph retained old startup preparation/transport')
    graph=inspect_graph(audit,dag['nodes'],dag['edges'])
    if graph is None: return
    patches={p['patch_id']:p for p in dag['patches']}
    requests=set()
    for n in dag['nodes']:
        op=n['operation']; operands=n['patch_operands']; nid=n['id']
        if op not in ARITIES or set(operands)!=set(ARITIES.get(op,())) or len(set(operands.values()))!=len(operands) or not set(operands.values())<=set(patches):
            audit.fail('LOGICAL_OPERATION_SIGNATURE','Unknown operation or incorrect operand roles/direction',node_id=nid); continue
        if not n['source_ids'] or n['semantic_version']!='1.0.0': audit.fail('LOGICAL_SOURCE_DECLARATION','Semantic version and source IDs are required',node_id=nid)
        if op=='SE':
            if len(n['writes'])!=8 or n.get('data_effect')!='preserve_live_data_no_data_reset': audit.fail('SE_RESULT_OR_DATA_EFFECT','SE must preserve live data and expose eight independent results',node_id=nid)
        if op in ('T','TDG'):
            own=n['resource_requests']
            if len(own)!=1: audit.fail('MAGIC_REQUEST_MISSING','Each T-like node needs one resource request',node_id=nid); continue
            request=own[0]
            if request['request_id'] in requests or request['kind']!='accepted_encoded_A' or request['quantity']!=1 or request['target_patch_id']!=operands['block'] or request['requested_logical_gate']!=op or request['initial_inventory_allowed'] is not False or request['condition']!=n['condition']:
                audit.fail('MAGIC_REQUEST_BINDING','Magic request is aliased, free, wrong-target or detached from the conditional T operation',node_id=nid)
            requests.add(request['request_id'])
    policy=dag['resource_policy']
    if policy['magic_initial_ready_inventory']!=0 or policy['magic_factory_count']!=1 or policy['max_ready_magic_outputs']!=1:
        audit.fail('INITIAL_MAGIC_POLICY','Preinitialized entry cannot grant extra accepted magic inventory')
    for pid,p in patches.items():
        state=p['initial_state']
        if state['encoding_status']!='assumed_encoded_surface17' or state['logical_basis']!='Z' or state['logical_value']!=0 or state['ancilla_basis']!='Z' or state['ancilla_value']!=0:
            audit.fail('LOGICAL_ENTRY_ENCODING','Declared Shor input is not the explicit encoded logical-zero boundary',patch_id=pid)
    source=dag.get('source_program')
    if source is not None:
        from na_pipeline.frontend import iter_logical_ops
        # Public enumeration is data access. The acceptance decisions below
        # do not call producer validation, scheduling or dependency builders.
        ops=list(iter_logical_ops(source))
        if dag['source_program_ref']['canonical_sha256']!=_hash(source): audit.fail('LOGICAL_SOURCE_HASH','Logical source reference differs from the full original program')
        projection={n['source_operation']['id']:{'node_id':n['id'],'source_operation':n['source_operation']} for n in dag['nodes'] if 'source_operation' in n}
        entry=[r['source_operation'] for r in dag['entry']['source_preconditions']]
        annotations=source.get('dependency_annotations',{})
        protocol_edges=[(dep,target) for target,entries in annotations.items() for dep,record in entries.items() if record.get('kind')=='protocol']
        inspect_source_projection(audit,graph,ops,projection,entry,protocol_edges=protocol_edges)
        dispositions={(r['source_operation_id'],r['target_operation_id']):r for r in dag['source_dependency_audit']}
        expected_edges={(dep,o['id']) for o in ops for dep in o['after']}
        if set(dispositions)!=expected_edges or len(dispositions)!=len(dag['source_dependency_audit']): audit.fail('DAG_SOURCE_EDGE_LEDGER','Every old after edge needs exactly one auditable disposition')
        original={o['id']:o for o in ops}; migrated={o['id'] for o in entry}
        for (a,b),record in dispositions.items():
            before,after=original[a],original[b]; shared=set(before['qubits'])&set(after['qubits'])
            classical=(set(before['writes'])&set(after['reads']))|(set(before['reads'])&set(after['writes']))|(set(before['writes'])&set(after['writes']))
            expected='preserved_explicit_protocol' if (a,b) in protocol_edges else 'covered_by_preinitialized_entry' if a in migrated or b in migrated else 'covered_by_patch_order' if shared else 'preserved_classical_causality' if classical else 'relaxed_generated_serialization'
            if record['disposition']!=expected: audit.fail('DAG_SOURCE_EDGE_DISPOSITION','Source edge was classified without its actual semantic justification',source_id=b,predecessor=a,expected=expected)
        expected_coverage={s:{'kind':'node','node_id':row['node_id']} for s,row in projection.items()}
        expected_coverage.update({r['source_operation']['id']:{'kind':'entry_precondition','patch_id':r['patch_id']} for r in dag['entry']['source_preconditions']})
        if dag['source_coverage']!=expected_coverage: audit.fail('LOGICAL_COVERAGE_LEDGER','Source coverage ledger differs from actual source/entry bindings')
        for n in dag['nodes']:
            if 'source_operation' not in n: continue
            original=n['source_operation']; op=original['params']['name'] if original['kind']=='gate' else original['kind'].upper()
            expected_qubits=[n['patch_operands'].get(role) for role in ARITIES.get(op,())]
            if n['operation']!=op or expected_qubits!=original['qubits'] or n['reads']!=original['reads'] or n['writes']!=original['writes'] or n['condition']!=original['condition'] or n['source_parameters']!=original['params']:
                audit.fail('LOGICAL_NODE_SOURCE_SEMANTICS','Logical operation no longer implements its own immutable source',node_id=n['id'])
        expected_phases=[{'first_node_id':projection[o['id']]['node_id'],'source_operation_id':o['synthesis_instance_id'],'condition':o['condition'],'global_phase_pi':o['branch_global_phase_pi'],'scope':'classical_branch_global_not_quantum_control'} for o in ops if 'branch_global_phase_pi' in o]
        if dag['branch_global_phases']!=expected_phases: audit.fail('LOGICAL_BRANCH_PHASES','Synthesis branch phase ledger changed')
        if dag['synthesis']!=source['synthesis'] or dag['rounds']!=source['rounds'] or dag['phase_bit_order']!=source['bit_order']: audit.fail('LOGICAL_ALGORITHM_METADATA','Full synthesis/round/bit-order contract was changed')
        # D01: derive only mandatory same-qubit and producer edges. Any old
        # explicitly-added last/previous edge outside that order is a known
        # serialization gap, not a proof of semantic necessity.
        minimal=[]; last={}; writers={}; runtime=[o for o in ops if o['id'] in projection]
        for o in runtime:
            for q in o['qubits']:
                if q in last: minimal.append({'source':last[q],'target':o['id'],'kind':'quantum','qubit_id':q})
                last[q]=o['id']
            for rid in o['reads']:
                if rid in writers: minimal.append({'source':writers[rid],'target':o['id'],'kind':'classical','result_id':rid})
            for rid in o['writes']: writers[rid]=o['id']
        scratch=DAGAudit('source_partial_order',{},fixture=audit.fixture); causal=inspect_graph(scratch,runtime,minimal)
        reverse={v['node_id']:s for s,v in projection.items()}; unnecessary=[]
        for edge in dag['edges']:
            a,b=reverse.get(edge['source']),reverse.get(edge['target'])
            if edge.get('reason')=='explicit_algorithm_after' and a and b and causal and not causal.precedes(a,b): unnecessary.append([a,b])
        if unnecessary: audit.need('ARTIFICIAL_SOURCE_SERIALIZATION','Old last/previous ordering still serializes independent source operations',count=len(unnecessary),examples=unnecessary[:8])
        audit.metrics['artificial_source_serial_edges']=len(unnecessary)
        audit.metrics['source_schema']=source['schema_version']
    audit.metrics.update(operation_counts=dict(Counter(n['operation'] for n in dag['nodes'])),magic_requests=len(requests),patch_count=len(patches))
    return graph


def validate_logical_dag_source(dag):
    audit=DAGAudit('logical_dag_source',{'logical_dag':dag},fixture=dag.get('provenance',{}).get('fixture',False))
    audit.interfaces={'R2-LOGICAL-DAG-001':'0.1.1-draft'}
    audit.check('logical_graph_source_and_entry',lambda:inspect_logical(audit,dag))
    return audit.report()
