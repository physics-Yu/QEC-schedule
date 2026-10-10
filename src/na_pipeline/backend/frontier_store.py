"""Immutable geometry-bound front decisions; never execution/session state."""
from copy import deepcopy
import json
import uuid

from .enola_kernel import digest, StrategyError
from .se_frontier import se_direction_rank


def select_frontier(library, operations, world, *, build_missing):
    # Cohorts are scheduling policy only. Every ready node is recorded, even
    # when a partial transversal is deferred until its input SE is complete.
    cohorts = {}
    for op in operations:
        m = op.get('metadata', {}).get('logical_cohort')
        if m:
            key = (m['local_id'], *(q.rsplit('/', 1)[0] for q in op['qubits']))
            cohorts.setdefault(key, []).append(op['id'])
    complete = {i for ids in cohorts.values() if len(ids) == 9 for i in ids}
    partial = {i for ids in cohorts.values() if len(ids) < 9 for i in ids}
    eligible = [o for o in operations if o['id'] not in partial] or operations
    order = {o['id']: i for i, o in enumerate(operations)}
    eligible = sorted(eligible, key=lambda o: (0 if o['id'] in complete else 1,
        -1 if se_direction_rank(o) is None else se_direction_rank(o), order[o['id']]))
    atoms = sorted(world['atoms'], key=lambda a: (a['position_um'], a['aod_group']))
    sites = {a.get('site_id', a['qubit_id']): i for i, a in enumerate(atoms)}
    normalized = [{'name': o['params']['name'], 'sites': [sites[q] for q in o['qubits']],
                   'direction_rank': se_direction_rank(o), 'cohort': next((j for j, ids in enumerate(cohorts.values()) if o['id'] in ids), None)} for o in operations]
    core = {'schema_version': 'JointFrontierDecision/0.1', 'compiler_hash': library.compiler_hash,
            'device_hash': digest(library.device), 'operations': normalized,
            'eligible_indices': [order[o['id']] for o in eligible],
            'scene': [{k: a[k] for k in ('position_um', 'carrier', 'aod_group')} for a in atoms]}
    key = digest(core); path = library.directory / ('frontier-' + key + '.json') if library.directory else None
    item = library.frontiers.get(key)
    if item is None and path and path.is_file():
        item = json.loads(path.read_bytes())
    if item is None:
        if not build_missing:
            raise StrategyError('MODULE_DEPENDENCY_MISSING', 'Build the geometry-bound joint frontier decision first; no implicit search', frontier_key=key)
        from .physical_window import PhysicalWindowCompiler
        projected = deepcopy(eligible)
        for op in projected:
            op['after'] = []
        compiler = PhysicalWindowCompiler(projected, [], library.device, world,
                                          budget=library.budget, enola_root=library.enola_root)
        compiler.closed_coupling_batch = False  # choosing a frontier, not lowering a committed leaf
        # Actual scheduler receives every applicable ready pair, not a leaf
        # already stripped down to one protocol's preferred coupling subset.
        compiler.scheduler.partition(projected, set())
        chosen, receipt, _ = compiler.select_entangle(projected)
        indices = [order[c['op_id']] for c in chosen]
        body = {'identity': core, 'selected_indices': indices,
                'scheduler_receipts': compiler.scheduler.receipts,
                'kernel_receipts': compiler.kernel.receipts,
                'selected_decision_hash': receipt['decision_hash'],
                'build_source_ids': [o['id'] for o in operations],
                'search_counts': {'placement_candidates': compiler.candidate_count, 'routing_calls': compiler.route_calls},
                'cached_runtime_state': False}
        item = {'schema_version': 'JointFrontierDecision/0.1', 'hash': digest(body), 'body': body}
        library.counters['frontier_search_count'] += 1
        library.counters['placement_search_count'] += compiler.candidate_count
        library.counters['routing_search_count'] += compiler.route_calls
        if path:
            tmp = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
            tmp.write_text(json.dumps(item, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            tmp.replace(path)
    if digest(item['body']) != item['hash'] or item['body']['identity'] != core:
        raise StrategyError('FRONTIER_DECISION_HASH_MISMATCH', 'Immutable geometry-bound decision changed')
    library.frontiers[key] = item
    chosen = item['body']['selected_indices']
    if not chosen or len(set(chosen)) != len(chosen) or any(type(i) is not int or i not in range(len(operations)) for i in chosen):
        raise StrategyError('FRONTIER_DECISION_COVERAGE', 'Invalid stored source selection')
    evidence = {'decision_hash': item['hash'], 'artifact_file': path.name if path else None,
                'ready_source_ids': [o['id'] for o in operations],
                'candidate_source_ids': [o['id'] for o in eligible],
                'selected_source_ids': [operations[i]['id'] for i in chosen],
                'deferred': [{'source_id': o['id'], 'reason': 'incomplete_transversal_cohort_schedule_policy'} for o in operations if o not in eligible],
                'unselected': [{'source_id': o['id'], 'reason': 'bounded_joint_assignment_choice_not_proven_infeasible'} for o in eligible if order[o['id']] not in chosen],
                'policy_is_not_source_dependency': True, 'search_repeated_on_bind': False}
    selected_receipt = next(r for r in item['body']['kernel_receipts'] if r['decision_hash']==item['body']['selected_decision_hash'])
    source_remap = dict(zip(item['body']['build_source_ids'], [o['id'] for o in operations]))
    evidence['unselected_details'] = [{**deepcopy(v), 'source_id':source_remap[v['source_id']]}
        for v in selected_receipt['joint_search']['unselected_details']]
    return [operations[i] for i in chosen], evidence
