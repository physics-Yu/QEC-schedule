"""Unsupported compiler outputs must not masquerade as physical programs."""
import pytest

from neutral_atom_experiments.qec_pbc.logical_pauli import LogicalGate, compile_logical_pauli
from neutral_atom_experiments.qec_pbc.magic_injection import make_magic_injection
from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical


@pytest.mark.parametrize('program', [
    compile_logical_pauli([LogicalGate('T', ('data',))]),
    make_magic_injection('T', 'data', 'resource', measurement_id='m', provenance='test'),
])
def test_logical_reference_cannot_enter_physical_compiler(program):
    with pytest.raises(TypeError, match='no implemented physical lowering'):
        lower_to_physical(program)
