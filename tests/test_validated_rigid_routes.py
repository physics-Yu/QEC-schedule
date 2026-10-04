"""Independent route costs, real handoffs and complete device geometry."""
from dataclasses import replace
from heapq import heappop, heappush
from math import hypot, inf

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import (
    Atom, GridCoord, HolderRef, HolderType as H, MobileCellIndex as C,
    Position2D as P, Rectangle, StaticTrap, Zone, ZoneType,
)
from neutral_atom_env.domain.operations import CaptureBinding, HardwareConfig, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.hardware.multi_aod import backend_for, with_aod
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.world import AODRuntimeState, PlacementState, WorldState
from neutral_atom_strategies.motion.validated_rigid import append_rigid_route, shortest_rigid_route


def lattice_state(obstacles=(), *, capacity=1, loaded=1, width=25, static_obstacles=False):
    bounds = Rectangle(P(0, 0), P(width, 25))
    traps = {f'O{i}': StaticTrap(f'O{i}', GridCoord(round(x / 2.5), round(y / 2.5)), P(x, y))
             for i, (x, y) in enumerate(obstacles)}
    world = WorldState(bounds, traps, (Zone('COMPUTE', ZoneType.ENTANGLEMENT, bounds),),
                       grid_spacing_um=2.5)
    aod = AODRuntimeState(pose=P(2.5, 2.5), rows=1, columns=capacity, spacing_um=10,
                          enabled_rows=(True,), enabled_columns=(True,) * capacity)
    holders = {f'Q{i:03d}': HolderRef(H.MOBILE, C(0, i)) for i in range(loaded)}
    if static_obstacles:
        holders.update({f'S{i}': HolderRef(H.STATIC, trap_id) for i, trap_id in enumerate(traps)})
    return SimulationState(world, PlacementState(holders), {q: Atom(q) for q in holders},
                           aod, DynamicGateDAG(PhysicalCircuit(())),
                           hardware=HardwareConfig(ez_neighbor_guard_enabled=False))


def dijkstra_5_by_5(state, target):
    """Hand-built fixture lattice, independent of planner graph/heuristic."""
    nodes = {(2.5 + 5 * x, 2.5 + 5 * y) for x in range(5) for y in range(5)}
    start = (state.aod.pose.x_um, state.aod.pose.y_um)
    best, queue = {start: 0.}, [(0., start)]
    backend = backend_for(state)
    while queue:
        cost, p = heappop(queue)
        if cost != best[p]:
            continue
        if p == target:
            return cost
        here = with_aod(state, 'AOD_0', replace(state.aod, pose=P(*p)))
        for dx, dy in ((5, 0), (-5, 0), (0, 5), (0, -5)):
            q = (p[0] + dx, p[1] + dy)
            if q not in nodes:
                continue
            try:
                backend.validate_move(here, P(*q))
            except ValidationError:
                continue
            if cost + 5 < best.get(q, inf):
                best[q] = cost + 5
                heappush(queue, (cost + 5, q))
    return inf


def execute_route(state, target, *, aod_id='AOD_0'):
    before = state.snapshot()
    builder = ProgramBuilder(state, TaskIntent('route-proof', TaskTarget(), phase='program'))
    result = append_rigid_route(builder, target, aod_id=aod_id)
    assert state.snapshot() == before
    plan = builder.finish('validated-rigid-test')
    executor = Executor(state)
    executor.submit(plan)
    executor.run()
    replay = SimulationState.restore(before)
    executor = Executor(replay)
    executor.submit(plan)
    executor.run()
    assert replay.snapshot() == state.snapshot()
    return result, plan


def test_clear_diagonal_attains_euclidean_lower_bound_and_replays():
    state = lattice_state()
    result, plan = execute_route(state, P(22.5, 22.5))
    assert result.points == (P(2.5, 2.5), P(22.5, 22.5))
    assert result.optimality_scope == 'euclidean-direct' and result.graph_result is None
    assert result.distance_um == pytest.approx(hypot(20, 20))
    assert plan.estimated_distance_um == pytest.approx(hypot(20, 20))
    assert state.aod.pose == P(22.5, 22.5)


def test_blocked_diagonal_uses_half_grid_cost_equal_to_independent_dijkstra():
    state = lattice_state(((12.5, 12.5),))
    before = state.snapshot()
    result = shortest_rigid_route(state, P(22.5, 22.5))
    assert result.optimality_scope == 'halfgrid-distance'
    assert result.distance_um == dijkstra_5_by_5(state, (22.5, 22.5)) == 40
    assert result.graph_result.geometry_lower_bound_um == 40
    assert result.graph_result.optimality_certified and state.snapshot() == before
    assert all(a.x_um == b.x_um or a.y_um == b.y_um
               for a, b in zip(result.points, result.points[1:]))


