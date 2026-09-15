"""Bounded greedy search over order-preserving AOD axis assignments.

No environment mutations or SMT dependency. Endpoints are proposed here; every
transport segment, capture and actual pulse is checked by the physical backend.
"""
from dataclasses import dataclass, replace
from math import hypot
from time import perf_counter

from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, MobileCellIndex, Position2D
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.hardware.trap_spacing import minimum_trap_spacing
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.ordered_routes import discrete_corridor_routes,OccupiedSLMGrid
from neutral_atom_strategies.motion.axis_hold_routes import axis_hold_routes,transfer_annotation


@dataclass(frozen=True)
class AxisBatch:
    # gate id, stationary operand, moving operand, destination x, destination y
    assignments: tuple
    pickup: AODConfiguration
    target: AODConfiguration
    bindings: tuple

    @property
    def gate_ids(self):
        return tuple(a[0] for a in self.assignments)


def build_batch(state, assignments, *, translation_only=False, check_closure=True, check_interactions=True):
    """Solve shared-axis equality/order constraints for a partial matching.

    Source coordinate order fixes axis identity; spare axes extend to the right
    and above and remain physically present, even when disabled.
    """
    positions={q:state.placement.position(q,state.world,state.aod) for q in state.atoms}
    used=set(); xm={};ym={}; shifts=set()
    for gid,anchor,mobile,x,y in assignments:
        if {anchor,mobile}&used:raise ValidationError('AXIS_OPERAND_CONFLICT','Batch operands must be disjoint')
        used.update((anchor,mobile));p=positions[mobile]
        for mapping,s,t in ((xm,p.x_um,x),(ym,p.y_um,y)):
            if s in mapping and abs(mapping[s]-t)>1e-7:
                raise ValidationError('AXIS_SHARED_COORDINATE','Atoms sharing an axis need the same target coordinate')
            mapping[s]=t
        shifts.add((round(x-p.x_um,7),round(y-p.y_um,7)))
    if translation_only and len(shifts)>1:
        raise ValidationError('AXIS_TRANSLATION_ONLY','Ablation requires one common displacement')
    gap=minimum_trap_spacing(state.hardware)
    def axes(mapping,count):
        start=tuple(sorted(mapping));end=tuple(mapping[v] for v in start)
        if len(start)>count:raise ValidationError('AXIS_CAPACITY','Too many distinct source axes')
        if any(b-a<=gap+1e-9 for values in (start,end) for a,b in zip(values,values[1:])):
            raise ValidationError('AXIS_ORDER','Axis order or minimum spacing would be violated')
        spare=count-len(start)
        return (start+tuple(start[-1]+10*i for i in range(1,spare+1)),
                end+tuple(end[-1]+10*i for i in range(1,spare+1)))
    sx,tx=axes(xm,state.aod.columns);sy,ty=axes(ym,state.aod.rows)
    pickup=AODConfiguration(sx,sy);target=AODConfiguration(tx,ty)
    if any(not state.world.bounds.contains(Position2D(x,y)) for c in (pickup,target)
           for x in (c.x_um[0],c.x_um[-1]) for y in (c.y_um[0],c.y_um[-1])):
        raise ValidationError('AXIS_BOUNDS','Full capacity axes leave world bounds')
    mobile={a[2] for a in assignments}
    if check_closure:
        captured={q for q,p in positions.items() if p.x_um in xm and p.y_um in ym}
        if captured!=mobile:
            raise ValidationError('AXIS_CAPTURE_CLOSURE','Enabled row × column would capture an unrequested atom')
        ends={q:Position2D(x,y) for _,_,q,x,y in assignments}
        ids=sorted(positions);actual=set()
        for i,a in enumerate(ids):
            p=ends.get(a,positions[a])
            for b in ids[i+1:]:
                q=ends.get(b,positions[b])
                if hypot(p.x_um-q.x_um,p.y_um-q.y_um)<=state.hardware.interaction_distance_um+1e-9:
                    actual.add(frozenset((a,b)))
        if check_interactions and actual!={frozenset((a,b)) for _,a,b,_,_ in assignments}:
            raise ValidationError('AXIS_EXTRA_PAIR','Endpoint interaction pairs differ from requested gates')
    bindings=tuple(sorted((CaptureBinding(q,MobileCellIndex(sy.index(positions[q].y_um),sx.index(positions[q].x_um)),
                       state.placement.atom_to_holder[q].holder_id) for q in mobile),key=lambda b:b.atom_id))
    return AxisBatch(tuple(assignments),pickup,target,bindings)


