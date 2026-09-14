"""Future resume guard tests: no physical compilation or 68-atom fixture.

Authored with the full worker still active; execute only after applying the
explicit boundary-resume patch together with tests/test_qec_resume.py.
"""
from types import SimpleNamespace

import pytest

import neutral_atom_env.simulation.qec_temporal_four as wrapper
from neutral_atom_env.experiments.surface_qec_temporal_four import HISTORY_IDS,CORRECTION_PREFIX
from neutral_atom_env.simulation.m4 import M4Result


def completed_protocol_view(*,terminal=False):
    ids=HISTORY_IDS+(CORRECTION_PREFIX+'test',)
    gates=tuple(SimpleNamespace(id=gid) for gid in ids)
    return SimpleNamespace(
        dag=SimpleNamespace(circuit=SimpleNamespace(gates=gates),completed=True),
        measurement_results=dict.fromkeys(HISTORY_IDS,0),
        # The fake runner models both post-correction cleanup and a terminal
        # no-op. The wrapper must not require another measurement event.
        at_original_terminal=terminal)


def completed_result():return M4Result('completed',(),(),0,())


@pytest.mark.parametrize('terminal',[False,True],ids=['corrections_complete','already_terminal'])
def test_resume_revalidates_full_history_without_requiring_another_event(monkeypatch,terminal):
    state=completed_protocol_view(terminal=terminal)
    before=dict(state.measurement_results);calls=[]
    real_validate=wrapper.validate_history
    target=object()
    def validate(bits):
        calls.append('validate')
        assert bits is state.measurement_results
        return real_validate(bits)
    def joint(current,**options):
        calls.append('joint')
        assert calls==['validate','joint']
        assert current is state and options['resume'] is True and options['terminal'] is target
        # Deliberately emit no events and do not invoke frontier_validator:
        # all correction gates are already completed on this resumed input.
        return completed_result()
    monkeypatch.setattr(wrapper,'validate_history',validate)
    monkeypatch.setattr(wrapper,'run_qec_joint',joint)
    result=wrapper.run_qec_temporal_four(state,resume=True,terminal=target)
    assert result.status=='completed'
    assert calls==['validate','joint'] and state.measurement_results==before


def test_resume_unknown_complete_history_is_rejected_before_joint_is_called(monkeypatch):
    state=completed_protocol_view(terminal=True)
    state.measurement_results['round1_X0_0']=1
    state.measurement_results['round1_Z3_0']=1
    before=dict(state.measurement_results)
    def forbidden(*args,**kwargs):pytest.fail('Unsupported resume history must fail before invoking the physical runner')
    monkeypatch.setattr(wrapper,'run_qec_joint',forbidden)
    result=wrapper.run_qec_temporal_four(state,resume=True,terminal=object())
    assert result.status=='stalled' and result.decisions==0
    assert result.diagnostics[0]['code']=='UNSUPPORTED_SYNDROME_HISTORY'
    assert state.measurement_results==before


@pytest.mark.parametrize('options',[{}, {'resume':False}],ids=['default','explicit_false'])
def test_non_resume_keeps_existing_event_driven_history_check(monkeypatch,options):
    state=completed_protocol_view();calls=[]
    real_validate=wrapper.validate_history
    def validate(bits):
        calls.append('validate')
        return real_validate(bits)
    def joint(current,**kwargs):
        calls.append('joint')
        assert calls==['joint']  # No new entry guard on the old path.
        assert kwargs.get('resume',False) is False
        kwargs['on_event'](current,object())
        return completed_result()
    monkeypatch.setattr(wrapper,'validate_history',validate)
    monkeypatch.setattr(wrapper,'run_qec_joint',joint)
    result=wrapper.run_qec_temporal_four(state,**options)
    assert result.status=='completed' and calls==['joint','validate']


def test_resume_still_rejects_missing_required_circuit_measurement_before_joint(monkeypatch):
    state=completed_protocol_view()
    state.dag.circuit.gates=tuple(g for g in state.dag.circuit.gates if g.id!=HISTORY_IDS[-1])
    def forbidden(*args,**kwargs):pytest.fail('Missing temporal circuit dependencies must not enter the runner')
    monkeypatch.setattr(wrapper,'run_qec_joint',forbidden)
    result=wrapper.run_qec_temporal_four(state,resume=True,terminal=object())
    assert result.status=='stalled' and result.diagnostics[0]['code']=='INCOMPLETE_SYNDROME_HISTORY'


def test_resume_short_edited_circuit_without_temporal_corrections_needs_no_full_history(monkeypatch):
    state=SimpleNamespace(dag=SimpleNamespace(circuit=SimpleNamespace(gates=(SimpleNamespace(id='edited_h'),))),
                          measurement_results={})
    calls=[]
    def forbidden(bits):pytest.fail('An edited circuit without temporal correction slots does not invoke the protocol decoder')
    def joint(current,**options):calls.append(current);return completed_result()
    monkeypatch.setattr(wrapper,'validate_history',forbidden)
    monkeypatch.setattr(wrapper,'run_qec_joint',joint)
    result=wrapper.run_qec_temporal_four(state,resume=True,terminal=object())
    assert result.status=='completed' and calls==[state]
