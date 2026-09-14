"""Bounded local alternatives; every route and resulting program is audited."""
from dataclasses import dataclass, replace
from math import hypot, floor, ceil

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderRef, HolderType as H, Position2D, ZoneType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.hardware.rigid_aod import segment_clearance
from neutral_atom_env.hardware.raman import validate_rotation
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.motion.persistent import ResidentCompiler
from neutral_atom_strategies.motion.planners import HalfGridPlanner, OrthogonalHalfGridPlanner
from neutral_atom_strategies.motion.astar import AStarHalfGridPlanner
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.single_trap import in_zone, route


class ShortestCorridorPlanner:
    """Try the finite corridor family in increasing rigid travel time order."""
    id = 'shortest-valid-half-grid-v1'

    def candidates(self, request):
        def distance(points):
            return sum(hypot(b.x_um[0]-a.x_um[0], b.y_um[0]-a.y_um[0])
                       for a, b in zip(points, points[1:]))
        return sorted([(request.start,request.target),*HalfGridPlanner().candidates(request)], key=distance)


@dataclass(frozen=True)
class GateCandidate:
    key: str
    gate_id: str
    anchor: str | None
    site: str | None
    plan: object

    @property
    def cost(self):
        transfers = sum(o.operation_type in {K.AOD_LOAD, K.AOD_OFFLOAD} for o in self.plan.operations)
        return (self.plan.estimated_duration_us, transfers, self.plan.estimated_distance_um, self.key)

    def summary(self):
        return {'candidate': self.key, 'gate_id': self.gate_id, 'anchor': self.anchor, 'site': self.site,
                'completion_after_us': self.cost[0], 'transfers': self.cost[1], 'distance_um': self.cost[2],
                'switch_operations':sum(o.operation_type==K.TRAP_SWITCH for o in self.plan.operations),
                'ez_switch_operations':sum(o.label=='Disable empty EZ SLM for routing' for o in self.plan.operations),
                'end_holders': primitive(self.plan.predicted_placement)}


