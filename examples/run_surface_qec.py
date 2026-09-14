"""Reproducible physical GHZ2 syndrome experiment with editable input export."""
import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


def main():
    from neutral_atom_env.experiments.surface_qec import experiment_input
    from neutral_atom_env.visualization.workbench import compile_input
    from neutral_atom_env.visualization.viewer import write_html
    from neutral_atom_env.replay.serializer import canonical_json
    parser=argparse.ArgumentParser()
    parser.add_argument('--input')
    parser.add_argument('--output',default='artifacts/surface-qec-ghz2')
    parser.add_argument('--fault',choices=['none','X','Y','Z'],default='Y')
    parser.add_argument('--qubit',default='Q000')
    parser.add_argument('--seed',type=int,default=7)
    args=parser.parse_args()
    value=json.loads(Path(args.input).read_text(encoding='utf-8')) if args.input else experiment_input(
        None if args.fault=='none' else {'pauli':args.fault,'qubit_id':args.qubit})
    value['seed']=args.seed
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    (output/'input.json').write_text(canonical_json(value),encoding='utf-8')
    started=perf_counter();last=[-1]
    def progress(info):
        if info['completed_gates']!=last[0]:
            last[0]=info['completed_gates']
            info=info|{'wall_seconds':round(perf_counter()-started,2)}
            (output/'progress.json').write_text(canonical_json(info),encoding='utf-8')
            print(canonical_json(info),flush=True)
    result,state=compile_input(value,progress=progress)
    for key in ('input','recording','diagnostics','decision_log','candidate_rejections','run_options','qec_result','failure_report'):
        if key in result:(output/f'{key}.json').write_text(canonical_json(result[key]),encoding='utf-8')
    (output/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
    metrics=state.metrics()|{'status':result['status'],'compile_seconds':perf_counter()-started}
    (output/'metrics.json').write_text(canonical_json(metrics),encoding='utf-8')
    write_html(result['recording'],output/'index.html')
    print(canonical_json({'metrics':metrics,'qec_result':result.get('qec_result'),'diagnostics':result['diagnostics']}),flush=True)
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
