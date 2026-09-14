"""M3 C–F: independent effects, physical intervals, persistent targets and recovery."""
import json
from dataclasses import replace
import pytest
from neutral_atom_env.domain.models import HolderType as H, HolderRef, GateStatus, EventType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_strategies.motion.persistent import PersistentTargetCompiler, ResidentCompiler
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_strategies.motion.family import validate_family
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.platform import initialize
from neutral_atom_strategies.scheduling.m3 import run_m3, initial_terminal
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_app.visualization.workbench import build_inputs, compile_input
from neutral_atom_env.visualization.summary import summarize_trace


def make(gates=(),n=4,layout='row'):
    raw={'atom_count':n,'layout':layout,'seed':7,'gates':[
        {'id':str(i),'gate_type':kind,'qubit_ids':[f'Q{q:03d}' for q in qubits],
         'parameters':[],'column':i} for i,(kind,qubits) in enumerate(gates)]}
    _,c,p,h=build_inputs(raw,max_atoms=256)
    return initialize(c,p,h,seed=7)


def execute(state,plan,recorder=None):
    e=Executor(state);e.submit(plan);snapshots=[state.snapshot()]
    while state.event_queue:
        event=e.step();snapshots.append(state.snapshot())
        if recorder:recorder.observe(state,event)
    return snapshots


def overlap_case():
    state=make([('CZ',(0,1)),('H',(0,)),('X',(1,))])
    terminal=initial_terminal(state)
    execute(state,ResidentCompiler().compile_gate('0',state))
    # The former fixture lit Q000 at the 2 um CZ separation. Explicitly move
    # its loaded neighbor out first, then exercise legal Raman/return overlap.
    axes=replace(state.aod.configuration(),x_um=(-2.5,),y_um=(-35.,))
    execute(state,PersistentTargetCompiler().compile(TaskIntent('separate-before-overlap',
        TaskTarget(aod_configuration=axes)),state))
    intent=TaskIntent('return-partner',TaskTarget((('Q001',HolderRef(H.STATIC,'S001')),)),frozenset({'Q001'}),phase='cleanup')
    base=PersistentTargetCompiler().compile(intent,state)
    assert base.operations[0].operation_type==K.AOD_MOVE
    return state,terminal,base,scheduled_program(base,state,(('1',0),))


def effects(state):
    return [json.loads(r)['gate_id'] for r in state.trace.records if json.loads(r).get('effect_completed')]


def test_keep_reuses_loaded_partner_then_new_partner_and_explicit_terminal():
    state=make([('CZ',(0,1)),('CZ',(0,1)),('CZ',(0,2))]);terminal=initial_terminal(state)
    c=ResidentCompiler();execute(state,c.compile_gate('0',state))
    assert state.placement.atom_to_holder['Q000']==HolderRef(H.STATIC,'EZ0')
    assert state.placement.atom_to_holder['Q001'].holder_type==H.MOBILE
    second=c.compile_gate('1',state)
    assert [o.operation_type for o in second.operations]==[K.ENTANGLING_PULSE]
    execute(state,second);execute(state,c.compile_gate('2',state))
    assert state.placement.atom_to_holder['Q002'].holder_type==H.MOBILE
    assert state.placement.atom_to_holder['Q001'].holder_type==H.STATIC
    execute(state,c.compile(TaskIntent('full-exit',terminal,frozenset(state.atoms),phase='cleanup'),state))
    validate_target(terminal,state)
    assert effects(state)==['0','1','2'] and state.dag.completed
    assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()


def test_return_only_new_site_permutation_and_displaced_empty_aod_do_not_touch_dag():
    state=make();dag=state.dag;c=PersistentTargetCompiler()
    target=TaskTarget((('Q000',HolderRef(H.STATIC,'S001')),('Q001',HolderRef(H.STATIC,'S000'))))
    plan=c.compile(TaskIntent('swap',target,frozenset({'Q000','Q001'})),state)
    execute(state,plan);validate_target(target,state)
    assert state.metrics()['aod_load_count']==3 and state.metrics()['aod_offload_count']==3
    assert state.dag==dag and not effects(state)
    axes=replace(state.aod.configuration(),x_um=(12.5,),y_um=(-10,))
    execute(state,c.compile(TaskIntent('empty-pose',TaskTarget(aod_configuration=axes)),state))
    new=TaskTarget((('Q001',HolderRef(H.STATIC,'EZ1')),))
    execute(state,c.compile(TaskIntent('new-site',new,frozenset({'Q001'})),state))
    validate_target(new,state)
    assert state.metrics()['total_atom_distance_um']>0 and state.dag==dag


