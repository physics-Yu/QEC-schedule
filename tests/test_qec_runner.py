import json
from dataclasses import replace

from neutral_atom_experiments.qec_layout import build_qec_inputs
from neutral_atom_env.platform import initialize
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_strategies.scheduling.qec import run_qec
from neutral_atom_env.simulation.executor import Executor
from neutral_atom_env.replay.operation_codec import event_from_dict
from neutral_atom_env.replay.checkpoint import restore


def initial(gates):
    _,circuit,platform,placement=build_qec_inputs({'gates':gates})
    state=initialize(circuit,platform,placement,seed=3)
    return replace(state,quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))


def test_edited_readout_reset_circuit_executes_in_mz_and_replays_exactly():
    gates=[{'id':'user-h','gate_type':'H','qubit_ids':['Q018'],'column':0},
           {'id':'user-read','gate_type':'MEASURE','qubit_ids':['Q018'],'column':1},
           {'id':'user-reset','gate_type':'RESET','qubit_ids':['Q018'],'column':2},
           {'id':'user-correction','gate_type':'X','qubit_ids':['Q000'],'column':3,
            'condition':[['user-read',1]]}]
    state=initial(gates);origin=state.placement;seen=[]
    def observe(s,event):
        if event.event_type.value=='operation_completed':
            record=json.loads(s.trace.records[-1])
            if record.get('measurement_results'):
                seen.append((dict(s.measurement_results),s.placement.position('Q018',s.world,s.aod)))
    result=run_qec(state,on_event=observe)
    assert result.status=='completed',result.diagnostics
    assert seen and seen[0][1].y_um<=-150
    assert state.placement==origin and not state.atoms['Q018'].measured
    assert state.quantum_state.expectation({'Q018':'Z'})==1
    assert state.quantum_state.expectation({'Q000':'Z'})==(-1 if state.measurement_results['user-read'] else 1)
    assert restore(state.snapshot()).snapshot()==state.snapshot()
    replay=initial(gates)
    for raw in state.trace.records:
        event=event_from_dict(json.loads(raw)['event'])
        if event.event_type.value=='plan_started':
            executor=Executor(replay);executor.submit(event.plan);executor.run()
    assert replay.snapshot()==state.snapshot()
