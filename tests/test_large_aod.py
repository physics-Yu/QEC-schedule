"""Capacity-independent joint transport and future-demand prefetch behavior."""
from dataclasses import replace
import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderRef, HolderType, GateStatus
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.motion.multi_trap import MultiTrapGreedyCompiler
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.motion.scheduled import scheduled_program
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.m3 import initial_terminal
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization.workbench import build_inputs


def make(n,capacity=None,gates=(),layout='row'):
    raw={'compiler':'greedy','ez_policy':'adaptive','aod_traps':capacity or n,
         'atom_count':n,'layout':layout,'seed':7,
         'gates':[{'id':f'g{i}','gate_type':kind,'qubit_ids':[f'Q{q:03d}' for q in qubits],
                   'parameters':[],'column':i} for i,(kind,qubits) in enumerate(gates)]}
    _,c,p,h=build_inputs(raw)
    return initialize(c,p,h,seed=7)


@pytest.mark.parametrize('capacity',[9,36])
def test_full_row_joint_stage_and_terminal_return_use_two_loads(capacity):
    state=make(capacity);before=state.snapshot();terminal=initial_terminal(state)
    compiler=MultiTrapGreedyCompiler(adaptive_sites=True);compiler.check(state)
    destinations={f'Q{i:03d}':f'EZ_{i*10}_30' for i in range(capacity)}
    target=TaskTarget(tuple((q,HolderRef(HolderType.STATIC,s)) for q,s in destinations.items()))
    builder=ProgramBuilder(state,TaskIntent('full-row-stage',target,frozenset(destinations)))
    compiler.transfer_group(builder,destinations,label='Generic row staging')
    assert state.snapshot()==before
    plan=scheduled_program(builder.finish(compiler.id),state)
    e=Executor(state);e.submit(plan);peak=0;loaded=None
    while state.event_queue:
        e.step();peak=max(peak,len(state.placement.mobile_occupancy))
        if len(state.placement.mobile_occupancy)==capacity and state.transfer is None and not state.aod.is_moving:
            loaded=state.snapshot()
    assert peak==capacity and loaded is not None
    assert state.metrics()['aod_load_count']==1 and state.metrics()['aod_offload_count']==1
    assert all(state.placement.atom_to_holder[q].holder_id==site for q,site in destinations.items())
    restored=SimulationState.restore(loaded);Executor(restored).run()
    assert restored.snapshot()==state.snapshot()
    cleanup=compiler.compile(TaskIntent('full-row-return',terminal,frozenset(state.atoms),phase='cleanup'),state)
    assert sum(op.operation_type==K.AOD_LOAD for op in cleanup.operations)==1
    e.submit(scheduled_program(cleanup,state));e.run()
    assert state.metrics()['aod_load_count']==2 and state.metrics()['aod_offload_count']==2
    assert tuple(sorted(state.placement.atom_to_holder.items()))==terminal.holders
    assert state.aod.configuration()==terminal.aod_configuration


def test_future_blocked_cz_operand_is_prefetched_without_executing_its_gate():
    # Q8 is not in a READY CZ, but its later demand shares the source row.
    state=make(9,gates=[('CZ',(0,1)),('CZ',(0,8))]);before=state.snapshot()
    candidates,errors,_=MultiTrapGreedyCompiler(adaptive_sites=True).alternatives('g0',state,site_limit=1)
    joint=[c for c in candidates if '/joint-3/' in c.key]
    assert joint,errors
    plan=joint[0].plan
    group_load=next(op for op in plan.operations if op.operation_type==K.AOD_LOAD and len(op.transfer_bindings)>1)
    assert {b.atom_id for b in group_load.transfer_bindings}=={'Q000','Q001','Q008'}
    assert state.snapshot()==before
    e=Executor(state);e.submit(scheduled_program(plan,state));e.run()
    assert state.dag.nodes['g0'].status==GateStatus.COMPLETED
    assert state.dag.nodes['g1'].status==GateStatus.READY
    assert state.placement.atom_to_holder['Q008'].holder_id.startswith('EZ')


def test_joint_transfer_refuses_nonrigid_shape_and_occupied_destinations():
    state=make(9);compiler=MultiTrapGreedyCompiler();builder=ProgramBuilder(state,
        TaskIntent('invalid-row',TaskTarget((('Q000',HolderRef(HolderType.STATIC,'EZ_0_30')),))))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='JOINT_TRANSFER_SHAPE'):
        compiler.transfer_group(builder,{'Q000':'EZ_0_30','Q001':'EZ_15_30'})
    with pytest.raises(ValidationError,match='OCCUPIED_TASK_TARGET'):
        compiler.transfer_group(builder,{'Q000':'S001'})
    assert state.snapshot()==before and not builder.operations


def test_joint_prefetch_can_stage_only_one_side_of_cross_row_cz():
    state=make(6,capacity=9,gates=[('CZ',(0,4)),('CZ',(0,1))],layout='grid')
    candidates,errors,_=MultiTrapGreedyCompiler(adaptive_sites=True).alternatives('g0',state,site_limit=1)
    joint=[c for c in candidates if '/joint-2/' in c.key]
    assert joint,errors
    operation=next(op for op in joint[0].plan.operations if op.operation_type==K.AOD_LOAD and len(op.transfer_bindings)>1)
    assert {b.atom_id for b in operation.transfer_bindings}=={'Q000','Q001'}
    assert 'Q004' not in {b.atom_id for b in operation.transfer_bindings}
    executor=Executor(state);executor.submit(scheduled_program(joint[0].plan,state));executor.run()
    assert state.dag.nodes['g0'].status==GateStatus.COMPLETED
