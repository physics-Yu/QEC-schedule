"""Full QEC GHZ comparison and editable UI on the ordered-axis backend."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

def main():
    from neutral_atom_experiments.qec_ordered_comparison import demos,run_one,STRATEGIES
    from neutral_atom_app.smt_experiment import isolated_comparison,create_server
    p=argparse.ArgumentParser();p.add_argument('--one',choices=STRATEGIES);p.add_argument('--input')
    p.add_argument('--serve',action='store_true');p.add_argument('--port',type=int,default=8795)
    p.add_argument('--output',default='artifacts/qec-ordered/attempt1');args=p.parse_args()
    module='neutral_atom_experiments.qec_ordered_comparison'
    if args.serve:
        server=create_server(args.output,args.port,experiment_module=module,worker_script=Path(__file__).name,
                             ui_file=ROOT/'src/neutral_atom_app/visualization/qec_ordered_experiment.html')
        print(f'QEC ordered comparison: http://127.0.0.1:{args.port}/',flush=True);server.serve_forever();return
    spec=json.loads(Path(args.input).read_text(encoding='utf-8')) if args.input else demos()['qec_ghz2']
    if args.one:run_one(spec,args.one,args.output);return
    report=isolated_comparison(spec,Path(args.output)/'qec_ghz2',lambda x:print(x,flush=True),
                               experiment_module=module,worker_script=Path(__file__).name)
    Path(args.output,'suite.json').write_text(json.dumps({'qec_ghz2':report},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
