"""Audit saved headless comparisons and export per-atom accounting, without UI."""
import json
from pathlib import Path
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.statistics import summarize_atoms, write_atom_statistics


root = Path('artifacts/initial-placement')
summary = []
for case in ('four-final','eight'):
    report = json.loads((root/case/'comparison.json').read_text(encoding='utf-8'))
    assert report['status'] == 'passed'
    reference = NeutralAtomEnv.restore((root/case/'baseline/checkpoint.json').read_text(encoding='utf-8')).state
    entries=[]
    for candidate in report['evaluations']:
        path=Path(candidate['evidence']); result=json.loads(path.read_text(encoding='utf-8'))
        assert result['status']=='passed' and result['independent_replay'] and result['effects_once']
        state=NeutralAtomEnv.restore((path.parent/'checkpoint.json').read_text(encoding='utf-8')).state
        assert state.dag.circuit == reference.dag.circuit
        assert state.hardware == reference.hardware
        assert state.placement == reference.placement
        assert state.aod.configuration() == reference.aod.configuration()
        assert state.slm_enabled == reference.slm_enabled
        assert state.world.bounds == reference.world.bounds and state.world.zones == reference.world.zones
        assert {k:t.position for k,t in state.world.traps.items()} == {k:t.position for k,t in reference.world.traps.items()}
        stats=summarize_atoms(state); write_atom_statistics(stats,path.parent)
        assert stats['pending_operations']==0
        assert abs(sum(a['distance_um'] for a in stats['atoms'].values())-state.metrics()['total_atom_distance_um'])<1e-6
        entries.append(dict(path=str(path),physical_us=state.time_us,
            load_batches=state.metrics()['aod_load_count'],
            atom_loads=sum(a['load_count'] for a in stats['atoms'].values()),
            atom_distance_um=state.metrics()['total_atom_distance_um']))
    summary.append(dict(case=case,common_terminal=True,same_circuit_and_hardware=True,
        improvement_percent=report['improvement_percent'],baseline_us=report['baseline_time_us'],
        selected_us=report['selected_time_us'],executions=entries))
output=dict(status='passed',comparisons=summary,gui='not_requested_not_run',
            boundary='CZ physical ablation; 100-atom search is proxy-only; initial assembly not included')
(root/'acceptance.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
print(json.dumps(output,indent=2))
