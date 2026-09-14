"""Actual EZ-off / cross / EZ-on / exact-exit task demonstration (zero gates)."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dataclasses import replace
from neutral_atom_env.domain.models import HolderRef, HolderType as H, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_strategies.motion.persistent import PersistentTargetCompiler
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.platform import initialize
from neutral_atom_env.simulation import Executor
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import run_m4
from neutral_atom_app.visualization.workbench import build_inputs
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.replay.serializer import canonical_json


def main():
    output=Path('artifacts/ez-switch-demo');output.mkdir(exist_ok=True)
    (output/'verification.json').unlink(missing_ok=True)
    raw={'compiler':'greedy','atom_count':4,'layout':'row','seed':7,'gates':[]}
    value,circuit,platform,placement=build_inputs(raw)
    state=initialize(circuit,platform,placement,seed=7);terminal=initial_terminal(state)
    recorder=VisualRecorder(state);executor=Executor(state)
    def execute(plan):
        executor.submit(plan)
        while state.event_queue:recorder.observe(state,executor.step())
    prep=TaskTarget((('Q000',HolderRef(H.MOBILE,MobileCellIndex(0,0))),),
                    replace(state.aod.configuration(),x_um=(0.,),y_um=(-35.,)))
    execute(PersistentTargetCompiler().compile(TaskIntent('prepare-crossing',prep),state))
    target=TaskTarget(aod_configuration=replace(state.aod.configuration(),x_um=(10.,)))
    baseline=PersistentTargetCompiler().compile(TaskIntent('detour',target),state)
    crossing=GreedyCompiler().compile(TaskIntent('cross-dark-ez',target),state)
    execute(crossing)
    masks=replace(trap_state(state),slm=tuple((k,True if k=='EZ0' else v) for k,v in trap_state(state).slm))
    execute(GreedyCompiler().compile(TaskIntent('enable-empty-ez',TaskTarget(traps=masks)),state))
    result=run_m4(state,terminal=terminal,on_event=recorder.observe)
    assert result.status=='completed'
    for name,data in [('input',value),('terminal',terminal),('recording',recorder.payload()),
        ('result',{'status':result.status,'metrics':state.metrics(),'crossing_us':crossing.estimated_duration_us,
                   'preserve_supports_detour_us':baseline.estimated_duration_us})]:
        (output/f'{name}.json').write_text(canonical_json(data),encoding='utf-8')
    (output/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
    recorder.write(output/'index.html')
    print(json.dumps({'crossing_us':crossing.estimated_duration_us,'detour_us':baseline.estimated_duration_us,
                      'status':result.status,'operations':len(recorder.operations)}))


if __name__=='__main__':main()
