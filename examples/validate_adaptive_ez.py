"""Reproducible diverse circuits, real failure, compiler-free verification."""
import json,random,sys,hashlib
from pathlib import Path
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.visualization.workbench import compile_input
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.replay.serializer import canonical_json
from verify_m3 import verify


def make(n,layout,seed,pairs=None):
    rng=random.Random(seed);gates=[]
    for i in range(10 if pairs is None else len(pairs)):
        pair=pairs[i] if pairs else rng.sample(range(n),2)
        kind='CZ' if pairs or i%3!=1 else 'U3'
        gates.append({'id':f'g{i}','gate_type':kind,'qubit_ids':[f'Q{q:03d}' for q in (pair if kind=='CZ' else pair[:1])],
                      'parameters':[] if kind=='CZ' else [round(rng.uniform(-3,3),4) for _ in range(3)],'column':i})
    return {'compiler':'greedy','ez_policy':'adaptive','atom_count':n,'layout':layout,'seed':seed,'gates':gates}


def main():
    root=Path('artifacts/m4-adaptive-ez');root.mkdir(parents=True,exist_ok=True)
    cases={f'partners-{layout}':make(4,layout,19,[(0,1),(0,2),(2,3),(1,3),(0,1)]) for layout in ('row','grid','shuffled')}
    cases.update({f'random-{n}-{seed}':make(n,layout,seed) for n,layout,seed in [(4,'row',41),(6,'grid',42),(8,'shuffled',43),(16,'grid',44)]})
    source=Path('artifacts/workbench/bea1faa3d00c406fbda9f0cfb0aba541/input.json')
    if source.exists():cases['user-current']=json.loads(source.read_text(encoding='utf-8'))|{'compiler':'greedy','ez_policy':'adaptive'}
    cases['budget-failure']=cases['partners-row']|{'max_decisions':1}
    reports=[]
    for name,value in cases.items():
        directory=root/name;directory.mkdir(parents=True,exist_ok=True)
        (directory/'verification.json').unlink(missing_ok=True)
        started=perf_counter();result,state=compile_input(value)
        for filename,data in [('input',result['input']),('recording',result['recording']),('decisions',result['decision_log']),
                              ('failure_report',result['failure_report']),('diagnostics',result['diagnostics']),
                              ('candidate_rejections',result['candidate_rejections']),('result',{'status':result['status'],'metrics':state.metrics()})]:
            (directory/(filename+'.json')).write_text(canonical_json(data),encoding='utf-8')
        (directory/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
        (directory/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
        write_html(result['recording'],directory/'index.html')
        verify(directory)
        summary={'case':name,'status':result['status'],'gates':len(value['gates']),'wall_us':state.time_us,
                 'compile_and_verify_seconds':round(perf_counter()-started,2),
                 'selected_sites':sorted({d['selected'].split('/')[-1] for d in result['decision_log'] if d['selected']!='explicit-terminal'}),
                 'ez_changes':[c for d in result['decision_log'] for c in d['ez_changes']],
                 'failure_report':result['failure_report']}
        reports.append(summary);print(canonical_json(summary),flush=True)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/neutral_atom_env').rglob('*') if p.suffix in {'.py','.js','.html'}}
    (root/'acceptance.json').write_text(canonical_json({'cases':reports,'source_sha256':hashes}),encoding='utf-8')
    assert all(r['status']==('stalled' if r['case']=='budget-failure' else 'completed') for r in reports)


if __name__=='__main__':main()
