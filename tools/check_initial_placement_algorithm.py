"""Nonvisual scaling/seed checks and reproducible editable JSON examples."""
from dataclasses import asdict
import json
from pathlib import Path
from random import Random

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_strategies.placement import PlacementProblem, Site, SearchConfig, optimize_initial
from neutral_atom_experiments.initial_placement import make_problem, request_json


def main():
    out = Path('artifacts/initial-placement/algorithm'); out.mkdir(parents=True,exist_ok=True)
    configs = Path('configs/placement'); configs.mkdir(parents=True,exist_ok=True)
    raw = dict(name='eight atoms on 10x10 storage',atom_count=8,
        pairs=[[0,1],[2,3],[4,5],[6,7],[0,2],[1,3],[4,6],[5,7],[0,4],[1,5],[2,6],[3,7]])
    _,small = make_problem(raw)
    (configs/'cz-eight.json').write_text(json.dumps(raw,indent=2),encoding='utf-8')
    (configs/'initial-eight.json').write_text(json.dumps(request_json(small,SearchConfig()),indent=2),encoding='utf-8')
    # Dense fully occupied 10x10 grid: 32 targets, 68 atoms idle this round.
    # This stresses capture compatibility, rather than just closeness to EZ.
    ids = tuple(f'Q{i:03d}' for i in range(100))
    sites = tuple(Site(f'S{r}_{c}',10*c,10*r) for r in range(10) for c in range(10))
    values = list(range(100)); Random(17).shuffle(values)
    dense = PlacementProblem(PhysicalCircuit(tuple(PhysicalGate(f'g{i}','CZ',(ids[2*i],ids[2*i+1])) for i in range(16))),
        ids,sites,tuple(Site(f'E{i}',20*i,130) for i in range(8)),
        tuple((q,sites[values[i]].id) for i,q in enumerate(ids)),aod_rows=10,aod_columns=10)
    reports=[]
    for name,p in [('eight',small),('dense100',dense)]:
        for seed in (7,19,41):
            for objective in ('distance','parking_aware'):
                result=optimize_initial(p,SearchConfig(iterations=1000,seed=seed,objective=objective))
                assert result.selected.cost.score_us <= result.baseline.cost.score_us
                p.validate_mapping(result.selected.mapping)
                path=out/f'{name}-{seed}-{objective}.json'
                path.write_text(json.dumps(asdict(result),indent=2),encoding='utf-8')
                reports.append(dict(case=name,seed=seed,objective=objective,
                    elapsed_seconds=result.diagnostics['elapsed_seconds'],
                    baseline_score=result.baseline.cost.score_us,selected_score=result.selected.cost.score_us,
                    baseline_captures=[d['capture_batches'] for d in result.baseline.cost.layer_details],
                    selected_captures=[d['capture_batches'] for d in result.selected.cost.layer_details],
                    physical_validation='not_run'))
    (out/'summary.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps(reports,indent=2))


if __name__=='__main__':
    main()
