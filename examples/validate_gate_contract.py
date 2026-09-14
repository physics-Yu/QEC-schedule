"""Reproduce same-type gate concurrency with compiler-independent replay."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_app.visualization.workbench import compile_input
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.replay.serializer import canonical_json
from verify_m3 import verify


def main():
    root=Path('artifacts/gate-contract');root.mkdir(parents=True,exist_ok=True)
    def singles(kinds):
        return {'compiler':'greedy','ez_policy':'adaptive','atom_count':4,'layout':'row','seed':7,
                'gates':[{'id':f'g{i}','gate_type':kind,'qubit_ids':[f'Q{i%4:03d}'],'parameters':[],
                          'column':i//4} for i,kind in enumerate(kinds)]}
    mixed=json.loads(Path('configs/workbench/m4_parallel.json').read_text())|{'ez_policy':'adaptive','compiler':'greedy'}
    cases={'four-h':singles(['H']*4),'h-x-groups':singles(['H','X','H','X']),
           'two-layers':singles(['H']*4+['T']*4),'mixed':mixed,'budget-failure':mixed|{'max_decisions':1}}
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
        assert result['status']==('stalled' if name=='budget-failure' else 'completed')
        kinds={g['id']:g['gate_type'] for g in result['input']['gates']}
        effects=[o for o in result['recording']['operations'] if o['kind'] in {'raman_rotation','entangling_pulse'}]
        for i,a in enumerate(effects):
            for b in effects[i+1:]:
                if max(a['start'],b['start'])<min(a['end'],b['end']):
                    assert kinds[a['gate_id']]==kinds[b['gate_id']]
        if name=='four-h':assert state.time_us==1
        if name in {'h-x-groups','two-layers'}:assert state.time_us==2
        row={'case':name,'status':result['status'],'wall_us':state.time_us,
             'gates':state.metrics()['completed_gate_count'],'effects':[(o['gate_id'],kinds[o['gate_id']],o['start'],o['end']) for o in effects]}
        summaries.append(row);print(canonical_json(row),flush=True)
    (root/'acceptance.json').write_text(canonical_json(summaries),encoding='utf-8')


if __name__=='__main__':main()
