"""Optimize an exported workbench input without opening or modifying the UI."""
import argparse
import json
from pathlib import Path
from neutral_atom_app.control import configured_strategy
from neutral_atom_app.placement_execution import optimize_compiled_layout
from neutral_atom_app.visualization.workbench import build_inputs,initialize_input
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_strategies.placement import CompilerSearchConfig


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--evaluations',type=int,default=12)
    p.add_argument('--seed',type=int,default=7)
    p.add_argument('--allow-vacancies',action='store_true')
    p.add_argument('--lock',action='append',default=[],metavar='QUBIT=SLM')
    args=p.parse_args()
    # Never overwrite a supplied source input through an output artifact name.
    if args.output.resolve() in args.input.resolve().parents:
        p.error('Output directory must not contain the input file')
    value,circuit,platform,mapping=build_inputs(json.loads(args.input.read_text(encoding='utf-8')))
    strategy=configured_strategy(value)
    if strategy.id not in {'ordered_greedy','smt_ordered'}:
        p.error('This physical adapter needs an ordered_greedy or smt_ordered input; no implicit compiler switch')
    locks={}
    for entry in args.lock:
        pair=entry.split('=',1)
        if len(pair)!=2 or pair[0] in locks:p.error('Locks must be unique QUBIT=SLM pairs')
        locks[pair[0]]=pair[1]
    state=initialize_input(value,circuit,platform,mapping)
    def progress(t):
        print(canonical_json(dict(trial=t.index,valid=t.evaluation.valid,time_us=t.evaluation.total_time_us,
                                  failure=t.evaluation.failure)),flush=True)
    result=optimize_compiled_layout(circuit,platform,mapping,locked=locks,
        config=CompilerSearchConfig(max_evaluations=args.evaluations,seed=args.seed,
                                    allow_vacancies=args.allow_vacancies),
        compiler_options=dict(strategy.options),seed=value['seed'],quantum_state=state.quantum_state,
        output=args.output,on_trial=progress)
    print(canonical_json(dict(status=result.status,improvement_percent=result.improvement_percent,
                              selected_mapping=dict(result.selected.mapping) if result.selected else None,
                              report=str(args.output/'search.json'))))
    return int(result.selected is None)


if __name__=='__main__':raise SystemExit(main())
