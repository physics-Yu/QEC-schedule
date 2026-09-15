from dataclasses import replace
from time import perf_counter

import pytest
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.aod import AODConfiguration as C
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from neutral_atom_experiments.ordered_axis_comparison import demos,make_state
from neutral_atom_experiments.qec_ordered_comparison import demos as qec_demos,make_state as qec_state
from neutral_atom_strategies.motion.axis_hold_routes import axis_hold_routes,settle_axes
from neutral_atom_strategies.scheduling.ordered_greedy import build_batch,realize_batch,new_builder,finish
from neutral_atom_strategies.scheduling.patch_greedy import patch_assignment
from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer
from neutral_atom_env.domain.operations import OperationType as K


def test_arrived_column_can_hold_while_other_column_finishes():
    points=(C((0,15),(-60,)),C((2.5,17.5),(-60,)),
            C((2.5,17.5),(-57.5,)),C((7.5,12.5),(-57.5,)),
            C((7.5,12.5),(-57,)),C((5,10),(-57,)))
    route=settle_axes(points,(0,))
    assert route[-3].x_um==(5,12.5)
    assert route[-2].x_um==(5,12.5)
    assert route[-1].x_um==(5,10)
    assert max(c.x_um[0] for c in route)==5


def test_candidates_include_both_direct_axes_orders_and_unchanged_axes():
    start,target=C((0,15),(-60,-45)),C((5,10),(-57,-48))
    routes=axis_hold_routes(start,target)
    assert (start,C(start.x_um,target.y_um),target) in routes
    assert (start,C(target.x_um,start.y_um),target) in routes
    assert all(a.x_um==b.x_um or a.y_um==b.y_um for r in routes for a,b in zip(r,r[1:]))


def test_backend_rejects_diagonal_and_keeps_order_and_collision_checks():
    state=make_state(demos()['stretch'])
    state=replace(state,hardware=replace(state.hardware,backend='row_column_orthogonal'))
    backend=get_backend(state.hardware);start=state.aod.configuration()
    with pytest.raises(ValidationError,match='ORTHOGONAL_MOVE_REQUIRED'):
        backend.validate_geometry_move(state,start.translated(2.5,2.5))
    # Moving only the last column is valid while all other columns hold.
    target=C(start.x_um[:-1]+(start.x_um[-1]+2.5,),start.y_um)
    backend.validate_geometry_move(state,target)
    assert NeutralAtomEnv.restore(state.snapshot()).state.hardware.backend=='row_column_orthogonal'


@pytest.mark.parametrize('backend',['row_column','row_column_orthogonal'])
def test_qec_first_batch_short_path_is_strategy_fix_on_either_backend(backend):
    spec=qec_demos()['qec_ghz2'];spec['aod_backend']=backend
    env=NeutralAtomEnv(qec_state(spec))
    p=new_builder(env.state);OrderedTransfer().transfer_group(p,patch_assignment(env.state))
    env.submit(finish(p));env.run()
    rotations=tuple(g.id for g in env.state.dag.ready_gates() if g.u_parameters is not None)
    p=new_builder(env.state,rotations);p.add(K.RAMAN_ROTATION,'prepare H',gate_ids=rotations)
    env.submit(finish(p));env.run()
    # Exactly the reported first SMT batch, including other Cartesian payload.
    assignments=(('QEC0025','Q018','Q000',5,-57),('QEC0026','Q004','Q019',10,-48),
                 ('QEC0027','Q001','Q020',10,-62),('QEC0028','Q021','Q006',5,-37),
                 ('QEC0029','Q026','Q009',45,-57),('QEC0030','Q013','Q027',50,-48),
                 ('QEC0031','Q010','Q028',50,-62),('QEC0032','Q029','Q015',45,-37))
    batch=build_batch(env.state,assignments)
    old=realize_batch(env.state,batch,perf_counter()+30,128,[],motion_router='legacy_corridor')
    new=realize_batch(env.state,batch,perf_counter()+30,128,[],motion_router='axis_hold')
    assert new.estimated_duration_us < old.estimated_duration_us
    config=batch.pickup;loaded=False;track=[]
    cell=next(b.cell for b in batch.bindings if b.atom_id=='Q000')
    for op in new.operations:
        if op.operation_type==K.AOD_LOAD:loaded=True;track=[config.position(cell)]
        if op.operation_type==K.ENTANGLING_PULSE:break
        if op.operation_type==K.AOD_MOVE:
            config=op.target_configuration
            if loaded:track.append(config.position(cell))
    assert [(p.x_um,p.y_um) for p in track]==[(0,-60),(0,-57),(5,-57)]
    initial=env.snapshot();env.submit(new);env.run()
    replay=NeutralAtomEnv.restore(initial);replay.submit(new);replay.run()
    assert env.snapshot()==replay.snapshot()
