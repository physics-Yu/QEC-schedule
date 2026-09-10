"""Replaceable geometric routing policy. Backend remains the authority on legality."""
from dataclasses import dataclass
from math import floor
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
