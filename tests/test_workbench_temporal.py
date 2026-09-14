"""The editable temporal profile preserves noise; legacy profiles reject it."""
from types import SimpleNamespace
import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_env.experiments.surface_qec import experiment_input
from neutral_atom_env.visualization.workbench import validate_input,build_inputs


def short_input():
    value=experiment_input(compiler='qec_temporal')
    value['gates']=[{'id':'read','gate_type':'MEASURE','qubit_ids':['Q018'],
                     'parameters':[],'column':0,'readout_flip':True},
                    {'id':'reset','gate_type':'RESET','qubit_ids':['Q018'],
                     'parameters':[],'column':1}]
    return value


def test_real_input_preserves_readout_flip_and_closes_roundtrip():
    raw=short_input()
    value,circuit,_,_=build_inputs(raw)
    assert value==validate_input(value)
    assert circuit.gates[0].readout_flip is True
    assert 'readout_flip' not in value['gates'][1]


@pytest.mark.parametrize('compiler',['qec_ghz2','qec_persistent','qec_joint'])
def test_old_profiles_cannot_silently_ignore_a_new_noise_flag(compiler):
    raw=short_input();raw['compiler']=compiler
    with pytest.raises(ValueError,match='qec_temporal'):validate_input(raw)


@pytest.mark.parametrize('value',[1,0,'true',None])
def test_flip_requires_actual_boolean(value):
    raw=short_input();raw['gates'][0]['readout_flip']=value
    with pytest.raises(ValueError,match='boolean'):validate_input(raw)


def test_history_guard_runs_before_any_edited_early_correction(monkeypatch):
    from neutral_atom_env.simulation import qec_temporal as runner
    from neutral_atom_env.experiments.surface_qec_temporal import HISTORY_IDS,CORRECTION_PREFIX
    gates=[PhysicalGate(gid,'MEASURE',('Q018',)) for gid in HISTORY_IDS]
    correction=PhysicalGate(CORRECTION_PREFIX+'edited','X',('Q000',))
    state=SimpleNamespace(dag=SimpleNamespace(circuit=SimpleNamespace(gates=gates+[correction])),measurement_results={})
    def joint(s,**options):
        # A deliberately damaged dependency lets the correction become ready
        # before the measurements. The guard must reject before plan creation.
        options['frontier_validator'](s,[correction])
        pytest.fail('The guard let a premature correction reach compilation')
    monkeypatch.setattr(runner,'run_qec_joint',joint)
    with pytest.raises(ValidationError) as caught:runner.run_qec_temporal(state)
    assert caught.value.violation.code=='INCOMPLETE_SYNDROME_HISTORY'


def test_complete_but_unsupported_reported_history_rejects_before_correction(monkeypatch):
    from neutral_atom_env.simulation import qec_temporal as runner
    from neutral_atom_env.experiments.surface_qec_temporal import HISTORY_IDS,CORRECTION_PREFIX
    gates=[PhysicalGate(gid,'MEASURE',('Q018',)) for gid in HISTORY_IDS]
    correction=PhysicalGate(CORRECTION_PREFIX+'edited','X',('Q000',))
    state=SimpleNamespace(dag=SimpleNamespace(circuit=SimpleNamespace(gates=gates+[correction])),
                          measurement_results={gid:1 for gid in HISTORY_IDS})
    def joint(s,**options):
        options['frontier_validator'](s,[correction])
        pytest.fail('Unsupported history reached a correction plan')
    monkeypatch.setattr(runner,'run_qec_joint',joint)
    with pytest.raises(ValidationError) as caught:runner.run_qec_temporal(state)
    assert caught.value.violation.code=='UNSUPPORTED_SYNDROME_HISTORY'


def test_arbitrary_short_edits_do_not_require_full_named_protocol(monkeypatch):
    from neutral_atom_env.simulation import qec_temporal as runner
    state=SimpleNamespace(dag=SimpleNamespace(circuit=SimpleNamespace(gates=[PhysicalGate('edited','H',('Q000',))])),
                          measurement_results={})
    expected=SimpleNamespace(status='completed')
    monkeypatch.setattr(runner,'run_qec_joint',lambda *a,**k:expected)
    assert runner.run_qec_temporal(state) is expected
