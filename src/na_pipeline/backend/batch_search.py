"""Bounded joint assignment search for every ready CZ/CX, not a protocol rule.

Enola supplies axis compatibility and the original full-domain greedy proposal.
Capture closure is a complete-set constraint; it is never promoted to a pairwise
hardware conflict. Search omissions are explicit, not infeasibility certificates.
"""
from collections import Counter
from itertools import product
import math

from .enola_kernel import capture_closure, digest, StrategyError
from .se_frontier import se_direction_rank
from .independent_arrays import capture_assignment,route_arrays


def select_batch(compiler, operations, candidates):
    kernel = compiler.kernel
    scene = list(compiler.atoms.values())
    tol = compiler.device['geometry']['distance_tolerance_um']
    reasons = Counter(); checked = {}; accepted = []
    byop = {o['id']: o for o in operations}
    minimum_direction = {}
    for o in operations:
        r = se_direction_rank(o)
        if r is not None:
            block = o['qubits'][0].rsplit('/', 1)[0]
            minimum_direction[block] = min(r, minimum_direction.get(block, r))
    cohorts = {}
    for o in operations:
        m = o.get('metadata', {}).get('logical_cohort')
        if m:
            key = (m['local_id'], *(q.rsplit('/', 1)[0] for q in o['qubits']))
            cohorts.setdefault(key, set()).add(o['id'])

    def score(chosen):
        ids = {c['op_id'] for c in chosen}
        full = sum(len(g) == 9 and g <= ids for g in cohorts.values())
        ranks = [se_direction_rank(byop[i]) for i in ids]
        # A transparent scheduling preference, never an added DAG edge. This
        # avoids fragmenting the next transport direction to collect one extra
        # gate now. Compatible other phases remain in the candidate domain.
        primary = sum(se_direction_rank(byop[i]) == minimum_direction.get(byop[i]['qubits'][0].rsplit('/', 1)[0])
                      for i in ids if se_direction_rank(byop[i]) is not None)
        spill = len(ids) - ranks.count(None) - primary
        priorities = (ranks.count(None), primary, -spill)
        if getattr(compiler,'closed_coupling_batch',False):priorities=(len(ids),0,0)
        return (full, priorities, len(chosen), -max((math.dist(c['from_um'], c['to_um']) for c in chosen), default=0.))

    def qualify(chosen, origin):
        key = tuple(sorted((c['op_id'], c['mover'], *c['to_um']) for c in chosen))
        if not chosen or key in checked:
            return
        movers = [c['mover'] for c in chosen]
        reason = None; route = None; sweep_proof = None
        try:
            goals = capture_assignment(scene,chosen,tol)
        except StrategyError as exc:
            goals={};reason=exc.code
        if reason is None:
            trial = [dict(a, position_um=goals[a['atom_id']]) if a['atom_id'] in goals else a for a in scene]
            if sorted(compiler.projected_broadcast_pairs(trial)) != sorted(sorted(c['pair']) for c in chosen):
                reason = 'EXTRA_BROADCAST_PAIR'
        if reason is None:
            try:
                route, sweep_proof = route_arrays(compiler,scene,goals)
            except StrategyError as exc:
                reason = exc.code
        checked[key] = reason
        if reason:
            reasons[reason] += 1
        else:
            accepted.append((score(chosen), chosen, route, origin, goals, sweep_proof))

    # This receipt sees every applicable operation and endpoint candidate.
    original, first = kernel.select(candidates)
    qualify(original, 'full_domain_Enola')
    first['proposal_qualified'] = bool(accepted)
    first['accepted'] = False  # proposal only; only the emitted selection is accepted
    if not accepted:
        first['rejection'] = checked.get(tuple(sorted((c['op_id'], c['mover'], *c['to_um']) for c in original)))

    domains = [[i for i, c in enumerate(candidates) if c['op_id'] == o['id']] for o in operations]
    conflicts = {tuple(e) for e in first['conflicts']}
    compatible = lambda i, j: tuple(sorted((i, j))) not in conflicts
    def irreversible_capture_conflict(state):
        chosen = [candidates[i] for i in state]
        try:capture_assignment(scene,chosen,tol)
        except StrategyError:return True
        return False
    translations = {}
    for i, c in enumerate(candidates):
        v = (c['aod_group'], *(round(c['to_um'][k] - c['from_um'][k], 8) for k in (0, 1)))
        translations.setdefault(v, []).append(i)
        translations.setdefault(('independent_groups',*v[1:]), []).append(i)
        translations.setdefault((*v, 'row', c['from_um'][1], c['to_um'][1]), []).append(i)
        translations.setdefault((*v, 'column', c['from_um'][0], c['to_um'][0]), []).append(i)
    for indices in translations.values():
        state = []
        for i in indices:
            if all(compatible(i, j) for j in state):
                state.append(i)
        qualify([candidates[i] for i in state], 'common_translation_across_ready_blocks')
    # A ready logical CNOT in one array can coexist with a whole SE direction
    # in another array even when their displacement vectors differ. Preserve
    # these bundles; adding one SE pair at a time needlessly fragments it.
    array_proposals = {}
    for value in accepted:
        gs={c['aod_group'] for c in value[1]}
        if len(gs)==1:array_proposals.setdefault(next(iter(gs)),[]).append(value)
    if len(array_proposals)>1:
        for combination in product(*(sorted(v,key=lambda x:x[0],reverse=True)[:4] for v in array_proposals.values())):
            qualify([c for v in combination for c in v[1]],'independent_array_frontier_bundles')
    width = 192
    beam = [()]; expansions = 0
    primary_ids = {o['id'] for o in operations if se_direction_rank(o) is None or
                   se_direction_rank(o) == minimum_direction[o['qubits'][0].rsplit('/',1)[0]]}
    # All normal gates plus each block's complete current direction is the
    # cardinality upper bound under this explicitly recorded direction policy.
    # Once a qualified assignment reaches it, do not enumerate equivalent
    # rectangles just to rediscover the same source batch.
    if getattr(compiler,'closed_coupling_batch',False):primary_ids={o['id'] for o in operations}
    fast_complete = any({c['op_id'] for c in v[1]} == primary_ids for v in accepted)
    # Keep multiple endpoint assignments, including choices that become a full
    # rectangle only after a later block contributes the remaining corners.
    for domain in ([] if fast_complete else domains):
        proposed = set(beam)
        for state in beam:
            for i in domain:
                expansions += 1
                if all(compatible(i, j) for j in state) and not irreversible_capture_conflict(state+(i,)):
                    proposed.add(state + (i,))
        def rank(state):
            chosen = [candidates[i] for i in state]
            movers = [c['mover'] for c in chosen]
            extra = len(set(capture_closure(scene, movers, tolerance=tol)['captured_atoms']) - set(movers)) if movers else 0
            s = score(chosen)
            return (s[0], s[1], s[2], -extra, s[3], tuple(-i for i in state))
        beam = sorted(proposed, key=rank, reverse=True)[:width]
    # A bounded full-assignment pass retains closed arrays which the beam may
    # otherwise lose. It applies to encoders, SE, Clifford and mixed frontiers.
    visited = 0; assignment_limit = 20000
    def full(active_domains, index, state):
        nonlocal visited
        visited += 1
        if visited > assignment_limit:
            return
        if index == len(active_domains):
            qualify([candidates[i] for i in state], 'complete_assignment')
            return
        for i in active_domains[index]:
            if all(compatible(i, j) for j in state) and not irreversible_capture_conflict(state+(i,)):
                full(active_domains, index + 1, state + (i,))
                if accepted and len(accepted[-1][1]) == len(active_domains):
                    return
    primary = [d for o,d in zip(operations,domains) if o['id'] in primary_ids]
    if not fast_complete:full(primary, 0, ())
    if not fast_complete and (not accepted or max(len(v[1]) for v in accepted) < len(operations)):
        full(domains, 0, ())
    for state in beam[:48]:
        qualify([candidates[i] for i in state], 'joint_assignment_beam')
    # Extend closed primary arrays with compatible gates from any ready phase.
    for _, seed, _, _, _, _ in ([] if fast_complete else sorted(accepted, key=lambda v:v[0], reverse=True)[:8]):
        used = {c['op_id'] for c in seed}; seed_indices = [candidates.index(c) for c in seed]
        for domain in domains:
            if not domain or candidates[domain[0]]['op_id'] in used:
                continue
            for i in domain:
                if all(compatible(i, j) for j in seed_indices):
                    qualify(seed + [candidates[i]], 'cross_phase_extension')
    # Explicit singleton alternatives make progress without falsely forbidding
    # rectangles after the first rejected greedy proposal.
    if not accepted:
        for c in candidates:
            qualify([c], 'singleton_fallback')
    if not accepted:
        raise StrategyError('JOINT_BATCH_SEARCH_EXHAUSTED', 'Bounded candidate search found no qualified batch; not infeasibility', reasons=dict(reasons), expansions=expansions)
    _, chosen, route, origin, transport_goals, sweep_proof = max(accepted, key=lambda x: x[0])
    # Qualify the assigned endpoints through the pinned selector as well. The
    # complete upstream domain and its result remain in the previous receipt.
    selected, receipt = kernel.select(chosen)
    if len(selected) != len(chosen):
        raise StrategyError('JOINT_ASSIGNMENT_MISMATCH', 'Enola rejected a supposedly compatible assignment')
    selected_ids = {c['op_id'] for c in chosen}; selected_indices = [candidates.index(c) for c in chosen]
    missed = []
    for op in operations:
        if op['id'] in selected_ids:continue
        outcomes = []
        for i in domains[[o['id'] for o in operations].index(op['id'])]:
            c = candidates[i]
            blockers = [j for j in selected_indices if not compatible(i,j)]
            if blockers:
                outcomes.append({'candidate_index':i,'reason':'Enola_pair_or_axis_conflict_with_selected_assignment',
                                 'blocking_candidate_indices':blockers})
                continue
            extended = chosen+[c]
            key = tuple(sorted((v['op_id'],v['mover'],*v['to_um']) for v in extended))
            if irreversible_capture_conflict(tuple(selected_indices)+(i,)):
                reason='capture_includes_fixed_partner_or_foreign_AOD_group'
            elif key in checked:
                reason=checked[key] or 'qualified_extension_deferred_by_direction_or_cohort_policy'
            else:reason='extension_not_route_qualified_within_declared_budget'
            outcomes.append({'candidate_index':i,'reason':reason})
        missed.append({'source_id':op['id'],'relative_to_selected_assignment':True,'alternatives':outcomes,
                       'all_reassignments_proven_infeasible':False})
    receipt.update(accepted=True, transport_goals=transport_goals, independent_array_outbound_sweep=sweep_proof,
        captured_spectators=sorted(set(transport_goals)-{c['mover'] for c in chosen}), joint_search={
        'schema_version': 'JointBatchSearch/0.1', 'full_domain_hash': digest(candidates),
        'full_domain_decision_hash': first['decision_hash'], 'candidate_count': len(candidates),
        'candidate_source_ids': [o['id'] for o in operations], 'selection': origin,
        'beam_width': width, 'beam_expansions': expansions, 'complete_assignment_nodes': min(visited, assignment_limit),
        'beam_final_qualification_limit':48, 'cross_phase_extension_seed_limit':8,
        'qualified_complete_primary_frontier':fast_complete,
        'complete_assignment_budget_exhausted': visited > assignment_limit,
        'qualified_proposals': len(accepted), 'rejected_proposals_by_reason': dict(reasons),
        'unselected_source_ids': [o['id'] for o in operations if o['id'] not in {c['op_id'] for c in chosen}],
        'unselected_reason': 'bounded_assignment_schedule_choice_not_hardware_impossibility',
        'unselected_details':missed,
        'global_optimality_claimed': False})
    return chosen, receipt, route
