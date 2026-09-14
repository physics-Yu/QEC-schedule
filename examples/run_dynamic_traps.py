"""M3-A: timed empty switching plus one real CZ program and handoff checkpoints."""
import json
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.operations import OperationType as K, ExecuteGateBatchIntent
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_strategies.motion.single_trap import SingleTrapCompiler
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.platform import Platform, load_circuit, initialize
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.visualization.summary import render_summary
from neutral_atom_experiments.testing.renderer import render_layout
from neutral_atom_env.visualization.theme import VisualTheme
from neutral_atom_env.replay.serializer import canonical_json


def build(output='artifacts/m3-dynamic-traps'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    platform=Platform.load('configs/platforms/single_trap.json')
    # A separate, declared empty-support switching fixture, not a changed origin
    # for the standard twelve-gate acceptance (which keeps its input untouched).
    platform=replace(platform,aod=replace(platform.aod,pose=Position2D(-5,0)))
    circuit=PhysicalCircuit(load_circuit('configs/circuits/single_trap.json').gates[:1])
    placement=json.loads(Path('configs/placements/eight_atoms.json').read_text(encoding='utf-8'))
    state=initialize(circuit,platform,placement);intent=ExecuteGateBatchIntent({'G000'})
    origin=state.snapshot();traps=trap_state(state)
    builder=ProgramBuilder(state,intent)
    builder.add(K.TRAP_SWITCH,'Enable empty AOD at clear pose',switch_state=replace(traps,rows=(True,),columns=(True,)))
    builder.add(K.TRAP_SWITCH,'Disable empty AOD before timed reposition',switch_state=traps)
    for op in SingleTrapCompiler().compile(intent,state).operations:
        builder.add(op.operation_type,op.label,target=op.target_pose,bindings=op.transfer_bindings,
                    phase=op.transfer_phase,switch_state=op.switch_state)
    plan=builder.finish('m3-a-switch-acceptance')
    recorder=VisualRecorder(state);executor=Executor(state);executor.submit(plan)
    checkpoints={'initial':origin}
    while state.event_queue:
        event=executor.step();recorder.observe(state,event)
        if state.transfer:
            checkpoints.setdefault(state.transfer.kind.value+'-supported',state.snapshot())
        if event.operation_id:
            op=next(o for o in plan.operations if o.id==event.operation_id)
            if op.operation_type==K.TRAP_SWITCH:
                checkpoints[event.event_type.value+'-'+op.id]=state.snapshot()
    checkpoints['final']=state.snapshot()
    for name,saved in checkpoints.items():
        resumed=SimulationState.restore(saved)
        if name!='initial':
            Executor(resumed).run()
            assert resumed.snapshot()==state.snapshot()
        (output/(name+'.json')).write_text(saved,encoding='utf-8')
    assert state.dag.completed and state.placement==SimulationState.restore(origin).placement
    assert state.metrics()['episode_wall_time_us']==plan.estimated_duration_us
    recorder.write(output/'index.html');recorder.write_json(output/'recording.json')
    (output/'plan.json').write_text(canonical_json(plan),encoding='utf-8')
    (output/'metrics.json').write_text(canonical_json(state.metrics()),encoding='utf-8')
    state.trace.write(output/'trace.jsonl')
    render_summary(recorder.payload()['summary'],output/'timeline.png',VisualTheme.load())
    for name in ('initial','aod_load-supported','aod_offload-supported','final'):
        render_layout(checkpoints[name],output/(name+'.png'),show_aod=True)
    print(f'completed {output.resolve()} | {len(plan.operations)} operations | {state.time_us:.6f} us')


if __name__=='__main__':build()
