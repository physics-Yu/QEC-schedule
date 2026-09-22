"""Headless initial-placement ablation with common physical terminal state.

Fixed author frontend/dynamic-placement policy and local transport backend for
all candidates. Only initial mapping changes. No reports or HTML are rendered.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_env.statistics import summarize_atoms, write_atom_statistics
from neutral_atom_strategies.placement import (Site, PlacementProblem, SearchConfig,
    PhysicalEvaluation, optimize_initial, select_physically)
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.zac_reuse import ZACPlacementStrategy, site_id
from .zac_reuse import normalize_spec, make_state, frontend, DEFAULT_SOURCE


def make_problem(raw, grid=10):
    spec = normalize_spec(raw)
    if not 2 <= grid <= 10:
        raise ValueError('Acceptance grid must be 2..10')
    if grid * grid < spec['atom_count']:
        raise ValueError('Insufficient grid sites')
    storage = spec['architecture']['storage_zones'][0]['slms'][0]
    storage.update(r=grid, c=grid)
    edge = (grid-1)*10
    ez_y = edge + 30
    width = max(120, edge+60)
    spec['architecture']['arch_range'] = [[-20,-20], [width,ez_y+60]]
    spec['storage_bounds'] = [[-20,-20], [width,edge+10]]
    spec['entanglement_bounds'] = [[-20,ez_y-10], [width,ez_y+40]]
    spec['architecture']['rydberg_range'] = [spec['entanglement_bounds']]
    for slm in spec['architecture']['entanglement_zones'][0]['slms']:
        slm['location'][1] = ez_y
    # SLM grid dimensions are not AOD capacity. Keep unused axes within the
    # declared field of view rather than manufacturing a 100-trap AOD.
    aod_rows = min(grid,max(2,(spec['atom_count']+1)//2))
    aod_columns = min(grid,max(4,spec['atom_count']))
    spec['architecture']['aods'][0].update(r=aod_rows,c=aod_columns)
    spec['architecture']['arch_range'][1][1] = ez_y+40+10*(aod_rows-1)
    spec['initial_mapping'] = [[0,q//grid,q%grid] for q in range(spec['atom_count'])]
    if 'initial_mapping' in raw:
        spec['initial_mapping'] = deepcopy(raw['initial_mapping'])
    state = make_state(spec)
    slms = tuple(Site(site_id((0,r,c)), c*10, r*10) for r in range(grid) for c in range(grid))
    ez = spec['architecture']['entanglement_zones'][0]['slms'][0]
    interaction = tuple(Site(f'gate_{r}_{c}', ez['location'][0]+c*20, ez_y+r*20)
                        for r in range(ez['r']) for c in range(ez['c']))
    problem = PlacementProblem(state.dag.circuit, tuple(state.atoms), slms, interaction,
        tuple((q,h.holder_id) for q,h in state.placement.atom_to_holder.items()),
        locked=tuple(raw.get('locked',{}).items()),
        aod_rows=aod_rows,aod_columns=aod_columns,hardware=state.hardware)
    return spec, problem


def request_json(problem, config):
    return dict(schema='initial-placement/1', qubits=list(problem.qubits),
        gates=[asdict(g) for g in problem.circuit.gates], storage=[asdict(s) for s in problem.storage],
        interaction_sites=[asdict(s) for s in problem.interaction_sites],
        initial_mapping=dict(problem.initial_mapping), locked=dict(problem.locked),
        aod=dict(rows=problem.aod_rows, columns=problem.aod_columns),
        search=asdict(config))


def evaluate_physical(spec, candidate, terminal, directory, *, source=DEFAULT_SOURCE, reuse=False):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    trial = deepcopy(spec)
    mapping = dict(candidate.mapping)
    trial['initial_mapping'] = [[int(v) for v in mapping[f'Q{q:03d}'].replace('Z','').replace('R','').replace('C','').split('_')]
                                for q in range(trial['atom_count'])]
    started = perf_counter()
    env = NeutralAtomEnv(make_state(trial))
    initial = env.snapshot()
    strategy = None
    error = None
    try:
        placements = frontend(trial, source, directory/'upstream', reuse)
        strategy = ZACPlacementStrategy(placements, timeout_s=trial['timeout_s'], terminal_target=terminal)
        strategy.run(env)
    except Exception as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
    replay = NeutralAtomEnv.restore(initial)
    plans = strategy.plans if strategy else []
    replay_error = None
    try:
        for plan in plans:
            replay.submit(plan); replay.run()
    except Exception as exc:
        replay_error = str(exc)
    records = [json.loads(r) for r in env.state.trace.records]
    effects = Counter(g for r in records if r.get('effect_completed') for g in r.get('effect_gate_ids', []))
    once = effects == Counter({g.id:1 for g in env.state.dag.circuit.gates})
    equal = replay_error is None and replay.snapshot() == env.snapshot()
    valid = error is None and once and equal
    kinds = Counter(op.operation_type.value for plan in plans for op in plan.operations)
    decisions = strategy.decisions if strategy else []
    logical_end = max((d['end_us'] for d in decisions if d.get('kind') == 'CZ'), default=0)
    report = dict(status='passed' if valid else 'failed', error=error, replay_error=replay_error,
        independent_replay=equal, effects_once=once, terminal_verified=error is None,
        metrics=env.state.metrics(), physical_total_us=env.state.time_us,
        logical_end_us=logical_end, tail_us=env.state.time_us-logical_end,
        operation_counts=dict(kinds), compile_execute_replay_seconds=perf_counter()-started,
        mapping=dict(candidate.mapping), proxy=asdict(candidate.cost), decisions=decisions,
        terminal=primitive(terminal), circuit_sha256=sha256(json.dumps(primitive(env.state.dag.circuit),sort_keys=True).encode()).hexdigest())
    for name, value in [('result.json', report), ('plans.json', primitive(plans)),
                        ('rejections.json', strategy.rejections if strategy else [])]:
        (directory/name).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
    (directory/'initial.json').write_text(initial,encoding='utf-8')
    (directory/'checkpoint.json').write_text(env.snapshot(),encoding='utf-8')
    env.state.trace.write(directory/'trace.jsonl')
    write_atom_statistics(summarize_atoms(env.state),directory)
    return PhysicalEvaluation(valid, env.state.time_us if valid else None,
        failure=None if valid else json.dumps(error or replay_error or 'Gate effect/replay mismatch'),
        evidence=str(directory/'result.json'))


def run_experiment(raw, directory, config=SearchConfig(iterations=1000,top_k=2), *, grid=10, source=DEFAULT_SOURCE):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    spec, problem = make_problem(raw,grid)
    result = optimize_initial(problem,config)
    terminal = initial_terminal(make_state(spec))
    (directory/'request.json').write_text(json.dumps(request_json(problem,config),indent=2),encoding='utf-8')
    (directory/'search.json').write_text(json.dumps(asdict(result),indent=2),encoding='utf-8')
    counter = 0
    def evaluate(candidate):
        nonlocal counter
        name = 'baseline' if candidate.mapping == result.baseline.mapping else f'candidate-{counter}'
        counter += 1
        print(f'{directory.name}: evaluating {name}', flush=True)
        return evaluate_physical(spec,candidate,terminal,directory/name,source=source)
    selected, records = select_physically(result,evaluate)
    baseline = next(e for c,e in records if c.mapping == result.baseline.mapping)
    chosen = next((e for c,e in records if selected is not None and c.mapping == selected.mapping),None)
    report = dict(status='passed' if chosen and baseline.valid else 'failed',
        contract='same gates/platform/frontend/transport/explicit terminal; prepared initial mappings; reuse OFF',
        selected_mapping=dict(selected.mapping) if selected else None,
        baseline_time_us=baseline.total_time_us, selected_time_us=chosen.total_time_us if chosen else None,
        improvement_percent=(100*(baseline.total_time_us-chosen.total_time_us)/baseline.total_time_us)
                            if baseline.valid and chosen and baseline.total_time_us else None,
        evaluations=[dict(mapping=dict(c.mapping),proxy_us=c.cost.score_us,**asdict(e)) for c,e in records],
        search_diagnostics=result.diagnostics, gui='not_requested_not_run')
    (directory/'comparison.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    return report
