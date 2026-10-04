"""Full-state independent device contracts, real commits and negative geometry."""
import json
from dataclasses import replace
import pytest
from neutral_atom_env.circuit import DynamicGateDAG,PhysicalCircuit
from neutral_atom_env.domain.models import Atom,HolderRef,HolderType as H,MobileCellIndex as C,Position2D as P,Rectangle,StaticTrap,GridCoord,Zone,ZoneType,PhysicalGate
from neutral_atom_env.domain.operations import Operation,OperationInterval,OperationType as K,TaskIntent,TaskTarget,CaptureBinding,HardwareConfig
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import WorldState,PlacementState,AODRuntimeState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.hardware.multi_aod import backend_for,with_aod
from neutral_atom_env.program.scheduled import build_scheduled_program
from neutral_atom_env.program.binding import exact_validate
from neutral_atom_env.quantum.stabilizer import StabilizerState


def dual_state(*,mobile=True,gates=(),points=None,columns=1,tracked=False):
    bounds=Rectangle(P(0,0),P(200,100))
    zones=(Zone('MZ',ZoneType.MEASUREMENT,Rectangle(P(0,0),P(200,30))),
           Zone('compute',ZoneType.ENTANGLEMENT,Rectangle(P(0,30),P(200,100))))
    points=points or {'Q000':P(20,50),'Q001':P(120,50)}
    traps={} if mobile else {q:StaticTrap(q,GridCoord(round(p.x_um/5),round(p.y_um/5)),p) for q,p in points.items()}
    world=WorldState(bounds,traps,zones)
    aod=AODRuntimeState(pose=P(20,50),rows=1,columns=columns,spacing_um=5,
        enabled_rows=(mobile,),enabled_columns=(mobile,)*columns,envelope=Rectangle(P(0,0),P(80,100)))
    magic=AODRuntimeState(pose=P(120,50),rows=1,columns=1,
        enabled_rows=(mobile,),enabled_columns=(mobile,),aod_id='AOD_MAGIC',envelope=Rectangle(P(100,0),P(200,100)))
    holders={q:HolderRef(H.STATIC,q) for q in points}
    if mobile:
        holders={'Q000':HolderRef(H.MOBILE,C(0,0)),'Q001':HolderRef(H.MOBILE,C(0,0,'AOD_MAGIC'))}
        if columns>1: holders['Q002']=HolderRef(H.MOBILE,C(0,1));points=dict(points,Q002=P(25,50))
    return SimulationState(world,PlacementState(holders),{q:Atom(q) for q in points},aod,
        DynamicGateDAG(PhysicalCircuit(tuple(gates))),hardware=HardwareConfig(ez_neighbor_guard_enabled=False,interaction_distance_um=6),
        aods={'AOD_0':aod,'AOD_MAGIC':magic},quantum_state=StabilizerState.zero(tuple(points)) if tracked else None)


def move_program(state,targets):
    ops=[];spans=[]
    for index,(key,target) in enumerate(targets):
        duration=backend_for(state,key).move_duration(state.aods[key],target,state.hardware)
        op=Operation(f'op{index:02d}',K.AOD_MOVE,'Independent movement',duration,target_pose=target,aod_id=key)
        ops.append(op);spans.append(OperationInterval(op.id,0,duration,(),()))
    return build_scheduled_program(state,TaskIntent('dual-move',TaskTarget(),frozenset(state.atoms),phase='program'),ops,spans)


def test_same_cell_indices_on_distinct_devices_have_distinct_holders():
    state=dual_state()
    assert len(state.placement.mobile_occupancy)==2
    assert state.placement.position('Q000',state.world,state.aods)==P(20,50)
    assert state.placement.position('Q001',state.world,state.aods)==P(120,50)
    with pytest.raises(ValidationError,match='UNKNOWN_MOBILE_CELL'):
        state.placement.position('Q001',state.world,state.aod)
    with pytest.raises(ValidationError,match='UNKNOWN_AOD'):
        replace(state,placement=PlacementState(dict(state.placement.atom_to_holder,Q001=HolderRef(H.MOBILE,C(0,0,'unknown')))))


