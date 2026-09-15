"""Reproduce the reported Q000/783us batch with exactly the saved assignment."""
import json
import sys
from pathlib import Path
from dataclasses import replace
from time import perf_counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_strategies.scheduling.ordered_greedy import build_batch,realize_batch


def main():
    source=ROOT/'artifacts/qec-ordered/attempt2-direct-transfer/qec_ghz2/smt_ordered'
    target=ROOT/'artifacts/qec-axis-hold/counterfactual'
    target.mkdir(parents=True,exist_ok=True)
    original=json.loads((source/'plans.json').read_text(encoding='utf-8'))
    env=NeutralAtomEnv.restore((source/'initial.json').read_text(encoding='utf-8'))
    for saved in original[:2]:
        env.submit(plan_from_dict(saved));env.run()
    state=env.state
    decision=next(d for d in json.loads((source/'result.json').read_text(encoding='utf-8'))['decisions'] if d['kind']=='CZ')
    outcomes=[]
    for name in ('legacy_corridor','axis_hold'):
        initial=replace(state,hardware=replace(state.hardware,backend='row_column'))
        batch=build_batch(initial,decision['assignments']);rejections=[]
        plan=realize_batch(initial,batch,perf_counter()+180,128,rejections,motion_router=name)
        run=NeutralAtomEnv(initial);recorder=VisualRecorder(initial)
        run.submit(plan);run.run(on_event=lambda s,e:recorder.observe(s))
        recorder.write(target/(name+'.html'))
        (target/(name+'-plan.json')).write_text(canonical_json(plan),encoding='utf-8')
        points=[batch.pickup]
        for op in plan.operations:
            if op.operation_type==K.AOD_LOAD:points=[batch.pickup]
            elif op.operation_type==K.ENTANGLING_PULSE:break
            elif op.operation_type==K.AOD_MOVE:points.append(op.target_configuration)
        tracks={}
        for q in ('Q000','Q019'):
            cell=next(b.cell for b in batch.bindings if b.atom_id==q)
            positions=[c.position(cell) for c in points]
            tracks[q]={'points':[[p.x_um,p.y_um] for p in positions],
                       'distance_um':sum(abs(a.x_um-b.x_um)+abs(a.y_um-b.y_um) for a,b in zip(positions,positions[1:]))}
        outcomes.append(dict(backend='row_column',motion_router=name,duration_us=plan.estimated_duration_us,
                             distance_um=plan.estimated_distance_um,tracks=tracks,
                             validated_and_executed=True,rejections=len(rejections)))
    assert outcomes[1]['tracks']['Q000']['distance_um']==8
    assert outcomes[1]['duration_us']<outcomes[0]['duration_us']
    assert outcomes[1]['tracks']['Q000']['points'][-1]==[5,-57]
    (target/'comparison.json').write_text(json.dumps(outcomes,indent=2),encoding='utf-8')
    print(json.dumps(outcomes,indent=2))


if __name__=='__main__':main()
