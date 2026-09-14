"""Independent graph-distance and full rigid-array swept-geometry witnesses."""
from dataclasses import replace
from heapq import heappush, heappop
from math import inf
import pytest

from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import (Atom, GridCoord, HolderRef, HolderType,
    MobileCellIndex, Position2D, Rectangle, StaticTrap, Zone, ZoneType)
from neutral_atom_env.domain.operations import HardwareConfig, TaskIntent, TaskTarget, CaptureBinding, OperationType as K
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.motion.astar import AStarHalfGridPlanner
from neutral_atom_env.motion.planners import RouteRequest, OrthogonalHalfGridPlanner
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.motion.single_trap import route
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState


def physical(obstacles=(), *, capacity=1, loaded=1, width=25):
    bounds=Rectangle(Position2D(0,0),Position2D(width,25))
    traps={f'O{i}':StaticTrap(f'O{i}',GridCoord(round(x/2.5),round(y/2.5)),Position2D(x,y))
           for i,(x,y) in enumerate(obstacles)}
    world=WorldState(bounds,traps,(Zone('EZ',ZoneType.ENTANGLEMENT,bounds),),grid_spacing_um=2.5)
    aod=AODRuntimeState(pose=Position2D(2.5,2.5),rows=1,columns=capacity,spacing_um=10,
                        enabled_rows=(True,),enabled_columns=(True,)*capacity)
    atoms={f'Q{i:03d}':Atom(f'Q{i:03d}') for i in range(loaded)}
    placement=PlacementState({q:HolderRef(HolderType.MOBILE,MobileCellIndex(0,i)) for i,q in enumerate(atoms)})
    return SimulationState(world,placement,atoms,aod,DynamicGateDAG(PhysicalCircuit(())),hardware=HardwareConfig())


def request(state,target=(22.5,22.5),**kwargs):
    end=state.aod.configuration().translated(target[0]-state.aod.pose.x_um,target[1]-state.aod.pose.y_um)
    return RouteRequest(state.aod.configuration(),end,state.world.grid_spacing_um,0,(),state.world,state.hardware,state=state,**kwargs)


def execute_points(state,points):
    backend=get_backend(state.hardware)
    for end in points[1:]:state=backend.move(state,Position2D(end.x_um[0],end.y_um[0]))
    return state


def dijkstra_oracle(state,target):
    # Independently build the 5x5 cardinal lattice for this fixture; do not call
    # planner.graph or reuse its A* heuristic, neighbor generation or relaxations.
    nodes={(2.5+5*x,2.5+5*y) for x in range(5) for y in range(5)}
    start=(state.aod.pose.x_um,state.aod.pose.y_um);heap=[(0.,start)];best={start:0.}
    backend=get_backend(state.hardware)
    while heap:
        cost,p=heappop(heap)
        if cost!=best[p]:continue
        if p==target:return cost
        here=replace(state,aod=backend.target_aod(state.aod,Position2D(*p)))
        for dx,dy in ((5,0),(-5,0),(0,5),(0,-5)):
            q=(p[0]+dx,p[1]+dy)
            if q not in nodes:continue
            try:backend.validate_move(here,Position2D(*q))
            except ValidationError:continue
            if cost+5<best.get(q,inf):best[q]=cost+5;heappush(heap,(cost+5,q))
    return inf


def test_zigzag_obstacles_need_more_than_old_l_templates_and_match_dijkstra():
    obstacles=[(10,y) for y in (2.5,7.5,12.5,17.5)]+[(20,y) for y in (7.5,12.5,17.5,22.5)]
    state=physical(obstacles);before=state.snapshot();r=request(state)
    old=list(OrthogonalHalfGridPlanner().candidates(r))
    assert old
    for candidate in old:
        with pytest.raises(ValidationError):execute_points(state,candidate)
    result=AStarHalfGridPlanner().search(r)
    assert result.distance_um==dijkstra_oracle(state,(22.5,22.5))==80
    assert result.geometry_lower_bound_um==40 and not result.fast_path
    assert len(result.points)>=6 and result.optimality_certified
    assert execute_points(state,result.points).aod.pose==Position2D(22.5,22.5)
    # The same route goes through the real gateless compiler/executor envelope.
    builder=ProgramBuilder(state,TaskIntent('maze',TaskTarget(aod_configuration=r.target)))
    route(builder,Position2D(22.5,22.5),AStarHalfGridPlanner())
    plan=builder.finish('astar-test');assert plan.estimated_distance_um==80
    executor=Executor(state);executor.submit(plan);executor.run()
    assert state.aod.pose==Position2D(22.5,22.5)
    assert before!=state.snapshot()


