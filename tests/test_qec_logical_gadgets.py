import pytest
from neutral_atom_experiments.qec_pbc.logical_gadgets import (
    conjugate_sequence, d3_patch, logical_hadamard, transversal_cnot, transversal_cz)


def product(a, b):
    phase, p = a.multiply(b)
    assert phase in (1, -1)
    return type(p)(p.factors, int(phase.real))


@pytest.mark.parametrize('orientation', ['standard', 'dual'])
def test_transversal_preserves_stabilizer_group_and_logical_map(orientation):
    gadget = transversal_cnot('A', 'B', control_orientation=orientation,
                              target_orientation=orientation)
    a, b = gadget.control, gadget.target
    for sa, sb in zip(a.x_checks, b.x_checks):
        assert conjugate_sequence(sa, gadget.gates) == product(sa, sb)
        assert conjugate_sequence(sb, gadget.gates) == sb
    for sa, sb in zip(a.z_checks, b.z_checks):
        assert conjugate_sequence(sa, gadget.gates) == sa
        assert conjugate_sequence(sb, gadget.gates) == product(sa, sb)
    images = dict(gadget.logical_images)
    assert images == {'X_control': product(a.logical_x, b.logical_x),
        'Z_control': a.logical_z, 'X_target': b.logical_x,
        'Z_target': product(a.logical_z, b.logical_z)}
    binding = {q: f'Q{i:03d}' for i, q in enumerate((*a.data_roles, *b.data_roles))}
    assert len(gadget.backend_requests(binding)[0].directed_pairs) == 9
    assert len(gadget.physical_coupling(binding).gates) == 27


@pytest.mark.parametrize('orientation', ['standard', 'dual'])
def test_h_updates_checks_and_boundaries(orientation):
    g = logical_hadamard('A', orientation=orientation)
    assert g.output_patch.orientation != orientation
    assert tuple(conjugate_sequence(s, g.gates) for s in g.input_patch.x_checks) == g.output_patch.z_checks
    assert tuple(conjugate_sequence(s, g.gates) for s in g.input_patch.z_checks) == g.output_patch.x_checks
    assert dict(g.logical_images) == {'X': g.output_patch.logical_z, 'Z': g.output_patch.logical_x}
    assert logical_hadamard('A', orientation=g.output_patch.orientation).output_patch == g.input_patch
    assert len(g.physical_circuit({q: f'Q{i:03d}' for i, q in enumerate(g.input_patch.data_roles)}).gates) == 9


def test_fail_closed_orientation_and_cz_shortcut():
    with pytest.raises(ValueError, match='permutation'):
        transversal_cnot('A', 'B', target_orientation='dual')
    with pytest.raises(ValueError, match='distinct'):
        transversal_cnot('A', 'A')
    with pytest.raises(ValueError, match='shortcut'):
        transversal_cz('A', 'B')
    with pytest.raises(ValueError, match='Orientation'):
        d3_patch('A', orientation='rotated_unknown')
