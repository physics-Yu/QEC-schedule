"""Reproduce ordered-axis experiments or serve the editable comparison UI."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

def main():
    from neutral_atom_experiments.ordered_axis_comparison import demos,run_one,STRATEGIES
    from neutral_atom_app.smt_experiment import isolated_comparison,create_server
    p=argparse.ArgumentParser();p.add_argument('--one',choices=STRATEGIES);p.add_argument('--input')
    p.add_argument('--case',choices=tuple(demos()));p.add_argument('--serve',action='store_true');p.add_argument('--port',type=int,default=8794)
    p.add_argument('--output',default='artifacts/ordered-axis/attempt1');args=p.parse_args()
    module='neutral_atom_experiments.ordered_axis_comparison'
    if args.serve:
        server=create_server(args.output,args.port,experiment_module=module,worker_script='run_ordered_axis_experiment.py')
        print(f'Ordered axes: http://127.0.0.1:{server.server_port}/',flush=True);server.serve_forever();return
    if args.one:
        run_one(json.loads(Path(args.input).read_text(encoding='utf-8')),args.one,args.output);return
    if args.input:
        isolated_comparison(json.loads(Path(args.input).read_text(encoding='utf-8')),args.output,
                            experiment_module=module,worker_script='run_ordered_axis_experiment.py');return
    suite={}
    for key,spec in demos().items():
        if args.case and key!=args.case:continue
        suite[key]=isolated_comparison(spec,Path(args.output)/key,lambda x:print(x,flush=True),
                                      experiment_module=module,worker_script='run_ordered_axis_experiment.py')
    Path(args.output,'suite.json').write_text(json.dumps(suite,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
