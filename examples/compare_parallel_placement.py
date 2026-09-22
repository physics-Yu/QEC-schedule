"""Run the previous circuits under expanded parallel stable-completion search."""
import argparse,json
from pathlib import Path
from neutral_atom_app.placement_workbench import compare


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['partners-12','grid-16','all'],default='all')
    parser.add_argument('--evaluations',type=int,default=16)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--pool',type=int,default=256)
    args=parser.parse_args()
    for name in ('partners-12','grid-16'):
        if args.case not in {'all',name}:continue
        raw=json.loads(Path(f'configs/placement/{name}.json').read_text(encoding='utf-8'))
        raw.update(evaluations=args.evaluations,proposal_pool=args.pool,workers=args.workers,
                   terminal_mode='stable',compile_timeout_s=180)
        Path(f'configs/placement/{name}-parallel.json').write_text(json.dumps(raw,indent=2)+'\n',encoding='utf-8')
        output=Path('artifacts/free-placement')/(name+'-parallel')
        report=compare(raw,output,lambda p:print(json.dumps(dict(case=name,**p)),flush=True))
        print(json.dumps(dict(case=name,status=report['status'],gain=report['improvement_percent'],
                              wall_seconds=report['wall_seconds'])),flush=True)


if __name__=='__main__':main()
