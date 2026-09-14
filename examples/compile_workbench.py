"""Compile an exported workbench input without the browser/server."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.visualization.workbench import compile_input
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.replay.serializer import canonical_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default='configs/workbench/mixed.json')
    parser.add_argument('--output',default='artifacts/circuit-workbench-demo')
    args=parser.parse_args()
    value=json.loads(Path(args.input).read_text(encoding='utf-8'))
    result,state=compile_input(value)
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    for name,data in [('input',result['input']),('recording',result['recording']),('diagnostics',result['diagnostics'])]:
        (output/(name+'.json')).write_text(canonical_json(data),encoding='utf-8')
    (output/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    write_html(result['recording'],output/'index.html')
    print(canonical_json({'status':result['status'],'metrics':state.metrics(),'operations':len(result['recording']['operations'])}))
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
