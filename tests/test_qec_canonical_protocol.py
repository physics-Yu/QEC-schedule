"""Independent geometry, causal-layer and noiseless instrument acceptance."""
from collections import Counter
from dataclasses import FrozenInstanceError

import pytest

from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.ir import GateTask, MemoryContract, PBCProgram
from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical
from neutral_atom_experiments.qec_pbc.surface import memory_program, stabilizers
from neutral_atom_experiments.qec_pbc.validation import simulate_ideal


# Independent fixture for the official Stim 1.15.0 generator's CNOT ticks after
# reflected-x mapping into this project's established d/check numbering. Each
# tuple names one check ancilla and its data neighbor; X ancillas are controls,
# Z ancillas are targets. All four ticks are needed, including boundaries.
EXPECTED_LAYERS = (
    (('X0', 3), ('X1', 7), ('X2', 1), ('Z0', 4), ('Z1', 6), ('Z3', 8)),
    (('X0', 4), ('X1', 8), ('X2', 2), ('Z0', 1), ('Z1', 3), ('Z3', 5)),
    (('X0', 0), ('X1', 4), ('X3', 6), ('Z0', 5), ('Z1', 7), ('Z2', 3)),
    (('X0', 1), ('X1', 5), ('X3', 7), ('Z0', 2), ('Z1', 4), ('Z2', 0)),
)


def test_all_24_couplings_match_pinned_stim_ticks_and_control_directions():
    source = canonical_memory_program(rounds=1, patch='code.left')
    for layer, expected in enumerate(EXPECTED_LAYERS, start=1):
        pairs = tuple(pair for pair in source.couplings if pair.layer_index == layer)
        assert tuple((p.ancilla_role.removeprefix('code.left.'),
                      int(p.data_role.removeprefix('code.left.d'))) for p in pairs) == expected
        wires = [wire for pair in pairs for wire in (pair.control_role, pair.target_role)]
        assert len(wires) == len(set(wires)) == 12
        for pair in pairs:
            assert pair.control_role == (pair.ancilla_role if '.X' in pair.ancilla_role else pair.data_role)
            assert pair.target_role == (pair.data_role if '.X' in pair.ancilla_role else pair.ancilla_role)
    assert source.source_version == 'v1.15.0'
    assert source.source_commit == '42e0b9e099180e8570407c33f87b4683cac00d81'
    assert source.source_commit in source.source_url
    assert dict(source.role_coordinates) == {
        'code.left.d0': (5, 1), 'code.left.d1': (3, 1), 'code.left.d2': (1, 1),
        'code.left.d3': (5, 3), 'code.left.d4': (3, 3), 'code.left.d5': (1, 3),
        'code.left.d6': (5, 5), 'code.left.d7': (3, 5), 'code.left.d8': (1, 5),
        'code.left.X0': (4, 2), 'code.left.X1': (2, 4),
        'code.left.X2': (2, 0), 'code.left.X3': (4, 6),
        'code.left.Z0': (2, 2), 'code.left.Z1': (4, 4),
        'code.left.Z2': (6, 2), 'code.left.Z3': (0, 4),
    }


@pytest.mark.parametrize('basis', ('X', 'Z'))
@pytest.mark.parametrize('rounds', (1, 3, 5))
def test_round_count_is_total_rounds_with_no_extra_preparation_or_corrections(basis, rounds):
    source = canonical_memory_program(basis=basis, rounds=rounds)
    compiled = lower_to_physical(source.program)
    counts = Counter(g.gate_type for g in compiled.circuit.gates)
    assert counts == {
        'CZ': 24 * rounds, 'H': 56 * rounds + (18 if basis == 'X' else 0),
        'MEASURE': 8 * rounds + 9, 'RESET': 17 + 8 * rounds,
    }
    assert len(source.program.roles) == 17
    assert all(isinstance(op, GateTask) and not op.condition for op in source.program.operations)
    assert all('.r0.' not in op.id and '.correct.' not in op.id for op in source.program.operations)
    assert len(source.program.detectors) == 8 * rounds
    assert source.program.memory_contract.closing_round == rounds
    assert source.program.memory_contract.decoder == 'canonical_detector_memory'
    assert {m.result_id for m in compiled.measurements} == {
        *(f'A.r{r}.{kind}{i}' for r in range(1, rounds + 1)
          for kind in ('X', 'Z') for i in range(4)),
        *(f'A.final.m{i}' for i in range(9)),
    }


def test_parallel_phases_have_wire_disjoint_gates_and_explicit_barriers():
    source = canonical_memory_program()
    op_map = {op.id: op for op in source.program.operations}
    previous = ()
    native = lower_to_physical(source.program)
    native_ids = {gate.id for gate in native.circuit.gates}
    for phase in source.phases:
        ops = tuple(op_map[key] for key in phase.gate_ids)
        assert len({op.gate_type for op in ops}) == 1
        wires = [wire for op in ops for wire in op.targets]
        assert len(wires) == len(set(wires))
        assert phase.depends_on == previous
        assert set(phase.native_gate_ids) <= native_ids
        assert all(not set(op.depends_on) & set(phase.gate_ids) for op in ops)
        if phase.kind == 'ancilla_reset':
            for op in ops:
                assert len(op.depends_on) == 1
                measurement = op_map[op.depends_on[0]]
                assert measurement.gate_type == 'MEASURE' and measurement.targets == op.targets
        else:
            assert all(op.depends_on == previous for op in ops)
        previous = phase.gate_ids
    assert set(p.native_cz_id for p in source.couplings) == {
        g.id for g in native.circuit.gates if g.gate_type == 'CZ'}