@pytest.mark.parametrize('layout',['row','grid','shuffled'])
def test_constructive_family_mixed_multi_partner_circuit(layout):
    gates=[('CZ',(0,1)),('CZ',(0,2)),('CZ',(1,3)),('H',(0,)),('X',(3,))]
    state=make(gates,layout=layout);terminal=initial_terminal(state)
    assert validate_family(state)['atom_count']==4
    result=run_m3(state,terminal=terminal)
    assert result.status=='completed',result
    validate_target(terminal,state)
    assert sorted(effects(state))==list('01234')
    assert state.metrics()['raman_busy_time_us']==2


def test_compilers_have_materially_different_constructions_under_same_terminal():
    gates=[('CZ',(0,1)),('CZ',(0,1)),('H',(0,))];states=[]
    for compiler in ('resident','returning'):
        s=make(gates);terminal=initial_terminal(s);rec=VisualRecorder(s)
        result=run_m3(s,compiler=compiler,terminal=terminal,on_event=rec.observe)
        assert result.status=='completed';validate_target(terminal,s)
        assert effects(s)==['0','1','2']
        assert rec.payload()['summary']['resource_busy_us']['RAMAN:Q000']==pytest.approx(1)
        states.append(s)
    resident,returning=states
    assert resident.placement==returning.placement
    assert resident.metrics()['aod_load_count']<returning.metrics()['aod_load_count']
    assert resident.time_us<returning.time_us


def test_parallel_release_and_every_boundary_restores_identical_remaining_execution():
    state,terminal,base,program=overlap_case();rec=VisualRecorder(state)
    start=state.time_us;snapshots=execute(state,program,rec);final=state.snapshot()
    for snapshot in snapshots:
        restored=SimulationState.restore(snapshot);Executor(restored).run()
        assert restored.snapshot()==final
    simultaneous=next(SimulationState.restore(s) for s in snapshots if len(json.loads(s)['active_plan']['running_operations'] if json.loads(s)['active_plan'] else [])==2)
    assert simultaneous.dag.nodes['1'].status==GateStatus.RUNNING
    assert {r.resource_id for r in simultaneous.reservations}>={'AOD_0','RAMAN:Q000'}
    released=next(SimulationState.restore(s) for s in snapshots if json.loads(s)['time_us']==start+1)
    assert released.dag.nodes['1'].status==GateStatus.COMPLETED
    assert released.aod.is_moving and 'RAMAN:Q000' not in {r.resource_id for r in released.reservations}
    assert released.active_plan.running_operations and released.placement.mobile_occupancy
    assert state.time_us==pytest.approx(start+base.estimated_duration_us)
    payload=rec.payload();assert payload['summary']['overlap_time_us']==pytest.approx(1)
    assert any(len(f['active_operations'])==2 and f['movement'] for f in payload['frames'])
    assert summarize_trace(state.trace.records,state.metrics())['resource_busy_us']['RAMAN:Q000']==pytest.approx(1)
    # The scheduler drains a restored program, then completes remaining gates and the common exit.
    full=SimulationState.restore(final);assert run_m3(full,terminal=terminal).status=='completed'
    assert run_m3(simultaneous,terminal=terminal).status=='completed'
    assert simultaneous.snapshot()==full.snapshot()


def test_simultaneous_completion_precedes_start_on_same_resource():
    state,_,base,_=overlap_case()
    # End Raman exactly when the first MOVE ends; the next MOVE can start after both completions.
    move_end=base.operations[0].duration_us
    p=scheduled_program(base,state,(('1',move_end-1),))
    execute(state,p)
    events=[json.loads(r)['event'] for r in state.trace.records]
    at=[e['event_type'] for e in events if e['time_us']==p.initial_time_us+move_end]
    assert at[:2]==['operation_completed','operation_completed'] and at[2]=='operation_started'


@pytest.mark.parametrize('damage',['loaded_raman','transfer_overlap','duplicate_effect','resource','duration','dependencies','target','allowed','effect_set'])
def test_conflicting_or_tampered_program_is_rejected_atomically(damage):
    state,_,base,p=overlap_case();before=state.snapshot()
    with pytest.raises((ValidationError,ValueError)):
        if damage=='loaded_raman':scheduled_program(base,state,(('2',0),))
        elif damage=='transfer_overlap':
            start=sum(o.duration_us for o in base.operations[:-1])
            scheduled_program(base,state,(('2',start),))
        elif damage=='duplicate_effect':scheduled_program(base,state,(('1',0),('1',2)))
        else:
            if damage=='resource':p=replace(p,operation_intervals=tuple(replace(i,resources=()) for i in p.operation_intervals))
            if damage=='duration':p=replace(p,operations=(replace(p.operations[0],duration_us=1),)+p.operations[1:])
            if damage=='dependencies':p=replace(p,operations=(replace(p.operations[0],depends_on=(p.operations[1].id,)),)+p.operations[1:])
            if damage=='target':p=replace(p,intent=replace(p.intent,target=TaskTarget((('Q001',HolderRef(H.STATIC,'S002')),))))
            if damage=='allowed':p=replace(p,intent=replace(p.intent,allowed_atom_ids=frozenset({'Q001'})))
            if damage=='effect_set':p=replace(p,intent=replace(p.intent,gate_effects=frozenset()))
            Executor(state).submit(p)
    assert state.snapshot()==before


