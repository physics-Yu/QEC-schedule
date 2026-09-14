"""Bounded M4 policies over the same validated physical service candidates.

Lookahead executes private copies through Executor. Its finite horizon is scored
with actual elapsed time and actual terminal closure plus a remaining pulse-only
critical-path lower bound. That bound deliberately does not pretend to predict
unsearched transport, and the selected result has no optimality guarantee.
"""
from dataclasses import replace
from math import inf

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus, HolderType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.motion.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from .executor import Executor

STRATEGIES = ('basic', 'greedy', 'critical_path', 'lookahead')


class PolicySelectionError(ValidationError):
    """Preserve bounded-search evidence when no candidate can be selected."""
    def __init__(self, code, message, report, rejections):
        super().__init__(code, message)
        self.report = report
        self.rejections = tuple(rejections)


def critical_paths(state):
    """Longest unfinished successor chain, weighted by physical pulse duration."""
    memo = {}
    def visit(g):
        if g in memo:
            return memo[g]
        node = state.dag.nodes[g]
        if node.status == GateStatus.COMPLETED:
            memo[g] = 0.
        else:
            duration = (state.hardware.pulse_duration_us if node.gate.gate_type == 'CZ'
                        else state.hardware.raman_duration_us)
            memo[g] = duration + max((visit(s) for s in node.successors), default=0.)
        return memo[g]
    for g in state.dag.nodes:
        visit(g)
    return memo


def candidate_features(candidate, state, paths=None):
    paths = paths or critical_paths(state)
    root = state.dag.nodes[candidate.gate_id]
    # Shortest dependency-edge distance to the next use of each operand.
    distances = {}; queue = [(s, 1) for s in root.successors]; seen = set()
    while queue:
        g, depth = queue.pop(0)
        if g in seen:
            continue
        seen.add(g)
        node = state.dag.nodes[g]
        for q in node.gate.qubit_ids:
            if q in root.gate.qubit_ids:
                distances.setdefault(q, depth)
        queue.extend((s, depth + 1) for s in node.successors)
    holders = dict(candidate.plan.predicted_placement)
    reused = [q for q in root.gate.qubit_ids if q in distances and
              (holders[q].holder_type == HolderType.MOBILE or
               holders[q].holder_id.startswith('EZ'))]
    return {'critical_path_us': paths[candidate.gate_id],
            'next_use_distance': {q: distances.get(q) for q in root.gate.qubit_ids},
            'reuse_count': len(reused), 'reusable_atoms': reused,
            'disposition': 'return' if candidate.key.endswith('/return') else 'keep'}


def return_candidate(candidate, state, compiler, target):
    """Append explicit timed restoration; never modify the gate candidate."""
    intent = replace(candidate.plan.intent, task_id=candidate.plan.intent.task_id + '/return', target=target)
    builder = ProgramBuilder(state, intent)
    for op in candidate.plan.operations:
        builder.add(op.operation_type, op.label, target=op.target_pose,
                    configuration=op.target_configuration, bindings=op.transfer_bindings,
                    phase=op.transfer_phase, switch_state=op.switch_state)
    compiler.target(builder, target)
    return replace(candidate, key=candidate.key + '/return', plan=builder.finish(compiler.id))


def diverse_shortlist(candidates, width):
    """Retain different gates/holders/axes/masks, not duplicate route variants."""
    chosen = []; seen = set()
    ordered=sorted(candidates,key=lambda c:c.cost)
    first={}
    for c in ordered:first.setdefault(c.gate_id,c)
    # Cover distinct READY gates before spending extra beam slots on another
    # placement of the same gate. Within each group physical cost orders ties.
    ordered=list(first.values())+[c for c in ordered if c is not first[c.gate_id]]
    for c in ordered:
        signature = (c.gate_id, c.plan.predicted_placement, c.plan.predicted_traps,
                     # Return and KEEP can have equal holders but different axes.
                     tuple((o.target_pose, o.target_configuration) for o in c.plan.operations
                           if o.target_pose is not None or o.target_configuration is not None)[-1:])
        if signature in seen:
            continue
        seen.add(signature); chosen.append(c)
        if len(chosen) == width:
            break
    return chosen


