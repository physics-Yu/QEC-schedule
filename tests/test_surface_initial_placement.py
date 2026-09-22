"""Nonvisual QEC placement boundary tests; full runs live in the CLI artifact."""
from collections import Counter
import pytest
from neutral_atom_experiments.surface_initial_placement import prepare_experiment,candidate_state,shape_translation
from neutral_atom_experiments.surface_qec import simulate_ideal,atom_roles
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_env.program.task_validation import validate_target


@pytest.fixture(scope='module')
def prepared():
    return prepare_experiment()


def test_full_measured_surface_protocol_is_not_replaced_by_cz_only(prepared):
    spec,base,problem,config,search=prepared
    counts=Counter(g.gate_type for g in problem.circuit.gates)
    assert counts['CZ']==105 and counts['MEASURE']==counts['RESET']==32
    assert counts['Y']==1 and len(base.atoms)==34
    assert any(g.condition for g in problem.circuit.gates)
    roles=atom_roles()
    assert Counter(r['role'] for r in roles.values())=={'data':18,'ancilla':16}
    pairs={frozenset(g.qubit_ids) for g in problem.circuit.gates if g.gate_type=='CZ'
           and all(roles[q]['role']=='data' for q in g.qubit_ids)
           and len({roles[q]['patch'] for q in g.qubit_ids})==2}
    assert pairs=={frozenset((f'Q{i:03d}',f'Q{i+9:03d}')) for i in range(9)}
    _,quantum=simulate_ideal(spec['gates'],seed=spec['seed'])
    assert quantum['verified_logical_ghz2'] and quantum['measurement_protocol_complete']


def test_translation_candidates_preserve_every_data_ancilla_offset(prepared):
    spec,base,problem,config,search=prepared
    before=base.snapshot()
    assert config.iterations==0  # Only existing translation seeding, no atom swaps.
    assert search.selected.cost.score_us < search.baseline.cost.score_us
    assert search.selected.mapping!=search.baseline.mapping
    for candidate in search.candidates:
        state=candidate_state(base,candidate)
        dx,dy=shape_translation(base,state)
        assert dx==0 and dy in (-5,0,5,10)
        assert state.world is base.world and state.hardware==base.hardware
        assert state.dag.circuit==base.dag.circuit and state.quantum_state==base.quantum_state
        assert all(state.slm_enabled[h.holder_id] for h in state.placement.atom_to_holder.values())
    assert base.snapshot()==before


def test_common_terminal_is_baseline_not_optimized_origin(prepared):
    _,base,_,_,search=prepared
    terminal=initial_terminal(base)
    validate_target(terminal,base)
    from neutral_atom_env.domain.errors import ValidationError
    with pytest.raises(ValidationError):
        validate_target(terminal,candidate_state(base,search.selected))


def test_finite_footprint_pool_does_not_change_ez_mz_or_physics(prepared):
    spec,base,_,_,_=prepared
    from neutral_atom_experiments.qec_ordered_comparison import make_state
    original=make_state(spec)
    assert original.world.bounds==base.world.bounds and original.world.zones==base.world.zones
    assert original.hardware==base.hardware and original.aod==base.aod
    for key,trap in original.world.traps.items():
        assert base.world.traps[key]==trap
    assert all(k.startswith('INIT_') for k in set(base.world.traps)-set(original.world.traps))