def test_enabled_empty_slm_is_an_obstacle_and_explicitly_disabled_empty_slm_is_not():
    state = lattice_state(((12.5, 12.5),))
    before = state.snapshot()
    blocked = shortest_rigid_route(state, P(22.5, 22.5))
    closed = replace(state, slm_enabled={'O0': False})
    direct = shortest_rigid_route(closed, P(22.5, 22.5))
    assert blocked.optimality_scope == 'halfgrid-distance' and blocked.distance_um == 40
    assert direct.optimality_scope == 'euclidean-direct'
    assert direct.distance_um == pytest.approx(hypot(20, 20))
    assert state.snapshot() == before and state.slm_enabled['O0']


def test_zigzag_walls_require_multiple_turns_and_match_independent_80_um_cost():
    # Extra wall centres block the Euclidean diagonal as well as old L routes.
    obstacles = ([(10, y) for y in (2.5, 7.5, 10, 12.5, 17.5)]
                 + [(20, y) for y in (7.5, 12.5, 17.5, 20, 22.5)])
    state = lattice_state(obstacles)
    result, plan = execute_route(state, P(22.5, 22.5))
    assert result.optimality_scope == 'halfgrid-distance'
    assert result.distance_um == dijkstra_5_by_5(lattice_state(obstacles), (22.5, 22.5)) == 80
    assert plan.estimated_distance_um == 80 and len(result.points) >= 6
    assert result.graph_result.geometry_lower_bound_um == 40


def handoff_state():
    bounds = Rectangle(P(-10, -10), P(25, 25))
    traps = {'SOURCE': StaticTrap('SOURCE', GridCoord(0, 0), P(0, 0)),
             'DEST': StaticTrap('DEST', GridCoord(0, 4), P(0, 20), enabled=False)}
    world = WorldState(bounds, traps, (Zone('COMPUTE', ZoneType.ENTANGLEMENT, bounds),))
    return SimulationState(world, PlacementState({'Q000': HolderRef(H.STATIC, 'SOURCE')}),
        {'Q000': Atom('Q000')}, AODRuntimeState(pose=P(0, 0)), DynamicGateDAG(PhysicalCircuit(())),
        hardware=HardwareConfig(ez_neighbor_guard_enabled=False))


def test_actual_load_move_offload_preserves_short_transfer_boundary_stops():
    state = handoff_state()
    before = state.snapshot()
    source = CaptureBinding('Q000', C(0, 0), 'SOURCE')
    destination = CaptureBinding('Q000', C(0, 0), 'DEST')
    intent = TaskIntent('handoff-proof', TaskTarget(holders=(('Q000', HolderRef(H.STATIC, 'DEST')),)),
                        frozenset({'Q000'}), phase='program')
    builder = ProgramBuilder(state, intent)
    builder.add(K.AOD_LOAD, 'Actual source handoff', bindings=(source,))
    result = append_rigid_route(builder, P(0, 20), depart=(source,), approach=(destination,))
    builder.add(K.AOD_OFFLOAD, 'Actual destination handoff', bindings=(destination,))
    moves = [op for op in builder.operations if op.operation_type == K.AOD_MOVE]
    assert result.distance_um == 25 and result.optimality_scope == 'halfgrid-distance'
    assert moves[0].transfer_phase == 'depart' and moves[0].transfer_bindings == (source,)
    assert moves[-1].transfer_phase == 'approach' and moves[-1].transfer_bindings == (destination,)
    assert all(op.transfer_phase is None for op in moves[1:-1])
    assert hypot(result.points[1].x_um, result.points[1].y_um) <= 2.5
    assert hypot(result.points[-2].x_um, result.points[-2].y_um - 20) <= 2.5
    assert state.snapshot() == before
    plan = builder.finish('handoff-proof')
    executor = Executor(state)
    executor.submit(plan)
    executor.run()
    assert state.placement.atom_to_holder['Q000'] == HolderRef(H.STATIC, 'DEST')
    assert state.slm_enabled['DEST'] and not state.placement.mobile_occupancy
    assert plan.estimated_duration_us == 200 + 25 / state.hardware.speed_um_per_us
    replay = SimulationState.restore(before)
    executor = Executor(replay)
    executor.submit(plan)
    executor.run()
    assert replay.snapshot() == state.snapshot()