def test_public_observation_exposes_both_devices_without_quantum_or_rng():
    from neutral_atom_env.environment import NeutralAtomEnv
    state=dual_state();env=NeutralAtomEnv(state);before=state.snapshot();view=env.observe()
    assert view.positions=={'Q000':P(20,50),'Q001':P(120,50)}
    assert dict(view.aods)==dict(state.aods)
    assert dict(view.configurations_by_aod)=={key:a.configuration() for key,a in state.aods.items()}
    assert not hasattr(view,'quantum_state') and not hasattr(view,'rng_state')
    assert state.snapshot()==before and env.fork().snapshot()==before


def test_two_move_lanes_commit_simultaneously_and_restore_every_boundary():
    state=dual_state();initial=state.snapshot()
    plan=move_program(state,(('AOD_0',P(40,50)),('AOD_MAGIC',P(150,50))))
    assert plan.operation_intervals[0].resources==('AOD_0','atom:Q000')
    assert plan.operation_intervals[1].resources==('AOD_MAGIC','atom:Q001')
    executor=Executor(state);executor.submit(plan);overlap=False
    while state.event_queue:
        executor.step()
        restored=SimulationState.restore(state.snapshot());assert restored.snapshot()==state.snapshot()
        overlap|=all(a.is_moving for a in state.aods.values())
    assert overlap and state.time_us==60
    assert state.aods['AOD_0'].pose==P(40,50) and state.aods['AOD_MAGIC'].pose==P(150,50)
    assert dict(state.physical_metrics.aod_busy_by_device)=={'AOD_0':40,'AOD_MAGIC':60}
    assert state.metrics()['aod_utilization']==pytest.approx(5/6)
    replay=SimulationState.restore(initial);Executor(replay).submit(plan);Executor(replay).run()
    assert replay.snapshot()==state.snapshot()


def test_same_device_overlap_is_rejected_without_mutating_input():
    state=dual_state();before=state.snapshot()
    with pytest.raises(ValidationError,match='Resource interval conflict'):
        move_program(state,(('AOD_0',P(40,50)),('AOD_0',P(50,50))))
    assert state.snapshot()==before


def test_fixed_envelopes_reject_cross_device_collision_and_out_of_bounds():
    state=dual_state();before=state.snapshot()
    with pytest.raises(ValidationError,match='AOD_ENVELOPE_EXCEEDED'):
        backend_for(state).move(state,P(120,50))
    with pytest.raises(ValidationError,match='AOD_ENVELOPES_OVERLAP'):
        with_aod(state,'AOD_MAGIC',replace(state.aods['AOD_MAGIC'],envelope=Rectangle(P(20,0),P(200,100))))
    assert state.snapshot()==before


def test_same_lane_loaded_atoms_do_not_block_rigid_translation_through_old_positions():
    state=dual_state(columns=2)
    end=backend_for(state).move(state,P(35,50))
    assert end.placement.position('Q000',end.world,end.aods)==P(35,50)
    assert end.placement.position('Q002',end.world,end.aods)==P(40,50)
    assert end.placement.position('Q001',end.world,end.aods)==P(120,50)


def test_empty_active_trap_sweep_checks_every_static_atom():
    state=dual_state(mobile=False,points={'Q000':P(20,50),'Q001':P(120,50)})
    aod=replace(state.aod,pose=P(10,50),enabled_rows=(True,),enabled_columns=(True,))
    state=with_aod(state,'AOD_0',aod);before=state.snapshot()
    with pytest.raises(ValidationError,match='ACTIVE_TRAP_SWEEP'):
        backend_for(state).move(state,P(30,50))
    assert state.snapshot()==before


def test_changed_secondary_device_origin_and_prediction_are_rejected_atomically():
    state=dual_state();plan=move_program(state,(('AOD_0',P(40,50)),('AOD_MAGIC',P(150,50))))
    changed=with_aod(state,'AOD_MAGIC',replace(state.aods['AOD_MAGIC'],pose=P(125,50)))
    with pytest.raises(ValidationError,match='OUTDATED_STATE'): exact_validate(plan,changed)
    invalid=replace(plan,predicted_aods=tuple((key,replace(a,pose=P(130,50)) if key=='AOD_MAGIC' else a) for key,a in plan.predicted_aods))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='multi-device terminal prediction'): Executor(state).submit(invalid)
    assert state.snapshot()==before and not state.event_queue


