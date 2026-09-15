"""Matched-backend ablation of translation-only versus ordered-axis greedy."""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import canonical_json, primitive
from neutral_atom_env.statistics import write_atom_statistics
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.ordered_greedy import OrderedAxisGreedy, restore
from neutral_atom_experiments.smt_comparison import make_state as rigid_state, validate_spec as base_validate, demos as old_demos

STRATEGIES=('translation_greedy','ordered_greedy')


def demos():
    def spec(name,points,pairs,rows,columns):
        return dict(name=name,positions=points,gates=[dict(type='CZ',qubits=p) for p in pairs],
                    aod_rows=rows,aod_columns=columns,timeout_s=60,solver_timeout_ms=5000,
                    beam_width=64,plan_budget=24,route_budget=128)
    return {
        'stretch':spec('列独立伸缩：10 μm 源间距 → 20 μm 配对间距',
                       [[0,0],[10,0],[20,0],[0,30],[20,30],[40,30]],[[0,3],[1,4],[2,5]],1,3),
        'two_axes':spec('二维独立伸缩：2×2 源阵列 → 不同间距目标阵列',
                        [[0,0],[10,0],[0,10],[10,10],[40,40],[60,40],[40,70],[60,70]],
                        [[0,4],[1,5],[2,6],[3,7]],2,2),
        'parallel':old_demos()['parallel'],
        'closure':old_demos()['closure'],
        'dependency':old_demos()['dependency'],
    }


def validate_spec(spec):
    base_validate(spec)
    for key,default,limit in (('beam_width',64,512),('plan_budget',24,128),('route_budget',128,256)):
        v=spec.get(key,default)
        if type(v)!=int or not 1<=v<=limit:raise ValueError(f'{key} must be an integer in 1–{limit}')
    return spec


def make_state(spec):
    validate_spec(spec)
    state=rigid_state(spec)
    # Same hardware for BOTH policies; only the strategy's allowed targets differ.
    return replace(state,hardware=replace(state.hardware,backend='row_column'))


def run_one(spec,strategy,directory):
    if strategy not in STRATEGIES:raise ValueError('Unknown ordered-axis strategy')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    state=make_state(spec);env=NeutralAtomEnv(state);initial=env.snapshot();terminal=initial_terminal(state)
    recorder=VisualRecorder(state)
    planner=OrderedAxisGreedy(translation_only=strategy=='translation_greedy',beam_width=spec.get('beam_width',64),
                             plan_budget=spec.get('plan_budget',24),route_budget=spec.get('route_budget',128))
    started=perf_counter();deadline=started+spec.get('timeout_s',60)
    plans=[];decisions=[];error=None;execute_s=0.;planning_s=0.
    def execute(plan):
        nonlocal execute_s
        if plan is None:return
        tick=perf_counter();env.submit(plan);plans.append(plan)
        env.run(on_event=lambda s,e:recorder.observe(s));execute_s+=perf_counter()-tick
    try:
        while not env.state.dag.completed:
            if perf_counter()>deadline:raise TimeoutError('Overall ordered-axis planning deadline')
            tick=perf_counter();decision,plan=planner.propose(env.state,deadline);planning_s+=perf_counter()-tick
            decisions.append(primitive(decision));execute(plan)
        tick=perf_counter();plan=restore(env.state,terminal);planning_s+=perf_counter()-tick
        execute(plan);validate_target(terminal,env.state)
    except (ValidationError,TimeoutError) as e:
        error={'code':e.violation.code if isinstance(e,ValidationError) else 'COMPILE_TIMEOUT','message':str(e)}
    elapsed=perf_counter()-started
    tick=perf_counter();replay=NeutralAtomEnv.restore(initial)
    for plan in plans:replay.submit(plan);replay.run()
    replay_equal=replay.snapshot()==env.snapshot();replay_s=perf_counter()-tick
    effects=[json.loads(r) for r in env.state.trace.records if json.loads(r).get('effect_completed')]
    counts=Counter(g for r in effects for g in r.get('effect_gate_ids',[]))
    once=counts==Counter({g.id:1 for g in state.dag.circuit.gates}) if env.state.dag.completed else all(v==1 for v in counts.values())
    cz=[d for d in decisions if d['kind']=='CZ'];payload=recorder.payload()
    result=dict(strategy=strategy,status='completed' if error is None else 'failed',error=error,
                initial_sha256=sha256(initial.encode()).hexdigest(),input_sha256=sha256(canonical_json(spec).encode()).hexdigest(),
                compile_seconds=elapsed,realization_seconds=planning_s,execution_recording_seconds=execute_s,
                replay_seconds=replay_s,replay_equal=replay_equal,effects_once=once,terminal_verified=error is None,
                metrics=env.state.metrics(),cz_batch_sizes=[len(d['gate_ids']) for d in cz],
                max_cz_batch=max((len(d['gate_ids']) for d in cz),default=0),cz_stages=len(cz),
                decisions=decisions,baseline_log=planner.log,rejection_count=len(planner.rejections),
                scope='same row_column cubic backend; greedy batch-size then actual-duration; ordered axes vs common shift; restoring SLM batches',
                physical_optimality_claim=False)
    for name,value in [('input.json',spec),('result.json',result),('recording.json',payload),('plans.json',plans),('rejections.json',planner.rejections)]:
        (directory/name).write_text(canonical_json(value),encoding='utf-8')
    (directory/'initial.json').write_text(initial,encoding='utf-8');(directory/'checkpoint.json').write_text(env.snapshot(),encoding='utf-8')
    env.state.trace.write(directory/'trace.jsonl');recorder.write(directory/'animation.html')
    write_atom_statistics(payload['atom_statistics'],directory)
    if not replay_equal or not once:raise AssertionError('Ordered-axis physical replay/effect audit failed')
    return result
