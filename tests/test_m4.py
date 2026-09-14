"""Greedy behavior checked through real schedules, Executor and restore."""
import json
from collections import Counter
from dataclasses import replace

import pytest

from neutral_atom_env.domain.models import HolderType as H, HolderRef, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.motion.greedy import GreedyCompiler
from neutral_atom_env.motion.persistent import ResidentCompiler, PersistentTargetCompiler
from neutral_atom_env.motion.scheduled import scheduled_program
from neutral_atom_env.motion.task_validation import validate_target
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.m3 import initial_terminal
from neutral_atom_env.simulation.m4 import run_m4, fill_raman
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.visualization.workbench import build_inputs, compile_input


def make(gates, n=4, layout='row'):
    raw = {'compiler':'greedy', 'atom_count':n, 'layout':layout, 'seed':7, 'gates':[
        {'id':f'g{i}', 'gate_type':kind, 'qubit_ids':[f'Q{q:03d}' for q in qubits],
         'parameters':[], 'column':i} for i,(kind,qubits) in enumerate(gates)]}
    _,c,p,h = build_inputs(raw)
    return initialize(c,p,h,seed=7)


def execute(state, plan, observer=None):
    e = Executor(state); e.submit(plan)
    while state.event_queue:
        event=e.step()
        if observer:observer(state,event)


def test_alternatives_are_pure_distinct_and_cost_includes_handoffs():
    state=make([('CZ',(0,3))]); before=state.snapshot()
    candidates,rejected,cut=GreedyCompiler().alternatives('g0',state)
    assert state.snapshot()==before
    assert len(candidates)==16 and not rejected and not cut
    assert len({c.plan.predicted_placement for c in candidates})==4
    for c in candidates:
        assert c.cost[1]==3
        assert c.cost[0]>300
        assert c.cost[0]==pytest.approx(sum(o.duration_us for o in c.plan.operations))
    best=min(candidates,key=lambda c:c.cost)
    result=run_m4(state,max_decisions=1)
    assert result.decision_log[0]['selected']==best.key
    assert result.status=='stalled' and state.metrics()['completed_gate_count']==1


def test_frontier_selection_uses_physical_cost_instead_of_gate_id():
    state=make([('CZ',(2,3)),('CZ',(0,1))])
    candidates=[]
    for gate in state.dag.ready_gates(): candidates.extend(GreedyCompiler().alternatives(gate.id,state)[0])
    best=min(candidates,key=lambda c:c.cost)
    assert best.gate_id=='g1'
    result=run_m4(state,max_decisions=1)
    assert result.decision_log[0]['selected']==best.key


def test_consecutive_raman_successors_fill_one_move_and_restore_every_event():
    state=make([('CZ',(0,1)),('H',(2,)),('X',(2,)),('Y',(2,)),('H',(3,))])
    terminal=initial_terminal(state); before=state.snapshot()
    base=min(GreedyCompiler().alternatives('g0',state)[0],key=lambda c:c.cost).plan
    plan,slots=fill_raman(base,state)
    assert state.snapshot()==before and len(slots)==4
    times=dict(slots)
    assert times['g2']==pytest.approx(times['g1']+1)
    assert times['g3']==pytest.approx(times['g2']+1)
    assert plan.estimated_duration_us==pytest.approx(base.estimated_duration_us)
    recorder=VisualRecorder(state); e=Executor(state);e.submit(plan)
    snapshots=[state.snapshot()]
    while state.event_queue:
        event=e.step();recorder.observe(state,event);snapshots.append(state.snapshot())
    assert recorder.payload()['summary']['overlap_time_us']==pytest.approx(4)
    assert state.metrics()['completed_gate_count']==5
    final=state.snapshot()
    for saved in snapshots:
        restored=SimulationState.restore(saved);Executor(restored).run()
        assert restored.snapshot()==final
    assert run_m4(state,terminal=terminal).status=='completed'
    validate_target(terminal,state)


def test_loaded_partner_reused_despite_ready_static_raman():
    state=make([('CZ',(0,1)),('CZ',(1,2)),('H',(3,))])
    # Construct a valid persistent state with the next partner resident in EZ1.
    target=TaskTarget((('Q002',HolderRef(H.STATIC,'EZ1')),))
    execute(state,PersistentTargetCompiler().compile(TaskIntent('preposition',target),state))
    execute(state,ResidentCompiler().compile_gate('g0',state))
    assert state.placement.atom_to_holder['Q001'].holder_type==H.MOBILE
    result=run_m4(state,max_decisions=1)
    selected=result.decision_log[0]
    assert selected['selected'].startswith('g1/Q002/') and selected['selected'].endswith('/EZ1')
    assert selected['candidates'][0]['transfers']==0
    assert selected['raman_slots'][0]['gate_id']=='g2'
    assert state.metrics()['completed_gate_count']==3
    assert state.placement.atom_to_holder['Q001'].holder_type==H.MOBILE