def test_committed_secondary_lane_tamper_is_detected_by_runtime_restore():
    state=dual_state();Executor(state).submit(move_program(state,(('AOD_0',P(40,50)),('AOD_MAGIC',P(150,50)))))
    Executor(state).run();value=json.loads(state.snapshot())
    value['aods']['AOD_MAGIC']['pose']['x_um']=145
    with pytest.raises(ValidationError,match='Program runtime mismatch: aods'):
        SimulationState.restore(json.dumps(value))


def test_readout_in_compute_and_during_foreign_move_is_rejected():
    gates=(PhysicalGate('m','MEASURE',('Q000',)),)
    state=dual_state(gates=gates,tracked=True)
    op=Operation('op00',K.MEASUREMENT,'MZ readout',500,gate_id='m')
    intent=TaskIntent('readout',TaskTarget(),phase='program',gate_effects=frozenset({'m'}))
    with pytest.raises(ValidationError,match='READOUT_ZONE_UNAVAILABLE'):
        build_scheduled_program(state,intent,(op,),(OperationInterval(op.id,0,500,(),()),))


def test_mz_parallel_reset_h_measure_are_actual_committed_reports():
    points={'Q000':P(20,20),'Q001':P(120,20)}
    gates=tuple(PhysicalGate(f'{kind}{q}',kind,(q,)) for kind in ('RESET','H','MEASURE','RESET') for q in points)
    # Distinct reset epochs need distinct IDs.
    gates=tuple(replace(g,id=f'g{i}') for i,g in enumerate(gates))
    state=dual_state(mobile=False,gates=gates,points=points,tracked=True)
    state=replace(state,hardware=replace(state.hardware,raman_zone_types=('measurement','entanglement')))
    groups=((K.RESET,100,('g0','g1')),(K.RAMAN_ROTATION,1,('g2','g3')),(K.MEASUREMENT,500,('g4','g5')),(K.RESET,100,('g6','g7')))
    ops=[];spans=[];time=0
    for index,(kind,duration,ids) in enumerate(groups):
        op=Operation(f'op{index:02d}',kind,'Actual ideal branch',duration,gate_ids=ids,depends_on=(f'op{index-1:02d}',) if index else ())
        ops.append(op);spans.append(OperationInterval(op.id,time,time+duration,(),()));time+=duration
    intent=TaskIntent('MZ-epoch',TaskTarget(),phase='program',gate_effects=frozenset(g.id for g in gates))
    plan=build_scheduled_program(state,intent,ops,spans);Executor(state).submit(plan);Executor(state).run()
    assert set(state.measurement_results)=={'g4','g5'}
    assert all(not a.measured for a in state.atoms.values())
    assert state.quantum_state==StabilizerState.zero(tuple(points))
    assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()


def test_global_cz_includes_right_side_spectator_pairs():
    points={'Q000':P(20,50),'Q002':P(25,50),'Q001':P(120,50),'Q003':P(125,50)}
    gates=(PhysicalGate('left','CZ',('Q000','Q002')),PhysicalGate('right','CZ',('Q001','Q003')))
    state=dual_state(mobile=False,points=points,gates=gates,tracked=True)
    with pytest.raises(ValidationError,match='UNINTENDED_PAIR'): backend_for(state).validate_pulse_batch(state,('left',))
    assert backend_for(state).validate_pulse_batch(state,('left','right'))==frozenset({('Q000','Q002'),('Q001','Q003')})
    moving=with_aod(state,'AOD_MAGIC',replace(state.aods['AOD_MAGIC'],is_moving=True))
    with pytest.raises(ValidationError,match='AOD_MOVING'): backend_for(moving).validate_pulse_batch(moving,('left','right'))


def test_two_mobile_raman_targets_batch_locks_both_real_devices():
    gates=(PhysicalGate('h0','H',('Q000',)),PhysicalGate('h1','H',('Q001',)))
    state=dual_state(gates=gates,tracked=True)
    op=Operation('op00',K.RAMAN_ROTATION,'Both real devices',1,gate_ids=('h0','h1'))
    plan=build_scheduled_program(state,TaskIntent('mobile-H',TaskTarget(),phase='program',gate_effects=frozenset({'h0','h1'})),(op,),(OperationInterval('op00',0,1,(),()),))
    assert set(plan.operation_intervals[0].resources)>={'AOD_0','AOD_MAGIC','atom:Q000','atom:Q001'}
    Executor(state).submit(plan);Executor(state).run()
    assert state.dag.completed and state.time_us==1


