"""Step 3 first-attempt MZ service comparison; root runs the formal tests."""
from dataclasses import replace
from math import isclose
import json
import pytest

from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import Atom, PhysicalGate as Gate, Position2D as P, Rectangle, GridCoord, StaticTrap, Zone, ZoneType, HolderRef, HolderType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor
from neutral_atom_strategies.scheduling.qec import readout_service
from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.qec_readout import choose_readout_service
from neutral_atom_env.quantum.stabilizer import StabilizerState


def readout_state(*,mz_enabled=False):
    bounds=Rectangle(P(-10,-30),P(30,15))
    traps={'S0':StaticTrap('S0',GridCoord(0,0),P(0,0)),
        'S1':StaticTrap('S1',GridCoord(2,0),P(10,0)),
        'M0':StaticTrap('M0',GridCoord(0,-4),P(0,-20),enabled=mz_enabled)}
    world=WorldState(bounds,traps,(
        Zone('SZ',ZoneType.STORAGE,Rectangle(P(-10,-5),P(30,15))),
        Zone('MZ',ZoneType.MEASUREMENT,Rectangle(P(-10,-30),P(30,-10)))))
    atoms={'q0':Atom('q0'),'q1':Atom('q1')}
    gates=(Gate('m','MEASURE',('q0',)),Gate('r','RESET',('q0',)),
           Gate('correct','X',('q1',),condition=(('m',1),)))
    state=SimulationState(world,PlacementState({q:HolderRef(HolderType.STATIC,f'S{i}') for i,q in enumerate(atoms)}),
        atoms,AODRuntimeState(pose=P(0,0),rows=1,columns=1,enabled_rows=(False,),enabled_columns=(False,)),
        DynamicGateDAG(PhysicalCircuit(gates)),seed=17)
    # Independent expected syndrome is 1, then RESET->0 and correction X->1.
    return replace(state,quantum_state=StabilizerState.zero(tuple(atoms)).apply_gate('X',('q0',)))


def run_with_correction(state,plan):
    executor=Executor(state);executor.submit(plan);snapshots=[]
    while state.event_queue:
        executor.step();snapshots.append(state.snapshot())
    p=ProgramBuilder(state,TaskIntent(f'correction/{state.version}',TaskTarget(),phase='program',gate_effects=frozenset({'correct'})))
    p.add(K.RAMAN_ROTATION,'Actual measurement-conditioned X',gate_ids=('correct',))
    executor.submit(p.finish('joint-readout-test-correction'));executor.run()
    outcomes=[];resets=[];applied=[]
    for raw in state.trace.records:
        entry=json.loads(raw)
        if not entry.get('effect_completed'):continue
        outcomes.extend(entry.get('measurement_results',{}).items())
        resets.extend(entry.get('reset_projection_results',{}).items())
        applied.extend(entry.get('applied_gate_ids',()))
    return snapshots,(outcomes,resets,applied)


def test_loaded_mz_measure_reset_saves_one_pair_with_identical_branch_and_terminal():
    baseline=readout_state();joint=readout_state();compiler=PatchArrayCompiler()
    old,_=readout_service(baseline,compiler,(baseline.dag.nodes['m'].gate,))
    before=joint.snapshot()
    selected,count,report=choose_readout_service(joint,compiler,(joint.dag.nodes['m'].gate,))
    assert joint.snapshot()==before
    assert count==1 and report['selected_family']=='loaded_return'
    assert report['service_class_budget']==2 and len(report['candidates'])==2
    assert report['reference_destination_search']['destinations_attempted']==1
    assert isclose(report['saved_us'],200.,rel_tol=0,abs_tol=1e-7)
    old_snapshots,old_branch=run_with_correction(baseline,old)
    snapshots,branch=run_with_correction(joint,selected)
    assert branch==old_branch
    assert joint.measurement_results==baseline.measurement_results=={'m':1}
    assert joint.rng_state==baseline.rng_state and joint.quantum_state==baseline.quantum_state
    assert joint.quantum_state.expectation({'q0':'Z'})==1
    assert joint.quantum_state.expectation({'q1':'Z'})==-1
    assert joint.placement==baseline.placement and joint.aod==baseline.aod
    assert joint.slm_enabled==baseline.slm_enabled and joint.atoms==baseline.atoms
    assert isclose(joint.time_us,baseline.time_us-200.,rel_tol=0,abs_tol=1e-7)
    assert joint.physical_metrics.aod_load_count==baseline.physical_metrics.aod_load_count-1
    assert joint.physical_metrics.aod_offload_count==baseline.physical_metrics.aod_offload_count-1
    assert all(o.transfer_phase!='approach' for o in selected.operations)
    for snapshot in snapshots:
        restored=SimulationState.restore(snapshot)
        assert restored.snapshot()==snapshot
        Executor(restored).run()


def test_active_mz_slm_rejects_retained_candidate_and_selects_real_slm_fallback():
    state=readout_state(mz_enabled=True);compiler=PatchArrayCompiler();before=state.snapshot()
    reference,_=readout_service(state,compiler,(state.dag.nodes['m'].gate,))
    selected,count,report=choose_readout_service(state,compiler,(state.dag.nodes['m'].gate,))
    assert state.snapshot()==before
    assert report['selected_family']=='slm_return' and report['saved_us']==0
    rejected=report['candidates'][1]
    assert rejected['status']=='rejected' and rejected['violation']['code']=='QEC_READOUT_ACTIVE_MZ_SLM'
    assert selected.estimated_duration_us==reference.estimated_duration_us
    assert sum(o.operation_type==K.AOD_LOAD for o in selected.operations)==2
    assert sum(o.operation_type==K.AOD_OFFLOAD for o in selected.operations)==2
    Executor(state).submit(selected);Executor(state).run()
    assert state.measurement_results=={'m':1} and not state.placement.mobile_occupancy


def test_internal_reference_inconsistency_propagates_without_trying_fallback(monkeypatch):
    state=readout_state();before=state.snapshot();calls=[]
    def fail_finish(self,planner_id):
        calls.append(planner_id)
        raise ValidationError('PLAN_TAMPERED','Injected internal reference mismatch')
    monkeypatch.setattr(ProgramBuilder,'finish',fail_finish)
    with pytest.raises(ValidationError,match='PLAN_TAMPERED'):
        choose_readout_service(state,PatchArrayCompiler(),(state.dag.nodes['m'].gate,))
    assert calls==['qec-measure-reset-return-v1']
    assert state.snapshot()==before
