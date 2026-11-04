"""Compare staged atom events with executed C++ and check explicit grid legality."""

from math import hypot

import pytest

from nadit_physical_compiler.atom_ir import Load, Move, Store
from nadit_physical_compiler.contracts import AtomFragment
from nadit_physical_compiler.motion import check_load, check_move, check_store
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.state import validate_layout
from reference.cases import ReferenceCase


def _audit(case: ReferenceCase, fragment: AtomFragment) -> None:
    layout = case.entry
    moving = {move.atom_id for move in case.moves}
    stationary = {atom.id: atom for atom in layout.atoms if atom.id not in moving}
    validate_layout(case.device, layout)
    for step in fragment.steps:
        for action in step.actions:
            if isinstance(action, Load):
                checked = check_load(
                    case.device,
                    layout,
                    action.grid,
                    {atom: (row, column) for atom, row, column in action.bindings},
                )
                assert action.duration_us == case.device.timing.load_us
            elif isinstance(action, Move):
                checked = check_move(
                    case.device, layout, action.grid, dict(action.targets)
                )
                distances = (
                    hypot(
                        target.x - layout.atom(atom).position.x,
                        target.y - layout.atom(atom).position.y,
                    )
                    for atom, target in action.targets
                )
                assert action.duration_us == pytest.approx(
                    case.device.timing.move_duration(max(distances, default=0))
                )
            else:
                assert isinstance(action, Store)
                checked = check_store(
                    case.device, layout, action.grid, dict(action.bindings)
                )
                assert action.duration_us == case.device.timing.store_us
            assert checked.ok, (case.name, checked.message)
        layout = apply_step(layout, step, case.device)
        validate_layout(case.device, layout)
        for atom_id, atom in stationary.items():
            assert layout.atom(atom_id) == atom
    assert layout == fragment.exit_layout == case.target
    assert fragment.completed_operation_ids == ()
