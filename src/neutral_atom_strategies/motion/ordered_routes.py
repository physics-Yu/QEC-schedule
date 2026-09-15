"""Discrete orthogonal routes and stop removal for ordered Cartesian axes."""
from itertools import product
from math import floor,ceil

from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError


class OccupiedSLMGrid:
    """Read-only blocked routing nodes derived from CURRENT static holders.

    This is a cheap necessary check, never a replacement for continuous swept
    validation. All enabled Cartesian intersections (including empty ones) use
    the same forbidden-node set. No trap is physically switched by this map.
    """
    spacing=2.5

    def __init__(self,state):
        self.blocked=set();step=self.spacing;radius=state.hardware.minimum_clearance_um
        for trap in state.placement.static_occupancy:
            p=state.world.traps[trap].position
            for ix in range(ceil((p.x_um-radius)/step),floor((p.x_um+radius)/step)+1):
                for iy in range(ceil((p.y_um-radius)/step),floor((p.y_um+radius)/step)+1):
                    if (ix*step-p.x_um)**2+(iy*step-p.y_um)**2<(radius-1e-9)**2:
                        self.blocked.add((ix,iy))
        self.cells=tuple(state.aod.active_cells)

    def allows(self,points):
        step=self.spacing
        for a,b in zip(points,points[1:]):
            for cell in self.cells:
                u,v=a.position(cell),b.position(cell)
                if abs(u.y_um-v.y_um)<1e-9 and abs(u.y_um/step-round(u.y_um/step))<1e-9:
                    y=round(u.y_um/step)
                    if any((x,y) in self.blocked for x in range(ceil(min(u.x_um,v.x_um)/step),floor(max(u.x_um,v.x_um)/step)+1)):
                        return False
                elif abs(u.x_um-v.x_um)<1e-9 and abs(u.x_um/step-round(u.x_um/step))<1e-9:
                    x=round(u.x_um/step)
                    if any((x,y) in self.blocked for y in range(ceil(min(u.y_um,v.y_um)/step),floor(max(u.y_um,v.y_um)/step)+1)):
                        return False
        return True


def merge_straight_runs(points):
    """Remove waypoint stops when every axis continues on its straight line.

    A change of x/y direction or reversal of ANY individual axis keeps the stop.
    Merging may change relative progress of columns; the physical compiler must
    revalidate the resulting complete segments and recompute their duration.
    Never call across load, pulse, switch, or offload operation boundaries.
    """
    out=[]
    for c in points:
        if out and c==out[-1]:continue
        out.append(c)
        while len(out)>=3:
            a,b,c=out[-3:]
            axis=0 if a.y_um==b.y_um==c.y_um else 1 if a.x_um==b.x_um==c.x_um else None
            if axis is None:break
            first,mid,last=(p.x_um if axis==0 else p.y_um for p in (a,b,c))
            if any((y-x)*(z-y)<-1e-10 for x,y,z in zip(first,mid,last)):break
            out.pop(-2)
    return tuple(out)


def discrete_corridor_routes(start,target,spacing=2.5):
    """Bounded portals/corners on 2.5 + spacing*k; not complete grid A*.

    The spacing=2.5 graph contains both old half-grid corridors and SLM-aligned
    lines. Static atoms, enabled empty SLMs, and active empty AOD intersections
    are still checked by the backend; an available grid line is not a free lane.
    """
    def on_grid(v):return abs((v-2.5)/spacing-round((v-2.5)/spacing))<1e-9
    def portal(c,axis,side):
        values=c.x_um if axis==0 else c.y_um
        def snap(v):
            k=(v-2.5)/spacing
            # Strict neighboring lanes ensure a valid extraction option even
            # when the SLM itself is now on the routing grid.
            i=(ceil(k)-1) if side<0 else (floor(k)+1)
            return 2.5+spacing*i
        values=tuple(snap(v) for v in values)
        return AODConfiguration(values,c.y_um) if axis==0 else AODConfiguration(c.x_um,values)
    def portals(c):
        if all(on_grid(v) for v in c.x_um+c.y_um):yield(c,c,c)
        for first,sx,sy in product((0,1),(-1,1),(-1,1)):
            try:
                a=portal(c,first,sx if first==0 else sy)
                b=portal(a,1-first,sy if first==0 else sx)
                yield(c,a,b)
                # One existing grid axis can connect without the extra dogleg.
                if all(on_grid(v) for v in a.x_um+a.y_um):yield(c,a,a)
            except ValidationError:continue
    routes={}
    for left,right in product(tuple(portals(start)),tuple(portals(target))):
        a,b=left[-1],right[-1]
        for corner in (AODConfiguration(b.x_um,a.y_um),AODConfiguration(a.x_um,b.y_um)):
            points=merge_straight_runs((*left,corner,*reversed(right)))
            key=tuple((p.x_um,p.y_um) for p in points)
            cost=sum(max(abs(x-y) for x,y in zip(u.x_um+u.y_um,v.x_um+v.y_um)) for u,v in zip(points,points[1:]))
            routes[key]=(cost,points)
    return [r for _,r in sorted(routes.values(),key=lambda v:(v[0],len(v[1]),tuple((c.x_um,c.y_um) for c in v[1])))]
