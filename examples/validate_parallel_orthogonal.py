"""Independent reproducible acceptance of parallel 1Q and Manhattan corridors."""
import json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.visualization.workbench import compile_input
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.replay.serializer import canonical_json
from verify_m3 import verify


def main():
    root=Path('artifacts/m4-parallel-orthogonal');root.mkdir(parents=True,exist_ok=True)
    one={'compiler':'greedy','ez_policy':'adaptive','atom_count':4,'layout':'row','seed':7,'gates':[
        {'id':f'g{i}','gate_type':kind,'qubit_ids':[f'Q{i:03d}'],'parameters':[.2,.4,.6] if kind=='U3' else [],'column':0}
        for i,kind in enumerate(['H','X','U3','Z'])]}
    layers=one|{'gates':one['gates']+[dict(g,id=g['id']+'b',column=1) for g in one['gates']]}
    mixed=json.loads(Path('configs/workbench/m4_parallel.json').read_text(encoding='utf-8'))|{'compiler':'greedy','ez_policy':'adaptive'}
    cases={'four-1q':one,'two-layers':layers,'mixed-row':mixed,'mixed-shuffled':mixed|{'layout':'shuffled','seed':23},
           'budget-failure':mixed|{'max_decisions':1}}
    source=Path('artifacts/workbench/bea1faa3d00c406fbda9f0cfb0aba541/input.json')
    if source.exists():cases['user-current']=json.loads(source.read_text(encoding='utf-8'))|{'compiler':'greedy','ez_policy':'adaptive'}
    summaries=[]
    for name,value in cases.items():
        directory=root/name;directory.mkdir(parents=True,exist_ok=True)
        (directory/'verification.json').unlink(missing_ok=True)
        result,state=compile_input(value)
        for filename,data in [('input',result['input']),('recording',result['recording']),('decisions',result['decision_log']),
                              ('failure_report',result['failure_report']),('diagnostics',result['diagnostics']),
                              ('candidate_rejections',result['candidate_rejections']),('result',{'status':result['status'],'metrics':state.metrics()})]:
            (directory/(filename+'.json')).write_text(canonical_json(data),encoding='utf-8')
        (directory/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
        (directory/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
        write_html(result['recording'],directory/'index.html');verify(directory)
        count=0
        def half(v):return abs((v-2.5)/5-round((v-2.5)/5))<1e-8
        for raw in state.trace.records:
            r=json.loads(raw)
            if r.get('operation_type')!='aod_move' or r['event']['event_type']!='operation_started':continue
            a,b=r['source_configuration'],r['target_configuration'];x,y=a['x_um'][0],a['y_um'][0];xx,yy=b['x_um'][0],b['y_um'][0]
            assert x==xx or y==yy
            assert (y==yy and (half(y) or (abs(xx-x)<=2.5+1e-8 and (half(x) or half(xx))))) or (x==xx and (half(x) or (abs(yy-y)<=2.5+1e-8 and (half(y) or half(yy)))))
            count+=1
        pulses=[o for o in result['recording']['operations'] if o['kind']=='raman_rotation']
        peak=max((sum(p['start']<=o['start']<p['end'] for p in pulses) for o in pulses),default=0)
        if name=='four-1q':assert state.time_us==1 and peak==4
        if name=='two-layers':assert state.time_us==2 and peak==4
        assert result['status']==('stalled' if name=='budget-failure' else 'completed'),result['diagnostics']
        row={'case':name,'status':result['status'],'wall_us':state.time_us,'gates':state.metrics()['completed_gate_count'],
             'peak_parallel_1q':peak,'orthogonal_moves_checked':count,'raman_intervals':[(o['gate_id'],o['start'],o['end']) for o in pulses]}
        summaries.append(row);print(canonical_json(row),flush=True)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/neutral_atom_env').rglob('*') if p.suffix in {'.py','.js','.html'}}
    (root/'acceptance.json').write_text(canonical_json({'cases':summaries,'source_sha256':hashes}),encoding='utf-8')


if __name__=='__main__':main()
