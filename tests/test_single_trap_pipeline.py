import json
from dataclasses import replace
from pathlib import Path
import pytest
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate, HolderType, Position2D, MobileCellIndex
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent, OperationType as K, EndDisposition
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.motion.single_trap import SingleTrapCompiler
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.motion.compiler import exact_validate
from neutral_atom_env.simulation.pipeline import Platform, initialize, run_circuit, load_circuit
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.planning.eager_baseline import EagerBaseline
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder


def inputs(pairs=((0, 1),)):
    circuit = PhysicalCircuit(tuple(PhysicalGate(f'G{i:03d}', 'CZ', (f'Q{a:03d}', f'Q{b:03d}')) for i,(a,b) in enumerate(pairs)))
    return circuit, Platform.load('configs/platforms/single_trap.json'), {'Q000':'S000','Q001':'S001','Q002':'S002','Q003':'S003','Q004':'S004','Q005':'S005','Q006':'S006','Q007':'S007'}


def schedule(state, compiler=None, observe=None):
    return EagerScheduler(state, policy=EagerBaseline(compiler or SingleTrapCompiler())).run(observe)


@pytest.fixture(scope='module')
def completed_pair():
    state = initialize(*inputs())
    snapshots = [state.snapshot()]
    recorder = VisualRecorder(state)
    def observe(s,e):
        snapshots.append(s.snapshot())
        recorder.observe(s,e)
    assert schedule(state, observe=observe).status == 'completed'
    return state, snapshots, recorder


def test_one_trap_real_handoffs_and_independent_totals(completed_pair):
    final, snapshots, recorder = completed_pair
    initial = SimulationState.restore(snapshots[0])
    assert not initial.hardware.selective_transfer_enabled
    assert final.placement == initial.placement and final.aod == initial.aod
    data = recorder.payload()
    ops = data['operations']
    assert [o['captured'] for o in ops if o['kind']=='aod_load'] == [['Q000'],['Q001'],['Q000']]
    assert [o['captured'] for o in ops if o['kind']=='aod_offload'] == [['Q000'],['Q001'],['Q000']]
    holders = {}
    for frame in data['frames']:
        holders.update({a['id']:a for a in frame['atom_updates']})
        assert sum(a['holder']['holder_type']=='mobile' for a in holders.values()) <= 1
        if frame['gate_status']=='running':
            assert holders['Q000']['holder']['holder_id']=='EZ0'
            assert holders['Q000']['position']=={'x_um':5,'y_um':-35}
            assert holders['Q001']['position']=={'x_um':3,'y_um':-35}
    # Independent path lengths: a 40+45; b 2*(2.5+2.5+10+32.5+.5); empty 2*sqrt(5**2+35**2).
    m = final.metrics()
    assert m['total_atom_distance_um'] == 181
    distance = 181 + 2*(5**2+35**2)**.5
    assert m['total_aod_distance_um'] == pytest.approx(distance)
    assert m['episode_wall_time_us'] == pytest.approx(600+distance/.5+.3)
    assert m['aod_load_count'] == m['aod_offload_count'] == 3
    assert m['incidental_atom_transport_total'] == 0
    assert data['plans'][0]['paths']['Q000'][-1] == {'x_um':5,'y_um':-35}


def test_resume_every_boundary(completed_pair):
    final, snapshots, _ = completed_pair
    origin = initialize(*inputs())
    Executor(origin).submit(SingleTrapCompiler().compile(ExecuteGateBatchIntent({'G000'}), origin))
    # Decode every boundary, and finish from representative transfer/pulse/return boundaries.
    restored = [SimulationState.restore(s) for s in [origin.snapshot(), *snapshots]]
    for s in restored[::8] + [restored[-1]]:
        assert schedule(s).status == 'completed'
        assert s.snapshot() == final.snapshot()


def test_external_inputs_changed_circuit_and_strategy(tmp_path):
    circuit, platform, placement = inputs(((0,5),(5,7),(0,7)))
    path = tmp_path/'circuit.json'
    path.write_text(json.dumps({'gates':[{'id':g.id,'gate_type':g.gate_type,'qubit_ids':g.qubit_ids} for g in circuit.gates]}), encoding='utf-8')
    circuit = load_circuit(path)
    state = initialize(circuit, platform, placement)
    plan = SingleTrapCompiler(anchor_order='reverse').compile(ExecuteGateBatchIntent({'G000'}), state)
    assert next(op for op in plan.operations if op.operation_type==K.AOD_LOAD).transfer_bindings[0].atom_id=='Q005'
    result, final, _ = run_circuit(circuit, platform, placement, compiler=SingleTrapCompiler(anchor_order='reverse'))
    assert result.status=='completed' and final.metrics()['completed_gate_count']==3
    assert final.placement==state.placement