@pytest.mark.parametrize('loaded,static_obstacles', ((2, False), (1, True)))
def test_nonrequested_loaded_and_active_empty_cells_both_participate_in_route(loaded, static_obstacles):
    # Q000 is clear on x=2.5; a second active intersection on x=12.5 is not.
    state = lattice_state(((12.5, 10),), capacity=2, loaded=loaded, width=40,
                          static_obstacles=static_obstacles)
    before = state.snapshot()
    result, plan = execute_route(state, P(2.5, 22.5))
    assert result.optimality_scope == 'halfgrid-distance' and result.distance_um == 30
    assert state.placement.mobile_occupancy == SimulationState.restore(before).placement.mobile_occupancy
    assert state.aod.configuration().x_um[1] - state.aod.configuration().x_um[0] == 10
    assert plan.estimated_distance_um == 30


def test_dark_empty_array_can_reposition_directly_but_active_empty_array_must_avoid_atom():
    active = lattice_state(((12.5, 10),), capacity=2, loaded=0, width=40, static_obstacles=True)
    before = active.snapshot()
    dark = replace(active, aod=replace(active.aod, enabled_rows=(False,), enabled_columns=(False, False)))
    avoided = shortest_rigid_route(active, P(2.5, 22.5))
    direct = shortest_rigid_route(dark, P(2.5, 22.5))
    assert avoided.optimality_scope == 'halfgrid-distance' and avoided.distance_um == 30
    assert direct.optimality_scope == 'euclidean-direct' and direct.distance_um == 20
    assert active.snapshot() == before


def dual_state(*, magic_columns=1, magic_envelope_right=200, spectator=True):
    bounds = Rectangle(P(0, 0), P(200, 100))
    traps = {'SPECTATOR': StaticTrap('SPECTATOR', GridCoord(26, 10), P(130, 50))} if spectator else {}
    world = WorldState(bounds, traps, (Zone('COMPUTE', ZoneType.ENTANGLEMENT, bounds),))
    primary = AODRuntimeState(pose=P(20, 50), rows=1, columns=1,
                             enabled_rows=(True,), enabled_columns=(True,),
                             envelope=Rectangle(P(0, 0), P(80, 100)))
    magic = AODRuntimeState(pose=P(120, 50), rows=1, columns=magic_columns, spacing_um=10,
                           enabled_rows=(True,), enabled_columns=(True,) + (False,) * (magic_columns - 1),
                           aod_id='AOD_MAGIC', envelope=Rectangle(P(100, 0), P(magic_envelope_right, 100)))
    holders = {'Q000': HolderRef(H.MOBILE, C(0, 0)),
               'Q001': HolderRef(H.MOBILE, C(0, 0, 'AOD_MAGIC'))}
    if spectator:
        holders['Q002'] = HolderRef(H.STATIC, 'SPECTATOR')
    return SimulationState(world, PlacementState(holders), {q: Atom(q) for q in holders}, primary,
        DynamicGateDAG(PhysicalCircuit(())), hardware=HardwareConfig(ez_neighbor_guard_enabled=False),
        aods={'AOD_0': primary, 'AOD_MAGIC': magic})


def test_secondary_device_routes_around_global_spectator_without_moving_primary():
    state = dual_state()
    original_primary, original_holders = state.aods['AOD_0'], dict(state.placement.atom_to_holder)
    result, plan = execute_route(state, P(140, 50), aod_id='AOD_MAGIC')
    assert result.optimality_scope == 'halfgrid-distance' and result.distance_um == 25
    assert state.aods['AOD_MAGIC'].pose == P(140, 50)
    assert state.aods['AOD_0'] == original_primary and dict(state.placement.atom_to_holder) == original_holders
    assert all(op.aod_id == 'AOD_MAGIC' for op in plan.operations)
    assert state.placement.position('Q002', state.world, state.aods) == P(130, 50)
    assert all(100 <= p.x_um <= 200 for p in result.points)


def test_disabled_spare_axes_cannot_leave_secondary_envelope_even_inside_world():
    state = dual_state(magic_columns=3, magic_envelope_right=150, spectator=False)
    before = state.snapshot()
    with pytest.raises(ValidationError, match='AOD_ENVELOPE_EXCEEDED'):
        shortest_rigid_route(state, P(140, 50), aod_id='AOD_MAGIC')
    assert state.snapshot() == before


