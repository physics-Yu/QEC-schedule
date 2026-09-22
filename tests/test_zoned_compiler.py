"""Behavior contracts for the modular zoned compiler, on the real environment."""
from copy import deepcopy
import pytest
from neutral_atom_app.visualization.workbench import build_inputs, initialize_input
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_strategies.zoned import run_zoned


def spec(n=4,layout='row',rows=1,columns=2):
    return dict(studio={'mode':'custom'},circuit_profile='physical',atom_count=n,layout=layout,seed=13,
                ez_policy='adaptive',ez_neighbor_guard_enabled=True,aod_backend='row_column_orthogonal',
                aod_rows=rows,aod_columns=columns,aod_row_offsets_um=[15*i for i in range(rows)],
                aod_column_offsets_um=[20*i for i in range(columns)],
                compilation=dict(strategy='legacy',implementation='zoned_ids',compile_timeout_s=90),
                gates=[dict(id=f'cz{i}',gate_type='CZ',qubit_ids=[f'Q{2*i:03d}',f'Q{2*i+1:03d}'],column=0)
                       for i in range(n//2)])


def run(value,**options):
    normalized,circuit,platform,placement=build_inputs(value)
    env=NeutralAtomEnv(initialize_input(normalized,circuit,platform,placement))
    initial=env.snapshot();terminal=initial_terminal(env.state)
    plans=[];submit=env.submit
    def capture(plan):
        submit(plan);plans.append(plan)
    env.submit=capture
    result=run_zoned(env,**options)
    return result,env,initial,terminal,plans


def verify_replay(env,initial,plans):
    replay=NeutralAtomEnv.restore(initial)
    for plan in plans:
        replay.submit(plan);replay.run()
    assert replay.snapshot()==env.snapshot()


def test_parallel_cz_and_fixed_terminal_replay():
    result,env,initial,terminal,plans=run(spec())
    assert result.status=='completed',result.diagnostics
    assert [len(op.effect_gate_ids) for p in plans for op in p.operations if op.operation_type==K.ENTANGLING_PULSE]==[2]
    validate_target(terminal,env.state)
    verify_replay(env,initial,plans)


@pytest.mark.parametrize('layout,n,rows,columns',[('grid',9,2,2),('shuffled',5,1,1),('row',6,1,2)])
def test_only_frontier_operands_move_in_arbitrary_layout(layout,n,rows,columns):
    value=spec(n,layout,rows,columns);value['gates']=value['gates'][:1]
    result,env,initial,terminal,plans=run(value,restore_layout=False)
    assert result.status=='completed',result.diagnostics
    captured={b.atom_id for p in plans for op in p.operations if op.operation_type==K.AOD_LOAD for b in op.transfer_bindings}
    assert captured=={'Q000','Q001'}
    original=NeutralAtomEnv.restore(initial)
    for q in set(env.state.atoms)-captured:
        assert env.state.placement.atom_to_holder[q]==original.state.placement.atom_to_holder[q]
    verify_replay(env,initial,plans)


def test_anchor_residency_avoids_repeated_staging():
    value=spec(2,rows=1,columns=1)
    value['gates']=[dict(id=f'g{i}',gate_type='CZ',qubit_ids=['Q000','Q001'],column=i) for i in range(3)]
    result,env,initial,terminal,plans=run(value,restore_layout=False)
    assert result.status=='completed',result.diagnostics
    loads=[b.atom_id for p in plans for op in p.operations if op.operation_type==K.AOD_LOAD for b in op.transfer_bindings]
    assert sorted(loads.count(q) for q in env.state.atoms)==[1,3]
    verify_replay(env,initial,plans)


def test_rotations_do_not_move_atoms_and_empty_circuit_is_noop():
    value=spec(20,'grid',4,5)
    value['gates']=[dict(id=f'h{i}',gate_type='H',qubit_ids=[f'Q{i:03d}'],column=0) for i in range(20)]
    result,env,_,_,plans=run(value)
    assert result.status=='completed' and env.state.time_us==1
    assert all(op.operation_type==K.RAMAN_ROTATION for p in plans for op in p.operations)
    value['gates']=[]
    result,env,_,_,plans=run(value)
    assert result.status=='completed' and env.state.time_us==0 and not plans


def test_failure_keeps_live_state_atomic_and_reports_budget():
    value=spec();original=deepcopy(value)
    result,env,initial,_,plans=run(value,compile_timeout_s=0)
    assert result.status=='stalled' and result.diagnostics[0]['code']=='COMPILE_TIMEOUT'
    assert env.snapshot()==initial and not plans and value==original


def test_readout_reset_and_measurement_dependency_are_preserved():
    from neutral_atom_app.visualization.studio_config import demo_input
    value=demo_input('ordered-qec-ghz2');value.pop('studio')
    value['compilation']=dict(strategy='legacy',implementation='zoned_ids',compile_timeout_s=90)
    value['gates']=[dict(id='h',gate_type='H',qubit_ids=['Q019'],column=0),
                    dict(id='m',gate_type='MEASURE',qubit_ids=['Q019'],column=1),
                    dict(id='r',gate_type='RESET',qubit_ids=['Q019'],column=2),
                    dict(id='x',gate_type='X',qubit_ids=['Q019'],column=3,condition=[['m',1]])]
    result,env,initial,terminal,plans=run(value)
    assert result.status=='completed',result.diagnostics
    assert env.state.dag.completed and set(env.state.measurement_results)=={'m'}
    validate_target(terminal,env.state)
    verify_replay(env,initial,plans)


def test_api_factory_and_workbench_select_same_backend():
    from neutral_atom_app.control import configured_strategy
    from neutral_atom_strategies.api import make_strategy
    value=spec();normalized,*_=build_inputs(value)
    assert configured_strategy(normalized).runner is make_strategy('zoned_ids').runner
    assert normalized['compilation_backend']['kernel']=='zoned-ids-v1'


def test_failed_layer_candidate_does_not_commit_its_partial_staging(monkeypatch):
    from neutral_atom_strategies.zoned.codegen import PhysicalCodegen
    from neutral_atom_env.domain.errors import ValidationError
    def reject(self,p,assignments):
        raise ValidationError('TEST_PULSE_REJECTED','Reject after private transport')
    monkeypatch.setattr(PhysicalCodegen,'cz_group',reject)
    result,env,initial,_,plans=run(spec(2,columns=1),plan_budget=1)
    assert result.status=='stalled' and result.candidate_rejections
    assert result.diagnostics[0]['code']=='ZONED_LAYER_EXHAUSTED'
    assert env.snapshot()==initial and not plans


def test_partial_rectangles_preserve_eight_way_parallelism_across_layers():
    import json
    from pathlib import Path
    value=json.loads((Path(__file__).resolve().parents[1]/'configs/workbench/zoned_repeated16.json').read_text(encoding='utf-8'))
    result,env,initial,_,plans=run(value,restore_layout=False)
    assert result.status=='completed',result.diagnostics
    pulses=[op for p in plans for op in p.operations if op.operation_type==K.ENTANGLING_PULSE]
    assert [len(op.effect_gate_ids) for op in pulses]==[8,8,8,8]
    verify_replay(env,initial,plans)


def test_fixed_terminal_handles_cycle_of_atoms_without_cz():
    from dataclasses import replace
    from neutral_atom_env.world import PlacementState
    value=spec(2,columns=1);value['gates']=[]
    normalized,circuit,platform,mapping=build_inputs(value)
    origin=initialize_input(normalized,circuit,platform,mapping)
    terminal=initial_terminal(origin)
    holders=dict(origin.placement.atom_to_holder)
    holders['Q000'],holders['Q001']=holders['Q001'],holders['Q000']
    env=NeutralAtomEnv(replace(origin,placement=PlacementState(holders)))
    result=run_zoned(env,terminal_target=terminal)
    assert result.status=='completed',result.diagnostics
    validate_target(terminal,env.state)
    assert env.state.metrics()['aod_load_count']>=3


def test_readout_at_ez_edge_places_disabled_spares_inside_world():
    from dataclasses import replace
    from neutral_atom_env.domain.models import HolderRef,HolderType,ZoneType
    from neutral_atom_env.world import PlacementState
    from neutral_atom_strategies.scheduling.readout_placement import ReadoutPlacementPolicy
    from neutral_atom_strategies.motion.single_trap import in_zone
    from neutral_atom_app.visualization.studio_config import demo_input
    value=demo_input('ordered-qec-ghz2')
    normalized,circuit,platform,mapping=build_inputs(value)
    state=initialize_input(normalized,circuit,platform,mapping)
    site=max((t for t in state.world.traps.values() if in_zone(state,t.position,ZoneType.ENTANGLEMENT)
              and t.id not in state.placement.static_occupancy),
             key=lambda t:(t.position.x_um,t.position.y_um))
    holders=dict(state.placement.atom_to_holder);holders['Q000']=HolderRef(HolderType.STATIC,site.id)
    switches=dict(state.slm_enabled);switches[site.id]=True
    state=replace(state,placement=PlacementState(holders),slm_enabled=switches)
    old=ReadoutPlacementPolicy()
    assert not old.candidates(state,['Q000']) and 'AXIS_BOUNDS' in old.generation_rejections
    current=ReadoutPlacementPolicy(bounded_spares=True)
    assert current.candidates(state,['Q000'])
