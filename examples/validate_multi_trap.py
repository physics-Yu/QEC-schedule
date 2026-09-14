"""Reproducible editable circuit matrix for one AOD with multiple traps."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.visualization.workbench import compile_input
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.replay.serializer import canonical_json
from verify_m3 import verify


def main():
    root=Path('artifacts/multi-trap');root.mkdir(parents=True,exist_ok=True)
    base=json.loads(Path('configs/workbench/multi_trap.json').read_text(encoding='utf-8'))
    cases={f'capacity-{n}':base|{'aod_traps':n} for n in (1,2,4)}
    cases.update({'grid-4':base|{'layout':'grid'},'shuffled-4':base|{'layout':'shuffled','seed':13},
                  'budget-failure':base|{'max_decisions':1}})
    rows=[]
    for name,value in cases.items():
        directory=root/name;directory.mkdir(parents=True,exist_ok=True)
        start=time.perf_counter();result,state=compile_input(value);seconds=time.perf_counter()-start
        for filename,data in [('input',result['input']),('recording',result['recording']),('decisions',result['decision_log']),
            ('failure_report',result['failure_report']),('diagnostics',result['diagnostics']),
            ('candidate_rejections',result['candidate_rejections']),('result',{'status':result['status'],'metrics':state.metrics()})]:
            (directory/(filename+'.json')).write_text(canonical_json(data),encoding='utf-8')
        (directory/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
        (directory/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
        write_html(result['recording'],directory/'index.html');verify(directory)
        assert result['status']==('stalled' if name=='budget-failure' else 'completed'),result['diagnostics']
        ops=result['recording']['operations'];frames=result['recording']['frames']
        peak=max((o['moving_count'] for o in ops),default=0)
        active=max(sum(f['aod']['enabled_rows'])*sum(f['aod']['enabled_columns']) for f in frames)
        if name.startswith('capacity-'):assert peak==value['aod_traps']
        assert active<=value['aod_traps']
        row={'case':name,'status':result['status'],'wall_us':state.time_us,'peak_carried':peak,'peak_active':active,
             'capacity':value['aod_traps'],'loads':state.metrics()['aod_load_count'],
             'operations':len(ops),'compile_seconds':seconds}
        rows.append(row);print(canonical_json(row),flush=True)
    (root/'acceptance.json').write_text(canonical_json(rows),encoding='utf-8')


if __name__=='__main__':main()
