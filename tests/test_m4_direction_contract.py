"""The isotropic project CZ proxy: separation, zone and unintended pairs.

These tests verify the declared kinematic model, not experimental fidelity.
See docs/m4_physics_research.md for the distinction and primary sources.
"""
from dataclasses import replace

import pytest

from test_m4 import make, execute
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderRef, HolderType, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget
from neutral_atom_env.hardware import get_backend
from neutral_atom_strategies.motion.persistent import PersistentTargetCompiler


@pytest.mark.parametrize('dx,dy', [(-2, 0), (2, 0), (0, -2), (0, 2), (0, 4)])
def test_ez_cz_accepts_four_two_um_directions_but_not_four_um(dx, dy):
    state = make([('CZ', (0, 1))], n=2)
    site = state.world.traps['EZ0'].position
    axes = replace(state.aod.configuration(), x_um=(site.x_um+dx,), y_um=(site.y_um+dy,))
    target = TaskTarget((('Q000', HolderRef(HolderType.STATIC, 'EZ0')),
                         ('Q001', HolderRef(HolderType.MOBILE, MobileCellIndex(0, 0)))), axes)
    execute(state, PersistentTargetCompiler().compile(TaskIntent('prepare-direction', target), state))
    before = state.snapshot()
    if dy == 4:
        with pytest.raises(ValidationError, match='UNINTENDED_PAIR'):
            get_backend(state.hardware).validate_pulse(state, 'g0')
    else:
        assert get_backend(state.hardware).validate_pulse(state, 'g0') == frozenset({('Q000', 'Q001')})
    assert state.snapshot() == before
