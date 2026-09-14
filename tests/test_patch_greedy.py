import json
from dataclasses import replace
import pytest
from neutral_atom_experiments.surface_ghz import experiment_input
from neutral_atom_app.visualization.workbench import build_inputs
from neutral_atom_env.platform import initialize
from neutral_atom_strategies.scheduling.patch_greedy import run_patch, candidate_groups
from neutral_atom_strategies.scheduling.patch_greedy import spatial_components, preflight_group, patch_assignment
from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.replay.operation_codec import event_from_dict
from neutral_atom_env.simulation.executor import Executor


def initial(gates):
    value=experiment_input() | {'gates':gates}
    _,c,p,l=build_inputs(value)
    return initialize(c,p,l)


def layer():
    return [{'id':f'parallel-{i}','gate_type':'CZ','qubit_ids':[f'Q{i:03}',f'Q{i+18:03}'],'column':0}
            for i in range(18)]


@pytest.mark.parametrize('strategy',['patch_symmetric','patch_greedy'])
def test_eighteen_actual_parallel_pairs_skip_patch_gap_and_replay(strategy):
    state=initial(layer());result=run_patch(state,strategy=strategy,candidate_budget=16)
    assert result.status=='completed',result.diagnostics
    assert max(d.get('batch_size',0) for d in result.decision_log)==18
    pulses=[json.loads(r) for r in state.trace.records if json.loads(r).get('effect_completed')]
    assert len(pulses)==1 and len(pulses[0]['effect_gate_ids'])==18
    assert state.metrics()['aod_load_count']==3  # stage, eighteen partners, return
    assert all(h.holder_id==f'S{i:03}' for i,(_,h) in enumerate(sorted(state.placement.atom_to_holder.items())))
    replay=initial(layer())
    for raw in state.trace.records:
        event=event_from_dict(json.loads(raw)['event'])
        if event.event_type.value=='plan_started':
            executor=Executor(replay);executor.submit(event.plan);executor.run()
    assert replay.snapshot()==state.snapshot()


def test_nonuniform_rigid_axes_are_preserved_and_subset_alignment_uses_real_axes():
    state=initial(layer());compiler=PatchArrayCompiler()
    moved=get_backend(state.hardware).target_aod(state.aod,Position2D(2.5,-2.5))
    assert moved.configuration().x_um==(2.5,12.5,22.5,42.5,52.5,62.5)
    assert moved.configuration().y_um==(-2.5,7.5,17.5,37.5,47.5,57.5)
    # Source coordinates 20 and40 need retained nonuniform axis indices,
    # not round((position-minimum)/spacing), which would invent missing30.
    origin,bindings=compiler.bindings(state,['Q002','Q009'])
    assert tuple(state.aod.configured(state.aod.configuration().translated(origin.x_um,origin.y_um)).position(b.cell)
                 for b in bindings)==(Position2D(20,0),Position2D(40,0))


def test_arbitrary_circuit_names_single_qubit_types_and_empty_terminal():
    gates=[{'id':'custom-H','gate_type':'H','qubit_ids':['Q005'],'column':0},
           {'id':'custom-T','gate_type':'T','qubit_ids':['Q032'],'column':0},
           {'id':'edited-cross','gate_type':'CZ','qubit_ids':['Q005','Q032'],'column':1},
           {'id':'custom-X','gate_type':'X','qubit_ids':['Q005'],'column':2}]
    state=initial(gates);result=run_patch(state,strategy='patch_symmetric',candidate_budget=16)
    assert result.status=='completed',result.diagnostics
    assert state.metrics()['completed_gate_count']==4
    state=initial([]);before=state.snapshot();assert run_patch(state).status=='completed'
    assert state.snapshot()==before


def test_three_corner_group_keeps_legal_two_atom_cartesian_subsets():
    from neutral_atom_env.domain.models import HolderRef, HolderType
    from neutral_atom_env.world import PlacementState
    from neutral_atom_env.domain.errors import ValidationError
    gates=[{'id':f'local-{b}','gate_type':'CZ','qubit_ids':[f'Q{9*b:03}',f'Q{9*b+1:03}'],'column':0}
           for b in range(3)]
    state=initial(gates);destinations=patch_assignment(state)
    state=replace(state,placement=PlacementState({q:HolderRef(HolderType.STATIC,s) for q,s in destinations.items()}),
        slm_enabled={s:s in set(destinations.values()) for s in state.world.traps})
    assert len(set(spatial_components(state).values()))==4
    choices=candidate_groups(state,list(state.dag.ready_gates()),'patch_greedy')
    desired=(('local-0','Q000','Q001'),('local-1','Q009','Q010'))
    assert ((-8.,0.),desired) in choices
    preflight_group(state,PatchArrayCompiler(),(-8.,0.),desired)
    with pytest.raises(ValidationError,match='also capture'):
        preflight_group(state,PatchArrayCompiler(),(-8.,0.),desired+(('local-2','Q018','Q019'),))
