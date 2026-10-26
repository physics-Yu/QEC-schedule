"""Coordinate/identity rebinding of immutable atom-action templates."""

from collections.abc import Mapping
from dataclasses import replace

from nadit_physical_compiler.atom_ir import (
    AtomAction,
    AtomProgram,
    AtomStep,
    CZPulse,
    Load,
    LocalU,
    Measure,
    Move,
    Reset,
    Rotation,
    Store,
    Wait,
)
from nadit_physical_compiler.coverage import RegionSet
from nadit_physical_compiler.device import Position, Region
from nadit_physical_compiler.physical_ir import ResultRef
from nadit_physical_compiler.state import AODGrid


def shift_position(point: Position, shift: Position) -> Position:
    """Translate a position without changing its local displacement."""
    return Position(point.x + shift.x, point.y + shift.y)


def _coverage(
    value: Region | RegionSet | tuple[int, ...],
    shift: Position,
    atoms: Mapping[int, int],
) -> Region | RegionSet | tuple[int, ...]:
    if isinstance(value, tuple):
        return tuple(atoms[a] for a in value)
    if isinstance(value, RegionSet):
        return RegionSet(tuple(_region(r, shift) for r in value.regions))
    return _region(value, shift)


def _region(region: Region, shift: Position) -> Region:
    return Region(
        region.x_min + shift.x,
        region.y_min + shift.y,
        region.x_max + shift.x,
        region.y_max + shift.y,
    )


def _grid(grid: AODGrid, shift: Position, aod_id: str) -> AODGrid:
    return AODGrid(
        aod_id,
        tuple(replace(r, coordinate=r.coordinate + shift.y) for r in grid.rows),
        tuple(replace(c, coordinate=c.coordinate + shift.x) for c in grid.columns),
    )


def rebind_program(
    program: AtomProgram,
    *,
    shift: Position,
    atoms: Mapping[int, int],
    sites: Mapping[str, str],
    channels: Mapping[str, str],
    aod_id: str,
    results: Mapping[int, int],
) -> AtomProgram:
    """Translate coordinates and remap all executable references, preserving time.

    Geometry/capacity/timing admission is a separate mandatory step performed by
    the caller. Unsupported action kinds fail explicitly instead of being copied.
    """
    steps = []
    for step in program.steps:
        actions = []
        for action in step.actions:
            bound: AtomAction
            if isinstance(action, Load):
                bound = replace(
                    action,
                    grid=_grid(action.grid, shift, aod_id),
                    bindings=tuple((atoms[a], r, c) for a, r, c in action.bindings),
                )
            elif isinstance(action, Move):
                bound = replace(
                    action,
                    grid=_grid(action.grid, shift, aod_id),
                    targets=tuple(
                        (atoms[a], shift_position(p, shift)) for a, p in action.targets
                    ),
                )
            elif isinstance(action, Store):
                bound = replace(
                    action,
                    grid=_grid(action.grid, shift, aod_id),
                    bindings=tuple((atoms[a], sites[s]) for a, s in action.bindings),
                )
            elif isinstance(action, CZPulse):
                bound = replace(
                    action,
                    channel=channels["cz"],
                    coverage=_coverage(action.coverage, shift, atoms),
                )
            elif isinstance(action, Rotation | LocalU | Reset):
                bound = replace(
                    action,
                    channel=channels["local"],
                    atoms=tuple(atoms[a] for a in action.atoms),
                )
            elif isinstance(action, Measure):
                bound = replace(
                    action,
                    channel=channels["readout"],
                    results=tuple(
                        (atoms[a], ResultRef(results[r.measurement_id]))
                        for a, r in action.results
                    ),
                )
            elif isinstance(action, Wait):
                bound = action
            else:
                raise TypeError(
                    f"Unsupported component action {type(action).__name__}."
                )
            actions.append(bound)
        steps.append(AtomStep(tuple(actions)))
    return AtomProgram(tuple(steps), program.global_phase)
