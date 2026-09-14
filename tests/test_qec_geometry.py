from types import SimpleNamespace

from neutral_atom_env.experiments.qec_layout import build_qec_inputs
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.simulation.patch_greedy import patch_assignment, preflight_group, batch_service
from neutral_atom_env.simulation.qec import measurement_destinations, readout_groups, qec_cz_groups
from neutral_atom_env.motion.patch_array import PatchArrayCompiler
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget
from neutral_atom_env.domain.models import ZoneType
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.motion.single_trap import in_zone


def staged(gates=()):
    value,circuit,platform,placement=build_qec_inputs({'gates':list(gates)})
    state=initialize(circuit,platform,placement)
    builder=ProgramBuilder(state,TaskIntent('stage-test',TaskTarget(),frozenset(state.atoms),phase='prepare'))
    PatchArrayCompiler().transfer_group(builder,patch_assignment(state))
    return builder


def test_sparse_sixteen_ancilla_footprint_fits_readout_without_invented_corner():
    builder=staged();compiler=PatchArrayCompiler();state=builder.state
    ancillas=tuple(f'Q{i:03d}' for i in range(18,34))
    source={q:state.placement.atom_to_holder[q].holder_id for q in ancillas}
    destinations=measurement_destinations(state,ancillas)
    compiler.transfer_group(builder,destinations[0])
    assert all(in_zone(builder.state,builder.state.placement.position(q,builder.state.world,builder.state.aod),ZoneType.MEASUREMENT) for q in ancillas)
    for q in state.atoms:
        if q not in ancillas:
            assert builder.state.placement.atom_to_holder[q]==state.placement.atom_to_holder[q]
    compiler.transfer_group(builder,source)
    assert builder.state.placement==state.placement


def test_skip_rows_readout_group_closes_rectangular_four_ancilla_subset():
    state=staged().state
    ids=[f'Q{i:03d}' for i in (18,19,20,21,26,27,28,29)]
    groups=list(readout_groups(state,[SimpleNamespace(id=q,qubit_ids=(q,)) for q in ids]))
    expected={'Q018','Q021','Q026','Q029'}
    assert any({g.id for g in group}==expected for group in groups)
    compiler=PatchArrayCompiler()
    builder=ProgramBuilder(state,TaskIntent('skip-rows',TaskTarget(),frozenset(expected),phase='prepare'))
    compiler.transfer_group(builder,measurement_destinations(state,expected)[0])
    assert len(builder.state.placement.mobile_occupancy)==0


def test_nine_transversal_pairs_are_a_real_valid_batch_with_ancilla_spectators():
    gates=[{'id':f'cx-{i}','gate_type':'CZ','qubit_ids':[f'Q{i:03d}',f'Q{i+9:03d}'],'column':0} for i in range(9)]
    state=staged(gates).state;compiler=PatchArrayCompiler()
    choices=qec_cz_groups(state,list(state.dag.ready_gates()))
    for shift,members in choices:
        if len(members)!=9:continue
        try:
            preflight_group(state,compiler,shift,members)
            plan=batch_service(state,compiler,shift,members)
        except ValidationError:
            continue
        assert len(plan.intent.gate_ids)==9
        assert len(plan.predicted_placement)==34
        break
    else:
        raise AssertionError('No physical nine-pair transversal batch with 16 spectators')
