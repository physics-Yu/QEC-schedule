"""Compiler-in-the-loop search on a caller's fixed set of initial SLM sites.

No circuit family, regular grid, patch translation or routing policy is assumed.
The evaluator owns the complete execution/terminal contract. Geometry scores
only order proposals; only measured, valid executions can change the incumbent.
"""
from collections import Counter
from dataclasses import dataclass
from itertools import permutations
from math import perm
from random import Random
from time import perf_counter

from .models import PhysicalEvaluation


@dataclass(frozen=True)
class CompilerSearchConfig:
    max_evaluations: int = 12  # includes baseline, failures and independent replay
    proposal_pool: int = 64
    seed: int = 7
    allow_vacancies: bool = False
    exhaustive_limit: int = 64
    explore_every: int = 3
    batch_size: int = 1

    def __post_init__(self):
        for name, low, high in [('max_evaluations',1,10000), ('proposal_pool',1,1024),
                               ('exhaustive_limit',0,10000), ('explore_every',1,1000), ('batch_size',1,32)]:
            v = getattr(self, name)
            if type(v) is not int or not low <= v <= high:
                raise ValueError(f'{name} must be an integer in {low}..{high}')
        if type(self.seed) is not int or type(self.allow_vacancies) is not bool:
            raise ValueError('seed must be an integer and allow_vacancies a boolean')


@dataclass(frozen=True)
class MappingTrial:
    index: int
    mapping: tuple[tuple[str, str], ...]
    origin: str
    proposal_score: float  # weighted interaction distance; NOT microseconds
    evaluation: PhysicalEvaluation
    wall_seconds: float


@dataclass(frozen=True)
class CompilerPlacementResult:
    baseline: MappingTrial
    selected: MappingTrial | None
    trials: tuple[MappingTrial, ...]
    status: str
    improvement_percent: float | None
    diagnostics: dict