@pytest.mark.parametrize('obstacles',[(),((10,2.5),),((10,2.5),(10,7.5)),((10,2.5),(20,17.5))])
def test_cost_matches_independent_dijkstra_and_search_is_pure(obstacles):
    state=physical(obstacles);before=state.snapshot()
    result=AStarHalfGridPlanner().search(request(state))
    assert result.distance_um==dijkstra_oracle(state,(22.5,22.5))
    assert state.snapshot()==before
    assert all(a.x_um==b.x_um or a.y_um==b.y_um for a,b in zip(result.points,result.points[1:]))


def test_open_corridor_certified_lower_bound_avoids_per_grid_edge_audits():
    result=AStarHalfGridPlanner().search(request(physical()))
    assert result.fast_path and result.distance_um==result.geometry_lower_bound_um==40
    assert result.edge_checks<=3  # Merged straight segments, not all lattice edges.


def test_full_rigid_array_incidental_loaded_cell_avoids_obstacle():
    # Cell 0's direct vertical route is clear; cell 1 would hit the SLM at 12.5,10.
    state=physical(((12.5,10),),capacity=2,loaded=2,width=40)
    backend=get_backend(state.hardware)
    with pytest.raises(ValidationError,match='SLM_PATH_BLOCKED'):
        backend.validate_move(state,Position2D(2.5,22.5))
    result=AStarHalfGridPlanner().search(request(state,(2.5,22.5)))
    assert result.distance_um==30  # one 5 um lateral detour and return
    for p in result.points:assert p.x_um[1]-p.x_um[0]==10
    final=execute_points(state,result.points)
    assert final.placement.mobile_occupancy==state.placement.mobile_occupancy


def test_active_empty_cell_sweep_is_checked_against_static_atoms():
    state=physical(((12.5,10),),capacity=2,loaded=1,width=40)
    state=replace(state,atoms={**state.atoms,'Q001':Atom('Q001')},
        placement=PlacementState({**state.placement.atom_to_holder,
                                  'Q001':HolderRef(HolderType.STATIC,'O0')}))
    with pytest.raises(ValidationError,match='ACTIVE_TRAP_SWEEP'):
        get_backend(state.hardware).validate_move(state,Position2D(2.5,22.5))
    result=AStarHalfGridPlanner().search(request(state,(2.5,22.5)))
    assert result.distance_um==30
    execute_points(state,result.points)


def test_disabled_capacity_axes_still_restrict_world_and_deformation_rejected():
    state=physical(capacity=4,loaded=1,width=45)
    state=replace(state,aod=replace(state.aod,enabled_columns=(True,False,False,False)))
    with pytest.raises(ValidationError,match='AOD_OUTSIDE_WORLD'):
        AStarHalfGridPlanner().search(request(state,(22.5,22.5)))
    r=request(state,(7.5,22.5))
    with pytest.raises(ValidationError,match='UNSUPPORTED_DEFORMATION'):
        AStarHalfGridPlanner().search(replace(r,target=AODConfiguration((7.5,18,27.5,37.5),(22.5,))))


def test_portal_access_is_short_and_transfer_boundary_stop_survives_simplification():
    state=physical();state=replace(state,aod=replace(state.aod,pose=Position2D(3,5)))
    phases=[]
    def audit(a,b,phase,bindings):phases.append((a,b,phase,bindings))
    binding=CaptureBinding('Q000',MobileCellIndex(0,0),'SOURCE')
    r=request(state,(3,20),depart=(binding,),approach=(binding,),edge_validator=audit)
    result=AStarHalfGridPlanner().search(r)
    assert len(result.points)>=3
    assert phases[0][2]=='depart' and phases[-1][2]=='approach'
    for p,q in zip(result.points,result.points[1:]):
        x,y=p.x_um[0],p.y_um[0];xx,yy=q.x_um[0],q.y_um[0]
        half=lambda v:abs((v-2.5)/5-round((v-2.5)/5))<1e-9
        if not ((x==xx and half(x)) or (y==yy and half(y))):
            assert abs(xx-x)+abs(yy-y)<=2.5


def test_budget_and_graph_exhaustion_have_distinct_diagnostics():
    state=physical()
    with pytest.raises(ValidationError,match='GRAPH_ROUTE_BUDGET_EXHAUSTED.*expanded=1'):
        AStarHalfGridPlanner(max_expansions=1).search(request(state))
    def reject(*args):raise ValidationError('BLOCKED_FIXTURE','All outgoing edges are blocked')
    with pytest.raises(ValidationError,match='GRAPH_ROUTE_NO_PATH.*BLOCKED_FIXTURE'):
        AStarHalfGridPlanner().search(request(state,edge_validator=reject))
