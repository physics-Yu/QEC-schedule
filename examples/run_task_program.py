"""Replay workbench input as explicit prepare/effect/cleanup tasks (M3-B)."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.visualization.workbench import build_inputs
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.simulation import Executor
from neutral_atom_env.motion.single_trap import SingleTrapCompiler
from neutral_atom_env.motion.tasks import split_gate_program, TargetTaskCompiler
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent, TaskIntent, TaskTarget
from neutral_atom_env.domain.models import HolderRef, HolderType
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.replay.serializer import canonical_json, primitive


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default='configs/workbench/mixed.json')
    parser.add_argument('--output',default='artifacts/m3-task-program')
    parser.add_argument('--transport-only',action='store_true',help='Move Q000 to EZ0 without executing any gate')
    args=parser.parse_args()
    value,circuit,platform,placement=build_inputs(json.loads(Path(args.input).read_text(encoding='utf-8')))
    state=initialize(circuit,platform,placement,seed=value['seed'])
    recorder=VisualRecorder(state);executor=Executor(state)
    diagnostics=[];status='completed';plans=[]
    def execute(plan):
        plans.append(plan)
        executor.submit(plan)
        while state.event_queue:
            event=executor.step();recorder.observe(state,event)
    try:
        if args.transport_only:
            intent=TaskIntent('transport-Q000-to-EZ',TaskTarget((('Q000',HolderRef(HolderType.STATIC,'EZ0')),)),
                              frozenset({'Q000'}),allowed_atom_ids=frozenset({'Q000'}))
            execute(TargetTaskCompiler().compile(intent,state))
        else:
            compiler=SingleTrapCompiler(anchor_order=value['anchor_order'])
            while not state.dag.completed:
                full=None
                failures=[]
                for gate in state.dag.ready_gates():
                    try:
                        full=compiler.compile(ExecuteGateBatchIntent({gate.id}),state)
                        break
                    except ValidationError as error:
                        failures.append({'gate_id':gate.id,'violation':primitive(error.violation)})
                if full is None:
                    diagnostics.extend(failures);status='stalled';break
                gate=next(iter(full.intent.gate_ids))
                for recipe in split_gate_program(full,state,task_prefix=f'gate-{gate}'):
                    execute(recipe.compile(state))
    except ValidationError as error:
        status='stalled';diagnostics.append(primitive(error.violation))
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    for name,data in [('input',value),('plans',plans),('recording',recorder.payload()),('diagnostics',diagnostics),
                      ('result',{'status':status,'transport_only':args.transport_only,'metrics':state.metrics()})]:
        (output/f'{name}.json').write_text(canonical_json(data),encoding='utf-8')
    (output/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    recorder.write(output/'index.html')
    print(canonical_json({'status':status,'task_count':len(plans),'operations':len(recorder.operations),'metrics':state.metrics()}))
    return 0 if status=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
