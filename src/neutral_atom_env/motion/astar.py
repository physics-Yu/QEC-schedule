"""Deterministic shortest paths on the bounded rigid half-grid corridor graph.

Only fixed-mask translation is searched. Backend edge checks and final program
audits remain authoritative. This is local graph optimality, not continuous
configuration-space completeness or circuit scheduling optimality.
"""
from dataclasses import dataclass, replace
from heapq import heappop, heappush
from math import ceil, floor, inf

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.hardware import get_backend
from .planners import OrthogonalHalfGridPlanner, simplify_route


@dataclass(frozen=True)
class RouteSearchResult:
    points: tuple
    distance_um: float
    expanded_nodes: int
    edge_checks: int
    graph_nodes: int
    geometry_lower_bound_um: float | None = None
    fast_path: bool = False
    optimality_certified: bool = True


class AStarHalfGridPlanner:
    """A* with exact swept-edge rejection and an admissible Manhattan heuristic."""
    id = 'astar-rigid-half-grid-v1'
    orthogonal = True

    def __init__(self, max_expansions=20000):
        if type(max_expansions) is not int or max_expansions < 1:
            raise ValueError('Positive integer A* expansion budget required')
        self.max_expansions = max_expansions

    @staticmethod
    def graph(request):
        """Finite half-grid graph plus short endpoint access, full-array bounds."""
        a,b=request.start,request.target
        if a.translated(b.x_um[0]-a.x_um[0],b.y_um[0]-a.y_um[0])!=b:
            raise ValidationError('UNSUPPORTED_DEFORMATION','Rigid graph routing preserves every row and column offset')
        bounds=request.world.bounds
        left,bottom=bounds.lower.x_um,bounds.lower.y_um
        right=bounds.upper.x_um-(a.x_um[-1]-a.x_um[0])
        top=bounds.upper.y_um-(a.y_um[-1]-a.y_um[0])
        def inside(p):return left-1e-9<=p[0]<=right+1e-9 and bottom-1e-9<=p[1]<=top+1e-9
        def on_grid(v):return abs((v-2.5)/5-round((v-2.5)/5))<1e-9
        def near(v):return sorted({2.5+5*floor((v-2.5)/5),2.5+5*ceil((v-2.5)/5)})
        xs=[2.5+5*k for k in range(ceil((left-2.5)/5),floor((right-2.5)/5)+1)]
        ys=[2.5+5*k for k in range(ceil((bottom-2.5)/5),floor((top-2.5)/5)+1)]
        start=(a.x_um[0],a.y_um[0]);target=(b.x_um[0],b.y_um[0])
        if not inside(start) or not inside(target):
            raise ValidationError('AOD_OUTSIDE_WORLD','Full rigid array start or target exceeds world bounds')
        nodes={(x,y) for x in xs for y in ys};nodes.update((start,target))
        access=[]
        for endpoint in (start,target):
            x,y=endpoint
            for p in [(hx,y) for hx in near(x)]+[(x,hy) for hy in near(y)]:
                if inside(p) and 0<abs(p[0]-x)+abs(p[1]-y)<=2.5+1e-9:
                    nodes.add(p);access.append((endpoint,p))
        graph={p:set() for p in nodes}
        def join(a,b):
            if a!=b:graph[a].add(b);graph[b].add(a)
        for a,b in access:join(a,b)
        # Inserting endpoint portals into each line prevents an artificial trip
        # to an intersection and back when two endpoints share a corridor.
        columns={};rows={}
        for p in nodes:
            if on_grid(p[0]):columns.setdefault(p[0],[]).append(p)
            if on_grid(p[1]):rows.setdefault(p[1],[]).append(p)
        for line in [*columns.values(),*rows.values()]:
            ordered=sorted(line)
            for a,b in zip(ordered,ordered[1:]):join(a,b)
        return {p:tuple(sorted(neighbors)) for p,neighbors in graph.items()},start,target

    def search(self,request):
        graph,start,target=self.graph(request)
        if start==target:return RouteSearchResult((request.start,),0.,0,0,len(graph))
        base=request.start
        def config(p):return base.translated(p[0]-base.x_um[0],p[1]-base.y_um[0])
        backend=get_backend(request.hardware) if request.state is not None else None
        if backend is not None and backend.name!='rigid':
            raise ValidationError('GRAPH_BACKEND_UNSUPPORTED','Half-grid A* currently supports rigid constant-speed translation only')
        if request.edge_validator is None and backend is None:
            raise ValueError('A* needs a read-only physical state or edge validator')
        edge_cache={};state_cache={};checks=0;expanded=0;refusals={}
        def allowed(a,b):
            nonlocal checks
            phase='depart' if a==start and request.depart else ('approach' if b==target and request.approach else None)
            bindings=request.depart if phase=='depart' else request.approach if phase=='approach' else ()
            if a==start and b==target and request.depart and request.approach:return False
            key=(a,b,phase)
            if key not in edge_cache:
                checks+=1
                try:
                    if request.edge_validator is not None:
                        request.edge_validator(config(a),config(b),phase,bindings)
                    else:
                        physical=state_cache.get(a)
                        if physical is None:
                            physical=replace(request.state,aod=backend.target_aod(request.state.aod,Position2D(*a)))
                            state_cache[a]=physical
                        backend.validate_move(physical,Position2D(*b),transfer=phase,bindings=bindings)
                    edge_cache[key]=True
                except ValidationError as error:
                    edge_cache[key]=False
                    code=error.violation.code;refusals[code]=refusals.get(code,0)+1
            return edge_cache[key]
        def heuristic(p):return abs(target[0]-p[0])+abs(target[1]-p[1])
        def finish(path,cost):
            points=tuple(config(p) for p in path)
            # Transfer exemptions belong only to their boundary edges.
            left=1 if request.depart else 0;right=len(points)-1 if request.approach else len(points)
            points=points[:left]+simplify_route(points[left:right])+points[right:]
            return RouteSearchResult(points,cost,expanded,checks,len(graph))
        def find(check_edges):
            nonlocal expanded
            distance={start:0.};parents={};queue=[(heuristic(start),0.,start)];closed=set()
            while queue:
                _,negative_cost,current=heappop(queue);cost=-negative_cost
                if current in closed or cost!=distance[current]:continue
                if current==target:
                    path=[target]
                    while path[-1]!=start:path.append(parents[path[-1]])
                    return tuple(reversed(path)),cost
                if expanded>=self.max_expansions:
                    raise ValidationError('GRAPH_ROUTE_BUDGET_EXHAUSTED',
                        f'A* expansion budget {self.max_expansions} reached; expanded={expanded}, edge_checks={checks}, graph_nodes={len(graph)}; not proof of no route')
                closed.add(current);expanded+=1
                for neighbor in graph[current]:
                    if neighbor in closed:continue
                    if current==start and neighbor==target and request.depart and request.approach:continue
                    if check_edges and not allowed(current,neighbor):continue
                    candidate=cost+abs(neighbor[0]-current[0])+abs(neighbor[1]-current[1])
                    if candidate<distance.get(neighbor,inf)-1e-9:
                        distance[neighbor]=candidate;parents[neighbor]=current
                        # Prefer deeper equal-f nodes: open corridors should not
                        # flood-fill their entire Manhattan bounding rectangle.
                        heappush(queue,(candidate+heuristic(neighbor),-candidate,neighbor))
            return None
        # The obstacle-free graph optimum is a lower bound for the exact graph.
        # If its merged physical edges pass, this is a certified early stop.
        lower=find(False)
        if lower is not None:
            trial=finish(*lower)
            waypoints=[(p.x_um[0],p.y_um[0]) for p in trial.points]
            if all(allowed(a,b) for a,b in zip(waypoints,waypoints[1:])):
                return replace(trial,edge_checks=checks,geometry_lower_bound_um=lower[1],fast_path=True)
            actual=find(True)
            if actual is not None:return replace(finish(*actual),geometry_lower_bound_um=lower[1])
        raise ValidationError('GRAPH_ROUTE_NO_PATH',
            f'No route in bounded half-grid graph; expanded={expanded}, edge_checks={checks}, graph_nodes={len(graph)}, refusals={refusals}; not proof of continuous-space impossibility')

    def candidates(self,request):
        if request.state is None and request.edge_validator is None:
            # Old callers do not expose a physical state and retain their prior
            # finite-candidate contract. M4 always supplies state explicitly.
            yield from OrthogonalHalfGridPlanner().candidates(request)
        else:
            yield self.search(request).points
