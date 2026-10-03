"""Regress source-valid but target-invalid first-column rigid embeddings."""
import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler
from neutral_atom_experiments.qec_pbc.encoded_physical import encoded_parity_inputs
from neutral_atom_experiments.qec_pbc.encoded_ppm import encoded_parity_program


def test_full_array_uses_another_column_for_c_patch_shift_without_changing_world():
    inputs, _ = encoded_parity_inputs(encoded_parity_program())
    state = inputs.create_environment().state
    atom = dict(inputs.compiled.bindings)['C.X0']
    point = state.placement.position(atom, state.world, state.aod)
    compiler = PatchArrayCompiler()
    shift = (8., -10.)
    # This is the failed old embedding: first column fits source but not target.
    assert point.x_um + 70 <= state.world.bounds.upper.x_um
    assert point.x_um + 70 + shift[0] > state.world.bounds.upper.x_um
    origin, bindings = compiler.bindings(state, (atom,), required_shifts=(shift,))
    assert bindings[0].cell.column > 0
    assert origin.x_um < point.x_um
    for dx, dy in ((0., 0.), shift):
        assert state.world.bounds.lower.x_um <= origin.x_um + dx
        assert origin.x_um + 70 + dx <= state.world.bounds.upper.x_um
        assert state.world.bounds.lower.y_um <= origin.y_um + dy
        assert origin.y_um + 30 + dy <= state.world.bounds.upper.y_um
    assert state.world == inputs.platform.world
    assert state.hardware == inputs.platform.hardware


def test_no_valid_axis_embedding_remains_explicitly_rejected():
    inputs, _ = encoded_parity_inputs(encoded_parity_program())
    state = inputs.create_environment().state
    with pytest.raises(ValidationError) as error:
        PatchArrayCompiler().bindings(state, ('Q000',), required_shifts=((1000., 0.),))
    assert error.value.violation.code == 'PATCH_AOD_BOUNDS'
