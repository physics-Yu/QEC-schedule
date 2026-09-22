"""Independently inspect process overlap and the no-final-return contract."""
import json
from pathlib import Path
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.operations import TaskTarget
from neutral_atom_env.program.task_validation import validate_target
from analyze_complex_placement import analyze


def audit(root):
    summary=analyze(root)
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    search=read(root/'search'/'search.json')
    intervals=[];pids=set()
    for t in search['trials']:
        folder=root/'search'/f"trial-{t['index']:04d}"
        report=read(folder/'result.json')
        if 'worker_pid' in report:
            pids.add(report['worker_pid'])
            intervals += [(report['started_at'],1),(report['finished_at'],-1)]
        if not t['evaluation']['valid']:continue
        env=NeutralAtomEnv.restore((folder/'final.json').read_text(encoding='utf-8'));state=env.state
        validate_target(TaskTarget(),state)
        assert state.dag.completed and not env.pending
        assert report['replay_equal'] and report['effects_once'] and report['terminal_mode']=='stable'
        assert not any(d['kind'] in {'Return to initial SLM','terminal'} for d in report['execution']['decision_log'])
        assert report['total_time_us']==state.time_us==t['evaluation']['total_time_us']
    active=peak=0
    for _,delta in sorted(intervals):active+=delta;peak=max(peak,active)
    assert peak>1 and len(pids)>1,'No evidence of actual parallel compilation'
    return dict(**summary,worker_pids=sorted(pids),observed_concurrent_workers=peak,
                proposal_pool=search['diagnostics']['proposal_pool'],workers=search['diagnostics']['workers'],
                checked='stable final snapshots, complete gates, exactly-once effects, independent replay, no final layout return')


if __name__=='__main__':
    root=Path('artifacts/free-placement')
    rows=[audit(root/(name+'-parallel')) for name in ('partners-12','grid-16')]
    (root/'parallel-summary.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ('case','candidate_count','valid_count','improvement_percent',
          'wall_seconds','observed_concurrent_workers','proposal_pool','worker_pids')} for r in rows],indent=2))
