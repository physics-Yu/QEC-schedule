from itertools import combinations, product

import pytest

from neutral_atom_env.circuit import DynamicGateDAG
from neutral_atom_experiments.qec_pbc import (
    BitExpr, GateTask, PauliMeasurement, PauliProduct, PBCProgram, Role,
    decode_ideal_memory, logical_product, lower_to_physical, memory_program,
    patch_roles, stabilizers, syndrome_round)
from neutral_atom_experiments.qec_pbc import build_native_qec_inputs, d3_role_bindings
from neutral_atom_experiments.qec_pbc.validation import bell_parity_program, simulate_ideal


def test_d3_code_rank_distance_and_logical_algebra():
    checks = stabilizers()
    assert len(checks) == 8
    assert all(a.commutes_with(b) for a, b in combinations(checks, 2))
    rows = []
    for check in checks:
        rows.append(sum(1 << (int(q[3:]) + (9 if p == 'Z' else 0)) for q, p in check.factors))
    pivots = {}
    for row in rows:
        while row:
            pivot = row.bit_length() - 1
            if pivot in pivots:
                row ^= pivots[pivot]
            else:
                pivots[pivot] = row
                break
    assert len(pivots) == 8
    lx = logical_product(PauliProduct((('A', 'X'),)))
    lz = logical_product(PauliProduct((('A', 'Z'),)))
    assert not lx.commutes_with(lz)
    assert all(check.commutes_with(lx) and check.commutes_with(lz) for check in checks)
    for weight in (1, 2):
        for locations in combinations(range(9), weight):
            for bases in product('XYZ', repeat=weight):
                error = PauliProduct(tuple((f'A.d{q}', p) for q, p in zip(locations, bases)))
                if all(error.commutes_with(check) for check in checks):
                    assert error.commutes_with(lx) and error.commutes_with(lz)
    assert len(lx.support) == len(lz.support) == 3
    ly = logical_product(PauliProduct((('A', 'Y'),)))
    assert ly.to_dict() == {'sign': 1, 'factors': [
        ['A.d0', 'Y'], ['A.d1', 'Z'], ['A.d2', 'Z'], ['A.d3', 'X'], ['A.d6', 'X']]}


def test_round_counts_and_original_hook_orders_are_retained():
    ops = syndrome_round()
    assert len(patch_roles('A')) == 17
    assert len(ops) == 8 and sum(len(op.product.support) for op in ops) == 24
    assert ops[4].coupling_order == ('A.d1', 'A.d4', 'A.d2', 'A.d5')
    assert all(op.purpose == 'syndrome' for op in ops)
    native = lower_to_physical(PBCProgram(patch_roles('A'), ops))
    assert sum(g.gate_type == 'CZ' for g in native.circuit.gates) == 24


@pytest.mark.parametrize('basis', ['X', 'Z'])
@pytest.mark.parametrize('seed', range(5))
def test_memory_measurement_preparation_boundaries_and_outputs(basis, seed):
    compiled = lower_to_physical(memory_program(basis=basis, rounds=3))
    state, raw = simulate_ideal(compiled, seed=seed)
    outputs = compiled.classical_outputs(raw)
    assert len(outputs['detectors']) == 32
    assert set(outputs['detectors'].values()) == {0}
    assert list(outputs['observables'].values()) == [0]
    assert decode_ideal_memory(compiled.program, compiled.semantic_results(raw)) == 0
    binding = dict(compiled.bindings)
    assert all(state.expectation({binding[role.id]: 'Z'}) == 1 for role in
               compiled.program.roles if role.kind == 'syndrome_ancilla')


@pytest.mark.parametrize('basis', ['X', 'Z'])
@pytest.mark.parametrize('kind', ['X', 'Y', 'Z'])
@pytest.mark.parametrize('local', range(9))
def test_measured_only_frame_recovers_all_single_data_paulis(basis, kind, local):
    compiled = lower_to_physical(memory_program(basis=basis, rounds=2))
    _, raw = simulate_ideal(compiled, seed=local, fault_before=('A.r2.X0', f'A.d{local}', kind))
    bits = compiled.semantic_results(raw)
    for op in syndrome_round('A', 2):
        fault = PauliProduct(((f'A.d{local}', kind),))
        assert bits[op.id] == int(not fault.commutes_with(op.product))
    assert decode_ideal_memory(compiled.program, bits) == 0
    with pytest.raises(KeyError):
        decode_ideal_memory(compiled.program, {})


@pytest.mark.parametrize('seed', range(5))
def test_logical_pbc_parity_creates_encoded_bell_state(seed):
    compiled = lower_to_physical(bell_parity_program())
    state, raw = simulate_ideal(compiled, seed=seed)
    binding = dict(compiled.bindings)
    for patch in ('A', 'B'):
        assert all(state.expectation(dict(check.mapped(binding).factors)) == 1
                   for check in stabilizers(patch))
    for kind in ('X', 'Z'):
        word = logical_product(PauliProduct((('A', kind), ('B', kind)))).mapped(binding)
        assert state.expectation(dict(word.factors)) == 1
    assert compiled.semantic_results(raw)['bell.XX'] == 0
    assert state.expectation({binding['bus']: 'Z'}) == 1