class GreedyCompiler(ResidentCompiler):
    id = 'greedy-circuit-v1'

    def __init__(self, *, adaptive_sites=False):
        super().__init__(AStarHalfGridPlanner())
        self.adaptive_sites = adaptive_sites

    def interaction_poses(self,state,position):
        """Four axis-aligned sides at the configured separation, plus reuse."""
        d=hypot(state.hardware.interaction_offset.x_um,state.hardware.interaction_offset.y_um)
        poses=[(name,Position2D(position.x_um+dx,position.y_um+dy))
               for name,dx,dy in [('left',-d,0),('right',d,0),('down',0,-d),('up',0,d)]]
        if state.placement.mobile_occupancy and state.aod.pose not in [p for _,p in poses]:
            if hypot(state.aod.pose.x_um-position.x_um,state.aod.pose.y_um-position.y_um)<=state.hardware.interaction_distance_um:
                poses.insert(0,('reuse',state.aod.pose))
        return poses

    def ranked_sites(self, state, anchor, partner, sites):
        """Shortlist from the whole lattice using current demand, never site IDs.

        This inexpensive estimate only orders the search. Actual validated
        programs (including eviction, support changes and detours) decide cost.
        """
        def pos(q):
            h=state.placement.atom_to_holder[q]
            return state.aod.pose if h.holder_type==H.MOBILE else state.world.traps[h.holder_id].position
        a,b=pos(anchor),pos(partner); h=state.hardware
        def distance(a,b): return hypot(a.x_um-b.x_um,a.y_um-b.y_um)
        def estimate(site):
            p=state.world.traps[site].position
            resident=state.placement.static_occupancy.get(site)==anchor
            blocker=state.placement.static_occupancy.get(site)
            mobile=state.placement.atom_to_holder[partner].holder_type==H.MOBILE
            move=0 if resident else distance(a,p)/h.speed_um_per_us+h.load_duration_us+h.offload_duration_us
            # Moving the anchor may require parking the current loaded partner.
            if mobile and not resident: move+=h.offload_duration_us+h.load_duration_us
            if blocker and blocker!=anchor: move+=h.load_duration_us+h.offload_duration_us
            approach=min(distance(b,pose) for _,pose in self.interaction_poses(state,p))
            # Do not spend the finite site budget on a locally cheap destination
            # whose resident/neighbor parking would violate an EZ reservation.
            # This is ordering only: final handoffs and all carried cells are
            # still checked against their actual state by the shared backend.
            from neutral_atom_env.hardware.ez_neighbors import validate_ez_neighbors
            holders = dict(state.placement.atom_to_holder)
            if blocker and blocker != anchor:
                del holders[blocker]  # Existing candidate explicitly evicts it.
            holders[anchor] = HolderRef(H.STATIC, site)
            blocked = False
            try:
                validate_ez_neighbors(state, holders=holders)
            except ValidationError as error:
                if error.violation.code != 'EZ_NEIGHBOR_OCCUPIED':
                    raise
                blocked = True
            return (blocked, move+approach/h.speed_um_per_us+(0 if mobile else h.load_duration_us),site)
        return sorted(sites,key=estimate)

    def route(self,p,target,**options):
        """Compare preserving supports with disabling empty EZ obstacles.

        The latter keeps empty sites dark until a bound offload or explicit
        terminal restoration enables them. Occupied supports are never toggled.
        Every switch and route is timed and validated on a pure trial builder.
        """
        state=p.state
        if not state.placement.mobile_occupancy or state.aod.pose==target:
            return super().route(p,target,**options)
        empty=[k for k,t in sorted(state.world.traps.items()) if state.slm_enabled[k]
               and k not in state.placement.static_occupancy and in_zone(state,t.position,ZoneType.ENTANGLEMENT)]
        crossing=tuple(k for k in empty if segment_clearance(state.world.traps[k].position,state.aod.pose,target)[0]
                       <state.hardware.slm_clearance_um)
        masks=[()]
        for selected in (crossing,tuple(empty)):
            if selected and selected not in masks:masks.append(selected)
        trials=[];errors=[]
        for selected in masks:
            trial=ProgramBuilder(p.origin,p.intent);trial.state=state
            try:
                if selected:
                    current=trap_state(state)
                    switches=replace(current,slm=tuple((k,False if k in selected else v) for k,v in current.slm))
                    trial.add(K.TRAP_SWITCH,'Disable empty EZ SLM for routing',switch_state=switches)
                route(trial,target,self.planner,**options)
                trials.append((sum(o.duration_us for o in trial.operations),len(selected),trial))
            except ValidationError as error:errors.append(error)
        if not trials:raise errors[0]
        best=min(trials,key=lambda t:(t[0],t[1]))[2]
        for op in best.operations:
            p.add(op.operation_type,op.label,target=op.target_pose,configuration=op.target_configuration,
                  bindings=op.transfer_bindings,phase=op.transfer_phase,switch_state=op.switch_state)

    def alternatives(self, gate_id, state, *, site_limit=4, site_offset=0):
        """Both anchor orientations; bounded EZ sites. Return refusals explicitly."""
        self.check(state)
        node = state.dag.nodes.get(gate_id)
        if node is None or node.status.value != 'ready':
            raise ValidationError('GATE_NOT_READY', 'READY gate required')
        gate = node.gate
        ez = [k for k, t in sorted(state.world.traps.items())
              if in_zone(state, t.position, ZoneType.ENTANGLEMENT)]
        if gate.u_parameters is not None:
            q = gate.qubit_ids[0]
            near=False
            try:validate_rotation(state,gate_id)
            except ValidationError as error:near=error.violation.code=='RAMAN_NEIGHBOR_TOO_CLOSE'
            mobile = state.placement.atom_to_holder[q].holder_type == H.MOBILE
            choices = [(None, None)]  # Direct light on either stable holder.
            free = [k for k in state.world.traps if k not in state.placement.static_occupancy]
            point = state.placement.position(q,state.world,state.aod)
            free.sort(key=lambda k: (hypot(state.world.traps[k].position.x_um-point.x_um,
                                          state.world.traps[k].position.y_um-point.y_um), k))
            # Retain relocation as a fallback, including unavailable addressing zones.
            if mobile:choices.extend((None,s) for s in free[site_offset:site_offset+site_limit])
            truncated = max(0,len(free)-site_offset-site_limit) if mobile else 0
            if near:
                # Explicitly separate a resident CZ pair before local light.
                # Moving the loaded neighbor preserves the addressed SLM atom.
                if state.placement.mobile_occupancy:
                    point=state.placement.position(q,state.world,state.aod)
                    x,y=state.aod.pose.x_um,state.aod.pose.y_um
                    radius=state.hardware.raman_minimum_separation_um
                    span=ceil(radius/5)+1;cx=floor((x-2.5)/5);cy=floor((y-2.5)/5)
                    exits=[Position2D(2.5+5*i,2.5+5*j)
                           for i in range(cx-span,cx+span+2) for j in range(cy-span,cy+span+2)]
                    def separated(p):
                        if not mobile:return hypot(p.x_um-point.x_um,p.y_um-point.y_um)+1e-9>=radius
                        return all(hypot(p.x_um-state.placement.position(other,state.world,state.aod).x_um,
                                         p.y_um-state.placement.position(other,state.world,state.aod).y_um)+1e-9>=radius
                                   for other,atom in state.atoms.items() if other!=q and atom.alive)
                    exits=[p for p in exits if state.world.bounds.contains(p) and separated(p)]
                    exits.sort(key=lambda p:(abs(p.x_um-x)+abs(p.y_um-y),p.x_um,p.y_um))
                    choices.extend(('clear',p) for p in exits[site_offset:site_offset+site_limit])
                    truncated+=max(0,len(exits)-site_offset-site_limit)
                free=[k for k in state.world.traps if k not in state.placement.static_occupancy]
                point=state.placement.position(q,state.world,state.aod)
                free.sort(key=lambda k:(hypot(state.world.traps[k].position.x_um-point.x_um,state.world.traps[k].position.y_um-point.y_um),k))
                choices.extend((None,s) for s in free[site_offset:site_offset+site_limit] if (None,s) not in choices)
                truncated+=max(0,len(free)-site_offset-site_limit)
        elif gate.gate_type == 'CZ':
            choices=[]
            for q in gate.qubit_ids:
                partner=next(other for other in gate.qubit_ids if other!=q)
                ranked=self.ranked_sites(state,q,partner,ez) if self.adaptive_sites else ez
                choices.extend((q,s) for s in ranked[site_offset:site_offset+site_limit])
            truncated = max(0, len(ez)-site_offset-site_limit)*2
        else:
            raise ValidationError('UNSUPPORTED_GATE', 'Greedy supports H, X, Y, Z, T, CZ')
        candidates = []; rejected = []
        for anchor, site in choices:
            key = f'{gate_id}/{anchor or "raman"}/{site or "direct"}'
            intent = TaskIntent(f'{self.id}/{state.version}/{key}', TaskTarget(),
                                frozenset(gate.qubit_ids), gate_id, 'effect', gate_id)
            p = ProgramBuilder(state, intent)
            try:
                if gate.u_parameters is not None:
                    if anchor=='clear':self.route(p,site,label='Separate neighbor before single-qubit light')
                    elif site is not None:self.move_atom(p,gate.qubit_ids[0],site)
                    kind = K.RAMAN_ROTATION
                else:
                    blocker = p.state.placement.static_occupancy.get(site)
                    if blocker is not None and blocker != anchor:
                        self.move_atom(p, blocker, self.spare(p.state, exclude=(site,)))
                    self.move_atom(p, anchor, site)
                    partner = next(q for q in gate.qubit_ids if q != anchor)
                    self.load_atom(p, partner)
                    kind = K.ENTANGLING_PULSE
                poses=self.interaction_poses(p.state,p.state.world.traps[site].position) if kind==K.ENTANGLING_PULSE else [('static',None)]
                for direction,pose in poses:
                    branch_key=f'{gate_id}/{anchor}/{direction}/{site}' if pose is not None else key
                    branch=ProgramBuilder(state,replace(intent,task_id=f'{self.id}/{state.version}/{branch_key}'))
                    branch.state=p.state;branch.operations=list(p.operations);branch.bindings=dict(p.bindings);branch.distance=p.distance
                    try:
                        if pose is not None:self.route(branch,pose,label=f'Greedy partner to CZ ({direction})')
                        branch.add(kind,'Greedy gate effect')
                        branch.intent=replace(branch.intent,target=TaskTarget(tuple(sorted(branch.state.placement.atom_to_holder.items())),
                            branch.state.aod.configuration(),trap_state(branch.state)))
                        candidates.append(GateCandidate(branch_key,gate_id,anchor,site if isinstance(site,str) else None,branch.finish(self.id)))
                    except ValidationError as error:
                        rejected.append({'candidate':branch_key,'violation':primitive(error.violation)})
            except ValidationError as error:
                rejected.append({'candidate': key, 'violation': primitive(error.violation)})
        return candidates, rejected, truncated
