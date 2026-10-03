import pytest

from neutral_atom_experiments.qec_pbc.backend_contract import (
    AncillaLifecycle, BackendCapabilities, CouplingLayer, canonical_layer_requests,
    layer_requests, lower_coupling_layers, preflight, validate_aod_rectangle,
    validate_global_cz_pairs)


def test_direction_and_layer_barriers():
    layers = (CouplingLayer('one', (('a', 'b'), ('c', 'd'))),
              CouplingLayer('two', (('b', 'a'),)))
    binding = {q: q.upper() for q in 'abcd'}
    request = layer_requests(layers, binding)
    assert request[0].hadamard_targets == ('B', 'D')
    assert request[1].hadamard_targets == ('A',)
    assert request[1].predecessor_layer == 'one'
    gates = lower_coupling_layers(layers, binding).gates
    assert [(g.gate_type, g.qubit_ids) for g in gates[:4]] == [
        ('H', ('B',)), ('H', ('D',)), ('CZ', ('A', 'B')), ('CZ', ('C', 'D'))]
    assert gates[2].depends_on == (gates[0].id, gates[1].id)
    assert gates[6].depends_on == (gates[4].id, gates[5].id)


def test_overlap_rejected():
    with pytest.raises(ValueError, match='disjoint'):
        CouplingLayer('bad', (('a', 'b'), ('b', 'c')))


def test_binding_alias_rejected():
    with pytest.raises(ValueError, match='distinct'):
        layer_requests((CouplingLayer('l', (('a', 'b'),)),), {'a': 'Q0', 'b': 'Q0'})


def test_lifecycle_preflight_is_capability_only():
    cap = BackendCapabilities(34, True, True)
    reuse = preflight(cap, AncillaLifecycle(9, 8, 4))
    assert reuse.compatible and reuse.minimum_atoms == 17
    fresh = preflight(cap, AncillaLifecycle(9, 8, 4, 'fresh'))
    assert fresh.minimum_atoms == 41 and fresh.issues == ('insufficient_atoms',)
    assert preflight(BackendCapabilities(34, False, False),
        AncillaLifecycle(9, 8, 3)).issues == ('measurement_zone_required', 'reuse_requires_reset')
    assert 'unverified' in reuse.claim


def test_exact_pairs_include_spectators_and_radius_boundary():
    positions = {'A': (0, 0), 'B': (6, 0), 'spectator': (30, 0)}
    assert validate_global_cz_pairs(positions, [('B', 'A')], 6) == (('A', 'B'),)
    positions['spectator'] = (0, 4)
    with pytest.raises(ValueError, match='extra'):
        validate_global_cz_pairs(positions, [('A', 'B')], 6)
    with pytest.raises(ValueError, match='missing'):
        validate_global_cz_pairs({'A': (0, 0), 'B': (7, 0)}, [('A', 'B')], 6)


def test_rectangle_cannot_pick_diagonal_only():
    captured = {(0, 0): 'A', (0, 1): 'S', (1, 1): 'B'}
    with pytest.raises(ValueError, match='captures'):
        validate_aod_rectangle((0, 1), (0, 1), captured, ('A', 'B'))
    assert validate_aod_rectangle((0, 1), (0, 1), captured, ('A', 'B', 'S')) == ('A', 'B', 'S')
    with pytest.raises(ValueError, match='offsets'):
        validate_aod_rectangle((0,), (0,), {(0, 0): 'A'}, ('A',),
                              rigid_offsets_before=((0, 0),), rigid_offsets_after=((1, 0),))


def test_structural_canonical_adapter():
    from types import SimpleNamespace
    coupling = lambda r, l, c, t: SimpleNamespace(round_index=r, layer_index=l,
                                               control_role=c, target_role=t)
    memory = SimpleNamespace(couplings=(coupling(0, 1, 'b', 'a'), coupling(0, 0, 'a', 'b')))
    requests = canonical_layer_requests(memory, {'a': 'Q0', 'b': 'Q1'})
    assert requests[0].layer_id == 'round.0.layer.0'
    assert requests[1].directed_pairs == (('Q1', 'Q0'),)


@pytest.mark.parametrize('args', [(9, 8, 0), (True, 8, 3), (9, 8, 3, 'hidden')])
def test_invalid_lifecycle(args):
    with pytest.raises(ValueError):
        AncillaLifecycle(*args)


def test_duplicate_pair_and_ineligible_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        validate_global_cz_pairs({'A': (0, 0), 'B': (1, 0)},
                                 [('A', 'B'), ('B', 'A')], 6)
    with pytest.raises(ValueError, match='eligible'):
        validate_global_cz_pairs({'A': (0, 0)}, [('A', 'B')], 6)


def test_duplicate_layer_ids_rejected():
    layer = CouplingLayer('same', (('a', 'b'),))
    with pytest.raises(ValueError, match='IDs'):
        layer_requests((layer, layer), {'a': 'A', 'b': 'B'})
