"""Compile free placement versus sequential placement with real replay artifacts."""
import argparse,json
from pathlib import Path
from neutral_atom_app.placement_workbench import default_input,compare

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path,default=Path('artifacts/free-placement/default'))
    parser.add_argument('--evaluations',type=int)
    args=parser.parse_args()
    value=json.loads(args.input.read_text(encoding='utf-8')) if args.input else default_input()
    if args.evaluations is not None:value['evaluations']=args.evaluations
    report=compare(value,args.output,lambda p:print(json.dumps(p,ensure_ascii=False),flush=True))
    print(json.dumps({k:report[k] for k in ['status','search_status','improvement_percent','diagnostics','wall_seconds']},indent=2))
    raise SystemExit(report['status']!='completed')
