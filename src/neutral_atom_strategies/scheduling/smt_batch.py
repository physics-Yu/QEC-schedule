"""Joint symbolic batching for a declared rigid, restoring transport family.

This is an experiment backend, not OLSQ-DPQA or a complete motion planner.
Gate subsets, operand orientation and common displacement are solved jointly.
Each batch returns atoms to their SLMs; full swept legality remains in the env.
No list of complete heuristic batches is supplied to Z3.
"""
from dataclasses import dataclass
from itertools import combinations
from math import hypot
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, ZoneType
from neutral_atom_strategies.motion.single_trap import in_zone


@dataclass(frozen=True)
class BatchDecision:
    kind: str
    gate_ids: tuple
    members: tuple = ()
    shift: tuple = (0., 0.)


class SMTBatchPlanner:
    """Bounded model enumeration with explicit SAT/UNSAT/UNKNOWN diagnostics."""
    id = 'smt-rigid-restoring-v1'

    def __init__(self, *, mode='single', timeout_ms=5000, model_budget=16):
        if mode not in {'single', 'multi'}:
            raise ValueError('mode must be single or multi')
        if timeout_ms < 1 or model_budget < 1:
            raise ValueError('positive solver budgets required')
        self.mode, self.timeout_ms, self.model_budget = mode, timeout_ms, model_budget
        self.log = []

    @staticmethod
    def validate_family(state):
        if state.hardware.backend != 'rigid' or state.placement.mobile_occupancy or state.event_queue:
            raise ValidationError('SMT_FAMILY', 'Requires idle rigid AOD and all atoms on SLM')
        if any(h.holder_type != HolderType.STATIC for h in state.placement.atom_to_holder.values()):
            raise ValidationError('SMT_FAMILY', 'All operands must start on SLM')
        axes = state.aod.configuration()
        if any(abs(b-a-10) > 1e-8 for axis in (axes.x_um, axes.y_um) for a,b in zip(axis,axis[1:])):
            raise ValidationError('SMT_FAMILY', 'First experiment supports regular 10 um rigid axes')
        points = {q:state.placement.position(q,state.world,state.aod) for q in state.atoms}
        if any(not in_zone(state,p,ZoneType.ENTANGLEMENT) for p in points.values()):
            raise ValidationError('SMT_FAMILY', 'Restoring-batch experiment starts at fixed EZ SLM sites')
        for axis in ('x_um','y_um'):
            first = min(getattr(p,axis) for p in points.values())
            if any(abs((getattr(p,axis)-first)/10-round((getattr(p,axis)-first)/10))>1e-8 for p in points.values()):
                raise ValidationError('SMT_FAMILY', 'Occupied sites must lie on one 10 um lattice')
        if any(g.gate_type not in {'H','X','Y','Z','T','CZ'} or g.condition for g in state.dag.circuit.gates):
            raise ValidationError('SMT_GATE_FAMILY', 'This experiment accepts unconditional H/X/Y/Z/T/CZ only')
        return points

    def proposals(self, state, *, deadline=None):
        import z3 as z
        points = self.validate_family(state)
        gates = list(state.dag.ready_gates()) if self.mode=='single' else [
            g for g in state.dag.circuit.gates if state.dag.nodes[g.id].status.value!='completed']
        if not gates:
            return
        deadline = deadline or perf_counter()+60
        # Integer half-micrometre coordinates avoid nonlinear arithmetic.
        def coord(x):
            if abs(x*2-round(x*2))>1e-7:
                raise ValidationError('SMT_COORDINATES', 'Experiment requires half-um coordinates')
            return round(x*2)
        xy={q:(coord(p.x_um),coord(p.y_um)) for q,p in points.items()}
        radius=hypot(state.hardware.interaction_offset.x_um,state.hardware.interaction_offset.y_um)
        d=coord(radius)
        options={}
        for g in gates:
            if g.gate_type!='CZ':continue
            a,b=g.qubit_ids
            options[g.id]=[(anchor,mobile,xy[anchor][0]+ox-xy[mobile][0],xy[anchor][1]+oy-xy[mobile][1])
                for anchor,mobile in ((a,b),(b,a)) for ox,oy in ((0,d),(d,0),(0,-d),(-d,0))]
        shifts=sorted({(dx,dy) for opts in options.values() for _,_,dx,dy in opts})
        kinds={k:i for i,k in enumerate(('CZ','H','X','Y','Z','T'))}
        emitted=0
        horizons=(1,) if self.mode=='single' else range(1,len(gates)+1)
        for horizon in horizons:
            started=perf_counter()
            opt=z.Optimize()
            t={g.id:z.Int('t_'+g.id) for g in gates}
            choice={g.id:z.Int('choice_'+g.id) for g in gates if g.gate_type=='CZ'}
            kind=[z.Int(f'kind_{s}') for s in range(horizon)]
            dx=[z.Int(f'dx_{s}') for s in range(horizon)]
            dy=[z.Int(f'dy_{s}') for s in range(horizon)]
            ox=[z.Int(f'ox_{s}') for s in range(horizon)]
            oy=[z.Int(f'oy_{s}') for s in range(horizon)]
            moving={(q,s):z.Bool(f'moving_{q}_{s}') for q in xy for s in range(horizon)}
            for g in gates:
                opt.add(t[g.id]>=(-1 if self.mode=='single' else 0),t[g.id]<horizon)
                if g.id in choice:opt.add(choice[g.id]>=0,choice[g.id]<len(options[g.id]))
                for s in range(horizon):
                    opt.add(z.Implies(t[g.id]==s,kind[s]==kinds[g.gate_type]))
                    if g.id in choice:
                        for i,(_,_,x,y) in enumerate(options[g.id]):
                            opt.add(z.Implies(z.And(t[g.id]==s,choice[g.id]==i),z.And(dx[s]==x,dy[s]==y)))
            for a,b in combinations(gates,2):
                if set(a.qubit_ids)&set(b.qubit_ids):
                    opt.add(z.Or(t[a.id]<0,t[b.id]<0,t[a.id]!=t[b.id]))
            if self.mode=='multi':
                for parent in gates:
                    for child in state.dag.nodes[parent.id].successors:
                        if child in t:opt.add(t[parent.id]<t[child])
            axes=state.aod.configuration()
            spanx=coord(axes.x_um[-1]-axes.x_um[0]);spany=coord(axes.y_um[-1]-axes.y_um[0])
            bounds=state.world.bounds
            for s in range(horizon):
                opt.add(z.Or([t[g.id]==s for g in gates])) # no empty symbolic stages
                for q,(x,y) in xy.items():
                    terms=[z.And(t[g.id]==s,choice[g.id]==i) for g in gates if g.id in choice
                           for i,(_,mobile,_,_) in enumerate(options[g.id]) if mobile==q]
                    opt.add(moving[q,s]==z.Or(terms))
                cz=kind[s]==kinds['CZ']
                # Canonical capture origin matches PatchArrayCompiler.bindings:
                # min selected x/y on the regular grid, zero first axis offset.
                opt.add(z.Implies(cz,z.Or([z.And(moving[q,s],ox[s]==p[0]) for q,p in xy.items()])))
                opt.add(z.Implies(cz,z.Or([z.And(moving[q,s],oy[s]==p[1]) for q,p in xy.items()])))
                for q,(x,y) in xy.items():
                    opt.add(z.Implies(moving[q,s],z.And(ox[s]<=x,oy[s]<=y,x<=ox[s]+spanx,y<=oy[s]+spany)))
                    # All occupied intersections of enabled source rows x columns
                    # must be explicitly carried, including incidental atoms.
                    col=z.Or([moving[a,s] for a,p in xy.items() if p[0]==x])
                    row=z.Or([moving[a,s] for a,p in xy.items() if p[1]==y])
                    opt.add(z.Implies(z.And(col,row),moving[q,s]))
                for x,y in ((ox[s],oy[s]),(ox[s]+dx[s],oy[s]+dy[s])):
                    opt.add(z.Implies(cz,z.And(x>=coord(bounds.lower.x_um),
                        y>=coord(bounds.lower.y_um),x+spanx<=coord(bounds.upper.x_um),
                        y+spany<=coord(bounds.upper.y_um))))
                opt.add(z.Implies(z.Not(cz),z.And(dx[s]==0,dy[s]==0,
                    ox[s]==(ox[s-1] if s else coord(state.aod.pose.x_um)),
                    oy[s]==(oy[s-1] if s else coord(state.aod.pose.y_um)))))
                # Finite table of endpoint facts, not a list of candidate batches.
                for x,y in shifts:
                    chosen=z.And(cz,dx[s]==x,dy[s]==y)
                    for q,p in xy.items():
                        from neutral_atom_env.domain.models import Position2D
                        if not in_zone(state,Position2D((p[0]+x)/2,(p[1]+y)/2),ZoneType.ENTANGLEMENT):
                            opt.add(z.Implies(chosen,z.Not(moving[q,s])))
                    for a,b in combinations(xy,2):
                        desired=z.Or([t[g.id]==s for g in gates if g.gate_type=='CZ' and set(g.qubit_ids)=={a,b}])
                        cases=[]
                        for ma,mb in ((False,False),(False,True),(True,False),(True,True)):
                            pa=(xy[a][0]+ma*x,xy[a][1]+ma*y);pb=(xy[b][0]+mb*x,xy[b][1]+mb*y)
                            close=hypot(pa[0]-pb[0],pa[1]-pb[1])/2<=state.hardware.interaction_distance_um+1e-9
                            if close:cases.append(z.And(moving[a,s] if ma else z.Not(moving[a,s]),
                                                        moving[b,s] if mb else z.Not(moving[b,s])))
                        opt.add(z.Implies(chosen,desired==z.Or(cases)))
            if self.mode=='single':opt.maximize(z.Sum([z.If(t[g.id]>=0,1,0) for g in gates]))
            absolute=lambda x:z.If(x>=0,x,-x)
            cost=[]
            for s in range(horizon):
                px=ox[s-1] if s else coord(state.aod.pose.x_um)
                py=oy[s-1] if s else coord(state.aod.pose.y_um)
                cost.append(absolute(ox[s]-px)+absolute(oy[s]-py)+2*(absolute(dx[s])+absolute(dy[s])))
            cost.append(absolute(ox[-1]-coord(state.aod.pose.x_um))+absolute(oy[-1]-coord(state.aod.pose.y_um)))
            opt.minimize(z.Sum(cost)) # tie-break proxy; never claimed exact route time
            build_s=perf_counter()-started
            while emitted<self.model_budget:
                remaining=int((deadline-perf_counter())*1000)
                if remaining<=0:
                    self.log.append({'status':'UNKNOWN','reason':'overall_deadline','horizon':horizon});return
                opt.set(timeout=min(self.timeout_ms,remaining))
                started=perf_counter();status=opt.check()
                entry={'horizon':horizon,'status':str(status).upper(),'build_s':build_s,
                       'solve_s':perf_counter()-started,'assertions':len(opt.assertions()),
                       'previous_realizer_exclusions':emitted}
                if status==z.unknown:
                    entry['reason']=opt.reason_unknown();self.log.append(entry);return
                if status==z.unsat:
                    self.log.append(entry);break
                model=opt.model();selected=[]
                for s in range(horizon):
                    batch=[g for g in gates if model.eval(t[g.id]).as_long()==s]
                    members=tuple((g.id,*options[g.id][model.eval(choice[g.id]).as_long()][:2]) for g in batch if g.id in choice)
                    selected.append(BatchDecision(batch[0].gate_type,tuple(g.id for g in batch),members,
                        (model.eval(dx[s]).as_long()/2,model.eval(dy[s]).as_long()/2)))
                entry['batch_sizes']=[len(b.gate_ids) for b in selected]
                entry['symbolic_optimality_scope']='restoring endpoint model after recorded search exclusions'
                self.log.append(entry);emitted+=1
                build_s=0.
                yield tuple(selected)
                # A caller may resume after realization fails. This is a SEARCH
                # exclusion of one symbolic assignment, not proof of physical UNSAT.
                variables=list(t.values())+[v for g,v in choice.items() if model.eval(t[g]).as_long()>=0]
                opt.add(z.Or([v!=model.eval(v) for v in variables]))
            if emitted>=self.model_budget:
                self.log.append({'status':'UNKNOWN','reason':'model_budget','horizon':horizon});return