def test_single_device_clear_direct_route_cannot_take_disabled_spares_outside_envelope():
    state = lattice_state(capacity=3, width=45)
    state = replace(state, aod=replace(state.aod, enabled_columns=(True, False, False),
        envelope=Rectangle(P(0, 0), P(25, 25))))
    before = state.snapshot()
    target = P(12.5, 2.5)
    # This direct segment is genuinely obstacle-free and fits the world. The
    # legacy backend would accept it; only the complete 20 um spare footprint
    # violates the declared envelope (last column would reach x=32.5).
    backend_for(state).validate_move(state, target)
    without_envelope = replace(state, aod=replace(state.aod, envelope=None))
    direct = shortest_rigid_route(without_envelope, target)
    assert direct.optimality_scope == 'euclidean-direct' and direct.distance_um == 10
    builder = ProgramBuilder(state, TaskIntent('single-envelope-negative', TaskTarget(), phase='program'))
    with pytest.raises(ValidationError, match='AOD_ENVELOPE_EXCEEDED'):
        append_rigid_route(builder, target)
    assert state.snapshot() == before and builder.state.snapshot() == before
    assert builder.operations == []


def test_single_device_direct_route_at_complete_envelope_boundary_returns_and_replays():
    state = lattice_state(capacity=3, width=45)
    state = replace(state, aod=replace(state.aod, enabled_columns=(True, False, False),
        envelope=Rectangle(P(0, 0), P(25, 25))))
    before, home = state.snapshot(), state.aod.pose
    builder = ProgramBuilder(state, TaskIntent('single-envelope-round-trip',
        TaskTarget(aod_configuration=state.aod.configuration()), phase='program'))
    outbound = append_rigid_route(builder, P(5, 2.5))
    assert builder.state.aod.configuration().x_um[-1] == 25
    returned = append_rigid_route(builder, home)
    assert outbound.optimality_scope == returned.optimality_scope == 'euclidean-direct'
    assert outbound.distance_um == returned.distance_um == 2.5
    assert state.snapshot() == before
    plan = builder.finish('single-envelope-round-trip')
    assert plan.estimated_distance_um == 5
    assert plan.estimated_duration_us == 5 / state.hardware.speed_um_per_us
    executor = Executor(state)
    executor.submit(plan)
    executor.run()
    assert state.aod.pose == home and state.aod.envelope.upper == P(25, 25)
    assert state.placement.atom_to_holder == SimulationState.restore(before).placement.atom_to_holder
    replay = SimulationState.restore(before)
    executor = Executor(replay)
    executor.submit(plan)
    executor.run()
    assert replay.snapshot() == state.snapshot()


def test_disabled_spare_axes_cannot_leave_world():
    state = lattice_state(capacity=4, width=45)
    state = replace(state, aod=replace(state.aod, enabled_columns=(True, False, False, False)))
    before = state.snapshot()
    with pytest.raises(ValidationError, match='AOD_OUTSIDE_WORLD'):
        shortest_rigid_route(state, P(22.5, 22.5))
    assert state.snapshot() == before


@pytest.mark.parametrize('budget,error', ((1, 'GRAPH_ROUTE_BUDGET_EXHAUSTED'), (20000, 'GRAPH_ROUTE_NO_PATH')))
def test_exhaustion_diagnostics_do_not_change_physics_state_or_builder(budget, error):
    # Start is the graph's bottom-left vertex. Its two graph exits are blocked;
    # the central trap blocks the direct diagonal, forcing the graph search.
    state = lattice_state(((7.5, 2.5), (2.5, 7.5), (12.5, 12.5)))
    before, hardware = state.snapshot(), state.hardware
    builder = ProgramBuilder(state, TaskIntent('failure-proof', TaskTarget(), phase='program'))
    with pytest.raises(ValidationError, match=error):
        append_rigid_route(builder, P(22.5, 22.5), max_expansions=budget)
    assert state.snapshot() == before and builder.state.snapshot() == before
    assert builder.operations == [] and state.hardware == hardware
    assert state.hardware.minimum_clearance_um == state.hardware.slm_clearance_um == 1


def test_nonrigid_backend_is_rejected_before_any_candidate_or_state_change():
    state = lattice_state()
    state = replace(state, hardware=replace(state.hardware, backend='row_column'))
    before = state.snapshot()
    with pytest.raises(ValidationError, match='GRAPH_BACKEND_UNSUPPORTED'):
        shortest_rigid_route(state, P(22.5, 22.5))
    assert state.snapshot() == before