class OrderedAxisGreedy:
    """Beam constructs batches; outer scheduler greedily commits one real plan.

    Translation ablation and ordered variant share timing, candidates, backend
    and routes. Neither searches cross-batch residency or globally optimal order.
    """
    def __init__(self, *, translation_only=False, beam_width=64, plan_budget=24, route_budget=128, motion_router='axis_hold'):
        self.motion_router=motion_router
        self.translation_only=translation_only
        self.beam_width=beam_width;self.plan_budget=plan_budget;self.route_budget=route_budget
        self.log=[];self.rejections=[]

    def candidates(self,state,deadline):
        ready=sorted((g for g in state.dag.ready_gates() if g.gate_type=='CZ'),key=lambda g:g.id)
        beam=[()];singles=[];rejected={};generated=0
        def rank(a):
            # Geometric estimate only; complete candidates use real durations.
            d=0.
            for _,_,q,x,y in a:
                p=state.placement.position(q,state.world,state.aod)
                d=max(d,abs(x-p.x_um)+abs(y-p.y_um))
            return (-len(a),d,a)
        for gate in ready:
            if perf_counter()>deadline:raise TimeoutError('Axis assignment beam deadline')
            variants=[];a,b=gate.qubit_ids;d=state.hardware.interaction_distance_um
            for anchor,mobile in ((a,b),(b,a)):
                p=state.placement.position(anchor,state.world,state.aod)
                for dx,dy in ((-d,0),(d,0),(0,-d),(0,d)):
                    variants.append((gate.id,anchor,mobile,p.x_um+dx,p.y_um+dy))
            pool=set(beam)
            for variant in variants:
                singles.append((variant,))
                for prefix in beam:
                    group=prefix+(variant,);generated+=1
                    try:build_batch(state,group,translation_only=self.translation_only,check_closure=False)
                    except ValidationError as e:
                        rejected[e.violation.code]=rejected.get(e.violation.code,0)+1;continue
                    pool.add(group)
            beam=sorted(pool,key=rank)[:self.beam_width]
        result=[]
        for group in sorted(set(beam+singles)-{()},key=rank):
            try:result.append(build_batch(state,group,translation_only=self.translation_only))
            except ValidationError as e:rejected[e.violation.code]=rejected.get(e.violation.code,0)+1
        self.log.append({'generated_partial_assignments':generated,'endpoint_candidates':len(result),
                         'beam_width':self.beam_width,'rejected_constraints':rejected,
                         'beam_truncated_search':True,'physical_plan_budget':self.plan_budget})
        return result

    def propose(self,state,deadline):
        if state.hardware.backend not in {'row_column','row_column_orthogonal'} or state.placement.mobile_occupancy:
            raise ValidationError('AXIS_PLATFORM','Requires row_column backend and empty AOD at batch boundary')
        if any(h.holder_type!=HolderType.STATIC for h in state.placement.atom_to_holder.values()):
            raise ValidationError('AXIS_STATIC_START','This experiment starts each batch on SLM')
        rotations=[g for g in state.dag.ready_gates() if g.u_parameters is not None]
        if rotations:
            kind=rotations[0].gate_type;ids=tuple(g.id for g in rotations if g.gate_type==kind)
            p=new_builder(state,ids);p.add(K.RAMAN_ROTATION,f'{kind} ×{len(ids)}',gate_ids=ids)
            return {'kind':kind,'gate_ids':ids},finish(p)
        incumbent=None
        if not self.translation_only:
            baseline=OrderedAxisGreedy(translation_only=True,beam_width=self.beam_width,
                                       plan_budget=self.plan_budget,route_budget=self.route_budget,motion_router=self.motion_router)
            try:
                decision,plan=baseline.propose(state,deadline)
                assignments=decision['assignments']
                batch=build_batch(state,assignments)
                incumbent=((-len(batch.gate_ids),plan.estimated_duration_us,plan.estimated_distance_um,batch.assignments),batch,plan)
            except ValidationError:
                pass  # A failed restricted search does not veto the wider space.
            self.rejections.extend(baseline.rejections)
            self.log.append({'translation_incumbent':incumbent is not None,'baseline':baseline.log})
        try:candidates=self.candidates(state,deadline)
        except TimeoutError:
            if incumbent is None:raise
            candidates=[]
            self.log.append({'wider_search_budget_exhausted':True,'incumbent_retained':True})
        best=incumbent;attempts=0
        for batch in candidates:
            if attempts>=self.plan_budget:break
            if best is not None and len(batch.gate_ids)<len(best[1].gate_ids):break
            if perf_counter()>deadline:
                if best is None:raise TimeoutError('Axis batch realization deadline')
                self.log[-1]['wider_search_budget_exhausted']=True;break
            attempts+=1
            try:plan=realize_batch(state,batch,deadline,self.route_budget,self.rejections,motion_router=self.motion_router)
            except TimeoutError:
                if best is None:raise
                self.log[-1]['wider_search_budget_exhausted']=True;break
            except ValidationError as e:
                self.rejections.append({'stage':'batch','gate_ids':batch.gate_ids,'code':e.violation.code,'message':e.violation.message})
                continue
            key=(-len(batch.gate_ids),plan.estimated_duration_us,plan.estimated_distance_um,batch.assignments)
            if best is None or key<best[0]:best=(key,batch,plan)
            # Candidates sorted by descending size; only compare best-size ties.
            if attempts<len(candidates) and len(candidates[attempts].gate_ids)<len(batch.gate_ids):break
        self.log[-1]['physical_candidates_tried']=attempts
        if best is None:raise ValidationError('AXIS_SEARCH_EXHAUSTED','No validated batch in finite beam/route budgets; not proof of physical impossibility')
        _,batch,plan=best
        return {'kind':'CZ','gate_ids':batch.gate_ids,'assignments':batch.assignments,
                'pickup':batch.pickup,'target':batch.target},plan