@pytest.mark.parametrize('basis', ('X', 'Z'))
def test_detector_boundaries_and_destructive_logical_readout_are_explicit(basis):
    program = canonical_memory_program(basis=basis).program
    first = [d for d in program.detectors if d.boundary == 'known_product_preparation']
    assert len(first) == 4
    assert {d.expression.terms for d in first} == {(f'A.r1.{basis}{i}',) for i in range(4)}
    temporal = [d for d in program.detectors if d.boundary == 'temporal']
    assert {d.expression.terms for d in temporal} == {
        (f'A.r{r-1}.{kind}{i}', f'A.r{r}.{kind}{i}')
        for r in (2, 3) for kind in ('X', 'Z') for i in range(4)}
    # Independent supports include both bulk and boundary checks.
    final_supports = ((0, 1, 3, 4), (4, 5, 7, 8), (1, 2), (6, 7)) if basis == 'X' else (
        (1, 2, 4, 5), (3, 4, 6, 7), (0, 3), (5, 8))
    terminal = [d for d in program.detectors if d.boundary == 'destructive_readout']
    assert tuple(d.expression.terms for d in terminal) == tuple(
        (f'A.r3.{basis}{i}', *(f'A.final.m{q}' for q in support))
        for i, support in enumerate(final_supports))
    logical = (0, 3, 6) if basis == 'X' else (0, 1, 2)
    assert program.observables[0].expression.terms == tuple(f'A.final.m{q}' for q in logical)


@pytest.mark.parametrize('basis', ('X', 'Z'))
@pytest.mark.parametrize('seed', (0, 7, 19))
def test_ideal_memory_keeps_random_sector_stable_and_decodes_zero(basis, seed):
    source = canonical_memory_program(basis=basis)
    compiled = lower_to_physical(source.program)
    state, raw = simulate_ideal(compiled, seed=seed)
    bits = compiled.semantic_results(raw)
    outputs = compiled.classical_outputs(raw)
    assert set(outputs['detectors'].values()) == {0}
    assert outputs['observables'] == {f'A.logical_{basis}': 0}
    for kind in ('X', 'Z'):
        for index in range(4):
            assert bits[f'A.r1.{kind}{index}'] == bits[f'A.r2.{kind}{index}'] == bits[f'A.r3.{kind}{index}']
    physical = dict(compiled.bindings)
    assert all(state.expectation({physical[role.id]: 'Z'}) == 1
               for role in source.program.roles if role.kind == 'syndrome_ancilla')


@pytest.mark.parametrize('basis', ('X', 'Z'))
def test_closing_stabilizers_match_measured_signed_sector_without_initial_correction(basis):
    source = canonical_memory_program(basis=basis, rounds=1)
    prefix = tuple(op for op in source.program.operations if not op.id.startswith('A.final.'))
    compiled = lower_to_physical(PBCProgram(source.program.roles, prefix))
    state, raw = simulate_ideal(compiled, seed=0)
    bits = compiled.semantic_results(raw)
    physical = dict(compiled.bindings)
    opposite = 'Z' if basis == 'X' else 'X'
    assert any(bits[f'A.r1.{opposite}{i}'] == 1 for i in range(4))
    for kind, checks in zip(('X', 'Z'), (stabilizers()[:4], stabilizers()[4:])):
        for index, check in enumerate(checks):
            assert state.expectation(dict(check.mapped(physical).factors)) == (
                -1 if bits[f'A.r1.{kind}{index}'] else 1)


def test_wrapper_is_immutable_serializable_and_legacy_memory_is_unchanged():
    source = canonical_memory_program()
    with pytest.raises(FrozenInstanceError):
        source.phases = ()
    with pytest.raises(FrozenInstanceError):
        source.couplings[0].layer_index = 4
    payload = source.to_dict()
    assert payload['schema'] == 'qec-canonical-memory/1'
    assert payload['source']['commit'] == source.source_commit
    assert payload['phases'][0]['native_gate_ids'] == list(source.phases[0].native_gate_ids)
    assert len(payload['couplings']) == 72
    assert memory_program().memory_contract.decoder == 'perfect_readout_single_data_pauli'
    with pytest.raises(ValueError):
        MemoryContract('A', 'Z', 3, 'A.logical_Z', 'invented_decoder')


@pytest.mark.parametrize('kwargs', (
    {'rounds': 0}, {'rounds': -1}, {'rounds': True}, {'rounds': 1.5},
    {'basis': 'Y'}, {'basis': ''}, {'patch': ''}, {'patch': None},
))
def test_invalid_canonical_frontend_requests_fail(kwargs):
    with pytest.raises(ValueError):
        canonical_memory_program(**kwargs)
