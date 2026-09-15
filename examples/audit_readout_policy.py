"""Matched execution at the saved Q019/5241us service boundary."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_strategies.scheduling.qec import readout_service
from neutral_atom_strategies.scheduling.readout_placement import ReadoutPlacementPolicy
from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer


def main():
    initial=(ROOT/'artifacts/qec-axis-hold/q019-5241-audit/initial.json').read_text(encoding='utf-8')
    directory=ROOT/'artifacts/qec-readout-policy/q019';directory.mkdir(parents=True,exist_ok=True)
    rows=[];final=[]
    for mode in ('legacy','adaptive','slm_only'):
        env=NeutralAtomEnv.restore(initial);before=env.snapshot()
        gates=tuple(env.state.dag.nodes[g].gate for g in ('prepare_X0_1','prepare_X0_2','prepare_X1_1','prepare_X1_2'))
        policy=None if mode=='legacy' else ReadoutPlacementPolicy(mode=mode)
        plan,resets=readout_service(env.state,OrderedTransfer(),gates,placement_policy=policy)
        assert env.snapshot()==before
        rec=VisualRecorder(env.state);env.submit(plan);env.run(on_event=lambda s,e:rec.observe(s))
        replay=NeutralAtomEnv.restore(initial);replay.submit(plan);replay.run();assert replay.snapshot()==env.snapshot()
        rec.write(directory/(mode+'.html'));payload=rec.payload()
        counts={k:sum(o['kind']==k for o in payload['operations']) for k in ('aod_load','aod_offload','measurement','reset')}
        rows.append(dict(mode=mode,duration_us=plan.estimated_duration_us,operations=counts,
                         selected=policy.log[-1]['selected'] if policy else None,replay_equal=True))
        if policy:(directory/(mode+'-decisions.json')).write_text(json.dumps(policy.log,indent=2),encoding='utf-8')
        final.append(env.state)
    for s in final[1:]:
        assert s.quantum_state==final[0].quantum_state and s.measurement_results==final[0].measurement_results
        assert s.placement==final[0].placement and s.aod==final[0].aod and s.slm_enabled==final[0].slm_enabled
    report=dict(same_quantum_results_and_terminal=True,results=rows)
    (directory/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