@pytest.mark.parametrize('damage', ['cell','missing_binding','phase','duration','resources','origin','prediction'])
def test_generic_validator_rejects_forged_program_atomically(damage):
    state = initialize(*inputs()); before = state.snapshot()
    plan = SingleTrapCompiler().compile(ExecuteGateBatchIntent({'G000'}), state)
    ops = list(plan.operations)
    idx = next(i for i,o in enumerate(ops) if o.operation_type==K.AOD_OFFLOAD)
    if damage=='cell':ops[idx]=replace(ops[idx],transfer_bindings=(replace(ops[idx].transfer_bindings[0],cell=MobileCellIndex(0,1)),))
    elif damage=='missing_binding':ops[idx]=replace(ops[idx],transfer_bindings=())
    elif damage=='phase':ops[idx-1]=replace(ops[idx-1],transfer_phase=None)
    elif damage=='duration':ops[idx]=replace(ops[idx],duration_us=1)
    elif damage=='resources':plan=replace(plan,resources=plan.resources[:-1])
    elif damage=='origin':plan=replace(plan,initial_placement=plan.initial_placement[:-1])
    elif damage=='prediction':plan=replace(plan,predicted_placement=plan.predicted_placement[:-1])
    plan=replace(plan,operations=tuple(ops))
    with pytest.raises(ValidationError):Executor(state).submit(plan)
    assert state.snapshot()==before


def test_general_program_allows_nonreturn_end_without_strategy_template():
    state=initialize(*inputs())
    full=SingleTrapCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
    builder=ProgramBuilder(state,ExecuteGateBatchIntent({'G000'},EndDisposition.KEEP_LOADED))
    for op in full.operations:
        builder.add(op.operation_type,op.label,target=op.target_pose,bindings=op.transfer_bindings,phase=op.transfer_phase)
        if op.operation_type==K.ENTANGLING_PULSE:break
    plan=builder.finish('independent-test-compiler')
    assert plan.predicted_placement!=plan.initial_placement
    executor=Executor(state);executor.submit(plan);executor.run()
    assert state.placement.atom_to_holder['Q000'].holder_id=='EZ0'
    assert len(state.placement.mobile_occupancy)==1
    assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()


@pytest.mark.parametrize('case,code',[('no_site','NO_EZ_PARKING_SITE'),('gate','UNSUPPORTED_GATE'),('array','SINGLE_TRAP_REQUIRED')])
def test_diagnostics_without_phantom_moves(case,code):
    circuit,platform,placement=inputs()
    if case=='no_site':platform=replace(platform,world=replace(platform.world,traps={k:t for k,t in platform.world.traps.items() if not k.startswith('EZ')}))
    elif case=='gate':circuit=PhysicalCircuit((PhysicalGate('G000','MEASURE',('Q000',)),))
    else:platform=replace(platform,aod=replace(platform.aod,columns=2,enabled_columns=None))
    state=initialize(circuit,platform,placement);before=state.snapshot()
    result=schedule(state)
    assert result.status=='stalled' and code in str(result.diagnostics)
    assert state.snapshot()==before


def test_old_schema_and_corrupt_mid_handoff_rejected(completed_pair):
    _,snapshots,_=completed_pair
    saved=next(s for s in snapshots if json.loads(s)['active_plan'] is not None)
    data=json.loads(saved);data['schema_version']=8
    with pytest.raises(ValidationError):SimulationState.restore(json.dumps(data))
    data=json.loads(saved);data['active_plan']['plan']['initial_placement'].pop()
    with pytest.raises(ValidationError):SimulationState.restore(json.dumps(data))


def test_independent_platform_translation_atom_count_and_mapping(tmp_path):
    value=json.loads(Path('configs/platforms/single_trap.json').read_text(encoding='utf-8'))
    # Different world origin, trap positions/names and qubit count, with no scene code changes.
    world=value['world']; world['grid_origin']={'x_um':100,'y_um':10}
    for rect in [world['bounds'],*[z['bounds'] for z in world['zones']]]:
        for p in rect.values():p['x_um']+=100;p['y_um']+=10
    world['traps']=[t for t in world['traps'] if t['id'] in ('S000','S002','S004','EZ1')]
    for t in world['traps']:
        t['position']['x_um']+=100;t['position']['y_um']+=10;t['id']='custom_'+t['id']
    value['aod']['pose']={'x_um':100,'y_um':10}
    path=tmp_path/'platform.json';path.write_text(json.dumps(value),encoding='utf-8')
    circuit=PhysicalCircuit((PhysicalGate('G900','CZ',('Q100','Q900')),))
    placement={'Q100':'custom_S000','Q900':'custom_S004','Q500':'custom_S002'}
    result,final,_=run_circuit(circuit,Platform.load(path),placement)
    assert result.status=='completed' and len(final.atoms)==3
    assert {q:h.holder_id for q,h in final.placement.atom_to_holder.items()}==placement


def test_unknown_qubit_is_rejected_at_input_boundary():
    circuit,platform,placement=inputs(((0,9),))
    with pytest.raises(ValidationError,match='UNKNOWN_QUBIT'):initialize(circuit,platform,placement)
