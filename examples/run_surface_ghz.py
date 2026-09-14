"""Reproducible 4-logical surface-code GHZ physical scheduling experiment."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from neutral_atom_env.visualization.workbench import compile_input
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.replay.serializer import canonical_json


def run(strategy,output,*,input_path=None):
    from neutral_atom_env.experiments.surface_ghz import experiment_input
    value=json.loads(Path(input_path).read_text(encoding='utf-8')) if input_path else experiment_input(compiler=strategy)
    value['compiler']=strategy
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    source_start={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((ROOT/'src').rglob('*.py'))}
    (output/'input.json').write_text(canonical_json(value),encoding='utf-8')
    start=perf_counter(); last=[-1]
    with (output/'progress.jsonl').open('w',encoding='utf-8') as stream:
        def progress(p):
            if p['completed_gates']==last[0]:return
            last[0]=p['completed_gates']
            line=canonical_json(p|{'compile_elapsed_s':round(perf_counter()-start,3)})
            stream.write(line+'\n');stream.flush();print(line,flush=True)
        result,state=compile_input(value,progress)
    if result['status']=='completed':
        from neutral_atom_env.experiments.surface_ghz import verify_gate_sequence
        gates={g['id']:g for g in result['input']['gates']}
        effects=[]
        for raw in state.trace.records:
            record=json.loads(raw)
            if record.get('effect_completed'):
                effects.extend(record.get('gate_ids') or [record['gate_id']])
        result['ideal_logical_GHZ_verified']=verify_gate_sequence([gates[g] for g in effects])
        if not result['ideal_logical_GHZ_verified']:
            raise AssertionError('Actual physical effect order failed the independent logical GHZ check')
    for name,data in [('input',result['input']),('recording',result['recording']),
                      ('result',{k:v for k,v in result.items() if k!='recording'}|{'metrics':state.metrics()})]:
        (output/(name+'.json')).write_text(canonical_json(data),encoding='utf-8')
    (output/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
    write_html(result['recording'],output/'index.html')
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT/'src').rglob('*.py'))}
    (output/'source-sha256.json').write_text(canonical_json(hashes),encoding='utf-8')
    (output/'source-at-start.json').write_text(canonical_json(source_start),encoding='utf-8')
    (output/'source-stability.json').write_text(canonical_json({'changed_during_run':source_start!=hashes}),encoding='utf-8')
    print(canonical_json({'status':result['status'],'compile_seconds':result['compile_seconds'],
                          'metrics':state.metrics(),'diagnostics':result['diagnostics']}),flush=True)
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--strategy',choices=['patch_symmetric','patch_greedy','row_symmetric','row_greedy','greedy','critical_path','lookahead'],required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--input')
    a=p.parse_args();raise SystemExit(run(a.strategy,a.output,input_path=a.input))
