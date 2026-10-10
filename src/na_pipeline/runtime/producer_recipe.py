"""Derive an independent producer recipe without selecting new internal batches.

This is source/partition reuse, not inherited geometric qualification. Every
resulting instance must still bind its leaves and validate its complete world.
No runtime state, token, result or acceptance is created here.
"""
from copy import deepcopy

from na_pipeline.backend.enola_kernel import StrategyError, digest
from na_pipeline.qec import build_factory_physical_dag, validate_physical_dag
from na_pipeline.qec.factory import build_factory_producer
from na_pipeline.qec.geometry_variants import resolve_geometry_variants
from .parametric_component import CompiledComponentTemplate


def derive_producer_recipe(plan, validation, device):
    def reject(code, message):
        raise StrategyError(code, message)

    if (not validation.get('passed') or
            validation.get('input_sha256', {}).get('physical_plan') != digest(plan) or
            validation.get('input_sha256', {}).get('device') != digest(device)):
        reject('PRODUCER_PARENT_QUALIFICATION', 'Require the exact qualified parent plan and device')
    if len(plan['physical_dags']) != 1:
        reject('PRODUCER_PARENT_ARITY', 'One factory stage is required')
    original = plan['physical_dags'][0]
    binding = original.get('protocol_binding', {})
    stage = binding.get('stage_id')
    if not stage or stage.startswith('consume'):
        reject('PRODUCER_STAGE', 'Only production stages can drop independent data maintenance')
    # Derive the existing catalog namespace, then require an exact ID match.
    protocol = build_factory_producer(factory_id='factory0', epoch=0, batch_id='T_request_0')
    source = resolve_geometry_variants(build_factory_physical_dag(protocol, stage),
                                      plan['atom_program']['initial_state'])
    old = {n['id']: n for n in original['nodes']}
    new = {n['id']: n for n in source['nodes']}
    if not new.keys() <= old.keys():
        reject('PRODUCER_SOURCE_ADDITION', 'Independent producer contains new or renamed source operations')
    removed = set(old) - set(new)
    removed_results = {r for s in removed for r in old[s]['writes']}
    for s in removed:
        n = old[s]
        if n['qubits']:
            if not all(q.startswith('live_data/') for q in n['qubits']):
                reject('PRODUCER_DROPPED_FACTORY_OPERATION', 'Only the old independent data SE may be removed')
        elif not n['reads'] or not set(n['reads']) <= removed_results:
            reject('PRODUCER_DROPPED_NONDATA_CLASSICAL', 'Removed classical work must belong entirely to data SE')
    fields = ('id', 'kind', 'qubits', 'params', 'after', 'reads', 'writes', 'condition', 'metadata')
    for s, n in new.items():
        if any(n.get(k) != old[s].get(k) for k in fields):
            reject('PRODUCER_SOURCE_CHANGED', 'Retained production operations and dependencies must be byte-equivalent')
        if set(n['after']) & removed or set(n['reads']) & removed_results:
            reject('PRODUCER_REMOVED_DEPENDENCY', 'Data work cannot be removed across a production dependency')
    old_groups = {g['group_id']: g for g in original['groups']}
    if any(g != old_groups.get(g['group_id']) for g in source['groups']):
        reject('PRODUCER_GROUP_CHANGED', 'Retained readout grouping must be unchanged')
    graph = deepcopy(plan['module_composition']['dependency_graph'])
    modules, owner = [], {}
    declarations = {q['id']: q for q in source['qubits']}
    parent_partitions = []
    for previous in graph['modules']:
        ids = [s for s in previous['source_ids'] if s in new]
        if not ids:
            continue
        members = set(ids)
        if any(s in owner for s in ids):
            reject('PRODUCER_SOURCE_DUPLICATE', 'One retained source must belong to exactly one module')
        fragment = deepcopy(previous['dag'])
        fragment['nodes'] = [deepcopy(new[s]) for s in ids]
        for n in fragment['nodes']:
            n['after'] = [s for s in n['after'] if s in members]
        used = {q for n in fragment['nodes'] for q in n['qubits']}
        fragment['qubits'] = [deepcopy(declarations[q['id']]) for q in previous['dag']['qubits'] if q['id'] in used]
        fragment['groups'] = [deepcopy(g) for g in previous['dag']['groups']
                              if {m['measurement_op_id'] for m in g['members']} <= members]
        fragment['edges'] = [e for e in fragment['edges'] if e['source'] in members and e['target'] in members]
        targets = {e['target'] for e in fragment['edges']}
        predecessors = {e['source'] for e in fragment['edges']}
        fragment['roots'] = [s for s in ids if s not in targets]
        fragment['terminals'] = [s for s in ids if s not in predecessors]
        fragment['result_producers'] = {r: n['id'] for n in fragment['nodes'] for r in n['writes']}
        fragment['result_types'] = {r: t for r, t in fragment['result_types'].items() if r in fragment['result_producers']}
        fragment['external_reads'] = list(dict.fromkeys(r for n in fragment['nodes'] for r in n['reads']
                                                       if r not in fragment['result_producers']))
        fragment['source_map'] = {s: deepcopy(fragment['source_map'][s]) for s in ids}
        validate_physical_dag(fragment)
        dependencies = {s for i in ids for s in new[i]['after'] if s not in members}
        if not dependencies <= owner.keys():
            reject('PRODUCER_PARTITION_ORDER', 'The frozen module order must remain topological')
        modules.append({**deepcopy(previous), 'source_ids': ids, 'dag': fragment,
                        'dependencies': sorted({owner[s] for s in dependencies})})
        owner.update({s: previous['id'] for s in ids})
        parent_partitions.append({'module_id': previous['id'], 'parent_source_ids': previous['source_ids'],
                                  'retained_source_ids': ids, 'native_body_reused': False})
    if set(owner) != set(new):
        reject('PRODUCER_SOURCE_COVERAGE', 'Every original producer operation must remain in the recipe')
    graph.update(modules=modules, source_owner=owner, source_hashes=[digest(source)])
    virtual = deepcopy(plan)
    virtual['physical_dags'] = [source]
    virtual['module_composition']['dependency_graph'] = graph
    template = CompiledComponentTemplate(virtual)
    template.original_plan_hash = digest(plan)
    template.input_boundary = {'kind': 'independent_producer_projection', 'removed_data_operations': sorted(removed)}
    template.derivation = {'schema_version': 'IndependentProducerRecipe/0.1',
        'parent_plan_sha256': digest(plan), 'producer_source_sha256': digest(source),
        'producer_operation_count': len(new), 'removed_data_maintenance_count': len(removed),
        'partitions': parent_partitions, 'internal_batch_search_calls': 0,
        'geometry_qualification_inherited': False, 'runtime_state_copied': False,
        'qualification_required': 'exact leaf binding and full-world physical validation before submission'}
    return template
