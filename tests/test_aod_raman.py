"""Stationary AOD addressing, transport exclusion and actual holder replay."""
from dataclasses import replace
import pytest
from test_m4 import make, execute
from neutral_atom_env.domain.models import HolderRef, HolderType as H, MobileCellIndex, Position2D
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.raman import validate_rotation, validate_rotation_sweep
from neutral_atom_strategies.motion.persistent import PersistentTargetCompiler
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.simulation import Executor
from neutral_atom_strategies.scheduling.m4 import fill_raman
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder


def loaded(gates, x=5):
    state=make(gates,n=2)
    axes=replace(state.aod.configuration(),x_um=(float(x),),y_um=(0.,))
    target=TaskTarget((('Q001',HolderRef(H.MOBILE,MobileCellIndex(0,0))),),axes)
    execute(state,PersistentTargetCompiler().compile(TaskIntent('setup',target),state))
    return state


@pytest.mark.parametrize('distance,allowed',[(4.99,False),(5,True),(5.01,True)])
def test_mobile_target_distance_boundary(distance,allowed):
    state=loaded([('T',(1,))],distance)
    if allowed:assert validate_rotation(state,'g0').id=='g0'
    else:
        with pytest.raises(ValidationError,match='RAMAN_NEIGHBOR_TOO_CLOSE'):validate_rotation(state,'g0')


def test_aod_and_slm_same_gate_parallel_without_offload_and_restore():
    state=loaded([('T',(1,)),('T',(0,))])
    candidates,_,_=GreedyCompiler().alternatives('g0',state)
    base=min(candidates,key=lambda c:c.cost).plan
    assert [o.operation_type for o in base.operations]==[K.RAMAN_ROTATION]
    assert base.estimated_duration_us==1 and 'AOD_0' in base.resources
    plan,slots=fill_raman(base,state)
    assert slots==[('g1',0)] and plan.estimated_duration_us==1
    holders=state.placement;recorder=VisualRecorder(state);e=Executor(state);e.submit(plan)
    snapshots=[state.snapshot()]
    while state.event_queue:
        e.step();recorder.observe(state);snapshots.append(state.snapshot())
    assert state.dag.completed and state.placement==holders
    effects=[o for o in recorder.operations if o['kind']=='raman_rotation']
    assert {next(iter(o['target_holders'].values()))['holder_type'] for o in effects}=={'static','mobile'}
    for saved in snapshots:
        resumed=SimulationState.restore(saved);Executor(resumed).run()
        assert resumed.snapshot()==state.snapshot()


def test_aod_target_cannot_overlap_motion():
    state=loaded([('H',(1,))])
    target=Position2D(7.5,0)
    with pytest.raises(ValidationError,match='RAMAN_TARGET_MOVING'):
        validate_rotation_sweep(state,'g0',target)
    axes=replace(state.aod.configuration(),x_um=(7.5,))
    p=ProgramBuilder(state,TaskIntent('move',TaskTarget(aod_configuration=axes)))
    p.add(K.AOD_MOVE,'Move target',target=target)
    before=state.snapshot()
    with pytest.raises(ValidationError):scheduled_program(p.finish('test'),state,(('g0',0),))
    assert state.snapshot()==before


def test_aod_target_cannot_overlap_support_switch():
    from neutral_atom_env.hardware.dynamic_traps import trap_state
    state=loaded([('H',(1,))])
    masks=trap_state(state)
    # Even an unrelated empty SLM switch occupies the shared AOD service lane.
    changed=replace(masks,slm=tuple((k,False if k=='EZ0' else v) for k,v in masks.slm))
    p=ProgramBuilder(state,TaskIntent('switch',TaskTarget(traps=changed)))
    p.add(K.TRAP_SWITCH,'Switch during target pulse',switch_state=changed)
    before=state.snapshot()
    with pytest.raises(ValidationError):scheduled_program(p.finish('test'),state,(('g0',0),))
    assert state.snapshot()==before


def test_cz_pair_separates_loaded_target_then_lights_without_transfer():
    state=make([('CZ',(0,1)),('T',(0,)),('T',(1,)),('CZ',(0,1))])
    compiler=GreedyCompiler()
    execute(state,min(compiler.alternatives('g0',state)[0],key=lambda c:c.cost).plan)
    q=next(iter(state.placement.mobile_occupancy.values()))
    gate='g1' if q=='Q000' else 'g2'
    with pytest.raises(ValidationError,match='RAMAN_NEIGHBOR_TOO_CLOSE'):validate_rotation(state,gate)
    plan=min(compiler.alternatives(gate,state)[0],key=lambda c:c.cost).plan
    assert any(o.operation_type==K.AOD_MOVE for o in plan.operations)
    assert not any(o.operation_type in {K.AOD_LOAD,K.AOD_OFFLOAD} for o in plan.operations)
    execute(state,plan)
    assert state.placement.atom_to_holder[q].holder_type==H.MOBILE