def optimize_with_compiler(problem, evaluator, *, contract,
                           config=CompilerSearchConfig(), on_trial=None, seed_mappings=(), evaluate_batch=None):
    """Search mappings, calling evaluator(mapping) once per distinct proposal.

    ``contract`` must describe the fixed compiler, terminal and cost scope.
    Evaluator returns PhysicalEvaluation after full execution and independent
    replay. Its wall time is reported separately from simulated duration.
    Default moves permute atom identities on the user's occupied sites; explicit
    allow_vacancies also allows any other site in problem.storage.
    """
    if not isinstance(contract, str) or not contract.strip():
        raise ValueError('An explicit fixed evaluation contract is required')
    started = perf_counter(); rng = Random(config.seed)
    baseline = problem.validate_mapping(problem.initial_mapping)
    locked = dict(problem.locked)
    free = tuple(q for q in problem.qubits if q not in locked)
    allowed = ({s.id for s in problem.storage} if config.allow_vacancies
               else {s for _, s in baseline}) - set(locked.values())
    slots = tuple(sorted(allowed))
    seeds = tuple(problem.validate_mapping(m) for m in seed_mappings)
    if any(any(q in free and s not in allowed for q,s in m) for m in seeds):
        raise ValueError('Seed mapping outside permitted search domain')
    space = perm(len(slots), len(free))
    points = {s.id:(s.x_um, s.y_um) for s in problem.storage}
    weights = Counter(tuple(sorted(g.qubit_ids)) for g in problem.circuit.gates if g.is_two_qubit)

    def score(mapping):
        positions = {q:points[s] for q,s in mapping}
        return sum(w*(abs(positions[a][0]-positions[b][0])+abs(positions[a][1]-positions[b][1]))
                   for (a,b), w in weights.items())

    seen = set(); trials = []; incumbent = None

    def evaluate_many(proposals):
        nonlocal incumbent
        reserved=[]
        for mapping,origin in proposals:
            mapping=problem.validate_mapping(mapping)
            if mapping not in seen and len(trials)+len(reserved)<config.max_evaluations:
                seen.add(mapping);reserved.append((mapping,origin))
        if not reserved:return
        # A batch evaluator returns (PhysicalEvaluation, wall_seconds) in input
        # order. Workers may finish out of order; selection and numbering do not.
        if evaluate_batch is not None:
            values=list(evaluate_batch(tuple(m for m,o in reserved)))
            if len(values)!=len(reserved):raise ValueError('Batch evaluator result count mismatch')
        else:
            values=[]
            for mapping,origin in reserved:
                tick=perf_counter()
                try:value=evaluator(mapping)
                except Exception as error:value=PhysicalEvaluation(False,failure=f'{type(error).__name__}: {error}')
                values.append((value,perf_counter()-tick))
        for (mapping,origin),(value,seconds) in zip(reserved,values):
            if not isinstance(value,PhysicalEvaluation):
                value=PhysicalEvaluation(False,failure='TypeError: Evaluator must return PhysicalEvaluation')
            trial=MappingTrial(len(trials),mapping,origin,score(mapping),value,seconds)
            trials.append(trial)
            if value.valid and (incumbent is None or value.total_time_us<incumbent.evaluation.total_time_us):
                incumbent=trial
            if on_trial is not None:on_trial(trial)

    evaluate_many([(baseline,'baseline')])
    exact = space <= min(config.exhaustive_limit, config.max_evaluations)
    exhausted_proposals = False
    if exact:
        proposals=[]
        for assignment in permutations(slots, len(free)):
            mapping = dict(locked); mapping.update(zip(free, assignment))
            if problem.validate_mapping(mapping) in seen:continue
            proposals.append((mapping,'enumeration'))
            if len(proposals)>=config.batch_size:
                evaluate_many(proposals);proposals=[]
        evaluate_many(proposals)
    else:
        while len(trials) < config.max_evaluations and len(seen) < space:
            parent = incumbent.mapping if incumbent else baseline
            pool = {}
            for mapping in seeds:
                if mapping not in seen:
                    pool[mapping]='circuit_embedding'
                if len(pool)>=config.proposal_pool//2:
                    break
            # Bounded random neighborhood and global restarts. The global move
            # lets us cross a barrier even if all single swaps are slower.
            for _ in range(config.proposal_pool * 8):
                mapping = dict(parent)
                if rng.random() < .2:
                    mapping.update(zip(free, rng.sample(slots,len(free))))
                    origin = 'restart'
                else:
                    q = rng.choice(free); destination = rng.choice(slots)
                    other = next((a for a,s in mapping.items() if s == destination), None)
                    if other is not None:
                        mapping[other] = mapping[q]
                    mapping[q] = destination
                    origin = 'swap' if other else 'vacancy'
                key = problem.validate_mapping(mapping)
                if key not in seen:
                    pool[key] = origin
                if len(pool) >= config.proposal_pool:
                    break
            if not pool:
                exhausted_proposals = True; break
            proposals=[]
            for offset in range(min(config.batch_size,len(pool),config.max_evaluations-len(trials))):
                if (len(trials)+offset)%config.explore_every==0:
                    key=rng.choice(sorted(pool));origin='explore:'+pool[key]
                else:
                    key=min(pool,key=lambda m:(score(m),m));origin='ranked:'+pool[key]
                proposals.append((key,origin));del pool[key]
            evaluate_many(proposals)

    original = trials[0]
    if incumbent is None:
        status = 'no_valid_execution'
    elif not original.evaluation.valid:
        status = 'valid_without_baseline'
    elif incumbent.index == 0:
        status = 'baseline_retained'
    else:
        status = 'improved'
    improvement = None
    if incumbent and original.evaluation.valid:
        t0 = original.evaluation.total_time_us
        improvement = 100*(t0-incumbent.evaluation.total_time_us)/t0 if t0 else 0.
    return CompilerPlacementResult(original, incumbent, tuple(trials), status, improvement, dict(
        contract=contract, seed=config.seed, mapping_space=space, evaluated=len(trials),
        full_space_evaluated=len(seen)==space, optimality_scope='only evaluated mappings and this fixed compiler',
        stop_reason='mapping_space_exhausted' if len(seen)==space else
                    'proposal_generation_exhausted' if exhausted_proposals else 'evaluation_budget',
        proposal_score_units='weighted interaction distance in um; not execution time',
        mapping_scope='all allowed sites' if config.allow_vacancies else 'permutation of occupied sites',
        failures=sum(not t.evaluation.valid for t in trials),
        elapsed_seconds=perf_counter()-started,proposal_pool=config.proposal_pool,batch_size=config.batch_size))
