"""Bounded orthogonal routes that may settle individual ordered axes early.

This is a strategy, not a new freedom for individual Cartesian intersections.
Every proposed segment still requires the complete physical swept validator.
"""
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError
from .ordered_routes import discrete_corridor_routes, merge_straight_runs


def settle_axes(points, axes=(0, 1)):
    """Clamp selected axes at their target on first crossing; then hold them.

    Finite coordinate transforms can be obstructed or change inter-atom timing.
    They are only candidates; callers must not treat this as a legality proof.
    """
    target = points[-1]
    final = (target.x_um, target.y_um)
    held = [[v == t for v, t in zip(values, goals)]
            for values, goals in zip((points[0].x_um, points[0].y_um), final)]
    out = [points[0]]
    for previous, point in zip(points, points[1:]):
        values = [list(point.x_um), list(point.y_um)]
        for axis in axes:
            old = previous.x_um if axis == 0 else previous.y_um
            for i, goal in enumerate(final[axis]):
                if min(old[i], values[axis][i]) <= goal <= max(old[i], values[axis][i]):
                    held[axis][i] = True
                if held[axis][i]:
                    values[axis][i] = goal
        out.append(AODConfiguration(tuple(values[0]), tuple(values[1])))
    return merge_straight_runs(out)


def axis_hold_routes(start, target):
    legacy = discrete_corridor_routes(start, target)
    routes = set(legacy)
    for corner in (AODConfiguration(target.x_um, start.y_um),
                   AODConfiguration(start.x_um, target.y_um)):
        routes.add(merge_straight_runs((start, corner, target)))
    for path in legacy:
        for axes in ((0, 1), (0,), (1,)):
            try:
                routes.add(settle_axes(path, axes))
            except ValidationError:
                continue  # Early settling can break the shared-axis order.
    return sorted(routes, key=lambda path: (len(path), tuple((p.x_um, p.y_um) for p in path)))


def transfer_annotation(state, start, end, bindings, phase):
    """Use an exemption only when the entire declared transfer clears its SLM.

    LOAD has already disabled the source support. A held operand therefore
    needs no departure exemption; a free disabled OFFLOAD destination likewise
    needs none. Omission still invokes every regular swept/SLM validation.
    """
    radius = state.hardware.slm_clearance_um
    near, far = (start, end) if phase == 'depart' else (end, start)
    for binding in bindings:
        p = state.world.traps[binding.static_trap_id].position
        a, b = near.position(binding.cell), far.position(binding.cell)
        if ((a.x_um-p.x_um)**2+(a.y_um-p.y_um)**2 > 1e-12 or
                (b.x_um-p.x_um)**2+(b.y_um-p.y_um)**2 < radius**2-1e-9):
            return None, ()
    return phase, bindings
