"""Cross-check exported trials across layouts; no new compilation or replay."""
from collections import Counter
import json
from pathlib import Path
from neutral_atom_env import NeutralAtomEnv


def audit(root):
    root=Path(root);cases=[];count=0
    for name in ('general','general-three-round','general-irregular'):
        for path in sorted((root/name).glob('*/search.json')):
            search=json.loads(path.read_text(encoding='utf-8'))
            base=NeutralAtomEnv.restore((path.parent/'trial-0000'/'initial.json').read_text(encoding='utf-8')).state
            final_base=NeutralAtomEnv.restore((path.parent/'trial-0000'/'final.json').read_text(encoding='utf-8')).state
            durations=[];decompositions=[]
            for trial in search['trials']:
                folder=path.parent/f"trial-{trial['index']:04d}"
                report=json.loads((folder/'result.json').read_text(encoding='utf-8'))
                assert report['valid'] and report['replay_equal'] and report['effects_once'] and report['terminal_verified']
                initial=NeutralAtomEnv.restore((folder/'initial.json').read_text(encoding='utf-8')).state
                final=NeutralAtomEnv.restore((folder/'final.json').read_text(encoding='utf-8')).state
                assert initial.world==base.world and initial.hardware==base.hardware and initial.dag.circuit==base.dag.circuit
                assert initial.aod==base.aod and initial.slm_enabled==base.slm_enabled and initial.seed==base.seed
                assert final.world==base.world and final.hardware==base.hardware and final.dag.circuit==base.dag.circuit
                assert final.placement==final_base.placement and final.aod==final_base.aod and final.slm_enabled==final_base.slm_enabled
                assert final.time_us==trial['evaluation']['total_time_us']==report['total_time_us']
                times=Counter()
                for d in report['execution']['decision_log']:
                    times['initial_transfer' if d['kind']=='Stage to EZ' else
                          'terminal' if d['kind'] in ('terminal','Return to initial SLM') else 'circuit']+=d['duration_us']
                assert abs(sum(times.values())-final.time_us)<1e-6
                durations.append(final.time_us);count+=1
                decompositions.append(dict(trial=trial['index'],times_us=dict(times),
                    cz_batches=[len(d['gate_ids']) for d in report['execution']['decision_log'] if d['kind']=='CZ']))
            assert search['selected']['evaluation']['total_time_us']==min(durations)
            cases.append(dict(case=f'{name}/{path.parent.name}',baseline_us=durations[0],selected_us=min(durations),
                              gain_percent=search['improvement_percent'],trials=len(durations),
                              selected_trial=search['selected']['index'],decompositions=decompositions))
    assert len(cases)==14 and count==112,(len(cases),count)
    report=dict(status='passed',cases=cases,physical_executions=count,
                improved_cases=sum(c['gain_percent']>0 for c in cases),
                checks='same circuit/world/hardware/AOD/SLM/seed and absolute final state; effects/replay evidence; minimum evaluated time',
                scope='small general physical circuits; not a new full surface-QEC performance result')
    (root/'general-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
    return report


if __name__=='__main__':audit('artifacts/initial-placement')
