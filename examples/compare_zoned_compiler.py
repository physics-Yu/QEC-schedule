"""Same-input, same-terminal compiler comparison with independent plan replay."""
import argparse
import json
from pathlib import Path
from time import perf_counter
from collections import Counter
from neutral_atom_app.visualization.workbench import build_inputs, initialize_input
from neutral_atom_app.control import configured_strategy
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.operations import TaskTarget, OperationType as K
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_strategies.scheduling.m3 import initial_terminal


def compare_one(value, strategy, folder, *, fixed=False, timeout=90):
    value=json.loads(json.dumps(value))
    value.pop('studio',None)
    value['compilation']=dict(strategy='legacy',implementation=strategy,compile_timeout_s=timeout)
    value['placement_search']=dict(value.get('placement_search',{}),enabled=False)
    normalized,circuit,platform,placement=build_inputs(value)
    env=NeutralAtomEnv(initialize_input(normalized,circuit,platform,placement))
    origin=env.snapshot();terminal=initial_terminal(env.state) if fixed else TaskTarget()
    plans=[];submit=env.submit
    def capture(plan):
        submit(plan);plans.append(plan)
    env.submit=capture
    runner=configured_strategy(normalized)
    tick=perf_counter()
    options=dict(runner.options);options.pop('restore_layout',None)
    execution=runner.runner(env,restore_layout=fixed,**options)
    elapsed=perf_counter()-tick
    report=dict(strategy=strategy,status=execution.status,compile_seconds=elapsed,terminal_mode='fixed' if fixed else 'stable',
                physical_us=env.state.time_us,metrics=env.state.metrics(),execution=execution)
    captured={b.atom_id for p in plans for op in p.operations if op.operation_type==K.AOD_LOAD for b in op.transfer_bindings}
    report['moved_atoms']=sorted(captured)
    report['cz_batch_sizes']=[len(op.effect_gate_ids) for p in plans for op in p.operations if op.operation_type==K.ENTANGLING_PULSE]
    if execution.status=='completed':
        validate_target(terminal,env.state)
        effects=Counter()
        for row in env.state.trace.records:
            row=json.loads(row)
            if row.get('effect_completed'):effects.update(row.get('effect_gate_ids',[]))
        assert effects==Counter({g.id:1 for g in circuit.gates})
        tick=perf_counter();replay=NeutralAtomEnv.restore(origin)
        for plan in plans:replay.submit(plan);replay.run()
        assert replay.snapshot()==env.snapshot()
        report.update(replay_equal=True,effects_once=True,replay_seconds=perf_counter()-tick)
        if normalized.get('circuit_profile')=='qec_ghz2':
            from neutral_atom_experiments.surface_qec import summarize
            report['qec_result']=summarize(env.state)
    folder.mkdir(parents=True,exist_ok=True)
    for name,data in [('input',normalized),('report',report),('plans',plans)]:
        (folder/(name+'.json')).write_text(canonical_json(data),encoding='utf-8')
    (folder/'initial.json').write_text(origin,encoding='utf-8')
    (folder/'final.json').write_text(env.snapshot(),encoding='utf-8')
    print(canonical_json({k:v for k,v in report.items() if k not in {'metrics','execution'}}),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--strategy',choices=['ordered_greedy','zoned_ids','both'],default='both')
    parser.add_argument('--output',type=Path,default=Path('artifacts/zoned-compiler'))
    parser.add_argument('--fixed',action='store_true')
    parser.add_argument('--timeout',type=int,default=90)
    args=parser.parse_args();value=json.loads(args.input.read_text(encoding='utf-8'))
    for strategy in ['ordered_greedy','zoned_ids'] if args.strategy=='both' else [args.strategy]:
        compare_one(value,strategy,args.output/strategy,fixed=args.fixed,timeout=args.timeout)


if __name__=='__main__':main()