def test_two_concurrent_handoffs_merge_only_their_actual_slm_deltas():
    state=dual_state(mobile=False,points={'Q000':P(20,20),'Q001':P(120,20)})
    state=with_aod(state,'AOD_0',replace(state.aod,pose=P(20,20)))
    state=with_aod(state,'AOD_MAGIC',replace(state.aods['AOD_MAGIC'],pose=P(120,20)))
    traps=dict(state.world.traps)
    for name,p in (('D0',P(25,45)),('D1',P(130,50))):
        traps[name]=StaticTrap(name,GridCoord(round(p.x_um/5),round(p.y_um/5)),p,False)
    state=replace(state,world=replace(state.world,traps=traps),slm_enabled={key:t.enabled for key,t in traps.items()})
    ops=[];spans=[];targets={}
    for key,q,destination in (('AOD_0','Q000','D0'),('AOD_MAGIC','Q001','D1')):
        time=0.;parent=()
        source=CaptureBinding(q,C(0,0,key),q)
        out=CaptureBinding(q,C(0,0,key),destination)
        target=traps[destination].position
        duration=backend_for(state,key).move_duration(state.aods[key],target,state.hardware)
        for kind,duration,target_pose,bindings,phase in ((K.AOD_LOAD,100,None,(source,),None),
                (K.AOD_MOVE,duration,target,(source,),'depart'),(K.AOD_OFFLOAD,100,None,(out,),None)):
            op=Operation(f'op{len(ops):02d}',kind,'Independent real handoff',duration,target_pose=target_pose,
                transfer_bindings=bindings,transfer_phase=phase,depends_on=parent,aod_id=key)
            ops.append(op);spans.append(OperationInterval(op.id,time,time+duration,(),()));time+=duration;parent=(op.id,)
        targets[q]=HolderRef(H.STATIC,destination)
    initial=state.snapshot()
    plan=build_scheduled_program(state,TaskIntent('two-actual-transfers',TaskTarget(tuple(targets.items())),frozenset(state.atoms),phase='program'),ops,spans)
    Executor(state).submit(plan);overlap=False
    while state.event_queue:
        Executor(state).step();overlap|=len(state.transfers)==2
        assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()
    assert overlap and not state.transfers
    assert state.placement.atom_to_holder==targets
    assert state.slm_enabled=={'Q000':False,'Q001':False,'D0':True,'D1':True}
    assert state.physical_metrics.aod_load_count==2 and state.physical_metrics.aod_offload_count==2
    replay=SimulationState.restore(initial);Executor(replay).submit(plan);Executor(replay).run()
    assert replay.snapshot()==state.snapshot()


def test_valid_mz_readout_cannot_overlap_foreign_device_move():
    gates=(PhysicalGate('m','MEASURE',('Q000',)),)
    state=dual_state(mobile=False,points={'Q000':P(20,20),'Q001':P(120,20)},gates=gates,tracked=True)
    state=with_aod(state,'AOD_MAGIC',replace(state.aods['AOD_MAGIC'],is_moving=True))
    from neutral_atom_env.hardware.readout import validate_readout
    with pytest.raises(ValidationError,match='READOUT_UNSTABLE'):
        validate_readout(state,('m',),K.MEASUREMENT)


def test_global_mask_switch_cannot_race_foreign_offload_support():
    from neutral_atom_env.hardware.dynamic_traps import trap_state
    state=dual_state(mobile=False,points={'Q000':P(20,20),'Q001':P(120,20)})
    state=with_aod(state,'AOD_MAGIC',replace(state.aods['AOD_MAGIC'],pose=P(120,20)))
    binding=CaptureBinding('Q001',C(0,0,'AOD_MAGIC'),'Q001')
    # Pure preparation of an actual loaded support; no live field changes.
    state=backend_for(state,'AOD_MAGIC').load(state,(binding,))
    switch=Operation('op00',K.TRAP_SWITCH,'Primary mask update',1,switch_state=trap_state(state),aod_id='AOD_0')
    offload=Operation('op01',K.AOD_OFFLOAD,'Foreign handoff',100,transfer_bindings=(binding,),aod_id='AOD_MAGIC')
    spans=(OperationInterval('op00',0,1,(),()),OperationInterval('op01',0,100,(),()))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='Resource interval conflict'):
        build_scheduled_program(state,TaskIntent('support-race',TaskTarget(),frozenset(state.atoms),phase='program'),(switch,offload),spans)
    assert state.snapshot()==before
