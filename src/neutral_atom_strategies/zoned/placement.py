"""Bounded immediate-descent search over layer-local anchor sites and roles.

Cheap immutable placement hypotheses are ranked before physical route search.
This is neither exhaustive search nor an admissible global optimality proof.
"""
from dataclasses import dataclass
from heapq import heappop, heappush, nsmallest
from itertools import count
from math import hypot, sqrt
from time import perf_counter
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderRef, HolderType, Position2D, ZoneType
from neutral_atom_env.hardware.ez_neighbors import validate_ez_neighbors
from neutral_atom_env.world import PlacementState
from neutral_atom_strategies.motion.single_trap import in_zone
from .models import LayerPlacement, PlacementChoice
from .reuse import future_partners
from .routing import compatible_groups


@dataclass(frozen=True)
class PlacementView:
    """Geometry-only hypothesis; never submitted, replayed or used as runtime.

    Avoid constructing a SimulationState (and validating its quantum/support
    state) for each cheap search node. Physical codegen starts from real state.
    """
    base: object
    placement: PlacementState

    def __getattr__(self,name):
        return getattr(self.base,name)


def projected(state, choices):
    return project_destinations(state,{c.anchor:c.site for c in choices})


def project_destinations(state,destinations):
    holders = dict(state.placement.atom_to_holder)
    for q,site in destinations.items():
        holders[q] = HolderRef(HolderType.STATIC,site)
    if len(set(holders.values()))!=len(holders):
        raise ValidationError('ZONED_TARGET_DUPLICATE','Placement hypothesis has duplicate holders')
    view=PlacementView(state,PlacementState(holders))
    validate_ez_neighbors(view)
    return view


