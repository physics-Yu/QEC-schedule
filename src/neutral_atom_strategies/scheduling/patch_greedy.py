"""Geometry-based parallel CZ scheduling on a two-dimensional rigid array.

The structural baseline takes the first READY CZ and its equal-displacement
peers. Greedy compares maximal compatible groups, scores real service duration
per completed gate, and falls back to individual operands on geometry failure.
Neither policy uses SGHZ IDs or logical-code annotations.
"""
from neutral_atom_env.environment import as_environment
from dataclasses import replace
from math import hypot
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType as H, Position2D, ZoneType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.single_trap import in_zone
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import M4Result, fill_raman
from neutral_atom_strategies.scheduling.row_greedy import empty_graph_distance


def patch_assignment(state):
    if any(h.holder_type != H.STATIC for h in state.placement.atom_to_holder.values()):
        raise ValidationError('PATCH_ORIGIN', 'Initial patch layout must be supported by SLM')
    points = {q:state.placement.position(q,state.world,state.aod) for q in state.atoms}
    left=min(p.x_um for p in points.values()); bottom=min(p.y_um for p in points.values())
    free={(t.position.x_um,t.position.y_um):t.id for t in state.world.traps.values()
          if t.id not in state.placement.static_occupancy and in_zone(state,t.position,ZoneType.ENTANGLEMENT)}
    options=[]
    for x,y in free:
        destinations={q:free.get((x+p.x_um-left,y+p.y_um-bottom)) for q,p in points.items()}
        if all(destinations.values()):
            options.append((abs(x-left)+abs(y-bottom),x,y,destinations))
    if not options:
        raise ValidationError('PATCH_EZ_CAPACITY', 'No translated two-dimensional SLM layout fits in EZ')
    return min(options,key=lambda c:c[:3])[3]


def candidate_groups(state, gates, strategy):
    """Group oriented edges by equal physical displacement in O(ready gates)."""
    d=hypot(state.hardware.interaction_offset.x_um,state.hardware.interaction_offset.y_um)
    groups={}
    for gate in gates:
        a,b=gate.qubit_ids
        for anchor,mobile in ((a,b),(b,a)):
            pa=state.placement.position(anchor,state.world,state.aod)
            pm=state.placement.position(mobile,state.world,state.aod)
            for ox,oy in ((0,d),(d,0),(0,-d),(-d,0)):
                shift=(pa.x_um+ox-pm.x_um,pa.y_um+oy-pm.y_um)
                groups.setdefault(shift,[]).append((gate.id,anchor,mobile))
    # READY DAG gates cannot share qubits. Opposite orientation can only land
    # in the same shift in degenerate geometry; explicitly guard nevertheless.
    choices=[]
    for shift,members in groups.items():
        used=set(); accepted=[]
        for item in members:
            if used.intersection(item[1:]):continue
            accepted.append(item);used.update(item[1:])
        choices.append((shift,tuple(accepted)))
    if strategy=='patch_greedy':
        # A three-corner selection would activate the fourth corner too. Do
        # not jump straight from this refused maximal group to single atoms:
        # same-source-row/column subsets are cheap Cartesian-closed choices.
        seen=set(choices)
        for shift,members in tuple(choices):
            for axis in ('x_um','y_um'):
                buckets={}
                for item in members:
                    point=state.placement.position(item[2],state.world,state.aod)
                    buckets.setdefault(getattr(point,axis),[]).append(item)
                for subset in buckets.values():
                    choice=(shift,tuple(subset))
                    if choice not in seen:choices.append(choice);seen.add(choice)
    if strategy=='patch_symmetric':
        first=gates[0].id
        choices=[c for c in choices if any(g==first for g,_,_ in c[1])]
        choices.sort(key=lambda c:(-len(c[1]),c[0]))
    else:
        def estimate(item):
            shift,members=item
            ps=[state.placement.position(m,state.world,state.aod) for _,_,m in members]
            origin=Position2D(min(p.x_um for p in ps),min(p.y_um for p in ps))
            distance=abs(origin.x_um-state.aod.pose.x_um)+abs(origin.y_um-state.aod.pose.y_um)
            cost=200.+(distance+2*(abs(shift[0])+abs(shift[1])))/state.hardware.speed_um_per_us
            return (cost/len(members),-len(members),shift)
        choices.sort(key=estimate)
    # A refused maximal group does not prove any subset impossible. Singles
    # form a bounded general-circuit fallback; no exponential subset search.
    seen={(s,m) for s,m in choices}
    for shift,members in tuple(choices):
        for member in members:
            item=(shift,(member,))
            if item not in seen:choices.append(item);seen.add(item)
    return choices


