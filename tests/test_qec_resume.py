"""Opt-in QEC boundary resume contract.

These tests
use two ordinary-layout atoms, not the expensive 68-atom physical experiment.
"""
from dataclasses import replace

import pytest

from neutral_atom_env.domain.models import GateStatus, Position2D
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.simulation.m3 import initial_terminal
from neutral_atom_env.simulation.qec_joint import run_qec_joint
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization.workbench import build_inputs, initialize_input


def initial_state():
    gates=[{'id':gid,'gate_type':kind,'qubit_ids':qs,'column':column}
           for gid,kind,qs,column in (
               ('h0','H',['Q000'],0),('h1','H',['Q001'],0),
               ('cz_first','CZ',['Q000','Q001'],1),
               ('h_between','H',['Q001'],2),
               ('cz_last','CZ',['Q000','Q001'],3))]
    value,circuit,platform,placement=build_inputs({
        'compiler':'greedy','atom_count':2,'layout':'row','seed':7,
        'ez_policy':'adaptive','aod_traps':2,'aod_rows':1,'aod_columns':2,
        'gates':gates})
    state=initialize_input(value,circuit,platform,placement)
    return replace(state,quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))


@pytest.fixture(scope='module')
def uninterrupted():
    state=initial_state();origin=state.snapshot();terminal=initial_terminal(state)
    cuts={};in_flight={};plans=[];latest=None
    def observe(current,event):
        nonlocal latest
        kind=event.event_type.value
        if kind=='plan_started':
            latest=event.plan
            plans.append(canonical_json(event.plan))
            in_flight.setdefault('active_queue',current.snapshot())
        if current.transfer is not None:
            in_flight.setdefault('active_transfer',current.snapshot())
        if kind!='plan_completed':return
        assert not current.event_queue and current.active_plan is None
        assert current.transfer is None and not current.reservations and not current.aod.is_moving
        completed={gid for gid,node in current.dag.nodes.items() if node.status==GateStatus.COMPLETED}
        names=[]
        if latest.planner_id=='qec-stage-v1':names.append('poststage_empty')
        if current.placement.mobile_occupancy:
            if 'cz_first' in completed and 'h_between' not in completed:names.append('retained_cz')
            if 'h_between' in completed and 'cz_last' not in completed:names.append('retained_post_h')
            if current.dag.completed:names.append('dag_completed_before_terminal')
        if latest.planner_id=='qec-terminal-v1':names.append('already_terminal')
        for name in names:cuts.setdefault(name,(current.snapshot(),len(plans)))
    result=run_qec_joint(state,on_event=observe,terminal=terminal)
    assert result.status=='completed',result.diagnostics
    assert set(cuts)=={'poststage_empty','retained_cz','retained_post_h',
                       'dag_completed_before_terminal','already_terminal'}
    assert set(in_flight)=={'active_queue','active_transfer'}
    assert not state.placement.mobile_occupancy and state.dag.completed
    assert state.measurement_results=={}
    return {'origin':origin,'terminal':terminal,'final':state.snapshot(),'cuts':cuts,
            'plans':plans,'in_flight':in_flight}


@pytest.mark.parametrize('cut',['poststage_empty','retained_cz','retained_post_h',
                              'dag_completed_before_terminal','already_terminal'])
def test_resumed_suffix_is_exactly_the_uninterrupted_physical_trace(uninterrupted,cut):
    snapshot,plan_count=uninterrupted['cuts'][cut]
    restored=SimulationState.restore(snapshot)
    assert restored.snapshot()==snapshot
    suffix=[]
    def observe(current,event):
        if event.event_type.value=='plan_started':suffix.append(canonical_json(event.plan))
    result=run_qec_joint(restored,resume=True,terminal=uninterrupted['terminal'],on_event=observe)
    assert result.status=='completed',result.diagnostics
    # Includes trace/sequence, RNG, exact holders and trap masks, quantum state,
    # times, metrics, gate effects and all saved scheduled-plan fingerprints.
    assert restored.snapshot()==uninterrupted['final']
    assert suffix==uninterrupted['plans'][plan_count:]
    if cut=='already_terminal':assert suffix==[]


def require_atomic_rejection(state,**options):
    before=state.snapshot()
    result=run_qec_joint(state,resume=True,**options)
    assert result.status=='stalled',result
    assert result.diagnostics
    assert result.decisions==0
    assert state.snapshot()==before


def test_resume_requires_explicit_original_terminal(uninterrupted):
    state=SimulationState.restore(uninterrupted['cuts']['poststage_empty'][0])
    require_atomic_rejection(state)


@pytest.mark.parametrize('cut',['active_queue','active_transfer'])
def test_resume_does_not_drain_or_accept_an_in_flight_plan(uninterrupted,cut):
    state=SimulationState.restore(uninterrupted['in_flight'][cut])
    assert state.event_queue and state.active_plan is not None
    if cut=='active_transfer':assert state.transfer is not None
    require_atomic_rejection(state,terminal=uninterrupted['terminal'])


def test_resume_rejects_non_ez_working_layout_without_restaging(uninterrupted):
    stage=SimulationState.restore(uninterrupted['cuts']['poststage_empty'][0])
    origin=SimulationState.restore(uninterrupted['origin'])
    # Domain-valid supported SZ placement with a committed-stage-shaped trace:
    # resume must reject the contradictory work boundary, not restage it.
    bad=replace(stage,placement=origin.placement,slm_enabled=origin.slm_enabled)
    require_atomic_rejection(bad,terminal=uninterrupted['terminal'])


@pytest.mark.parametrize('defect',['missing_aligned_source','source_enabled'])
def test_retained_source_must_be_aligned_unique_and_switched_off(uninterrupted,defect):
    state=SimulationState.restore(uninterrupted['cuts']['retained_cz'][0])
    mobile=state.placement.mobile_occupancy
    assert mobile
    if defect=='missing_aligned_source':
        # Half a micron leaves the ordinary state supported, but it is not a
        # retained capture coordinate on the five-micron SLM lattice.
        pose=state.aod.pose
        state=replace(state,aod=replace(state.aod,pose=Position2D(pose.x_um+.5,pose.y_um)))
    else:
        cell=next(iter(mobile));point=state.aod.position(cell)
        sites=[t.id for t in state.world.traps.values() if t.position==point]
        assert len(sites)==1
        source=sites[0];assert not state.slm_enabled[source]
        state=replace(state,slm_enabled=dict(state.slm_enabled)|{source:True})
    require_atomic_rejection(state,terminal=uninterrupted['terminal'])
