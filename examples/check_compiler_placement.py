"""Same general placement optimizer on different layouts and physical circuits."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
from neutral_atom_app.visualization.workbench import build_inputs
from neutral_atom_app.placement_execution import optimize_compiled_layout
from neutral_atom_strategies.placement import CompilerSearchConfig
from neutral_atom_env.replay.serializer import canonical_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('artifacts/initial-placement/general'))
    parser.add_argument('--evaluations',type=int,default=8)
    parser.add_argument('--layouts',nargs='+',default=['row','grid','shuffled'])
    parser.add_argument('--rounds',type=int,default=1)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    if not 1 <= args.rounds <= 20:parser.error('rounds must be in 1..20')
    cases=[]
    for layout in args.layouts:
        for name,pairs in [('crossed',[(0,3),(1,2)]),('adjacent',[(0,1),(2,3)])]:
            gates=[dict(id='prepare',gate_type='H',qubit_ids=['Q000'],column=0)]
            for r in range(args.rounds):
                gates += [dict(id=f'cz{r}_{i}',gate_type='CZ',qubit_ids=[f'Q{a:03d}',f'Q{b:03d}'],column=1+2*r)
                          for i,(a,b) in enumerate(pairs)]
                if r+1 < args.rounds:
                    # Noncommuting rotations prevent a trivial CZ-CZ cancellation.
                    gates += [dict(id=f'h{r}_{q}',gate_type='H',qubit_ids=[f'Q{q:03d}'],column=2+2*r)
                              for q in (0,2)]
            gates.append(dict(id='finish',gate_type='T',qubit_ids=['Q003'],column=2*args.rounds))
            raw=dict(atom_count=4,layout='grid' if layout=='irregular' else layout,seed=13,ez_policy='adaptive',
                aod_backend='row_column_orthogonal',aod_rows=2,aod_columns=4,
                aod_row_offsets_um=[0,10],aod_column_offsets_um=[0,10,20,30],
                compilation=dict(strategy='legacy',implementation='ordered_greedy',compile_timeout_s=60),gates=gates)
            _,circuit,platform,mapping=build_inputs(raw)
            if layout=='irregular':
                # An explicit nonrectangular source set; no geometry changes by
                # the optimizer and no patch layout convention in its interface.
                from neutral_atom_env.domain.models import Position2D,GridCoord
                traps=dict(platform.world.traps)
                for i,(x,y) in enumerate([(0,0),(15,0),(5,10),(20,10)]):
                    key=f'S{i:03d}'
                    traps[key]=replace(traps[key],position=Position2D(x,y),grid=GridCoord(x//5,y//5))
                platform=replace(platform,world=replace(platform.world,traps=traps))
            target=args.output/f'{layout}-{name}'; target.mkdir(parents=True,exist_ok=True)
            (target/'input.json').write_text(canonical_json(raw),encoding='utf-8')
            def progress(t):
                print(json.dumps(dict(case=f'{layout}-{name}',trial=t.index,
                    valid=t.evaluation.valid,time_us=t.evaluation.total_time_us,
                    failure=t.evaluation.failure)),flush=True)
            result=optimize_compiled_layout(circuit,platform,mapping,
                config=CompilerSearchConfig(max_evaluations=args.evaluations,exhaustive_limit=0,seed=7),
                compiler_options=dict(compile_timeout_s=60),output=target,on_trial=progress)
            cases.append(dict(case=f'{layout}-{name}',rounds=args.rounds,status=result.status,
                baseline_us=result.baseline.evaluation.total_time_us,
                selected_us=result.selected.evaluation.total_time_us if result.selected else None,
                improvement_percent=result.improvement_percent,evaluated=len(result.trials),
                failures=result.diagnostics['failures'],wall_seconds=result.diagnostics['elapsed_seconds']))
            (args.output/'summary.json').write_text(canonical_json(cases),encoding='utf-8')
    print(json.dumps(cases,indent=2))
    return int(any(c['status'] not in {'improved','baseline_retained'} for c in cases))


if __name__=='__main__':raise SystemExit(main())