def spatial_components(state):
    """Nearest-spacing occupied components, a policy hint, never a permission."""
    points={q:state.placement.position(q,state.world,state.aod) for q,a in state.atoms.items() if a.alive}
    parent={q:q for q in points}
    def root(q):
        while parent[q]!=q:q=parent[q]
        return q
    pairs=[(hypot(a.x_um-b.x_um,a.y_um-b.y_um),q,r)
           for q,a in points.items() for r,b in points.items() if q<r]
    nearest=min((d for d,_,_ in pairs if d>1e-9),default=0.)
    for d,q,r in pairs:
        if abs(d-nearest)<1e-8:parent[root(q)]=root(r)
    return {q:root(q) for q in points}


def preflight_group(state,compiler,shift,members):
    """Cheap necessary endpoint conditions; never replaces swept validation."""
    source,bindings=compiler.bindings(state,[m for _,_,m in members])
    points={q:state.placement.position(q,state.world,state.aod) for q,a in state.atoms.items() if a.alive}
    selected={b.atom_id for b in bindings}
    xs={points[q].x_um for q in selected};ys={points[q].y_um for q in selected}
    tol=state.hardware.alignment_tolerance_um
    closure={q for q,p in points.items() if any(abs(p.x_um-x)<=tol for x in xs)
             and any(abs(p.y_um-y)<=tol for y in ys)}
    if closure!=selected:
        raise ValidationError('PATCH_CAPTURE_CLOSURE','Selected rows and columns also capture unrequested atoms')
    end={q:Position2D(p.x_um+shift[0],p.y_um+shift[1]) if q in selected else p for q,p in points.items()}
    eligible={q:p for q,p in end.items() if in_zone(state,p,ZoneType.ENTANGLEMENT)}
    actual={tuple(sorted((a,b))) for a,pa in eligible.items() for b,pb in eligible.items()
            if a<b and hypot(pa.x_um-pb.x_um,pa.y_um-pb.y_um)<=state.hardware.interaction_distance_um+1e-9}
    if actual!={tuple(sorted((a,b))) for _,a,b in members}:
        raise ValidationError('PATCH_PULSE_PAIRS','Proposed group endpoint does not give exactly the intended global CZ pairs')
    return source


def batch_service(state, compiler, shift, members):
    ids=frozenset(g for g,_,_ in members)
    p=ProgramBuilder(state,TaskIntent(f'patch/{state.version}/{"-".join(sorted(ids))}/{shift}',
        TaskTarget(),frozenset(q for _,a,b in members for q in (a,b)),phase='program',gate_effects=ids))
    compiler.pulse_group(p,members,shift)
    p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
        p.state.aod.configuration(),trap_state(p.state)))
    return p.finish('patch-restoring-batch-v1')


