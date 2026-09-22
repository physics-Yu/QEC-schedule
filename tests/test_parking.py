from dataclasses import replace
from itertools import product
import pytest
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.operations import OperationType as K, CaptureBinding
from neutral_atom_env.domain.models import MobileCellIndex
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.dynamic_traps import trap_state, switch_traps
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_experiments.parking_demo import default_input,make_state,run
from neutral_atom_strategies.motion.parking import plan_pickup,PlanningFailure


@pytest.mark.parametrize('strategy',['naive_rowwise','naive_columnwise'])
def test_full_job_protects_spectators_and_replays_from_parked_state(strategy):
    v=default_input();v['strategy']=strategy
    r=run(v);assert r['status']=='completed',r.get('error')
    assert all(r['validation'].values())
    final=NeutralAtomEnv.restore(r['checkpoint']).state
    parked=NeutralAtomEnv.restore(r['pickup_checkpoint']).state
    initial,targets,_=make_state(v)
    for q in targets:
        source=initial.placement.position(q,initial.world,initial.aod)
        p=parked.placement.position(q,parked.world,parked.aod)
        end=final.placement.position(q,final.world,final.aod)
        assert (p.x_um,p.y_um)==(source.x_um+2.5,source.y_um+2.5)
        assert (end.x_um,end.y_um)==(p.x_um+60,p.y_um+30)
    moves=[o for o in r['recording']['operations'] if o['kind']=='aod_move']
    assert all((o['source_axes']['x_um']==o['target_axes']['x_um']) != (o['source_axes']['y_um']==o['target_axes']['y_um']) for o in moves)
    assert not any(o['kind']=='aod_offload' for o in r['recording']['operations'])
    if strategy=='naive_rowwise':
        assert r['pickup']['transfer_events']==2 and r['pickup']['parking_sweeps']==2
        assert r['pickup']['movement_distance_um']==20
        # Shared target column Q001 is retained between captures, not reset/re-aligned.
        assert all(o['source_axes']['x_um'][1]==o['target_axes']['x_um'][1]
                   for o in moves if o['label']=='仅调整不匹配的列')


@pytest.mark.parametrize('strategy',['naive_rowwise','naive_columnwise'])
def test_all_2x2_ternary_masks_and_canonical_endpoint(strategy):
    v=default_input();v.update(rows=2,columns=2,aod_rows=2,aod_columns=2)
    for mask in product((0,1,2),repeat=4):
        v['cells']=[list(mask[:2]),list(mask[2:])]
        state,targets,c=make_state(v);before=state.snapshot()
        p=plan_pickup(state,targets,c,strategy)
        assert not isinstance(p,PlanningFailure),(mask,p)
        assert state.snapshot()==before
        assert set(p.atom_to_tone_mapping)==set(targets)
        for q,cell in p.atom_to_tone_mapping.items():
            pos=state.placement.position(q,state.world,state.aod);out=p.final_aod_state.position(cell)
            assert (out.x_um,out.y_um)==(pos.x_um+2.5,pos.y_um+2.5)
        if not targets:assert not p.operations and p.duration_us==0


@pytest.mark.parametrize('damage,code',[(dict(epsilon_x_um=.5),'PARKING_GEOMETRY'),(dict(aod_rows=1),'AXIS_CAPACITY'),(dict(strategy='unknown'),'STRATEGY_NOT_IMPLEMENTED')])
def test_constructive_failures_are_explicit_and_read_only(damage,code):
    v=default_input()|damage;state,targets,c=make_state(v);before=state.snapshot()
    p=plan_pickup(state,targets,c,v['strategy'])
    assert isinstance(p,PlanningFailure) and p.code==code
    assert state.snapshot()==before


def test_mid_segment_obstacle_rejected_and_no_optimizer_fallback():
    # Rowwise now leaves in Y first. Obstacle lies inside that departure sweep.
    v=default_input();v.update(obstacles=[[0,5]],epsilon_y_um=7.5)
    state,targets,c=make_state(v);before=state.snapshot();p=plan_pickup(state,targets,c)
    assert isinstance(p,PlanningFailure) and p.code in {'PATH_BLOCKED','ACTIVE_TRAP_SWEEP'}
    assert state.snapshot()==before


