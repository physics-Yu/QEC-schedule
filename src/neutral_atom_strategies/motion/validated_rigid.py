"""Device-aware straight routes, then shortest legal 2.5 um half-grid routes.

Fixed holders, masks and rigid offsets are inputs. Every candidate edge uses
the existing physical backend; the planner never changes live state or light
supports. Graph distance optimality is separate from movement timing.
"""
from dataclasses import dataclass
from math import hypot

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.operations import OperationType
from neutral_atom_env.hardware.multi_aod import backend_for, device, with_aod, validate_envelopes
from neutral_atom_strategies.motion.astar import AStarHalfGridPlanner
from neutral_atom_strategies.motion.planners import RouteRequest


STANDARD_ROUTING = 'shortest-direct-or-halfgrid-v1'
LEGACY_ROUTING = 'legacy-5um-v1'


@dataclass(frozen=True)
class RigidRouteResult:
    points: tuple
    distance_um: float
    optimality_scope: str
    graph_result: object = None


def shortest_rigid_route(state, target, *, aod_id='AOD_0', depart=(),
                         approach=(), max_expansions=20000):
    """Return a validated direct route, or the bounded half-grid optimum.

    A clear direct segment attains the Euclidean lower bound. Otherwise A*
    minimizes distance on x/y = 2.5 + 5k corridors with short endpoint access.
    Neither case optimizes placement, masks, circuit scheduling or nonlinear
    per-segment timing. Transfer boundaries remain explicit physical edges.
    """
    if state.hardware.backend != 'rigid':
        raise ValidationError('GRAPH_BACKEND_UNSUPPORTED', 'This routing policy requires fixed rigid offsets')
    aod = device(state, aod_id)
    backend = backend_for(state, aod_id)
    end = backend.target_aod(aod, target)
    backend.validate_pose(state, aod.pose)
    backend.validate_pose(state, target)
    # The legacy single-device backend checks world bounds only. Its optional
    # envelope remains a routing constraint, including a direct fast path.
    if len(state.aods) == 1 and aod.envelope is not None:
        validate_envelopes(state)
        validate_envelopes(with_aod(state, aod_id, end))
    start_config, end_config = aod.configuration(), end.configuration()
    depart, approach = tuple(depart), tuple(approach)

    def check_edge(start, finish, phase, bindings):
        here = with_aod(state, aod_id, aod.configured(start))
        backend.validate_move(here, Position2D(finish.x_um[0], finish.y_um[0]),
                              transfer=phase, bindings=bindings)

    if start_config == end_config:
        return RigidRouteResult((aod.pose,), 0., 'euclidean-direct')
    # One MOVE cannot carry both handoff exemptions. Use graph portals when
    # moving between two actual SLM supports rather than merging boundaries.
    if not (depart and approach):
        phase = 'depart' if depart else 'approach' if approach else None
        try:
            check_edge(start_config, end_config, phase, depart or approach)
        except ValidationError:
            pass
        else:
            return RigidRouteResult((aod.pose, target),
                hypot(target.x_um-aod.pose.x_um, target.y_um-aod.pose.y_um),
                'euclidean-direct')

    # Envelopes are fixed in-world rectangles. Restrict search, not the world:
    # foreign traps and atoms must stay visible to every physical edge check.
    request = RouteRequest(start_config, end_config, state.world.grid_spacing_um,
        state.world.grid_origin.x_um, depart, state.world, state.hardware,
        depart=depart, approach=approach, edge_validator=check_edge,
        routing_bounds=aod.envelope)
    result = AStarHalfGridPlanner(max_expansions=max_expansions).search(request)
    points = tuple(Position2D(c.x_um[0], c.y_um[0]) for c in result.points)
    # Recheck the merged route, including first/last transfer stops. This is
    # necessary even when search validated shorter constituent graph edges.
    for index, (start, finish) in enumerate(zip(result.points, result.points[1:])):
        phase = 'depart' if index == 0 and depart else (
            'approach' if index == len(result.points)-2 and approach else None)
        bindings = depart if phase == 'depart' else approach if phase == 'approach' else ()
        check_edge(start, finish, phase, bindings)
    return RigidRouteResult(points, result.distance_um, 'halfgrid-distance', result)


def append_rigid_route(builder, target, *, aod_id='AOD_0', depart=(),
                       approach=(), label='最短合法路径运输', max_expansions=20000):
    """Search without side effects, then append ordinary validated MOVE ops."""
    result = shortest_rigid_route(builder.state, target, aod_id=aod_id,
        depart=depart, approach=approach, max_expansions=max_expansions)
    for index, point in enumerate(result.points[1:]):
        phase = 'depart' if index == 0 and depart else (
            'approach' if index == len(result.points)-2 and approach else None)
        bindings = depart if phase == 'depart' else approach if phase == 'approach' else ()
        builder.add(OperationType.AOD_MOVE, label, target=point, bindings=bindings,
                    phase=phase, aod_id=aod_id)
    return result
