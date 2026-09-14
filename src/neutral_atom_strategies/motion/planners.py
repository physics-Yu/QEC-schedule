"""Replaceable geometric routing policy. Backend remains the authority on legality."""
from dataclasses import dataclass
from math import floor, ceil
from typing import Protocol, Iterable
from neutral_atom_env.domain.aod import AODConfiguration


@dataclass(frozen=True)
class RouteRequest:
    start: AODConfiguration
    target: AODConfiguration
    grid_spacing_um: float
    grid_origin_x_um: float
    bindings: tuple
    world: object
    hardware: object
    state: object = None
    depart: tuple = ()
    approach: tuple = ()
    edge_validator: object = None


class MotionPlanner(Protocol):
    id: str
    def candidates(self, request: RouteRequest) -> Iterable[tuple[AODConfiguration, ...]]: ...


def simplify_route(points):
    """Coalesce only positive collinear motion in the ENTIRE axis configuration."""
    result=[]
    for point in points:
        if result and point==result[-1]:continue
        result.append(point)
        while len(result)>=3:
            a,b,c=(p.x_um+p.y_um for p in result[-3:])
            u=[y-x for x,y in zip(a,b)];v=[y-x for x,y in zip(b,c)]
            k=next((i for i,x in enumerate(u) if abs(x)>1e-10),None)
            if k is None:break
            ratio=v[k]/u[k]
            if ratio<=0 or any(abs(y-ratio*x)>1e-9 for x,y in zip(u,v)):break
            result.pop(-2)
    return tuple(result)


@dataclass(frozen=True)
class HalfGridPlanner:
    """Bounded corridor candidates; failure is not a proof that no route exists."""
    sides: tuple[int, ...] = (1,-1)
    id: str = 'half-grid-v1'

    def candidates(self, request):
        a,b=request.start,request.target
        half=request.grid_spacing_um/2
        # Try right first. No same-direction intermediate stop on the long leg.
        for side in self.sides:
            depart=a.translated(side*half,0)
            yield (a,depart,depart.translated(0,b.y_um[0]-a.y_um[0]),b)
        # A half-row cross corridor permits lateral relocation before the long leg.
        origin=request.grid_origin_x_um
        near=origin+(floor((b.x_um[0]-origin)/request.grid_spacing_um)+.5)*request.grid_spacing_um
        for side in self.sides:
            for vertical in (-1,1):
                depart=a.translated(side*half,0)
                elbow=depart.translated(0,vertical*half)
                across=elbow.translated(near-elbow.x_um[0],0)
                yield (a,depart,elbow,across,across.translated(0,b.y_um[0]-across.y_um[0]),b)


class OrthogonalHalfGridPlanner:
    """Single-cell Manhattan corridors at x/y = 2.5 + 5k um.

    Only the first/last short segment joins a site or interaction pose to a
    corridor. Every candidate still needs the backend's complete sweep audit.
    """
    id='orthogonal-half-grid-v1'
    orthogonal=True

    def candidates(self,request):
        a,b=request.start,request.target
        if len(a.x_um)!=1 or len(a.y_um)!=1:return
        def near(v):
            return sorted({2.5+5*floor((v-2.5)/5),2.5+5*ceil((v-2.5)/5)})
        def config(x,y):return a.translated(x-a.x_um[0],y-a.y_um[0])
        def portals(p):
            x,y=p.x_um[0],p.y_um[0]
            for hx in near(x):
                for hy in near(y):
                    yield (p,config(hx,y),config(hx,hy))
                    yield (p,config(x,hy),config(hx,hy))
        routes={}
        for left in portals(a):
            for right in portals(b):
                s,t=left[-1],right[-1]
                for elbow in (config(t.x_um[0],s.y_um[0]),config(s.x_um[0],t.y_um[0])):
                    points=simplify_route((*left,elbow,*reversed(right)))
                    distance=sum(abs(v.x_um[0]-u.x_um[0])+abs(v.y_um[0]-u.y_um[0]) for u,v in zip(points,points[1:]))
                    key=tuple((p.x_um[0],p.y_um[0]) for p in points)
                    routes[key]=(distance,points)
        for key,(distance,points) in sorted(routes.items(),key=lambda item:(item[1][0],len(item[1][1]),item[0])):
            yield points