class IDSPlacer:
    def __init__(self, *, trials=4, queue_capacity=64, site_limit=8):
        self.trials = trials
        self.queue_capacity = queue_capacity
        self.site_limit = site_limit
        self.stats = {}

    def search(self, state, gates, deadline, *, staged_incumbent=True):
        if staged_incumbent:
            # Demand-only, shape-preserving transport is one placement family,
            # never an unconditional whole-patch preprocessing step.
            base=self.search(state,gates,deadline,staged_incumbent=False)
            stats=dict(self.stats)
            for staging in self.translated_frontier(state,gates):
                staged=project_destinations(state,dict(staging))
                alternatives=self.search(staged,gates,deadline,staged_incumbent=False)
                partners=future_partners(state,(g.id for g in gates))
                base+=tuple(LayerPlacement(a.choices,self.cost(state,a.choices,partners,dict(staging)),staging)
                            for a in alternatives)
                stats['staged_incumbent']=dict(self.stats)
                break  # One bounded constructive incumbent, not layout search.
            self.stats=stats
            return tuple(sorted(base,key=lambda a:a.estimated_cost))[:self.trials]
        sites = tuple(t for t in state.world.traps.values() if in_zone(state, t.position, ZoneType.ENTANGLEMENT))
        occupied = state.placement.static_occupancy
        positions = {q: state.placement.position(q, state.world, state.aod) for q in state.atoms}
        partners = future_partners(state, (g.id for g in gates))
        stats = self.stats = dict(expanded=0, endpoint_rejections=0, goals=0, queue_peak=0,
                                 trials=self.trials, queue_capacity=self.queue_capacity, site_limit=self.site_limit)

        def options(prefix, gate):
            used = {c.site for c in prefix}
            a, b = gate.qubit_ids
            distance = state.hardware.interaction_distance_um
            out = []
            for anchor, mobile in ((a, b), (b, a)):
                home = state.placement.atom_to_holder[anchor].holder_id
                available = [t for t in sites if t.id not in used and (t.id not in occupied or occupied[t.id] == anchor)]
                # Resident anchors first, then nearby transport destinations.
                available.sort(key=lambda t: (t.id != home, hypot(t.position.x_um-positions[mobile].x_um,
                    t.position.y_um-positions[mobile].y_um) + .5*hypot(t.position.x_um-positions[anchor].x_um,
                    t.position.y_um-positions[anchor].y_um), t.id))
                for site in available[:self.site_limit]:
                    if perf_counter() > deadline:
                        raise TimeoutError('Zoned placement deadline')
                    p = site.position
                    for dx, dy in ((0, -distance), (0, distance), (-distance, 0), (distance, 0)):
                        target = Position2D(p.x_um+dx, p.y_um+dy)
                        if not in_zone(state, target, ZoneType.ENTANGLEMENT):
                            continue
                        choice = PlacementChoice(gate.id, anchor, mobile, site.id, target.x_um, target.y_um)
                        candidate = (*prefix, choice)
                        try:
                            hypothesis = projected(state, candidate)
                            validate_ez_neighbors(hypothesis)
                            # Necessary pulse clearance; full group interactions
                            # and continuous trajectories remain codegen's job.
                            for q in positions:
                                if q in (anchor, mobile):
                                    continue
                                other = hypothesis.placement.position(q, state.world, state.aod)
                                if hypot(other.x_um-target.x_um, other.y_um-target.y_um) <= distance+1e-9:
                                    raise ValidationError('ZONED_ENDPOINT_PAIR', 'Unrequested endpoint interaction')
                        except ValidationError:
                            stats['endpoint_rejections'] += 1
                            continue
                        out.append((self.cost(state, candidate, partners,partial=True), candidate))
            return sorted(out, key=lambda v: (v[0], tuple(c.assignment for c in v[1])))

        queue = []
        serial = count()
        prefix = ()
        goals = []
        best_prefix = ()
        # Immediate descent: expand the best child now, retain bounded siblings.
        while True:
            if perf_counter() > deadline:
                raise TimeoutError('Zoned placement deadline')
            if len(prefix) == len(gates):
                goals.append(LayerPlacement(prefix, self.cost(state, prefix, partners)))
                stats['goals'] += 1
                if len(goals) >= self.trials:
                    break
                children = []
            else:
                stats['expanded'] += 1
                if stats['expanded'] > max(len(gates)*self.trials,self.queue_capacity):
                    stats['expansion_limit'] = True
                    break
                children = options(prefix, gates[len(prefix)])
            if children:
                for cost, child in children[1:]:
                    heappush(queue, (cost, next(serial), child))
                if len(queue) > self.queue_capacity:
                    queue = nsmallest(self.queue_capacity, queue)
                    # nsmallest returns sorted order, which is also a heap.
                stats['queue_peak'] = max(stats['queue_peak'], len(queue))
                prefix = children[0][1]
                if len(prefix)>len(best_prefix):best_prefix=prefix
            elif queue:
                _, _, prefix = heappop(queue)
            else:
                break
        # Small resident incumbents prevent bounded diving from discarding a
        # regular, already usable row/column pattern. They are circuit-agnostic.
        goals.extend(self.resident_incumbents(state,gates,partners))
        if not goals and best_prefix:
            goals=[LayerPlacement(best_prefix,self.cost(state,best_prefix,partners))]
            stats['partial_frontier']=len(best_prefix)
        unique={tuple(c.assignment for c in g.choices):g for g in goals}
        return tuple(sorted(unique.values(),key=lambda g:g.estimated_cost))[:self.trials]

    @staticmethod
    def resident_incumbents(state,gates,partners):
        positions={q:state.placement.position(q,state.world,state.aod) for g in gates for q in g.qubit_ids}
        if not all(in_zone(state,p,ZoneType.ENTANGLEMENT) for p in positions.values()):return ()
        out=[];d=state.hardware.interaction_distance_um
        for swap in (False,True):
            for dx,dy in ((-d,0),(d,0),(0,-d),(0,d)):
                choices=[]
                for gate in gates:
                    a,b=gate.qubit_ids[::-1] if swap else gate.qubit_ids
                    p=positions[a];x,y=p.x_um+dx,p.y_um+dy
                    if not in_zone(state,Position2D(x,y),ZoneType.ENTANGLEMENT):break
                    choices.append(PlacementChoice(gate.id,a,b,state.placement.atom_to_holder[a].holder_id,x,y))
                else:
                    choices=tuple(choices)
                    out.append(LayerPlacement(choices,IDSPlacer.cost(state,choices,partners)))
        return tuple(out)

    @staticmethod
    def translated_frontier(state,gates):
        atoms=sorted({q for g in gates for q in g.qubit_ids})
        if not atoms:return
        positions={q:state.placement.position(q,state.world,state.aod) for q in atoms}
        if all(in_zone(state,p,ZoneType.ENTANGLEMENT) for p in positions.values()):return
        # Do not move already-resident atoms merely to preserve a patch shape.
        if any(in_zone(state,p,ZoneType.ENTANGLEMENT) for p in positions.values()):return
        first=positions[atoms[0]]
        lookup={(t.position.x_um,t.position.y_um):t.id for t in state.world.traps.values()
                if in_zone(state,t.position,ZoneType.ENTANGLEMENT) and t.id not in state.placement.static_occupancy}
        for x,y in sorted(lookup,key=lambda p:(hypot(p[0]-first.x_um,p[1]-first.y_um),p)):
            dx,dy=x-first.x_um,y-first.y_um
            destinations={q:lookup.get((p.x_um+dx,p.y_um+dy)) for q,p in positions.items()}
            if any(t is None for t in destinations.values()):continue
            try:project_destinations(state,destinations)
            except ValidationError:continue
            yield tuple(sorted(destinations.items()))
            return

    @staticmethod
    def cost(state, choices, partners, staging=None,*,partial=False):
        destinations=dict(staging or {})
        destinations.update({c.anchor:c.site for c in choices})
        hypothetical = project_destinations(state,destinations)
        moves = []
        for q,site in destinations.items():
            if state.placement.atom_to_holder[q].holder_id != site:
                p = state.world.traps[site].position
                moves.append((q,q,q,p.x_um,p.y_um))
        # A partial rectangle can close after later gate assignments. Rejecting
        # it now destroys parallelism (three corners become four singletons).
        # Codegen requires full closure of each completed actual transport.
        groups = compatible_groups(state, moves, interactions=False,require_closure=not partial)
        gates = compatible_groups(hypothetical, [c.assignment for c in choices],require_closure=not partial)
        value = 0.
        # Proxy uses hardware transfer cost plus max group movement length.
        # It is deliberately NOT reported as physical execution time.
        hardware=state.hardware
        def motion(d):
            return max(1.5*d/hardware.speed_um_per_us,sqrt(6*d/hardware.max_acceleration_um_per_us2),
                       (12*d/hardware.max_jerk_um_per_us3)**(1/3))
        for source, batches, multiplier in ((state, groups, 1), (hypothetical, gates, 1)):
            for group in batches:
                longest = max(hypot(x-source.placement.position(q,source.world,source.aod).x_um,
                                    y-source.placement.position(q,source.world,source.aod).y_um)
                              for _,_,q,x,y in group)
                value += hardware.load_duration_us + hardware.offload_duration_us + multiplier*motion(longest)
        for c in choices:
            partner = partners.get(c.anchor)
            if partner:
                p = hypothetical.placement.position(partner, state.world, state.aod)
                t = state.world.traps[c.site].position
                value += .1*motion(hypot(p.x_um-t.x_um,p.y_um-t.y_um))
        return value