def test_incremental_capture_rejects_missing_actual_intersection():
    state,targets,c=make_state(default_input());p=plan_pickup(state,targets,c)
    env=NeutralAtomEnv(state);env.submit(p.plan);env.run()
    # Additional capture is explicit capability, not an exemption from closure.
    start,_,_=make_state(default_input())
    assert get_backend(start.hardware).capture_closure(start,start.aod.pose)
    from neutral_atom_env.program.builder import apply_operation
    work=start
    for op in p.operations:
        if op.operation_type==K.AOD_RECAPTURE:
            with pytest.raises(ValidationError,match='CAPTURE_CHANGED'):
                apply_operation(work,replace(op,transfer_bindings=op.transfer_bindings[:1]),None)
            with pytest.raises(ValidationError,match='SELECTIVE_TRANSFER_UNSUPPORTED'):
                apply_operation(replace(work,hardware=replace(work.hardware,selective_transfer_enabled=False)),op,None)
            break
        work=apply_operation(work,op,None)
    else:pytest.fail('Expected incremental transfer')
    with pytest.raises(ValidationError,match='HOLDER_SUPPORT_DISABLED'):
        switch_traps(env.state,replace(trap_state(env.state),rows=(False,)*env.state.aod.rows))


def test_loaded_entry_rejected_and_empty_selection_no_op():
    state,targets,c=make_state(default_input());p=plan_pickup(state,targets,c);env=NeutralAtomEnv(state);env.submit(p.plan);env.run()
    fail=plan_pickup(env.state,targets,c);assert fail.code=='AOD_ENTRY_LOADED'
    assert plan_pickup(env.state,[],c).operations==()


def test_world_bounds_and_three_group_checkerboard():
    from neutral_atom_env.domain.models import Position2D, Rectangle
    state,targets,c=make_state(default_input())
    bounds=Rectangle(Position2D(-20,-20),Position2D(21,11))
    world=replace(state.world,bounds=bounds,zones=tuple(replace(z,bounds=bounds) for z in state.world.zones))
    state=replace(state,world=world)
    before=state.snapshot();failure=plan_pickup(state,targets,c)
    assert isinstance(failure,PlanningFailure) and failure.code=='AOD_OUTSIDE_WORLD'
    assert state.snapshot()==before
    v=default_input();v.update(rows=3,columns=3,aod_rows=3,aod_columns=3,
        cells=[[2,1,2],[1,2,1],[2,1,2]])
    for strategy in ('naive_rowwise','naive_columnwise'):
        state,targets,c=make_state(v);p=plan_pickup(state,targets,c,strategy)
        assert not isinstance(p,PlanningFailure),p
        assert p.transfer_events==3 and len(p.atom_to_tone_mapping)==5
        env=NeutralAtomEnv(state);env.submit(p.plan);env.run()
        for q,h in state.placement.atom_to_holder.items():
            if q not in targets:assert env.state.placement.atom_to_holder[q]==h


def test_large_editor_preset_and_capacity_limit():
    from neutral_atom_experiments.parking_demo import large_input
    v=large_input();state,targets,config=make_state(v)
    assert config.rows==config.columns==10 and len(state.world.traps)==100
    assert len(targets)==43 and len(state.atoms)==85
    assert state.aod.rows==state.aod.columns==10
    assert all(any(value==2 for value in row) for row in v['cells'])
    assert all(any(row[c]==2 for row in v['cells']) for c in range(10))
    with pytest.raises(ValueError,match='128'):
        make_state(v|dict(aod_rows=12,aod_columns=12))


@pytest.mark.parametrize('strategy',['naive_rowwise','naive_columnwise'])
def test_grouped_execution_keeps_unsplit_operations_and_physical_time(strategy):
    from neutral_atom_env.visualization.recording import VisualRecorder
    from neutral_atom_strategies.motion.parking import plan_collective_transport
    v=default_input()|dict(strategy=strategy);state,targets,c=make_state(v)
    pickup=plan_pickup(state,targets,c,strategy)
    env=NeutralAtomEnv(state);rec=VisualRecorder(state)
    env.submit(pickup.plan);env.run(on_event=rec.observe)
    onward=plan_collective_transport(env.state,v['shift_x_um'],v['shift_y_um'])
    env.submit(onward);env.run(on_event=rec.observe)
    grouped=run(v);assert grouped['status']=='completed'
    old,new=rec.payload()['operations'],grouped['recording']['operations']
    assert len(old)==len(new)
    for a,b in zip(old,new):
        for key in ('kind','label','source_axes','target_axes','moving_atom_ids'):
            assert a.get(key)==b.get(key)
        assert a['start']==pytest.approx(b['start'],abs=1e-8)
        assert a['end']==pytest.approx(b['end'],abs=1e-8)
    final=NeutralAtomEnv.restore(grouped['checkpoint']).state
    assert env.state.placement==final.placement
    assert env.state.aod.configuration()==final.aod.configuration()
    assert env.state.time_us==pytest.approx(final.time_us,abs=1e-8)
