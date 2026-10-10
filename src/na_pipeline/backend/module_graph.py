"""Deterministic physical module dependencies, before any placement search."""
from copy import deepcopy
from .enola_kernel import StrategyError, digest
from .se_frontier import select_se_frontier, defer_readout_basis, se_direction_rank


def module_graph(dags, *, select_couplings=None, consume_module=None):
    dags = dags if isinstance(dags, list) else [dags]
    from na_pipeline.qec import validate_physical_dag
    used=set()
    for dag in dags:
        validate_physical_dag(dag)
        operands={q for o in dag['nodes'] for q in o['qubits']}
        if used & operands:
            raise StrategyError('JOINT_DAG_QUBIT_CONFLICT', 'A ready batch cannot alias quantum operands; encode order inside one DAG')
        used |= operands
    operations = [deepcopy(o) for d in dags for o in d['nodes']]
    byid = {o['id']: o for o in operations}
    if len(byid) != len(operations):
        raise StrategyError('MODULE_SOURCE_ALIAS', 'Source IDs must be unique')
    for d in dags:
        for edge in d['edges']:
            if edge['source'] not in byid[edge['target']]['after']:
                byid[edge['target']]['after'].append(edge['source'])
    groups = [deepcopy(g) for d in dags for g in d['groups']]
    cohorts={};cohort_of={}
    for op in operations:
        meta=op.get('metadata',{}).get('logical_cohort')
        if meta is None:continue
        if (not isinstance(meta,dict) or meta.get('schema_version')!='logical-coupling-cohort/0.1'
                or meta.get('size')!=9 or type(meta.get('index')) is not int or meta['index'] not in range(9)
                or not isinstance(meta.get('local_id'),str) or not meta['local_id']
                or meta.get('operation')!='CX' or op['params'].get('name')!='CX' or len(op['qubits'])!=2):
            raise StrategyError('LOGICAL_COHORT_DECLARATION','Invalid transversal coupling group')
        key=(meta['local_id'],*(q.rsplit('/',1)[0] for q in op['qubits']))
        cohorts.setdefault(key,[]).append(op);cohort_of[op['id']]=key
    for key,members in cohorts.items():
        if len(members)!=9 or {m['metadata']['logical_cohort']['index'] for m in members}!=set(range(9)):
            raise StrategyError('LOGICAL_COHORT_COVERAGE','A logical transversal must retain all nine declared pairs')
        controls={m['qubits'][0] for m in members};targets={m['qubits'][1] for m in members}
        if len(controls)!=9 or len(targets)!=9 or controls&targets:
            raise StrategyError('LOGICAL_COHORT_ALIAS','A transversal requires nine disjoint physical pairs')
    grouped_measurements = {m['measurement_op_id'] for g in groups for m in g['members']}
    declared = {q['id']: q for d in dags for q in d['qubits']}
    pending = dict(byid); done = set(); owner = {}; modules = []
    while pending:
        ready = [o for o in pending.values() if set(o['after']) <= done]
        if not ready:
            raise StrategyError('MODULE_DEPENDENCY_CYCLE', 'No source-ready module')
        rid = {o['id'] for o in ready}
        chosen_groups = []
        local = [o for o in ready if o['kind'] in ('reset', 'wait') or (o['kind'] == 'gate' and len(o['qubits']) == 1)]
        local = defer_readout_basis(local, ready, groups, done)
        group = next((g for g in groups if {m['measurement_op_id'] for m in g['members']} <= rid), None)
        if local:
            selected = local; kind = 'local_layer'
        elif group:
            chosen_groups = [g for g in groups if {m['measurement_op_id'] for m in g['members']} <= rid]
            ids = {m['measurement_op_id'] for g in chosen_groups for m in g['members']}
            ids |= {m['post_readout_reset_op_id'] for g in chosen_groups for m in g['members'] if m.get('post_readout_reset_op_id')}
            if any(set(byid[i]['after']) - done - ids for i in ids):
                raise StrategyError('MODULE_READOUT_DEPENDENCY', 'Readout service cannot cross an unresolved dependency')
            selected = [o for o in operations if o['id'] in ids]
            kind = 'readout_connector'
        else:
            first = next((o for o in ready if o['kind'] == 'measure' and o['id'] not in grouped_measurements), None)
            if first:
                ag = declared[first['qubits'][0]]['aod_group']
                selected = [o for o in ready if o['kind'] == 'measure' and o['id'] not in grouped_measurements and declared[o['qubits'][0]]['aod_group'] == ag]
                kind = 'readout_connector'
            else:
                first = next((o for o in ready if o['kind'] in ('classical', 'permute')), None)
                if first:
                    selected = [first]; kind = first['kind']
                else:
                    couplings=[o for o in ready if o['kind']=='gate' and len(o['qubits'])==2]
                    # Do not let a maintenance stream starve ready algorithm,
                    # encoder or uncompute gates that unlock additional patches.
                    # SE direction ordering is local to the remaining SE front.
                    normal=[o for o in couplings if se_direction_rank(o) is None]
                    complete=[o for o in normal if o['id'] in cohort_of and
                              {m['id'] for m in cohorts[cohort_of[o['id']]]} <= done|rid]
                    plain=[o for o in normal if o['id'] not in cohort_of]
                    se=[o for o in couplings if se_direction_rank(o) is not None]
                    # Ready full logical CNOTs unlock patches. Partial CNOTs
                    # wait for their input SE instead of fragmenting both the
                    # transversal and its following destructive measurement.
                    # A source-ready fallback avoids introducing a cohort cycle
                    # in an unusual, otherwise legal interleaved source DAG.
                    selected=(select_couplings(couplings) if select_couplings else
                              complete or plain or select_se_frontier(se) or normal)
                    kind = 'entangling_layer'
        if not selected:
            raise StrategyError('MODULE_UNSUPPORTED_SOURCE', 'No supported ready module', source_ids=sorted(rid))
        ids = {o['id'] for o in selected}; mid = f'module:{len(modules)}'
        dependencies = sorted({owner[p] for o in selected for p in o['after'] if p not in ids})
        qs = list(dict.fromkeys(q for o in selected for q in o['qubits']))
        local_ops = deepcopy(selected)
        for o in local_ops:
            o['after'] = [p for p in o['after'] if p in ids]
        writers = {r: o['id'] for o in local_ops for r in o['writes']}
        external = list(dict.fromkeys(r for o in local_ops for r in o['reads'] if r not in writers))
        edges = [{'source': p, 'target': o['id'], 'kind': 'protocol'} for o in local_ops for p in o['after']]
        targets = {e['target'] for e in edges}; sources = {e['source'] for e in edges}
        for g in chosen_groups:
            for m in g['members']:
                m['transport_after_op_ids'] = [i for i in m['transport_after_op_ids'] if i in ids]
                m['prepare_op_ids'] = [i for i in m['prepare_op_ids'] if i in ids]
        dag = {'schema_version': 'PhysicalDAG/0.1.0', 'artifact_id': mid, 'entry_mode': 'preinitialized',
               'operation': 'MODULE_FRAGMENT', 'qubits': [deepcopy(declared[q]) for q in qs], 'nodes': local_ops,
               'edges': edges, 'roots': [o['id'] for o in local_ops if o['id'] not in targets],
               'terminals': [o['id'] for o in local_ops if o['id'] not in sources], 'groups': chosen_groups,
               'external_reads': external, 'execution_guard': None, 'result_producers': writers,
               'result_types': {r: 'bit' for r in writers}, 'source_map': {o['id']: {'physical_source_op_id': o['id'], 'source_ids': o['source_ids']} for o in local_ops},
               'provenance': {'owner': 'R0', 'fixture': any(d.get('provenance', {}).get('fixture') for d in dags)},
               'execution_kind': 'compile_plan', 'quantum_state_simulated': False, 'hardware_executed': False, 'loss_enabled': False}
        modules.append({'id': mid, 'kind': kind, 'dependencies': dependencies, 'dag': dag, 'source_ids': [o['id'] for o in selected]})
        if consume_module:
            consume_module(modules[-1])
        for o in selected:
            done.add(o['id']); pending.pop(o['id']); owner[o['id']] = mid
    return {'schema_version': 'CompilationDependencyDAG/0.1', 'modules': modules,
            'source_hashes': [digest(d) for d in dags], 'source_owner': owner}