def select_candidate(candidates, state, compiler, terminal, *, strategy, depth,
                     beam_width, rollout_budget, alternatives, schedule):
    """Return chosen original-state candidate, bounded diagnostics, extra refusals."""
    paths = critical_paths(state)
    candidates.sort(key=lambda c: c.cost)
    report = {'depth': depth, 'beam_width': beam_width, 'node_budget': rollout_budget,
              'nodes_used': 0, 'budget_exhausted': False, 'limit_reached': False,
              'unexpanded_horizons': 0, 'omitted_children': 0, 'evaluations': [],
              'score_model': 'actual horizon + actual terminal closure + remaining pulse critical path',
              'candidate_count': len(candidates), 'omitted_candidates': 0}
    rejected = []
    if strategy == 'greedy':
        return candidates[0], report, rejected
    if strategy == 'critical_path':
        return min(candidates, key=lambda c: (-paths[c.gate_id], *c.cost)), report, rejected
    if strategy == 'basic':
        first = min(c.gate_id for c in candidates)
        roots = diverse_shortlist([c for c in candidates if c.gate_id == first], beam_width)
        returns = []
        # Basic returns to the initial physical configuration after each service.
        origin = TaskTarget(tuple(sorted(state.placement.atom_to_holder.items())),
                            state.aod.configuration(), trap_state(state))
        report['omitted_candidates'] = len(candidates) - len(roots)
        for c in roots:
            try:
                returns.append(return_candidate(c, state, compiler, origin))
            except ValidationError as error:
                rejected.append({'candidate': c.key + '/return', 'violation': primitive(error.violation)})
        if not returns:
            raise PolicySelectionError('BASIC_RETURN_EXHAUSTED',
                                       'No searched gate can return to its physical origin', report, rejected)
        return min(returns, key=lambda c: c.cost), report, rejected

    origin_time = state.time_us
    def run(candidate, physical):
        if report['nodes_used'] >= rollout_budget:
            report['budget_exhausted'] = True
            return None
        report['nodes_used'] += 1
        # Fork the top-level runtime, sharing persistent immutable children.
        # Checkpoint parsing is for external restoration, not an in-memory fork.
        # Executor still validates every submitted plan and committed boundary.
        branch = replace(physical)
        plan, _ = schedule(candidate.plan, branch)
        executor = Executor(branch); executor.submit(plan); executor.run()
        return branch

    def closure(physical):
        lower = max(critical_paths(physical).values(), default=0.)
        cleanup = 0.
        try:
            validate_target(terminal, physical)
        except ValidationError:
            exit_plan = compiler.compile(TaskIntent('lookahead-exit/' + str(physical.version), terminal,
                                         frozenset(physical.atoms), phase='cleanup'), physical)
            # Closure is independently validated, but not a promise about future
            # unsearched gates. It is an endpoint evaluation of this branch.
            cleanup = exit_plan.estimated_duration_us
        return physical.time_us - origin_time + cleanup + lower, cleanup, lower

    def evaluate(candidate, physical, remaining, node_ceiling):
        branch = run(candidate, physical)
        if branch is None:
            return None
        score, cleanup, lower = closure(branch)
        evidence = {'projected_total_us': score, 'terminal_cleanup_us': cleanup,
                    'remaining_lower_bound_us': lower, 'horizon_elapsed_us': branch.time_us-origin_time,
                    'actual_depth': depth-remaining+1,
                    'end_holders': primitive(branch.placement.atom_to_holder),
                    'gates_completed': sum(n.status == GateStatus.COMPLETED for n in branch.dag.nodes.values()),
                    'horizon_complete': branch.dag.completed, 'status': 'evaluated'}
        if remaining > 1 and not branch.dag.completed and report['nodes_used'] >= node_ceiling:
            # A remaining requested horizon was prevented by the root's node
            # quota. Reaching the limit at an already-complete leaf is different.
            report['budget_exhausted'] = True
            report['unexpanded_horizons'] += 1
        elif remaining > 1 and not branch.dag.completed:
            children = diverse_shortlist(alternatives(branch), beam_width)
            values = []
            for index, child in enumerate(children):
                if report['nodes_used'] >= node_ceiling:
                    report['budget_exhausted'] = True
                    report['omitted_children'] += len(children)-index
                    break
                try:
                    outcome = evaluate(child, branch, remaining - 1, node_ceiling)
                    if outcome is not None:
                        values.append(outcome)
                except ValidationError as error:
                    rejected.append({'candidate': child.key, 'scope': 'lookahead', 'violation': primitive(error.violation)})
            if values:
                score, evidence = min(values, key=lambda value: value[0])
        return score, evidence

    roots = diverse_shortlist(candidates, beam_width)
    # Keep and return share the same physical gate prefix, making the effect of
    # retained holders explicit. Root variants are evaluated fairly breadth-first.
    variants = list(roots)
    for c in roots:
        try:
            returned = return_candidate(c, state, compiler, terminal)
            if returned.plan.operations != c.plan.operations:
                variants.append(returned)
        except ValidationError as error:
            rejected.append({'candidate': c.key + '/return', 'scope': 'lookahead', 'violation': primitive(error.violation)})
    report['omitted_candidates'] = max(0, len(candidates)-len(roots))
    ranked = []
    # Equal per-root quotas prevent the first branch consuming the entire tree
    # budget. If the budget cannot cover roots, the omitted roots are explicit.
    selected_roots = variants[:rollout_budget]
    report['omitted_roots'] = len(variants)-len(selected_roots)
    quota = max(1, rollout_budget // len(selected_roots))
    report['nodes_per_root'] = quota
    for c in selected_roots:
        skipped_before=report['omitted_children']
        unexpanded_before=report['unexpanded_horizons']
        try:
            value = evaluate(c, state, depth, min(rollout_budget, report['nodes_used']+quota))
            if value is not None:
                score, evidence = value
                report['evaluations'].append(dict(evidence, candidate=c.key,
                    skipped_budget_children=report['omitted_children']-skipped_before,
                    unexpanded_budget_horizons=report['unexpanded_horizons']-unexpanded_before))
                features=candidate_features(c,state,paths)
                # Only break equal projected-cost ties with actual next-use
                # residency, rather than adding an uncalibrated time bonus.
                ranked.append((score, -features['reuse_count'], *c.cost, c))
        except ValidationError as error:
            rejected.append({'candidate': c.key, 'scope': 'lookahead', 'violation': primitive(error.violation)})
    report['limit_reached'] = report['nodes_used'] >= rollout_budget
    report['budget_exhausted'] = report['budget_exhausted'] or bool(report['omitted_roots'])
    if not ranked:
        raise PolicySelectionError('LOOKAHEAD_CANDIDATES_EXHAUSTED',
                                   'No branch has a validated terminal closure within the rollout budget', report, rejected)
    return min(ranked, key=lambda row: row[:-1])[-1], report, rejected