def new_builder(state,ids=()):
    return ProgramBuilder(state,TaskIntent(f'ordered-axis/{state.version}/{"-".join(ids)}',TaskTarget(),
                           frozenset(state.atoms),phase='program',gate_effects=frozenset(ids)))


def finish(p,terminal=None):
    p.intent=replace(p.intent,target=terminal or TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
                     p.state.aod.configuration(),trap_state(p.state)))
    return p.finish('ordered-axis-greedy-v1')


def empty_reconfigure(p,target):
    if p.state.placement.mobile_occupancy:raise ValidationError('AXIS_EMPTY_REQUIRED','Empty positioning requires no payload')
    masks=replace(trap_state(p.state),rows=(False,)*p.state.aod.rows,columns=(False,)*p.state.aod.columns)
    if masks!=trap_state(p.state):p.add(K.TRAP_SWITCH,'Disable empty array for axis positioning',switch_state=masks)
    # Coordinate-wise moves preserve orthogonality for every trap.
    for c in (AODConfiguration(target.x_um,p.state.aod.configuration().y_um),target):
        if c!=p.state.aod.configuration():p.add(K.AOD_MOVE,'Position ordered empty axes',configuration=c)


def corridor_routes(start,target,motion_router='axis_hold'):
    if motion_router=='axis_hold':return axis_hold_routes(start,target)
    if motion_router=='legacy_corridor':return discrete_corridor_routes(start,target)
    raise ValueError('Unknown motion router: '+motion_router)


def realize_batch(state,batch,deadline,route_budget,rejections,*,motion_router='axis_hold'):
    paths=corridor_routes(batch.pickup,batch.target,motion_router)
    prepared=new_builder(state,batch.gate_ids)
    empty_reconfigure(prepared,batch.pickup)
    prepared.add(K.AOD_LOAD,f'Load {len(batch.bindings)} operands',bindings=batch.bindings)
    obstacles=OccupiedSLMGrid(prepared.state)
    viable=[];filtered=0
    for path in paths:
        if obstacles.allows(path):viable.append(path)
        else:filtered+=1
    if filtered:rejections.append({'stage':'occupancy_grid','code':'OCCUPIED_SLM_GRID','filtered_routes':filtered,
                                   'blocked_nodes':len(obstacles.blocked),'gate_ids':batch.gate_ids})
    from neutral_atom_env.hardware import get_backend
    backend=get_backend(state.hardware)
    def duration(path):
        return sum(backend.move_duration(prepared.state.aod.configured(a),b,state.hardware) for a,b in zip(path,path[1:]))
    viable.sort(key=lambda path:(duration(path),len(path)))
    for path in viable[:route_budget]:
        if perf_counter()>deadline:raise TimeoutError('Ordered corridor search deadline')
        p=new_builder(state,batch.gate_ids)
        try:
            # Reuse the immutable, checked setup instead of replaying identical
            # empty-axis positioning and LOAD for every geometric candidate.
            p.state=prepared.state;p.operations=list(prepared.operations)
            p.bindings=dict(prepared.bindings);p.distance=prepared.distance
            for i,c in enumerate(path[1:]):
                phase,bindings=transfer_annotation(p.state,p.state.aod.configuration(),c,batch.bindings,'depart') if i==0 else (None,())
                p.add(K.AOD_MOVE,'Order-preserving orthogonal transport',configuration=c,phase=phase,bindings=bindings)
            p.add(K.ENTANGLING_PULSE,f'Parallel CZ ×{len(batch.gate_ids)}',gate_ids=batch.gate_ids)
            back=list(reversed(path[:-1]))
            for i,c in enumerate(back):
                last=i==len(back)-1
                phase,bindings=transfer_annotation(p.state,p.state.aod.configuration(),c,batch.bindings,'approach') if last else (None,())
                p.add(K.AOD_MOVE,'Separate and return ordered axes',configuration=c,phase=phase,bindings=bindings)
            p.add(K.AOD_OFFLOAD,'Restore original SLM atoms',bindings=batch.bindings)
            return finish(p)
        except ValidationError as e:
            rejections.append({'stage':'route','gate_ids':batch.gate_ids,'code':e.violation.code,'message':e.violation.message})
    raise ValidationError('AXIS_ROUTE_EXHAUSTED',f'No legal route in {min(len(viable),route_budget)} checked candidates; {filtered} occupied-grid rejections')


def restore(state,terminal):
    p=new_builder(state);empty_reconfigure(p,terminal.aod_configuration)
    if trap_state(p.state)!=terminal.traps:p.add(K.TRAP_SWITCH,'Restore original trap switches',switch_state=terminal.traps)
    return finish(p,terminal) if p.operations else None
