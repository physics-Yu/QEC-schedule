"""CZ prediction changes the parking guard at the actual effect boundary."""
from dataclasses import replace
import pytest

from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import (Atom, GateStatus, GridCoord, HolderRef, HolderType,
    MobileCellIndex, PhysicalGate, Position2D, Rectangle, StaticTrap, Zone, ZoneType)
from neutral_atom_env.domain.operations import HardwareConfig, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.hardware.ez_neighbors import next_cz
from neutral_atom_env.motion.greedy import GreedyCompiler
from neutral_atom_env.motion.program import ProgramBuilder, replay_program
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState


def ready_pair(*,successor=True):
    bounds=Rectangle(Position2D(-10,-10),Position2D(25,25))
    points={'EZ0':(0,0),'S1':(15,0),'S2':(10,10),'PARK':(5,0),'SPARE':(20,20)}
    traps={k:StaticTrap(k,GridCoord(x//5,y//5),Position2D(x,y),enabled=k in {'EZ0','S2'})
           for k,(x,y) in points.items()}
    world=WorldState(bounds,traps,(Zone('EZ',ZoneType.ENTANGLEMENT,bounds),))
    gates=[PhysicalGate('g0','CZ',('Q000','Q001'))]
    if successor:gates.append(PhysicalGate('g1','CZ',('Q000','Q002')))
    aod=AODRuntimeState(pose=Position2D(2,0),rows=1,columns=1,enabled_rows=(True,),enabled_columns=(True,))
    holders={'Q000':HolderRef(HolderType.STATIC,'EZ0'),
             'Q001':HolderRef(HolderType.MOBILE,MobileCellIndex(0,0)),
             'Q002':HolderRef(HolderType.STATIC,'S2')}
    return SimulationState(world,PlacementState(holders),{q:Atom(q) for q in holders},aod,
                           DynamicGateDAG(PhysicalCircuit(tuple(gates))),hardware=HardwareConfig())


def builder_for(state):
    return ProgramBuilder(state,TaskIntent('cz-with-suffix',TaskTarget(),
        frozenset(('Q000','Q001')),effect_gate_id='g0',phase='effect'))


def finalize(builder):
    builder.intent=replace(builder.intent,target=TaskTarget(tuple(sorted(builder.state.placement.atom_to_holder.items())),
        builder.state.aod.configuration()))
    return builder.finish('cz-prediction-test')


def test_cz_prediction_releases_successor_and_rejects_old_partner_suffix_without_mutating_live():
    state=ready_pair();before=state.snapshot();p=builder_for(state)
    p.add(K.ENTANGLING_PULSE,'First CZ')
    assert p.state.dag.nodes['g0'].status==GateStatus.COMPLETED
    assert p.state.dag.nodes['g1'].status==GateStatus.READY
    assert next_cz(p.state)['Q000']==('g1','Q002')
    with pytest.raises(ValidationError,match='EZ_NEIGHBOR_OCCUPIED'):
        p.add(K.AOD_MOVE,'Old partner cannot park next door',target=Position2D(5,0))
    assert len(p.operations)==1 and state.snapshot()==before


def test_new_partner_suffix_is_allowed_and_every_serial_boundary_restores():
    state=ready_pair();p=builder_for(state);compiler=GreedyCompiler()
    p.add(K.ENTANGLING_PULSE,'First CZ')
    compiler.move_atom(p,'Q001','S1')
    compiler.move_atom(p,'Q002','PARK')
    plan=finalize(p)
    predicted,_=replay_program(plan,state)
    assert predicted.placement.atom_to_holder['Q002']==HolderRef(HolderType.STATIC,'PARK')
    assert next_cz(predicted)['Q000']==('g1','Q002')
    e=Executor(state);e.submit(plan);snapshots=[state.snapshot()]
    while state.event_queue:e.step();snapshots.append(state.snapshot())
    assert state.dag.nodes['g1'].status==GateStatus.READY
    for snapshot in snapshots:
        restored=SimulationState.restore(snapshot);Executor(restored).run()
        assert restored.snapshot()==state.snapshot()


def test_last_cz_releases_guard_for_unrelated_atom_in_timed_suffix():
    state=ready_pair(successor=False);p=builder_for(state);compiler=GreedyCompiler()
    p.add(K.ENTANGLING_PULSE,'Last CZ')
    assert not next_cz(p.state)
    compiler.move_atom(p,'Q001','S1')
    compiler.move_atom(p,'Q002','PARK')
    plan=finalize(p);Executor(state).submit(plan);Executor(state).run()
    assert state.placement.atom_to_holder['Q002']==HolderRef(HolderType.STATIC,'PARK')
    assert state.dag.completed
    assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()


def test_prediction_cannot_apply_same_cz_twice():
    state=ready_pair();p=builder_for(state);p.add(K.ENTANGLING_PULSE,'First CZ')
    with pytest.raises(ValidationError,match='already completed'):
        p.add(K.ENTANGLING_PULSE,'Duplicate CZ')
