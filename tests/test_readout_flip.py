"""Fixed classical readout faults preserve real projection and schema19 replay."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from test_quantum_readout import state_for, build
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import PhysicalGate as Gate
from neutral_atom_env.domain.operations import OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.replay.serializer import primitive, canonical_json
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization.recording import VisualRecorder


@pytest.mark.parametrize('value',[0,1,None,'true',[],1.0])
def test_readout_flip_requires_strict_boolean(value):
    with pytest.raises(ValueError,match='must be a boolean'):
        Gate('m','MEASURE',('q0',),readout_flip=value)


@pytest.mark.parametrize('kind',['RESET','X','H','CZ'])
def test_flip_is_only_allowed_on_measurement(kind):
    with pytest.raises(ValueError,match='only valid for MEASURE/MZ'):
        Gate('g',kind,('q0','q1') if kind=='CZ' else ('q0',),readout_flip=True)


def test_false_only_omission_preserves_all_old_fields_and_true_round_trip():
    old={'id':'m','gate_type':'MEASURE','qubit_ids':['q0'],'parameters':[],'condition':[],'depends_on':[]}
    assert primitive(Gate(**old))==old
    assert primitive(Gate(**old,readout_flip=False))==old
    noisy=old|{'readout_flip':True}
    assert primitive(Gate(**noisy))==noisy
    assert Gate(**json.loads(canonical_json(Gate(**noisy))))==Gate(**noisy)
    assert Gate('alias','MZ',('q0',),readout_flip=True).readout_flip


def run(state,steps):
    plan,predicted=build(state,steps);executor=Executor(state);executor.submit(plan)
    snapshots=[state.snapshot()]
    while state.event_queue:
        executor.step();snapshots.append(state.snapshot())
    return predicted,snapshots


def effects(state):
    return [json.loads(raw) for raw in state.trace.records if json.loads(raw).get('effect_completed')]


@pytest.mark.parametrize('seed',range(4))
def test_bell_true_bits_correlate_reports_flip_and_rng_is_unchanged(seed):
    final=[]
    for noisy in (False,True):
        gates=(Gate('m0','MEASURE',('q0',),readout_flip=noisy),Gate('m1','MEASURE',('q1',)))
        state=state_for(gates,seed=seed)
        state=replace(state,quantum_state=state.quantum_state.apply_gate('H',('q0',)).apply_gate('CX',('q0','q1')))
        predicted,snapshots=run(state,[(K.MEASUREMENT,('m0','m1'))])
        assert predicted.quantum_state==state.quantum_state and predicted.measurement_results==state.measurement_results
        assert predicted.rng_state==state.rng_state
        final.append(state)
        for saved in snapshots:
            restored=SimulationState.restore(saved);Executor(restored).run()
            assert restored.snapshot()==state.snapshot()
    ideal,noisy=final
    assert ideal.quantum_state==noisy.quantum_state and ideal.rng_state==noisy.rng_state
    bit=ideal.measurement_results['m0']
    assert ideal.measurement_results['m1']==bit
    assert noisy.measurement_results=={'m0':bit^1,'m1':bit}
    assert noisy.quantum_state.expectation({'q0':'Z','q1':'Z'})==1
    assert noisy.quantum_state.expectation({'q0':'Z'})==(-1 if bit else 1)
    ideal_record,record=effects(ideal)[0],effects(noisy)[0]
    assert 'measurement_true_results' not in ideal_record and 'readout_flips' not in ideal_record
    assert record['measurement_true_results']=={'m0':bit,'m1':bit}
    assert record['readout_flips']=={'m0':True,'m1':False}


def test_reset_uses_projection_while_condition_uses_reported_bit():
    gates=(Gate('m','MEASURE',('q0',),readout_flip=True),Gate('r','RESET',('q0',)),
           Gate('m2','MEASURE',('q0',)),Gate('x','X',('q1',),condition=(('m',1),)))
    state=state_for(gates)
    _,snapshots=run(state,[(K.MEASUREMENT,('m',)),(K.RESET,('r',)),
                         (K.MEASUREMENT,('m2',)),(K.RAMAN_ROTATION,('x',))])
    records=effects(state)
    assert state.measurement_results=={'m':1,'m2':0}
    assert records[0]['measurement_true_results']=={'m':0}
    assert records[1]['reset_projection_results']=={'r':0}
    assert records[-1]['applied_gate_ids']==['x']
    assert state.quantum_state.expectation({'q1':'Z'})==-1
    assert state.quantum_state.expectation({'q0':'Z'})==1
    assert all('measurement_true_results' not in r for r in records[1:])
    for saved in snapshots:
        restored=SimulationState.restore(saved);Executor(restored).run()
        assert restored.snapshot()==state.snapshot()


def test_recorder_exposes_truth_only_after_measurement_commits():
    state=state_for((Gate('m','MEASURE',('q0',),readout_flip=True),))
    plan,_=build(state,[(K.MEASUREMENT,('m',))])
    recorder=VisualRecorder(state);executor=Executor(state);executor.submit(plan)
    started=False
    while state.event_queue:
        executor.step();recorder.observe(state)
        if recorder.operations and not state.measurement_results:
            started=True
            assert recorder.operations[0]['measurement_results']=={}
            assert recorder.operations[0]['measurement_true_results']=={}
    assert started
    operation=recorder.payload()['operations'][0]
    assert operation['measurement_results']=={'m':1}
    assert operation['measurement_true_results']=={'m':0}
    assert operation['readout_flips']=={'m':True}
    assert all(frame['measurement_results']=={} for frame in recorder.frames if frame['time']<500)


@pytest.mark.parametrize('field,value',[
    ('measurement_true_results',{'m':1}),('measurement_true_results',{'m':False}),
    ('measurement_true_results',None),('readout_flips',{'m':False}),
    ('readout_flips',{'m':1}),('readout_flips',None),('measurement_results',{'m':0}),
])
def test_earlier_plan_noise_trace_tampering_is_rejected(field,value):
    state=state_for((Gate('m','MEASURE',('q0',),readout_flip=True),
                     Gate('x','X',('q1',),condition=(('m',1),))))
    for task,kind,gid in [('first',K.MEASUREMENT,'m'),('second',K.RAMAN_ROTATION,'x')]:
        p=ProgramBuilder(state,TaskIntent(task,TaskTarget(),phase='program',gate_effects=frozenset({gid})))
        p.add(kind,task,gate_id=gid);Executor(state).submit(p.finish(task));Executor(state).run()
    saved=json.loads(state.snapshot())
    for i,raw in enumerate(saved['trace']):
        record=json.loads(raw)
        if record.get('measurement_true_results') is not None:
            if value is None:record.pop(field)
            else:record[field]=value
            saved['trace'][i]=json.dumps(record);break
    with pytest.raises(ValidationError,match='READOUT_AUDIT_MISMATCH'):
        SimulationState.restore(json.dumps(saved))


def test_noise_metadata_cannot_appear_before_projection_or_on_ideal_readout():
    for noisy in (False,True):
        state=state_for((Gate('m','MEASURE',('q0',),readout_flip=noisy),))
        run(state,[(K.MEASUREMENT,('m',))]);saved=json.loads(state.snapshot())
        for i,raw in enumerate(saved['trace']):
            record=json.loads(raw)
            if record['event']['event_type']==('operation_started' if noisy else 'operation_completed'):
                record['measurement_true_results']={'m':0};record['readout_flips']={'m':noisy}
                saved['trace'][i]=json.dumps(record);break
        with pytest.raises(ValidationError,match='READOUT_AUDIT_MISMATCH'):
            SimulationState.restore(json.dumps(saved))


def test_saved_ideal_schema19_baseline_restores_exactly():
    path=Path(__file__).resolve().parents[1]/'artifacts/surface-qec-ghz2/browser/checkpoint.json'
    if not path.exists():pytest.skip('Saved project acceptance artifact not available in this checkout')
    snapshot=path.read_text(encoding='utf-8')
    assert '"schema_version":19' in snapshot and 'readout_flip' not in snapshot
    restored=SimulationState.restore(snapshot)
    assert restored.snapshot()==snapshot
    assert all(not g.readout_flip for g in restored.dag.circuit.gates)
