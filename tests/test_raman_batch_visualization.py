"""Actual native Raman batches; display checks consume Executor recordings."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_quantum_readout import state_for,build,Gate,K,Executor
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.experiments.surface_qec import experiment_input
from neutral_atom_env.visualization.workbench import build_inputs,validate_input


@pytest.mark.parametrize('expected_bits',[(0,0),(0,1),(1,1)])
def test_native_batch_records_each_condition_and_draws_only_actual_targets(tmp_path,expected_bits):
    # Measurement of |0> deterministically supplies 0; no fabricated runtime bits.
    gates=[Gate('m','MEASURE',('q2',)),
           Gate('x0','X',('q0',),condition=(('m',expected_bits[0]),)),
           Gate('x1','X',('q1',),condition=(('m',expected_bits[1]),))]
    state=state_for(gates,n=3)
    plan,_=build(state,[(K.MEASUREMENT,('m',)),(K.RAMAN_ROTATION,('x0','x1'))])
    recorder=VisualRecorder(state);executor=Executor(state);executor.submit(plan)
    while state.event_queue:
        executor.step();recorder.observe(state)
    data=recorder.payload();op=next(o for o in data['operations'] if o['kind']=='raman_rotation')
    applied={f'x{i}':bit==0 for i,bit in enumerate(expected_bits)}
    assert op['gate_ids']==['x0','x1'] and op['batch_size']==2
    assert op['applied_by_gate']==applied
    assert op['applied_gate_ids']==[g for g in ('x0','x1') if applied[g]]
    assert op['gate_qubits']=={'x0':['q0'],'x1':['q1']}
    assert set(op['target_holders'])=={'q0','q1'}
    assert op['applied']==any(applied.values())
    assert op['category']==('raman' if any(applied.values()) else 'control')
    assert state.physical_metrics.raman_busy_time_us==int(any(applied.values()))
    complete=[json.loads(r) for r in state.trace.records if json.loads(r).get('effect_completed')]
    batch=next(r for r in complete if r.get('applied_by_gate')==applied)
    assert batch['applied_gate_ids']==op['applied_gate_ids']
    html=write_html(data,tmp_path/'batch.html')
    node=shutil.which('node')
    assert node,'Node.js required for declared viewer contract check'
    subprocess.run([node,'tests/raman_batch_controls.cjs',str(html)],check=True,capture_output=True,text=True)


def test_joint_editor_keeps_exact_edited_gate_conditions_and_dependencies():
    raw=experiment_input();raw['compiler']='qec_joint'
    raw['gates']=[{'id':'m','gate_type':'MEASURE','qubit_ids':['Q018'],'parameters':[],'column':0},
                  {'id':'x','gate_type':'X','qubit_ids':['Q000'],'parameters':[],'column':1,
                   'condition':[['m',0]],'depends_on':['m']}]
    value,circuit,_,_=build_inputs(raw)
    assert value['compiler']=='qec_joint' and value==validate_input(value)
    assert [g.id for g in circuit.gates]==['m','x']
    assert circuit.gates[1].condition==(('m',0),) and circuit.gates[1].depends_on==('m',)
