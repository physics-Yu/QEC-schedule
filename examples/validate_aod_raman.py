"""Editable-input acceptance with independent trace replay, no compiler shortcut."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.visualization.workbench import compile_input
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.replay.serializer import canonical_json
from verify_m3 import verify


def main():
    root=Path('artifacts/aod-raman');root.mkdir(parents=True,exist_ok=True)
    base=json.loads(Path('configs/workbench/aod_raman.json').read_text(encoding='utf-8'))
    def singles(kinds):
        return base|{'gates':[{'id':f'g{i}','gate_type':kind,'qubit_ids':[f'Q{i:03d}'],'parameters':[],'column':0}
                             for i,kind in enumerate(kinds)]}
    cases={'aod-t-reuse':base,'four-h':singles(['H']*4),'h-x-groups':singles(['H','X','H','X']),
           'shuffled':base|{'layout':'shuffled','seed':13},'budget-failure':base|{'max_decisions':1}}
    rows=[]
    for name,value in cases.items():
        directory=root/name;directory.mkdir(parents=True,exist_ok=True)
        result,state=compile_input(value)
        for filename,data in [('input',result['input']),('recording',result['recording']),('decisions',result['decision_log']),
            ('failure_report',result['failure_report']),('diagnostics',result['diagnostics']),
            ('candidate_rejections',result['candidate_rejections']),('result',{'status':result['status'],'metrics':state.metrics()})]:
            (directory/(filename+'.json')).write_text(canonical_json(data),encoding='utf-8')
        (directory/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
        (directory/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
        write_html(result['recording'],directory/'index.html');verify(directory)
        assert result['status']==('stalled' if name=='budget-failure' else 'completed')
        effects=[o for o in result['recording']['operations'] if o['kind'] in {'raman_rotation','entangling_pulse'}]
        for i,a in enumerate(effects):
            for b in effects[i+1:]:
                if max(a['start'],b['start'])<min(a['end'],b['end']):assert a['gate_type']==b['gate_type']
        if name=='aod-t-reuse':
            raman=[o for o in effects if o['kind']=='raman_rotation']
            assert len(raman)==2 and raman[0]['start']==raman[1]['start']
            assert {h['holder_type'] for o in raman for h in o['target_holders'].values()}=={'static','mobile'}
            cz=[o for o in effects if o['kind']=='entangling_pulse']
            assert not any(o['kind'] in {'aod_load','aod_offload'} and cz[0]['end']<=o['start']<cz[1]['start']
                           for o in result['recording']['operations'])
        if name=='four-h':assert state.time_us==1
        if name=='h-x-groups':assert state.time_us==2
        row={'case':name,'status':result['status'],'wall_us':state.time_us,'effects':effects}
        rows.append(row);print(name,result['status'],state.time_us,flush=True)
    (root/'acceptance.json').write_text(canonical_json(rows),encoding='utf-8')


if __name__=='__main__':main()