@pytest.mark.parametrize('damage',['queue','runtime','resources','origin_dag','live_dag','future_interval','future_motion','schema'])
def test_concurrent_checkpoint_audits_prefix_and_future_schedule(damage):
    state,_,_,p=overlap_case();e=Executor(state);e.submit(p)
    e.step();e.step();e.step();saved=json.loads(state.snapshot())
    if damage=='queue':saved['event_queue']['pending'].pop()
    if damage=='runtime':saved['active_plan']['running_operations'].pop()
    if damage=='resources':saved['reservations'].pop()
    if damage=='live_dag':saved['dag']['1']['status']='completed'
    if damage=='schema':saved['schema_version']=12
    if damage in {'origin_dag','future_interval','future_motion'}:
        # Coordinated origin-plan + trace edits cannot hide invalid future operations.
        plan=saved['active_plan']['plan']
        if damage=='origin_dag':plan['initial_dag']='{}'
        if damage=='future_interval':plan['operation_intervals'][-2]['start_us']=0
        if damage=='future_motion':plan['operations'][1]['target_pose']['x_um']=99999
        for i in range(len(saved['trace'])-1,-1,-1):
            r=json.loads(saved['trace'][i])
            if r['event']['event_type']=='plan_started':
                r['event']['plan']=plan;saved['trace'][i]=json.dumps(r,sort_keys=True,separators=(',',':'));break
    with pytest.raises((ValidationError,ValueError)):SimulationState.restore(json.dumps(saved))


def test_finite_budget_failure_preserves_checkpoint_and_exact_budget_success():
    state=make([('CZ',(0,1)),('CZ',(0,2))]);terminal=initial_terminal(state)
    result=run_m3(state,terminal=terminal,max_decisions=1)
    assert result.status=='stalled' and result.diagnostics[0]['code']=='DECISION_BUDGET_EXHAUSTED'
    assert effects(state)==['0'] and '1' in result.diagnostics[0]['unfinished_gates']
    restored=SimulationState.restore(state.snapshot());assert run_m3(restored,terminal=terminal).status=='completed'
    h=make([('H',(0,))]);assert run_m3(h,max_decisions=1).status=='completed'
    empty=make();bad=TaskTarget((('Q000',HolderRef(H.STATIC,'S001')),('Q001',HolderRef(H.STATIC,'S001'))))
    before=empty.snapshot();result=run_m3(empty,terminal=bad)
    assert result.status=='stalled' and result.diagnostics[0]['code']=='TERMINAL_CAPACITY'
    assert empty.snapshot()==before


def test_workbench_m3_strategy_and_family_outside_geometry():
    value={'atom_count':4,'layout':'grid','compiler':'resident','gates':[
        {'id':'cz','gate_type':'CZ','qubit_ids':['Q000','Q001'],'parameters':[],'column':0},
        {'id':'h','gate_type':'H','qubit_ids':['Q000'],'parameters':[],'column':1}]}
    result,state=compile_input(value)
    assert result['status']=='completed' and result['recording']['summary']['overlap_time_us']==pytest.approx(1)
    validate_family(state)
    with pytest.raises(ValidationError):validate_family(replace(state,hardware=replace(state.hardware,slm_clearance_um=1.1)))


def test_idle_wait_and_rng_after_program_then_next_plan_remain_recoverable():
    from neutral_atom_env.domain.models import SimulationEvent
    state,terminal,_,p=overlap_case();execute(state,p)
    e=Executor(state)
    e.schedule(SimulationEvent(state.time_us+2,EventType.WAIT_COMPLETED));e.run()
    e.schedule(SimulationEvent(state.time_us,EventType.RNG_DRAW));e.run()
    restored=SimulationState.restore(state.snapshot())
    assert run_m3(state,terminal=terminal).status=='completed'
    assert run_m3(restored,terminal=terminal).status=='completed'
    assert state.snapshot()==restored.snapshot()


def test_program_and_recording_determinism_across_process_hashseeds():
    import os,subprocess,sys
    script='''
import sys,json,hashlib
sys.path.insert(0,'tests')
from test_m3 import make
from neutral_atom_strategies.scheduling.m3 import run_m3
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.replay.serializer import canonical_json
s=make([('CZ',(0,1)),('H',(0,)),('X',(2,))]);r=VisualRecorder(s)
assert run_m3(s,on_event=r.observe).status=='completed'
print(hashlib.sha256((s.snapshot()+canonical_json(r.payload())).encode()).hexdigest())
'''
    values=[subprocess.check_output([sys.executable,'-c',script],env=dict(os.environ,PYTHONHASHSEED=seed),text=True).strip() for seed in ('1','917')]
    assert values[0]==values[1]
