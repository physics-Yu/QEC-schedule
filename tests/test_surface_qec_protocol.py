import pytest

from neutral_atom_experiments.surface_qec import DATA_IDS, X_CHECKS, Z_CHECKS, X_ORDER, Z_ORDER, protocol, simulate_ideal, decode, correction_table, data


@pytest.mark.parametrize('seed', range(12))
def test_measurement_preparation_random_syndromes_and_optimized_circuit(seed):
    quantum, report = simulate_ideal(seed=seed)
    assert report['verified_logical_ghz2']
    assert report['measurement_protocol_complete']
    assert all(quantum.expectation({f'Q{i:03d}': 'Z'}) == 1 for i in range(18, 34))
    assert len(report['syndrome_bits']) == 32
    assert all(bit == 0 for key, bit in report['syndrome_bits'].items() if key.startswith('final'))
    if seed < 3:
        _, unoptimized = simulate_ideal(protocol(optimize=False)['gates'], seed=seed)
        assert report['syndrome_bits'] == unoptimized['syndrome_bits']
        assert unoptimized['verified_logical_ghz2']


@pytest.mark.parametrize('qubit', DATA_IDS)
@pytest.mark.parametrize('pauli', ('X', 'Y', 'Z'))
def test_all_54_single_data_faults_measured_and_corrected(qubit, pauli):
    index = int(qubit[1:])
    _, report = simulate_ideal(seed=100+index, fault={'pauli': pauli, 'qubit_id': qubit})
    assert report['verified_logical_ghz2']
    for block in range(2):
        for kind, checks in (('X', X_CHECKS), ('Z', Z_CHECKS)):
            for i, check in enumerate(checks):
                expected = int(block == index//9 and index % 9 in check and pauli != kind)
                assert report['syndrome_bits'][f'final_{kind}{block}_{i}'] == expected
    assert decode(report['syndrome_bits'])


def test_protocol_dependencies_readout_reset_and_hook_orientation():
    definition = protocol()
    assert definition['optimization'] == {
        'raw_gate_slots': 604, 'optimized_gate_slots': 480, 'cancelled_H_pairs': 62}
    seen = set()
    for gate in sorted(definition['gates'], key=lambda g: (g['column'], g['id'])):
        assert set(gate.get('depends_on', ())) <= seen
        assert all(ref in seen for ref, _ in gate.get('condition', ()))
        seen.add(gate['id'])
    for order in (X_ORDER, Z_ORDER):
        for layer in range(4):
            targets = [check[layer] for check in order if layer < len(check)]
            assert len(set(targets)) == len(targets)
    # X hooks horizontal; Z hooks vertical, transverse to respective logical strings.
    assert all(a//3 == b//3 for *_, a, b in X_ORDER[:2])
    assert all(a % 3 == b % 3 for *_, a, b in Z_ORDER[:2])
    for kind in ('X', 'Z'):
        assert len(correction_table(kind)) == 16


def test_no_oracle_correction_and_negative_control_missing_recovery():
    definition = protocol({'pauli': 'X', 'qubit_id': 'Q004'})
    final_corrections = {item['gate_id'] for item in definition['stages'] if item['stage'] == 'final-correction'}
    gates = [gate for gate in definition['gates'] if gate['id'] not in final_corrections]
    _, broken = simulate_ideal(gates, seed=9)
    assert not broken['verified_logical_ghz2']
    assert any(value == -1 for value in broken['stabilizer_expectations'].values())
    with pytest.raises(KeyError):
        decode({})  # cannot infer an error from metadata or missing readouts


def test_exit_frontier_barriers_cover_all_previous_stage_operations():
    definition = protocol({'pauli': 'Y', 'qubit_id': 'Q013'})
    stages = {item['gate_id']: item['stage'] for item in definition['stages']}
    closure = {}
    last = {}
    groups = {}
    for gate in sorted(definition['gates'], key=lambda g: (g['column'], g['id'])):
        parents = set(gate.get('depends_on', ())) | {ref for ref, _ in gate.get('condition', ())}
        parents.update(last[q] for q in gate['qubit_ids'] if q in last)
        closure[gate['id']] = parents | set().union(*(closure[p] for p in parents))
        groups.setdefault(stages[gate['id']], []).append(gate['id'])
        for q in gate['qubit_ids']:
            last[q] = gate['id']
    names = list(groups)
    for previous, following in zip(names, names[1:]):
        assert set(groups[previous]) <= closure[groups[following][0]]
    assert max(len(g.get('depends_on', ())) for g in definition['gates']) <= 34


def test_missing_check_coupling_or_reset_not_reported_as_complete_protocol():
    gates = protocol()['gates']
    coupling = next(g['id'] for g in gates if g['gate_type'] == 'CZ' and 'Q018' in g['qubit_ids'])
    _, report = simulate_ideal([g for g in gates if g['id'] != coupling], seed=4)
    assert not report['measurement_protocol_complete']


def test_dependency_reduction_preserves_every_gate_ancestor_set_independently():
    def ancestors(gates):
        result = {}
        wires = {}
        for gate in sorted(gates, key=lambda g: (g['column'], g['id'])):
            parents = set(gate.get('depends_on', ())) | {ref for ref, _ in gate.get('condition', ())}
            parents.update(wires[q] for q in gate['qubit_ids'] if q in wires)
            result[gate['id']] = parents | set().union(*(result[parent] for parent in parents))
            for q in gate['qubit_ids']:
                wires[q] = gate['id']
        return result
    for fault in (None, {'pauli': 'Z', 'qubit_id': 'Q010'}):
        before = protocol(fault, reduce_edges=False)['gates']
        after = protocol(fault)['gates']
        assert ancestors(before) == ancestors(after)
        assert [{k: v for k, v in gate.items() if k != 'depends_on'} for gate in before] == [
            {k: v for k, v in gate.items() if k != 'depends_on'} for gate in after]
        assert sum(len(g.get('depends_on', ())) for g in after) < 1100
        assert sum(len(g.get('depends_on', ())) for g in after) < sum(
            len(g.get('depends_on', ())) for g in before) / 9
