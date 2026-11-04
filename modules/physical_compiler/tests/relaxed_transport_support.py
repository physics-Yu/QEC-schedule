"""Device-admitted relaxed batches preserve active line order at every move."""

from nadit_physical_compiler.atom_ir import Move
from nadit_physical_compiler.contracts import AtomFragment
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.state import AODHolder, AODLine
from reference.cases import ReferenceCase


def _order(lines: tuple[AODLine, ...]) -> tuple[int, ...]:
    return tuple(line.id for line in sorted(lines, key=lambda line: line.coordinate))


def _peak_carried(case: ReferenceCase, fragment: AtomFragment) -> int:
    layout = case.entry
    peak = 0
    for step in fragment.steps:
        for action in step.actions:
            if isinstance(action, Move):
                before = layout.grid(action.grid.aod_id)
                assert _order(before.rows) == _order(action.grid.rows)
                assert _order(before.columns) == _order(action.grid.columns)
        layout = apply_step(layout, step, case.device)
        peak = max(
            peak,
            sum(isinstance(atom.holder, AODHolder) for atom in layout.atoms),
        )
    return peak