@pytest.mark.parametrize('layout',['row','grid','shuffled'])
def test_mixed_circuit_exact_exit_and_once_only_effects(layout):
    state=make([('CZ',(0,1)),('H',(0,)),('CZ',(0,2)),('X',(1,)),('CZ',(1,3))],layout=layout)
    terminal=initial_terminal(state)
    result=run_m4(state)
    assert result.status=='completed',result.diagnostics
    validate_target(terminal,state)
    effects=Counter(json.loads(r)['gate_id'] for r in state.trace.records if json.loads(r).get('effect_completed'))
    assert effects==Counter({f'g{i}':1 for i in range(5)})
    assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()


def test_budget_resume_matches_uninterrupted_and_records_truncation():
    gates=[('CZ',(0,1)),('CZ',(0,1)),('H',(2,))]
    state=make(gates);terminal=initial_terminal(state)
    first=run_m4(state,max_decisions=1,site_limit=1)
    assert first.status=='stalled' and first.decision_log[0]['truncated']==2
    restored=SimulationState.restore(state.snapshot())
    assert run_m4(restored,terminal=terminal,site_limit=1).status=='completed'
    whole=make(gates);assert run_m4(whole,site_limit=1).status=='completed'
    assert restored.snapshot()==whole.snapshot()


def test_shared_validator_rejects_double_booked_raman_and_blocked_successor():
    state=make([('CZ',(0,1)),('H',(2,)),('X',(2,)),('H',(3,))])
    base=min(GreedyCompiler().alternatives('g0',state)[0],key=lambda c:c.cost).plan
    _,slots=fill_raman(base,state);t=slots[0][1]
    before=state.snapshot()
    assert scheduled_program(base,state,(('g1',t),('g3',t))).execution_mode=='scheduled'
    with pytest.raises(ValidationError):scheduled_program(base,state,(('g1',t),('g2',t)))
    with pytest.raises(ValidationError):scheduled_program(base,state,(('g2',t),))
    assert state.snapshot()==before


def test_one_qubit_chain_uses_one_raman_channel_with_fixed_timing():
    state=make([('H',(0,)),('X',(0,)),('Y',(0,)),('Z',(0,))],n=1)
    result=run_m4(state)
    assert result.status=='completed' and result.decisions==1
    assert state.time_us==4 and state.metrics()['aod_load_count']==0
    assert len(result.decision_log[0]['raman_slots'])==3


def test_workbench_changed_gate_type_recompiles_actual_effects():
    value={'compiler':'greedy','atom_count':1,'layout':'grid','seed':7,'raman_duration_us':999,
           'gates':[{'id':'u','gate_type':'T','qubit_ids':['Q000'],'parameters':[],'column':0}]}
    first,_=compile_input(value)
    value['gates'][0]['gate_type']='Z'
    second,_=compile_input(value)
    assert first['status']==second['status']=='completed'
    assert first['recording']['operations'][0]['u_parameters_rad']==[0,0,3.141592653589793/4]
    assert second['recording']['operations'][0]['u_parameters_rad']==[0,0,3.141592653589793]
    assert second['recording']['duration']==1 and second['decision_log']
    assert 'raman_duration_us' not in second['input']


def test_empty_and_invalid_budgets():
    state=make([])
    assert run_m4(state).status=='completed' and state.time_us==0
    for budget in (0,-1,True,1.5):
        with pytest.raises(ValueError):run_m4(state,ready_limit=budget)


def test_exit_can_use_free_future_destination_when_both_ez_sites_occupied():
    state=make([]); terminal=initial_terminal(state)
    target=TaskTarget((('Q000',HolderRef(H.STATIC,'EZ0')),('Q001',HolderRef(H.STATIC,'EZ1')),
                      ('Q002',HolderRef(H.MOBILE,MobileCellIndex(0,0))),('Q003',HolderRef(H.STATIC,'S000'))))
    compiler=PersistentTargetCompiler()
    execute(state,compiler.compile(TaskIntent('packed-residents',target),state))
    assert state.placement.static_occupancy['S000']=='Q003'
    assert run_m4(state,terminal=terminal).status=='completed'
    validate_target(terminal,state)
