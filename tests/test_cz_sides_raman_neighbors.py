"""Directional CZ freedom and the inclusive 5 um Raman safety boundary."""
from dataclasses import replace
import pytest
from test_m4 import make,execute
from neutral_atom_env.domain.models import Position2D, HolderRef, HolderType, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.raman import validate_rotation
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.persistent import PersistentTargetCompiler
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.world import PlacementState


@pytest.mark.parametrize('mobile',[False,True])
@pytest.mark.parametrize('separation,allowed',[(4.99,False),(5,True),(5.01,True)])
def test_neighbor_distance_boundary_independent_of_neighbor_holder(mobile,separation,allowed):
    state=make([('H',(0,))],n=2)
    if mobile:
        holders=dict(state.placement.atom_to_holder);holders['Q001']=HolderRef(HolderType.MOBILE,MobileCellIndex(0,0))
        axes=replace(state.aod.configuration(),x_um=(separation,),y_um=(0.,))
        state=replace(state,placement=PlacementState(holders),aod=replace(state.aod.configured(axes),enabled_rows=(True,),enabled_columns=(True,)),slm_enabled=dict(state.slm_enabled)|{'S001':False})
    else:
        traps=dict(state.world.traps);traps['S001']=replace(traps['S001'],position=Position2D(separation,0))
        state=replace(state,world=replace(state.world,traps=traps,grid_spacing_um=.01))
    if allowed:assert validate_rotation(state,'g0').id=='g0'
    else:
        with pytest.raises(ValidationError,match='RAMAN_NEIGHBOR_TOO_CLOSE'):validate_rotation(state,'g0')


def test_greedy_enumerates_all_four_sides_and_reuses_ready_pose():
    state=make([('CZ',(0,1)),('CZ',(0,1))])
    compiler=GreedyCompiler();candidates,_,_=compiler.alternatives('g0',state)
    poses=set()
    for candidate in candidates:
        site=state.world.traps[candidate.site].position
        axes=candidate.plan.intent.target.aod_configuration
        poses.add((round(axes.x_um[0]-site.x_um,6),round(axes.y_um[0]-site.y_um,6)))
    assert poses=={(-2.,0.),(2.,0.),(0.,-2.),(0.,2.)}
    execute(state,min(candidates,key=lambda c:c.cost).plan)
    second=min(compiler.alternatives('g1',state)[0],key=lambda c:c.cost).plan
    assert second.estimated_duration_us==pytest.approx(.3)
    assert [o.operation_type for o in second.operations]==[K.ENTANGLING_PULSE]


def test_moving_neighbor_checked_during_pulse_not_only_move_endpoints():
    state=make([('H',(0,))],n=2)
    axes=replace(state.aod.configuration(),x_um=(-6.,),y_um=(3.,))
    target=TaskTarget((('Q001',HolderRef(HolderType.MOBILE,MobileCellIndex(0,0))),),axes)
    execute(state,PersistentTargetCompiler().compile(TaskIntent('setup',target),state))
    end=replace(axes,x_um=(6.,))
    p=ProgramBuilder(state,TaskIntent('pass',TaskTarget(aod_configuration=end)))
    p.add(K.AOD_MOVE,'Pass at 3 um',target=Position2D(6,3))
    base=p.finish('test-exact-sweep')
    # Both complete-move endpoints are >5 um from Q000, midpoint is 3 um.
    before=state.snapshot()
    with pytest.raises(ValidationError,match='RAMAN_NEIGHBOR_TOO_CLOSE'):
        scheduled_program(base,state,(('g0',11.5),))
    assert state.snapshot()==before
    # A pulse early in the same move is actually separated and remains legal.
    plan=scheduled_program(base,state,(('g0',0),))
    execute(state,plan);assert state.dag.completed
