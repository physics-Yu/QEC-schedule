"""SMT selection of a READY CZ batch with ordered, shared AOD axes.

The solver creates operand orientations and pair offsets itself; it does not
rank a beam produced by greedy. Swept geometry stays with the shared realizer.
No whole-circuit or minimum physical makespan optimality claim is made.
"""
from math import hypot
from time import perf_counter
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.trap_spacing import minimum_trap_spacing
from neutral_atom_strategies.scheduling.ordered_greedy import build_batch,realize_batch


class SMTOrderedAxisPlanner:
    def __init__(self,timeout_ms=5000,model_budget=16,route_budget=128,motion_router='axis_hold'):
        self.motion_router=motion_router
        self.timeout_ms=timeout_ms;self.model_budget=model_budget;self.route_budget=route_budget
        self.log=[];self.rejections=[]

    def propose(self,state,deadline):
        import z3
        tick=perf_counter()
        ready=sorted((g for g in state.dag.ready_gates() if g.gate_type=='CZ'),key=lambda g:g.id)
        pos={q:state.placement.position(q,state.world,state.aod) for q in state.atoms}
        d=state.hardware.interaction_distance_um;gap=minimum_trap_spacing(state.hardware)
        solver=z3.Optimize();variants=[];by_gate={};by_atom={q:[] for q in pos}
        for g in ready:
            indices=[]
            for a,m in (g.qubit_ids,g.qubit_ids[::-1]):
                p=pos[a]
                for dx,dy in ((-d,0),(d,0),(0,-d),(0,d)):
                    item=(g.id,a,m,p.x_um+dx,p.y_um+dy)
                    i=len(variants);b=z3.Bool(f'option_{i}')
                    variants.append((item,b));indices.append(b);by_atom[m].append(i)
            solver.add(z3.AtMost(*indices,1));by_gate[g.id]=z3.Or(indices)
        if not variants:raise ValidationError('SMT_NO_CZ','No READY CZ gate')
        for q in pos:
            operands=[by_gate[g.id] for g in ready if q in g.qubit_ids]
            if operands:solver.add(z3.AtMost(*operands,1))
        moving={q:z3.Or([variants[i][1] for i in indices]) for q,indices in by_atom.items()}
        xs={p.x_um for p in pos.values()};ys={p.y_um for p in pos.values()}
        active_x={x:z3.Or([b for (_,_,m,_,_),b in variants if pos[m].x_um==x]) for x in xs}
        active_y={y:z3.Or([b for (_,_,m,_,_),b in variants if pos[m].y_um==y]) for y in ys}
        solver.add(z3.Sum([z3.If(v,1,0) for v in active_x.values()])<=state.aod.columns,
                   z3.Sum([z3.If(v,1,0) for v in active_y.values()])<=state.aod.rows)
        for q,p in pos.items():solver.add(z3.Implies(z3.And(active_x[p.x_um],active_y[p.y_um]),moving[q]))
        # Pairwise equality/order is sufficient for each shared ordered axis.
        for i,(a,ba) in enumerate(variants):
            for b,bb in variants[i+1:]:
                if a[0]==b[0]:continue
                pa,pb=pos[a[2]],pos[b[2]]
                conflict=False
                for sa,sb,ta,tb in ((pa.x_um,pb.x_um,a[3],b[3]),(pa.y_um,pb.y_um,a[4],b[4])):
                    conflict |= abs(ta-tb)>1e-7 if sa==sb else ((tb-ta if sa<sb else ta-tb)<=gap+1e-9)
                if conflict:solver.add(z3.Not(z3.And(ba,bb)))
        # All possible endpoint positions, including the stationary alternative.
        # Require exactly the selected gate pairs under the same distance rule.
        alternatives={q:[(pos[q].x_um,pos[q].y_um,z3.Not(moving[q]))]+
                      [(variants[i][0][3],variants[i][0][4],variants[i][1]) for i in by_atom[q]] for q in pos}
        ids=sorted(pos)
        for k,q in enumerate(ids):
            for r in ids[k+1:]:
                intended=z3.Or([by_gate[g.id] for g in ready if set(g.qubit_ids)=={q,r}])
                near=[]
                for x,y,b in alternatives[q]:
                    for xx,yy,bb in alternatives[r]:
                        if hypot(x-xx,y-yy)<=d+1e-9:near.append(z3.And(b,bb))
                solver.add(z3.Or(near)==intended)
        count=z3.Sum([z3.If(b,1,0) for b in by_gate.values()]);solver.add(count>=1)
        cardinality=solver.maximize(count)
        distance=z3.Real('max_l1_displacement');solver.add(distance>=0)
        for (_,_,m,x,y),b in variants:
            solver.add(z3.Implies(b,distance>=abs(x-pos[m].x_um)+abs(y-pos[m].y_um)))
        solver.minimize(distance)
        log={'ready_cz':len(ready),'symbolic_options':len(variants),'build_seconds':perf_counter()-tick,'models':[]}
        self.log.append(log)
        for attempt in range(self.model_budget):
            remaining=deadline-perf_counter()
            if remaining<=0:raise TimeoutError('SMT ordered frontier deadline')
            solver.set(timeout=max(1,min(self.timeout_ms,int(remaining*1000))))
            tick=perf_counter();status=solver.check()
            entry={'status':str(status),'solver_seconds':perf_counter()-tick};log['models'].append(entry)
            if status==z3.unknown:
                entry['reason']=solver.reason_unknown()
                raise ValidationError('SMT_UNKNOWN',f'Solver did not finish: {entry["reason"]}; not proof of infeasibility')
            if status==z3.unsat:break
            model=solver.model();chosen=[(a,b) for a,b in variants if z3.is_true(model.eval(b))]
            entry['batch_size']=len(chosen)
            entry['encoded_batch_lower']=str(cardinality.lower())
            entry['encoded_batch_upper']=str(cardinality.upper())
            entry['encoded_maximum_proven']=str(cardinality.lower())==str(cardinality.upper())
            try:
                batch=build_batch(state,tuple(a for a,b in chosen))
                plan=realize_batch(state,batch,deadline,self.route_budget,self.rejections,motion_router=self.motion_router)
                entry['physical_accepted']=True
                return {'kind':'CZ','gate_ids':batch.gate_ids,'assignments':batch.assignments,
                        'pickup':batch.pickup,'target':batch.target},plan
            except ValidationError as e:
                self.rejections.append({'code':e.violation.code,'message':str(e)})
                entry['physical_accepted']=False;entry['code']=e.violation.code
            # Exclude this exact assignment only; retain its possible subsets.
            solver.add(z3.Or([b!=model.eval(b,model_completion=True) for a,b in variants]))
        raise ValidationError('SMT_ORDERED_EXHAUSTED','No physically validated model in finite model/route budgets; not proof of physical impossibility')
