"""Locality is a preference: a failed local route must not hide legal cross work.

Fault injection changes compiler availability only. Successful operations still
use the real backend, scheduled audit and Executor. These tests are prepared
before the source patch; they require the cross-component fallback behavior.
"""
import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus
from neutral_atom_env.simulation import patch_greedy as module
from test_patch_greedy import initial


GATES=[{'id':'local-edge','gate_type':'CZ','qubit_ids':['Q000','Q001'],'column':0},
       {'id':'cross-edge','gate_type':'CZ','qubit_ids':['Q009','Q027'],'column':0}]


def inject(monkeypatch,*,always_fail_cross=False,fail_local=True):
    real_service=module.batch_service;real_groups=module.candidate_groups
    calls=[]
    # One candidate per phase makes the exact remaining-budget expectation
    # independent of candidate enumeration details or incidental rejections.
    monkeypatch.setattr(module,'candidate_groups',lambda state,gates,strategy:real_groups(state,gates,strategy)[:1])
    def service(state,compiler,shift,members):
        ids={g for g,_,_ in members};calls.append(tuple(sorted(ids)))
        if fail_local and 'local-edge' in ids and state.dag.nodes['cross-edge'].status!=GateStatus.COMPLETED:
            raise ValidationError('TEST_LOCAL_UNROUTABLE','Local service is unavailable until another physical task advances')
        if always_fail_cross and 'cross-edge' in ids:
            raise ValidationError('TEST_CROSS_UNROUTABLE','Cross service also unavailable')
        return real_service(state,compiler,shift,members)
    monkeypatch.setattr(module,'batch_service',service)
    return calls


def test_failed_local_uses_remaining_budget_for_cross_and_then_finishes(monkeypatch):
    calls=inject(monkeypatch);state=initial(GATES)
    result=module.run_patch(state,strategy='patch_greedy',candidate_budget=2)
    assert result.status=='completed',result.diagnostics
    effects=[d for d in result.decision_log if d.get('kind')=='cz_batch']
    assert [d['selected'] for d in effects]==['cross-edge','local-edge']
    assert effects[0]['fallback_to_cross_component'] is True
    assert effects[0]['constructed']==2
    assert calls[:2]==[('local-edge',),('cross-edge',)]
    assert state.dag.completed


def test_exhausted_local_attempt_budget_cannot_start_cross(monkeypatch):
    calls=inject(monkeypatch);state=initial(GATES)
    result=module.run_patch(state,strategy='patch_greedy',candidate_budget=1)
    assert result.status=='stalled'
    assert calls==[('local-edge',)]
    assert all(n.status==GateStatus.READY for n in state.dag.nodes.values())
    assert any(r['violation']['code']=='TEST_LOCAL_UNROUTABLE' for r in result.candidate_rejections)


def test_both_scopes_fail_preserves_causes_and_commits_neither_gate(monkeypatch):
    calls=inject(monkeypatch,always_fail_cross=True);state=initial(GATES)
    result=module.run_patch(state,strategy='patch_greedy',candidate_budget=2)
    assert result.status=='stalled'
    assert calls==[('local-edge',),('cross-edge',)]
    assert all(n.status==GateStatus.READY for n in state.dag.nodes.values())
    assert {'TEST_LOCAL_UNROUTABLE','TEST_CROSS_UNROUTABLE'}<=set(r['violation']['code'] for r in result.candidate_rejections)


def test_successful_local_still_keeps_original_priority(monkeypatch):
    calls=inject(monkeypatch,fail_local=False);state=initial(GATES)
    result=module.run_patch(state,strategy='patch_greedy',candidate_budget=2,max_decisions=2)
    assert result.status=='stalled'  # stage + local reached the deliberate boundary
    assert calls==[('local-edge',)]
    assert state.dag.nodes['local-edge'].status==GateStatus.COMPLETED
    assert state.dag.nodes['cross-edge'].status==GateStatus.READY
