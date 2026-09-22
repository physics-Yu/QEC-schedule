"""Picklable process entry point: one isolated environment and evidence folder."""
from collections import Counter
import json
import os
from pathlib import Path
from time import perf_counter, time
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.operations import TaskTarget
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_strategies.placement import PhysicalEvaluation
from neutral_atom_strategies.scheduling.ordered_controller import run_ordered


def execute_candidate(request):
    tick=perf_counter(); started=time(); env=None; plans=[]
    initial=request['initial']; folder=Path(request['directory']) if request['directory'] else None
    if folder:folder.mkdir(parents=True,exist_ok=True)
    report=dict(contract_sha256=request['contract'],mapping=dict(request['mapping']),valid=False,
                worker_pid=os.getpid(),started_at=started,terminal_mode=request['terminal_mode'])
    compile_seconds=replay_seconds=0.
    try:
        env=NeutralAtomEnv.restore(initial); origin=env.state; submit=env.submit
        def capture(plan):
            submit(plan);plans.append(plan)
        env.submit=capture
        fixed=request['terminal_mode']=='fixed'
        runner=run_ordered
        if request['options'].get('strategy')=='zoned_ids':
            from neutral_atom_strategies.zoned import run_zoned as runner
        options=dict(request['options']);options.pop('restore_layout',None)
        execution=runner(env,terminal_target=request['terminal'] if fixed else None,
                              restore_layout=fixed,**options)
        compile_seconds=perf_counter()-tick;report['execution']=execution
        if execution.status!='completed':raise RuntimeError(canonical_json(execution.diagnostics))
        if env.pending or not env.state.dag.completed:raise AssertionError('Unfinished circuit or pending physical operation')
        if (env.state.dag.circuit!=origin.dag.circuit or env.state.hardware!=origin.hardware
                or env.state.world!=origin.world):raise AssertionError('Fixed circuit or hardware contract changed')
        validate_target(request['terminal'] if fixed else TaskTarget(),env.state)
        effects=Counter()
        for raw in env.state.trace.records:
            row=json.loads(raw)
            if row.get('effect_completed'):effects.update(row.get('effect_gate_ids',[]))
        if effects!=Counter({g.id:1 for g in origin.dag.circuit.gates}):
            raise AssertionError('Gate effects must complete exactly once')
        if not fixed and any(d['kind'] in {'Return to initial SLM','terminal'} for d in execution.decision_log):
            raise AssertionError('Stable mode executed fixed-layout restoration')
        replay_tick=perf_counter();replay=NeutralAtomEnv.restore(initial)
        for plan in plans:replay.submit(plan);replay.run()
        replay_seconds=perf_counter()-replay_tick
        if replay.snapshot()!=env.snapshot():raise AssertionError('Independent replay mismatch')
        report.update(valid=True,total_time_us=env.state.time_us,replay_equal=True,effects_once=True,
                      terminal_verified=True,metrics=env.state.metrics())
        value=PhysicalEvaluation(True,env.state.time_us,evidence=str(folder/'result.json') if folder else None)
    except Exception as error:
        report['failure']=f'{type(error).__name__}: {error}'
        value=PhysicalEvaluation(False,failure=report['failure'],evidence=str(folder/'result.json') if folder else None)
    final=env.snapshot() if env else None
    report.update(compile_seconds=compile_seconds,replay_seconds=replay_seconds,elapsed_seconds=perf_counter()-tick,
                  plan_count=len(plans),finished_at=time())
    if folder:
        (folder/'result.json').write_text(canonical_json(report),encoding='utf-8')
        (folder/'initial.json').write_text(initial,encoding='utf-8')
        (folder/'plans.json').write_text(canonical_json(plans),encoding='utf-8')
        if final:(folder/'final.json').write_text(final,encoding='utf-8')
    return value,report['elapsed_seconds'],final if request['return_final'] else None