def run_patch(state, *, strategy='patch_greedy', terminal=None, on_event=None,
              max_decisions=10000, candidate_budget=4096, route_expansions=100000):
    env = as_environment(state)
    state = env.state
    if strategy not in {'patch_symmetric','patch_greedy'}:raise ValueError('Unknown patch strategy')
    terminal=terminal or initial_terminal(state)
    compiler=PatchArrayCompiler(route_expansions);executor=env
    log=[];rejected=[];decisions=0;phase='initialization'
    def drain():
        while state.event_queue:
            event=executor.step()
            if on_event:on_event(state,event)
    def submit(plan,entry,started,raman=False):
        nonlocal decisions
        rotations=()
        if raman:plan,rotations=fill_raman(plan,state)
        entry.update(decision=decisions,start_us=state.time_us,duration_us=plan.estimated_duration_us,
                     compile_wall_time_s=perf_counter()-started,raman_count=len(rotations))
        executor.submit(plan);log.append(entry);decisions+=1;drain()
    def result(status,error=None):
        diagnostics=() if error is None else ({'code':error.violation.code,'message':error.violation.message,
            'phase':phase,'decisions_completed':decisions,'unfinished_gates':[
                g.id for g in state.dag.circuit.gates if state.dag.nodes[g.id].status.value!='completed']},)
        return M4Result(status,diagnostics,tuple(rejected),decisions,tuple(log))
    try:
        drain()
        if state.dag.completed:
            validate_target(terminal,state);return result('completed')
        components=spatial_components(state)
        destinations=patch_assignment(state);started=perf_counter();phase='joint_preparation'
        p=ProgramBuilder(state,TaskIntent(f'patch-stage/{state.version}',TaskTarget(),frozenset(state.atoms),phase='prepare'))
        compiler.transfer_group(p,destinations,'Stage two-dimensional patches in EZ')
        p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items()))))
        submit(p.finish('patch-stage-v1'),{'selected':'joint-2d-stage','atoms':len(destinations)},started,raman=True)
        while not state.dag.completed:
            if decisions>=max_decisions:raise ValidationError('DECISION_BUDGET_EXHAUSTED','Patch decision budget exhausted')
            started=perf_counter();phase='candidate_search';ready=list(state.dag.ready_gates())
            rotations=[g for g in ready if g.u_parameters is not None]
            if rotations:
                gate=rotations[0]
                p=ProgramBuilder(state,TaskIntent(f'patch-raman/{state.version}/{gate.id}',TaskTarget(),
                    frozenset(gate.qubit_ids),gate.id,'effect',gate.id))
                p.add(K.RAMAN_ROTATION,'Parallel ready single-qubit gates')
                submit(p.finish('patch-raman-v1'),{'selected':gate.id,'kind':'raman'},started,raman=True)
                continue
            gates=[g for g in ready if g.gate_type=='CZ']
            frontier_count=len(gates)
            local=[g for g in gates if components[g.qubit_ids[0]]==components[g.qubit_ids[1]]]
            priority='all_ready';cross_fallback=[]
            if strategy=='patch_greedy' and local:
                # Finish available work inside separated spatial groups before
                # fragmenting long inter-group batches. No artificial idle:
                # cross-group dependencies proceed when no local gate is READY.
                cross_fallback=[g for g in gates if g not in local]
                gates=local;priority='within_spatial_component'
            choices=candidate_groups(state,gates,strategy);best=None;attempts=0
            bounds_pruned=0;preflight_rejected=0
            fallback={'used':False}
            def candidate_stream():
                # Preserve the successful local path exactly. Only after every
                # local candidate failed may remaining construction budget be
                # spent on otherwise-hidden READY cross-component work.
                yield from tuple(choices)
                if best is None and cross_fallback and attempts<candidate_budget:
                    fallback['used']=True
                    extra=candidate_groups(state,cross_fallback,strategy)
                    choices.extend(extra)
                    yield from extra
            for shift,members in candidate_stream():
                if attempts>=candidate_budget:break
                # All services pay load/offload and the out/back Manhattan
                # distance. An admissible bound avoids expensive replay of
                # groups which cannot improve the incumbent per-gate score.
                try:
                    origin=preflight_group(state,compiler,shift,members)
                    axes=state.aod.configuration()
                    spanx=axes.x_um[-1]-axes.x_um[0];spany=axes.y_um[-1]-axes.y_um[0]
                    target=Position2D(origin.x_um+shift[0],origin.y_um+shift[1])
                    lower=lambda a,b:empty_graph_distance(state.world.bounds,spanx,a,b,spany)
                    bound=(state.hardware.load_duration_us+state.hardware.offload_duration_us+
                        state.hardware.pulse_duration_us+(lower(state.aod.pose,origin)+2*lower(origin,target))/state.hardware.speed_um_per_us)/len(members)
                except ValidationError as error:
                    preflight_rejected+=1
                    rejected.append({'candidate':str((shift,members)),'stage':'endpoint_preflight',
                        **({'fallback_to_cross_component':True} if fallback['used'] else {}),
                        'violation':primitive(error.violation)})
                    continue
                if best and bound>=best[0][0]-1e-9:
                    bounds_pruned+=1;continue
                attempts+=1
                try:plan=batch_service(state,compiler,shift,members)
                except ValidationError as error:
                    rejected.append({'candidate':str((shift,members)),
                        **({'fallback_to_cross_component':True} if fallback['used'] else {}),
                        'violation':primitive(error.violation)});continue
                key=(plan.estimated_duration_us/len(members),-len(members),plan.estimated_distance_um,shift)
                if best is None or key<best[0]:best=(key,plan,members)
                if strategy=='patch_symmetric':break
            if best is None:raise ValidationError('PATCH_CANDIDATES_EXHAUSTED',
                'No valid group or single-operand fallback within the candidate budget'+
                ('; cross-component fallback also failed' if fallback['used'] else ''))
            submit(best[1],{'selected':','.join(g for g,_,_ in best[2]),'kind':'cz_batch',
                'batch_size':len(best[2]),'ready_cz':frontier_count,'eligible_cz':len(gates)+(len(cross_fallback) if fallback['used'] else 0),
                'priority':'cross_component_after_local_failure' if fallback['used'] else priority,
                **({'fallback_to_cross_component':True} if fallback['used'] else {}),
                'spatial_components':len(set(components.values())),
                'candidate_count':len(choices),'constructed':attempts,'preflight_rejected':preflight_rejected,
                'bound_pruned':bounds_pruned,'budget_omitted':max(0,len(choices)-attempts-bounds_pruned-preflight_rejected),
                'selection_objective':'restoring service duration per completed gate'},started)
        phase='terminal';started=perf_counter()
        if decisions>=max_decisions:raise ValidationError('DECISION_BUDGET_EXHAUSTED','Patch terminal budget exhausted')
        p=ProgramBuilder(state,TaskIntent(f'patch-return/{state.version}',terminal,frozenset(state.atoms),phase='cleanup'))
        compiler.restore(p,terminal)
        submit(p.finish('patch-terminal-v1'),{'selected':'explicit-terminal'},started)
        validate_target(terminal,state);return result('completed')
    except ValidationError as error:
        return result('stalled',error)