def test_overlapping_measurements_wait_for_complete_instrument_exit():
    roles = tuple(Role(q, 'data') for q in ('q0', 'q1')) + tuple(
        Role(q, 'parity_ancilla') for q in ('a', 'b'))
    ops = tuple(PauliMeasurement(key, PauliProduct((('q0', p), ('q1', p))), anc,
                ('q0', 'q1')) for key, p, anc in (('A', 'X', 'a'), ('B', 'Z', 'b')))
    compiled = lower_to_physical(PBCProgram(roles, ops))
    dag = DynamicGateDAG(compiled.circuit)
    parents = {key: set() for key in dag.nodes}
    for key, node in dag.nodes.items():
        for child in node.successors:
            parents[child].add(key)
    closure = {}
    for gate in compiled.circuit.gates:
        closure[gate.id] = parents[gate.id] | set().union(*(closure[p] for p in parents[gate.id]))
    exits = dict(compiled.exits)
    first_b = next(g for g, op, _ in compiled.provenance if op == 'B')
    assert set(exits['A']) <= closure[first_b]


def test_signed_readout_native_condition_and_classical_xor_remain_distinct():
    roles = (Role('q', 'data'), Role('a', 'parity_ancilla'))
    measure = PauliMeasurement('minusZ', PauliProduct((('q', 'Z'),), -1), 'a', ('q',))
    correction = GateTask('correct', 'X', ('q',), condition=(('minusZ', 1),))
    compiled = lower_to_physical(PBCProgram(roles, (measure, correction)))
    _, raw = simulate_ideal(compiled)
    bits = compiled.semantic_results(raw)
    assert bits['minusZ'] == 1
    assert compiled.circuit.gates[-1].condition == ((compiled.measurements[0].raw_gate_id, 0),)
    assert BitExpr(('a', 'b'), 1).evaluate({'a': 1, 'b': 0}) == 0
    with pytest.raises(KeyError):
        compiled.semantic_results({})


def test_unsupported_capabilities_and_invalid_roles_fail_explicitly():
    roles = (Role('q', 'data'), Role('a', 'parity_ancilla'))
    op = PauliMeasurement('y', PauliProduct((('q', 'Y'),)), 'a', ('q',))
    program = PBCProgram(roles, (op,))
    with pytest.raises(ValueError, match='S/Sdg'):
        lower_to_physical(program)
    with pytest.raises(ValueError, match='fault-tolerant'):
        lower_to_physical(program, require_fault_tolerant=True)
    with pytest.raises(ValueError, match='distinct physical'):
        lower_to_physical(program, {'q': 'Q000', 'a': 'Q000'})
    with pytest.raises(ValueError, match='earlier semantic'):
        PBCProgram(roles, (GateTask('bad', 'X', ('q',), condition=(('missing', 1),)),))
    with pytest.raises(ValueError, match='each factor'):
        PauliMeasurement('bad', PauliProduct((('q', 'X'),)), 'a', ('q', 'q'))


def test_decoder_contract_is_explicit_and_rejects_edited_checks():
    from dataclasses import replace
    source = memory_program(basis='Z', patch='A.logical_X', rounds=1)
    compiled = lower_to_physical(replace(source, name='renamed-program'))
    _, raw = simulate_ideal(compiled, fault_before=('A.logical_X.r1.X0', 'A.logical_X.d0', 'X'))
    assert decode_ideal_memory(compiled.program, compiled.semantic_results(raw)) == 0
    bits = compiled.semantic_results(raw)
    bits['A.logical_X.r1.Z0'] = True
    with pytest.raises(ValueError, match='integer bits'):
        decode_ideal_memory(compiled.program, bits)
    edited = tuple(replace(op, product=PauliProduct(op.product.factors, -1))
                   if op.id == 'A.logical_X.r1.Z0' else op for op in source.operations)
    bad_program = replace(source, operations=edited)
    with pytest.raises(ValueError, match='positive d3'):
        decode_ideal_memory(bad_program, {})
    with pytest.raises(ValueError, match='AND-of'):
        GateTask('malformed', 'X', ('q',), condition=((),))


def test_native_adapter_keeps_complete_platform_and_rejects_extra_bus():
    from dataclasses import replace
    check = replace(syndrome_round()[6], depends_on=())
    program = PBCProgram(patch_roles('A'), (check,))
    inputs = build_native_qec_inputs(program, seed=7)
    assert inputs.circuit == inputs.compiled.circuit
    assert d3_role_bindings(program)['A.d0'] == 'Q000'
    assert d3_role_bindings(program)['A.Z2'] == 'Q024'
    env = inputs.create_environment()
    assert len(env.state.atoms) == len(env.state.quantum_state.qubit_ids) == 34
    assert len(inputs.compiled.bindings) == 17
    assert env.state.time_us == 0
    with pytest.raises(ValueError, match='explicit native bindings'):
        build_native_qec_inputs(bell_parity_program())
    mapping = d3_role_bindings(program)
    mapping['A.d0'] = 'Q999'
    with pytest.raises(ValueError, match='existing 34-atom'):
        build_native_qec_inputs(program, mapping)
