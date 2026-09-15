"""Readout support/target policy, independent of circuit IDs and movement search.

Cheap target estimates precede bounded movement realization. They are not
physical feasibility proofs. The environment remains the sole legality model.
"""
from dataclasses import dataclass,replace
from itertools import product
from math import sqrt
from neutral_atom_env.domain.models import ZoneType,HolderType,Position2D
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.rigid_aod import segment_clearance
from neutral_atom_strategies.scheduling.ordered_greedy import build_batch,new_builder,finish,empty_reconfigure


@dataclass(frozen=True)
class ReadoutTarget:
    support: str
    positions: tuple
    slm: tuple
    estimated_us: float
    features: dict


class ReadoutPlacementPolicy:
    """Replaceable candidate/score/selection policy for one readout service.

    Source holders are restored after the service. Cross-service residency and
    concurrent release of the AOD are deliberately not optimized by this policy.
    """
    def __init__(self,mode='adaptive',candidate_budget=16,top_k=3):
        if mode not in ('adaptive','aod_only','slm_only'):raise ValueError('Unknown readout placement mode')
        if type(candidate_budget)!=int or not 1<=candidate_budget<=64:raise ValueError('Readout candidate budget must be 1..64')
        if type(top_k)!=int or not 1<=top_k<=candidate_budget:raise ValueError('Readout top_k must be 1..candidate_budget')
        self.mode=mode;self.candidate_budget=candidate_budget;self.top_k=top_k;self.log=[]
        self.generation_rejections={}

    def candidates(self,state,atoms):
        self.generation_rejections={}
        points={q:state.placement.position(q,state.world,state.aod) for q in atoms}
        if self.mode!='aod_only' and all(any(z.zone_type==ZoneType.MEASUREMENT and z.bounds.contains(p)
                                            for z in state.world.zones) for p in points.values()):
            return [ReadoutTarget('slm',tuple(sorted((q,(p.x_um,p.y_um)) for q,p in points.items())),
                    tuple(sorted((q,state.placement.atom_to_holder[q].holder_id) for q in atoms)),0.,
                    dict(max_dx_um=0,max_dy_um=0,blocked_direct_rays=0,estimated_transfer_us=0,
                         empty_position_estimate_us=0,estimated_motion_and_escape_us=0))]
        xs=sorted({p.x_um for p in points.values()});ys=sorted({p.y_um for p in points.values()})
        stationary=[state.placement.position(q,state.world,state.aod) for q in state.atoms if q not in points and state.atoms[q].alive]
        hw=state.hardware;targets={}
        def time(d):
            return max(1.5*d/hw.speed_um_per_us,sqrt(6*d/hw.max_acceleration_um_per_us2),
                       (12*d/hw.max_jerk_um_per_us3)**(1/3))
        def add(support,positions,slm=()):
            positions=tuple(sorted(positions.items()));key=(support,positions)
            if key in targets:return
            try:batch=build_batch(state,tuple((q,q,q,x,y) for q,(x,y) in positions),check_interactions=False)
            except ValidationError as e:
                code=e.violation.code
                self.generation_rejections[code]=self.generation_rejections.get(code,0)+1
                return
            dx=max(abs(x-points[q].x_um) for q,(x,y) in positions)
            dy=max(abs(y-points[q].y_um) for q,(x,y) in positions)
            # Cheap two orthogonal rays estimate the need for an escape lane;
            # no grid search or physical move compilation occurs at this stage.
            hits=[]
            for horizontal_first in (True,False):
                count=0
                for q,(x,y) in positions:
                    p=points[q];end=Position2D(x,y)
                    corner=Position2D(x,p.y_um) if horizontal_first else Position2D(p.x_um,y)
                    count+=sum(any(segment_clearance(o,a,b)[0]<hw.minimum_clearance_um-1e-9
                                   for a,b in ((p,corner),(corner,end))) for o in stationary)
                hits.append(count)
            blocked=min(hits)
            transfer=(hw.load_duration_us+hw.offload_duration_us)*(2 if support=='slm' else 1)
            current=state.aod.configuration()
            empty=time(max(abs(a-b) for a,b in zip(current.x_um,batch.pickup.x_um)))+time(max(abs(a-b) for a,b in zip(current.y_um,batch.pickup.y_um)))
            estimate=2*(time(dx)+time(dy))+transfer+empty+(2*time(2.5) if blocked else 0)
            targets[key]=ReadoutTarget(support,positions,tuple(sorted(slm)),estimate,
                dict(max_dx_um=dx,max_dy_um=dy,blocked_direct_rays=blocked,
                     estimated_transfer_us=transfer,empty_position_estimate_us=empty,
                     estimated_motion_and_escape_us=estimate-transfer-empty))

        for zone in state.world.zones:
            if zone.zone_type!=ZoneType.MEASUREMENT:continue
            rect=zone.bounds
            if self.mode!='slm_only':
                # Preserve original gaps or compress axes to a conservative
                # discrete pitch. These change shape without changing axis order.
                pitch=max(2.5,2.5*int(hw.minimum_axis_spacing_um/2.5+1))
                for xshape,yshape in product((tuple(x-xs[0] for x in xs),tuple(i*pitch for i in range(len(xs)))),
                                              (tuple(y-ys[0] for y in ys),tuple(i*pitch for i in range(len(ys))))):
                    if xshape[-1]>rect.upper.x_um-rect.lower.x_um or yshape[-1]>rect.upper.y_um-rect.lower.y_um:continue
                    def clamp(v,lo,hi):return max(lo,min(hi,v))
                    x0=clamp(xs[0],rect.lower.x_um,rect.upper.x_um-xshape[-1])
                    y0=clamp(ys[0],rect.lower.y_um,rect.upper.y_um-yshape[-1])
                    for ox,oy in product((0,-2.5,2.5,-5,5),(0,-2.5,2.5)):
                        tx=tuple(clamp(x0+ox,rect.lower.x_um,rect.upper.x_um-xshape[-1])+v for v in xshape)
                        ty=tuple(clamp(y0+oy,rect.lower.y_um,rect.upper.y_um-yshape[-1])+v for v in yshape)
                        add('aod',{q:(tx[xs.index(p.x_um)],ty[ys.index(p.y_um)]) for q,p in points.items()})
            if self.mode!='aod_only':
                free={(t.position.x_um,t.position.y_um):t.id for t in state.world.traps.values()
                      if rect.contains(t.position) and t.id not in state.placement.static_occupancy}
                anchor=points[min(points)]
                # Existing translated footprints remain available as baselines.
                for x,y in free:
                    positions={q:(x+p.x_um-anchor.x_um,y+p.y_um-anchor.y_um) for q,p in points.items()}
                    if all(p in free for p in positions.values()):add('slm',positions,((q,free[p]) for q,p in positions.items()))
                # Independent monotone axis assignment also permits nonuniform
                # reshape; only actually existing intersections can be used.
                fx=sorted({x for x,y in free});fy=sorted({y for x,y in free})
                for i,j in product(range(len(fx)-len(xs)+1),range(len(fy)-len(ys)+1)):
                    positions={q:(fx[i+xs.index(p.x_um)],fy[j+ys.index(p.y_um)]) for q,p in points.items()}
                    if all(p in free for p in positions.values()):add('slm',positions,((q,free[p]) for q,p in positions.items()))
        return sorted(targets.values(),key=lambda c:(c.estimated_us,c.features['blocked_direct_rays'],c.positions,c.support))

    def realize(self,state,compiler,gates,resets,target):
        ids=tuple(g.id for g in gates)+tuple(g.id for g in resets)
        p=new_builder(state,ids);source={g.qubit_ids[0]:state.placement.atom_to_holder[g.qubit_ids[0]].holder_id for g in gates}
        batch=None
        if target.support=='slm':compiler.transfer_group(p,dict(target.slm),'Move readout atoms to selected MZ SLM')
        else:
            batch=build_batch(state,tuple((q,q,q,x,y) for q,(x,y) in target.positions),check_interactions=False)
            empty_reconfigure(p,batch.pickup);p.add(K.AOD_LOAD,'Load readout group for AOD measurement',bindings=batch.bindings)
            compiler.move_loaded(p,batch.target,'Move supported atoms to selected MZ position')
        p.add(K.MEASUREMENT if gates[0].gate_type=='MEASURE' else K.RESET,
              'Readout on '+target.support.upper(),gate_ids=tuple(g.id for g in gates))
        if resets:p.add(K.RESET,'Reset measured atoms on stable support',gate_ids=tuple(g.id for g in resets))
        if batch is None:compiler.transfer_group(p,source,'Return readout atoms to working sites')
        else:
            compiler.move_loaded(p,batch.pickup,'Return supported readout atoms to working sites')
            p.add(K.AOD_OFFLOAD,'Restore readout atoms to source SLM',bindings=batch.bindings)
        return finish(p)

    def plan(self,state,compiler,gates,resets):
        atoms=tuple(g.qubit_ids[0] for g in gates)
        if state.placement.mobile_occupancy or any(state.placement.atom_to_holder[q].holder_type!=HolderType.STATIC for q in atoms):
            raise ValidationError('READOUT_POLICY_START','Current service policy requires SLM source holders and empty AOD')
        candidates=self.candidates(state,atoms)
        effect_us=(state.hardware.measurement_duration_us if gates[0].gate_type=='MEASURE' else state.hardware.reset_duration_us)
        if resets:effect_us+=state.hardware.reset_duration_us
        candidates=[replace(c,estimated_us=c.estimated_us+effect_us,features=c.features|{'effect_us':effect_us}) for c in candidates]
        shortlist=candidates[:self.candidate_budget]
        # Keep one fallback of either support type if the budget permits it.
        if self.mode=='adaptive' and self.candidate_budget>=2:
            for support in ('aod','slm'):
                if not any(c.support==support for c in shortlist):
                    alternative=next((c for c in candidates if c.support==support),None)
                    if alternative is not None:shortlist[-1:]=[alternative]
        log=dict(mode=self.mode,gate_ids=[g.id for g in gates],generated=len(candidates),
                 generation_rejections=dict(self.generation_rejections),
                 candidate_budget=self.candidate_budget,top_k=self.top_k,candidates=[],selected=None)
        self.log.append(log);best=None;accepted=0
        for target in shortlist:
            entry=dict(support=target.support,positions=target.positions,estimated_us=target.estimated_us,features=target.features)
            log['candidates'].append(entry)
            try:plan=self.realize(state,compiler,gates,resets,target)
            except ValidationError as e:
                entry.update(status='rejected',code=e.violation.code,message=str(e));continue
            except TimeoutError:
                entry.update(status='timeout');log['budget_exhausted']=True
                if best is None:raise
                break
            entry.update(status='accepted',actual_us=plan.estimated_duration_us)
            key=(plan.estimated_duration_us,plan.estimated_distance_um,target.positions)
            if best is None or key<best[0]:best=(key,plan,entry)
            accepted+=1
            if accepted>=self.top_k:break
        if best is None:raise ValidationError('READOUT_TARGETS_EXHAUSTED',f'No validated readout target among {len(log["candidates"])} checked candidates; not proof of infeasibility')
        log['selected']=best[2];log['optimality_claim']=False
        return best[1],len(resets)
