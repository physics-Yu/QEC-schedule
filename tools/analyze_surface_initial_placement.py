"""Explain QEC initial-placement costs with validated staging plans and traces."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_experiments.surface_initial_placement import prepare_experiment,candidate_state
from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer
from neutral_atom_strategies.scheduling.ordered_greedy import new_builder,finish
from neutral_atom_strategies.scheduling.patch_greedy import patch_assignment


def analyze(directory,stage_only=False):
    directory=Path(directory)
    spec,base,problem,config,search=prepare_experiment()
    lookup={(t.position.x_um,t.position.y_um):k for k,t in base.world.traps.items()}
    stages=[];common=None
    for dy in (-5,0,5,10):
        mapping=[]
        for q in base.atoms:
            p=base.placement.position(q,base.world,base.aod)
            mapping.append((q,lookup[p.x_um,p.y_um+dy]))
        candidate=replace(search.baseline,mapping=tuple(mapping))
        env=NeutralAtomEnv(candidate_state(base,candidate))
        initial=env.snapshot()
        builder=new_builder(env.state)
        OrderedTransfer().transfer_group(builder,patch_assignment(env.state),'Full patch staging diagnostic')
        plan=finish(builder)
        env.submit(plan);env.run()
        replay=NeutralAtomEnv.restore(initial);replay.submit(plan);replay.run()
        assert replay.snapshot()==env.snapshot()
        signature=(env.state.placement,env.state.aod.configuration(),dict(env.state.slm_enabled),
                   env.state.dag,env.state.quantum_state,env.state.measurement_results,env.state.rng_state)
        if common is None:common=signature
        assert signature==common
        stages.append(dict(dy_um=dy,physical_stage_us=env.state.time_us,
            operations=[dict(kind=o.operation_type.value,duration_us=o.duration_us,label=o.label) for o in plan.operations],
            replay_equal=True,same_post_stage_geometry_quantum_dag_rng=True))
    (directory/'staging-analysis.json').write_text(json.dumps(stages,indent=2),encoding='utf-8')
    if stage_only:
        return stages
    results={n:json.loads((directory/n/'result.json').read_text(encoding='utf-8')) for n in ('baseline','candidate-0')}
    plans={n:json.loads((directory/n/'plans.json').read_text(encoding='utf-8')) for n in results}
    def operations(ps):
        # Labels/operation IDs/dependency IDs are not physical changes.
        return [[{k:v for k,v in op.items() if k not in {'id','depends_on','label'}} for op in p['operations']] for p in ps]
    same_tail=operations(plans['baseline'][1:])==operations(plans['candidate-0'][1:])
    delta=results['candidate-0']['metrics']['simulation_time_us']-results['baseline']['metrics']['simulation_time_us']
    stage_delta=plans['candidate-0'][0]['estimated_duration_us']-plans['baseline'][0]['estimated_duration_us']
    assert same_tail and abs(delta-stage_delta)<1e-6
    output=dict(status='passed',candidate_minus_baseline_us=delta,
        staging_difference_us=stage_delta,identical_subsequent_physical_operations=same_tail,
        all_four_staging_plans=stages,
        conclusion='Prepared-array closeness to EZ saves loaded motion but adds empty AOD positioning; all choices converge after staging. Proxy charges initial coordinates repeatedly across CZ layers; physical controller stages only once.')
    (directory/'cost-analysis.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',default='artifacts/initial-placement/surface-ghz2')
    parser.add_argument('--stage-only',action='store_true')
    args=parser.parse_args()
    print(json.dumps(analyze(args.directory,args.stage_only),indent=2))
