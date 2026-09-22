"""Bounded initial mapping search. Never mutates a live environment."""
from itertools import permutations
from math import exp, perm
from random import Random
from time import perf_counter

from .cost import PlacementCostModel
from .models import PlacementCandidate, PlacementResult, SearchConfig


def optimize_initial(problem, config=SearchConfig()):
    started = perf_counter()
    model = PlacementCostModel(problem, config)
    baseline = PlacementCandidate(problem.validate_mapping(problem.initial_mapping),
                                  model.estimate(problem.initial_mapping), 'baseline')
    keep = {baseline.mapping: baseline}
    locked = dict(problem.locked)
    free = [q for q in problem.qubits if q not in locked]
    slots = [s.id for s in problem.storage if s.id not in locked.values()]
    space = perm(len(slots), len(free))

    def remember(candidate):
        keep[candidate.mapping] = candidate
        ordered = sorted(keep.values(), key=lambda c: (c.cost.score_us, c.mapping))[:config.top_k]
        keep.clear(); keep.update((c.mapping, c) for c in ordered)
        # Baseline survives even when it is outside the proxy shortlist.
        keep[baseline.mapping] = baseline

    def evaluate(mapping, origin):
        candidate = PlacementCandidate(problem.validate_mapping(mapping), model.estimate(mapping), origin)
        remember(candidate)
        return candidate

    exact = bool(config.exact_limit and space <= config.exact_limit)
    iterations = 0
    if exact:
        for values in permutations(slots, len(free)):
            mapping = dict(locked); mapping.update(zip(free, values))
            evaluate(mapping, 'enumeration'); iterations += 1
    elif free and slots and model.layers:
        rng = Random(config.seed)
        # Coherent translations cross barriers that one-atom swaps cannot:
        # splitting a jointly transported pair across rows temporarily costs more.
        coordinates = {(s.x_um,s.y_um):s.id for s in problem.storage}
        by_id = {s.id:s for s in problem.storage}
        anchor = by_id[dict(baseline.mapping)[free[0]]]
        if not locked:
            for target in problem.storage:
                dx,dy = target.x_um-anchor.x_um, target.y_um-anchor.y_um
                proposal = {q:coordinates.get((by_id[s].x_um+dx,by_id[s].y_um+dy)) for q,s in baseline.mapping}
                if all(s is not None for s in proposal.values()):
                    evaluate(proposal, 'translated_seed')
        current = min(keep.values(), key=lambda c:(c.cost.score_us,c.mapping))
        initial_temp = max(baseline.cost.score_us * .05, 1)
        for i in range(config.iterations):
            mapping = dict(current.mapping)
            # Whole-row/column swaps preserve useful pickup patterns while
            # exploring their locations. Missing sites and locks reject the
            # move before scoring; nothing is dropped from the mapping.
            if rng.random() < .25:
                axis = rng.choice(('x_um', 'y_um'))
                values = sorted({getattr(s,axis) for s in problem.storage})
                if len(values) < 2:
                    iterations += 1
                    continue
                v1,v2 = rng.sample(values,2)
                valid = True
                for q,s in current.mapping:
                    point = by_id[s]; value = getattr(point,axis)
                    shifted = v2 if value == v1 else v1 if value == v2 else value
                    xy = (shifted,point.y_um) if axis == 'x_um' else (point.x_um,shifted)
                    destination = coordinates.get(xy)
                    if destination is None or q in locked and destination != locked[q]:
                        valid = False; break
                    mapping[q] = destination
                if not valid:
                    iterations += 1
                    continue
            else:
                q = rng.choice(free); destination = rng.choice(slots)
                occupant = next((a for a, s in mapping.items() if s == destination), None)
                if occupant is not None:
                    mapping[occupant] = mapping[q]
                mapping[q] = destination
            candidate = evaluate(mapping, 'annealing')
            temperature = initial_temp * (.001 ** (i / max(config.iterations - 1, 1)))
            delta = candidate.cost.score_us - current.cost.score_us
            if delta <= 0 or rng.random() < exp(-delta / temperature):
                current = candidate
            iterations += 1
    candidates = tuple(sorted(keep.values(), key=lambda c: (c.cost.score_us, c.mapping)))
    # Preserve input on a tie; no unmotivated permutation for zero CZ circuits.
    selected = baseline if baseline.cost.score_us <= candidates[0].cost.score_us else candidates[0]
    return PlacementResult(selected, baseline, candidates, dict(
        seed=config.seed, iterations=iterations, search_space=space,
        exact_proxy_optimum=exact, objective=config.objective,
        elapsed_seconds=perf_counter()-started, **model.statistics(),
        physical_validation='not_run', circuit_gate_count=len(problem.circuit.gates),
        scored_cz_layers=len(model.layers),
        unscored_operations=sorted({g.gate_type for g in problem.circuit.gates if not g.is_two_qubit}),
        limitations=['static mapping used throughout lookahead', 'pair costs omit destination contention',
                     'capture proxy omits downstream unload/reload batches and empty-AOD positioning',
                     'no collision/path/terminal verification until physical evaluation']))


def select_physically(result, evaluator):
    """Evaluate all shortlisted mappings INCLUDING baseline under one contract.

    evaluator(candidate) must run an isolated environment and return a
    PhysicalEvaluation. Failed candidates never win; failures remain visible.
    """
    from .models import PhysicalEvaluation
    records = []
    for candidate in result.candidates:
        try:
            evaluation = evaluator(candidate)
            if not isinstance(evaluation, PhysicalEvaluation):
                raise TypeError('Evaluator must return PhysicalEvaluation')
        except Exception as error:
            evaluation = PhysicalEvaluation(False, failure=f'{type(error).__name__}: {error}')
        records.append((candidate, evaluation))
    valid = [(c, e) for c, e in records if e.valid]
    selected = min(valid, key=lambda item: (item[1].total_time_us,
                    item[0].mapping != result.baseline.mapping, item[0].mapping))[0] if valid else None
    return selected, tuple(records)
