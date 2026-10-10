"""Independent source projection and removal of artificial serial edges.

For the R2 gate/measure/reset source subset, maintaining each qubit's complete
order and classical producer order is sufficient when reordering disjoint ops.
Explicit protocol edges are retained separately, never guessed from list order.
"""


def inspect_source_projection(audit,graph,source_ops,projection,entry_ops,*,protocol_edges=()):
    """projection maps source ID to {node_id, source_operation, ...}."""
    original={o['id']:o for o in source_ops}; migrated={o['id']:o for o in entry_ops}
    if len(original)!=len(source_ops) or len(migrated)!=len(entry_ops):
        audit.fail('DAG_SOURCE_ID_DUPLICATE','Source/migrated entry IDs repeat')
    if set(projection)&set(migrated) or set(projection)|set(migrated)!=set(original):
        audit.fail('DAG_SOURCE_COVERAGE','Every source operation must be represented once by a real node or justified entry condition')
    first={}; last={}; writers={}; removed_serial=0; required_quantum=0
    for source in source_ops:
        sid=source['id']; qubits=source['qubits']
        for q in qubits: first.setdefault(q,sid)
        if sid in migrated:
            if migrated[sid]!=source or source['kind']!='reset' or source.get('condition') is not None or source['params'].get('basis')!='Z' or source['params'].get('value',0)!=0 or len(qubits)!=1 or first[qubits[0]]!=sid:
                audit.fail('DAG_INVALID_ENTRY_MIGRATION','Only the first unconditioned logical zero preparation may move to the encoded entry assumption',source_id=sid)
            if source['reads'] or source['writes']: audit.fail('DAG_ENTRY_RESULT_CREATION','Entry cannot contain runtime result dependencies',source_id=sid)
            continue
        if sid not in projection: continue
        projected=projection[sid]; nid=projected['node_id']
        if nid not in graph.nodes:
            audit.fail('DAG_SOURCE_NODE_MISSING','Source is mapped to an absent DAG node',source_id=sid); continue
        stored=projected['source_operation']
        for field in ('id','kind','qubits','params','reads','writes','condition','source_ids'):
            if stored.get(field)!=source.get(field):
                audit.fail('DAG_SOURCE_SEMANTICS','Projected source changed identity, parameters, operands, classical control or provenance',source_id=sid,field=field)
        for q in qubits:
            if q in last and not graph.precedes(last[q],nid):
                audit.fail('DAG_QUANTUM_ORDER','Removing serial edges reordered operations on the same qubit',source_id=sid,qubit_id=q,predecessor=last[q])
            if q in last: required_quantum+=1
            last[q]=nid
        reads=set(source['reads'])
        if source.get('condition'): reads.add(source['condition']['bit'])
        for rid in reads:
            if rid not in writers or not graph.precedes(writers[rid],nid):
                audit.fail('DAG_SOURCE_CLASSICAL_ORDER','Source measurement/control causality was lost during DAG conversion',source_id=sid,result_id=rid)
        for rid in source['writes']:
            if rid in writers: audit.fail('DAG_SOURCE_RESULT_WRITER','Source result is produced twice',result_id=rid)
            writers[rid]=nid
        for dep in source.get('after',[]):
            if dep in projection and not graph.precedes(projection[dep]['node_id'],nid):
                previous=original[dep]
                if set(previous['qubits'])&set(qubits) or set(previous['writes'])&reads:
                    audit.fail('DAG_DEPENDENCY_DELETION','Removed source dependency is not a disjoint-operation ordering edge',source_id=sid,predecessor=dep)
                else: removed_serial+=1
    for earlier,later in protocol_edges:
        if earlier not in projection or later not in projection or not graph.precedes(projection[earlier]['node_id'],projection[later]['node_id']):
            audit.fail('DAG_PROTOCOL_EDGE_REMOVED','Explicit protocol/lifecycle precedence was removed',source_id=later,predecessor=earlier)
    audit.metrics.update(source_operation_count=len(source_ops),runtime_source_operations=len(projection),entry_source_operations=len(migrated),required_qubit_orders_checked=required_quantum,disjoint_source_serial_edges_removed=removed_serial)
