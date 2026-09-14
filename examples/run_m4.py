"""M4 greedy acceptance: editable input, local alternatives, exact terminal, real replay."""
import argparse,json,sys
from time import perf_counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_app.visualization.workbench import build_inputs
from neutral_atom_env.platform import initialize
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import run_m4
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.replay.serializer import canonical_json, primitive
from neutral_atom_strategies.motion.family import validate_family


def scale_input(count):
    pairs=[(0,count-1),(0,count//2),(count//2-1,count//2),(count-2,count-1)]
    gates=[]
    for i,(a,b) in enumerate(pairs):
        gates.extend([{'id':f'G{i*2:03d}','gate_type':'CZ','qubit_ids':[f'Q{a:03d}',f'Q{b:03d}'],'parameters':[],'column':i*2},
                      {'id':f'G{i*2+1:03d}','gate_type':'U3','qubit_ids':[f'Q{a:03d}'],'parameters':[.3,.7,-.2],'column':i*2+1}])
    return {'atom_count':count,'layout':'grid','seed':7,'anchor_order':'forward','gates':gates}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',default='configs/workbench/m3_mixed.json')
    parser.add_argument('--compiler',choices=['greedy','resident','returning'],default='greedy')
    parser.add_argument('--atoms',type=int);parser.add_argument('--output',default='artifacts/m4-greedy')
    parser.add_argument('--serial',action='store_true');parser.add_argument('--max-decisions',type=int)
    args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    # A fresh attempt invalidates any previous verification before execution.
    (output/'verification.json').unlink(missing_ok=True)
    (output/'result.json').write_text(canonical_json({'status':'running'}),encoding='utf-8')
    if args.atoms is not None and not 4<=args.atoms<=256:parser.error('Scale acceptance supports 4–256 atoms')
    raw=scale_input(args.atoms) if args.atoms else json.loads(Path(args.input).read_text(encoding='utf-8'))
    value,circuit,platform,placement=build_inputs(raw,max_atoms=256)
    value['compiler']=args.compiler  # Export the actual strategy selected by this run.
    args.max_decisions=args.max_decisions if args.max_decisions is not None else value.get('max_decisions',10000)
    if not 1<=args.max_decisions<=10000:parser.error('--max-decisions must be 1–10000')
    value['max_decisions']=args.max_decisions
    state=initialize(circuit,platform,placement,seed=value['seed']);terminal=initial_terminal(state)
    family=({'id':'m4-adaptive-ez-5um-v1','arbitrary_layout_complete':False,
             'validation':'Each candidate and executed boundary audited; not an M3 constructive-family proof'}
            if value.get('ez_policy')=='adaptive' else validate_family(state))
    recorder=VisualRecorder(state)
    started=perf_counter()
    if args.compiler=='greedy':
        if args.serial:parser.error('--serial applies only to the M3 comparison strategies')
        result=run_m4(state,terminal=terminal,max_decisions=args.max_decisions,on_event=recorder.observe,
                      adaptive_sites=value.get('ez_policy')=='adaptive')
    else:
        from neutral_atom_strategies.scheduling.m3 import run_m3
        result=run_m3(state,compiler=args.compiler,terminal=terminal,overlap=not args.serial,max_decisions=args.max_decisions,on_event=recorder.observe)
    compile_seconds=perf_counter()-started
    from neutral_atom_app.visualization.workbench import failure_report
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    for name,data in [('input',value),('family',family),('result',primitive(result)|{'metrics':state.metrics(),'compile_seconds':compile_seconds}),('terminal',terminal),
                      ('run_options',{'compiler':args.compiler,'overlap':not args.serial,'max_decisions':args.max_decisions}),
                      ('failure_report',failure_report(result,state,value)),
                      ('decisions',getattr(result,'decision_log',())),('recording',recorder.payload()),('diagnostics',result.diagnostics),('candidate_rejections',result.candidate_rejections)]:
        (output/f'{name}.json').write_text(canonical_json(data),encoding='utf-8')
    (output/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
    recorder.write(output/'index.html')
    print(canonical_json({'status':result.status,'decisions':result.decisions,'operations':len(recorder.operations),
                          'overlap_time_us':recorder.payload()['summary']['overlap_time_us'],'metrics':state.metrics(),
                          'diagnostics':[{k:v for k,v in d.items() if k!='holders'} for d in result.diagnostics]}))
    return 0 if result.status=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
