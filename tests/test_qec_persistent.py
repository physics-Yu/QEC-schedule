"""Step 2 attempt 1: real baseline/reuse comparisons, no physical mocks."""
from dataclasses import replace
import json
from math import isclose

from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import Atom, PhysicalGate as Gate, Position2D as P, Rectangle, GridCoord, StaticTrap, Zone, ZoneType, HolderRef, HolderType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor
from neutral_atom_strategies.scheduling.qec import run_qec
from neutral_atom_strategies.scheduling.qec_persistent import run_qec_persistent
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.visualization.recording import VisualRecorder


def initial(gates,n):
    bounds=Rectangle(P(-10,-30),P(10*n+15,30))
    traps={}
    for prefix,y in (('S',-20),('E',0)):
        for i in range(n):traps[f'{prefix}{i}']=StaticTrap(f'{prefix}{i}',GridCoord(2*i,y//5),P(10*i,y))
    world=WorldState(bounds,traps,(
        Zone('SZ',ZoneType.STORAGE,Rectangle(P(-10,-30),P(10*n+15,-10))),
        Zone('EZ',ZoneType.ENTANGLEMENT,Rectangle(P(-10,-5),P(10*n+15,30)))))
    atoms={f'q{i}':Atom(f'q{i}') for i in range(n)}
    state=SimulationState(world,PlacementState({q:HolderRef(HolderType.STATIC,f'S{i}') for i,q in enumerate(atoms)}),
        atoms,AODRuntimeState(pose=P(0,-20),rows=1,columns=n,spacing_um=10,
            enabled_rows=(False,),enabled_columns=(False,)*n),DynamicGateDAG(PhysicalCircuit(tuple(gates))),
        hardware=HardwareConfig())
    return replace(state,quantum_state=StabilizerState.zero(tuple(atoms)))


def execute(state,runner):
    recorder=VisualRecorder(state);snapshots=[]
    def observe(s,event):
        recorder.observe(s,event);snapshots.append(s.snapshot())
    result=runner(state,on_event=observe)
    assert result.status=='completed',result.diagnostics
    return result,recorder.payload(),snapshots


def test_two_cz_same_cohort_with_intermediate_h_saves_one_handoff_pair():
    gates=(Gate('a','CZ',('q0','q1')),Gate('b','H',('q0',)),Gate('c','CZ',('q0','q1')))
    baseline=initial(gates,2);persistent=initial(gates,2)
    original_placement=persistent.placement;original_aod=persistent.aod
    base_result,base_view,_=execute(baseline,run_qec)
    result,view,snapshots=execute(persistent,run_qec_persistent)
    assert isclose(persistent.time_us,baseline.time_us-200,rel_tol=0,abs_tol=1e-7)
    assert persistent.physical_metrics.aod_load_count==baseline.physical_metrics.aod_load_count-1
    assert persistent.physical_metrics.aod_offload_count==baseline.physical_metrics.aod_offload_count-1
    assert persistent.quantum_state==baseline.quantum_state
    assert persistent.quantum_state.expectation({'q0':'X'})==1
    assert persistent.quantum_state.expectation({'q1':'Z'})==1
    assert persistent.placement==original_placement and persistent.aod==original_aod
    assert persistent.measurement_results==baseline.measurement_results=={}
    summary=result.decision_log[-1]
    assert (summary['retained_count'],summary['reuse_count'],summary['flush_count'])==(1,1,1)
    raman=next(o for o in view['operations'] if o['kind']=='raman_rotation')
    assert raman['target_holders']['q0']['holder_type']=='mobile'
    # A retained return must not carry a transfer exemption without OFFLOAD.
    for record in persistent.trace.records:
        entry=json.loads(record);event=entry['event']
        if event['event_type']!='plan_started':continue
        plan=event['plan']
        if plan['planner_id']!='qec-persistent-cohort-v1':continue
        assert not any(o['transfer_phase']=='approach' for o in plan['operations'])
    # Checkpoints at every operation boundary reconstruct the same committed
    # prefix; in-flight suffix execution completes only that submitted plan.
    for snapshot in snapshots:
        restored=SimulationState.restore(snapshot)
        assert restored.snapshot()==snapshot
        Executor(restored).run()
    assert sum(o['kind']=='entangling_pulse' for o in view['operations'])==2


def test_different_cohort_explicitly_releases_before_next_capture():
    gates=(Gate('a','CZ',('q0','q1')),Gate('b','CZ',('q1','q2')))
    baseline=initial(gates,3);persistent=initial(gates,3)
    base_result,_,_=execute(baseline,run_qec)
    result,view,_=execute(persistent,run_qec_persistent)
    assert isclose(persistent.time_us,baseline.time_us,rel_tol=0,abs_tol=1e-7)
    assert persistent.physical_metrics.aod_load_count==baseline.physical_metrics.aod_load_count
    assert persistent.physical_metrics.aod_offload_count==baseline.physical_metrics.aod_offload_count
    assert persistent.quantum_state==baseline.quantum_state and persistent.placement==baseline.placement
    assert result.decision_log[-1]['reuse_count']==0
    assert any(e.get('reason')=='baseline_selected_different_cohort' for e in result.decision_log)
    assert not persistent.placement.mobile_occupancy
