"""Reusable sparse-row service with a constructive baseline and lazy greedy search.

The row is transported as one rigid group, each CZ restores its moving operand
to the row, and the declared original terminal is restored at the end. This is
an explicit restricted action family, not a claim of global scheduling optimality.
Every candidate uses the shared backend, program audit and Executor.
"""
from neutral_atom_env.environment import as_environment
from dataclasses import replace
from math import hypot
from functools import lru_cache
from heapq import heappop, heappush
from types import SimpleNamespace
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType as H, Position2D, ZoneType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_strategies.motion.multi_trap import MultiTrapGreedyCompiler
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.single_trap import in_zone
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import M4Result, fill_raman


@lru_cache(maxsize=8192)
def empty_graph_distance(bounds, span, source, target, vertical_span=0):
    """Shortest distance in the exact routing graph after removing obstacles.

    Only immutable geometry is cached. The full footprint determines bounds;
    no holder/mask/pulse permission or physical path validation is cached here.
    """
    from neutral_atom_env.domain.aod import AODConfiguration
    from neutral_atom_strategies.motion.astar import AStarHalfGridPlanner
    def axes(point):
        return AODConfiguration((point.x_um,point.x_um+span) if span else (point.x_um,),
            (point.y_um,point.y_um+vertical_span) if vertical_span else (point.y_um,))
    request=SimpleNamespace(start=axes(source),target=axes(target),world=SimpleNamespace(bounds=bounds))
    graph,start,goal=AStarHalfGridPlanner.graph(request)
    distances={start:0.};queue=[(abs(start[0]-goal[0])+abs(start[1]-goal[1]),0.,start)]
    while queue:
        _,negative,current=heappop(queue);cost=-negative
        if cost!=distances[current]:continue
        if current==goal:return cost
        for point in graph[current]:
            new=cost+abs(point[0]-current[0])+abs(point[1]-current[1])
            if new<distances.get(point,float('inf')):
                distances[point]=new
                heappush(queue,(new+abs(point[0]-goal[0])+abs(point[1]-goal[1]),-new,point))
    return float('inf')


def row_assignment(state):
    """Find a translated EZ row; do not change the 5 um reservation lattice."""
    if state.hardware.backend != 'rigid' or state.aod.rows != 1 or state.aod.spacing_um != 10:
        raise ValidationError('ROW_PLATFORM', 'Row service requires one rigid 1xN AOD with 10 um spacing')
    holders = state.placement.atom_to_holder
    if any(h.holder_type != H.STATIC for h in holders.values()):
        raise ValidationError('ROW_ORIGIN', 'Row service starts with all atoms on SLM')
    points = {q: state.world.traps[h.holder_id].position for q, h in holders.items()}
    if len({p.y_um for p in points.values()}) != 1:
        raise ValidationError('ROW_ORIGIN', 'Row service requires one source row')
    left = min(p.x_um for p in points.values())
    if any(abs((p.x_um-left)/10-round((p.x_um-left)/10)) > 1e-9 for p in points.values()):
        raise ValidationError('ROW_ORIGIN', 'Occupied sites must be separated by integer multiples of 10 um')
    if max(round((p.x_um-left)/10) for p in points.values()) >= state.aod.columns:
        raise ValidationError('ROW_CAPACITY', 'The AOD must span the complete occupied row')
    free = {(t.position.x_um, t.position.y_um): t.id for t in state.world.traps.values()
            if t.id not in state.placement.static_occupancy and in_zone(state,t.position,ZoneType.ENTANGLEMENT)}
    choices = []
    for x,y in free:
        destinations = {q:free.get((x+p.x_um-left,y)) for q,p in points.items()}
        if all(destinations.values()):
            source_y = next(iter(points.values())).y_um
            choices.append((abs(x-left)+abs(y-source_y),x,y,destinations))
    if not choices:
        raise ValidationError('ROW_EZ_CAPACITY', 'No free EZ row can hold the complete sparse source row')
    return min(choices,key=lambda c:c[:3])[3]


def service_lower_bound(state, gate, anchor, pose):
    """Admissible duration bound for this restoring service, ignoring obstacles.

    AOD reposition + operand out and back are unavoidable; closing empty axes
    is omitted from the bound. It is not a bound on the full remaining circuit.
    """
    partner = next(q for q in gate.qubit_ids if q != anchor)
    source = state.placement.position(partner,state.world,state.aod)
    h = state.hardware
    span=state.aod.configuration().x_um[-1]-state.aod.pose.x_um
    def lower(a,b):
        try:return empty_graph_distance(state.world.bounds,span,a,b)
        except ValidationError:return float('inf')
    return (lower(state.aod.pose,source)+2*lower(source,pose))/h.speed_um_per_us + h.load_duration_us+h.offload_duration_us+h.pulse_duration_us


def gate_service(state, compiler, gate, anchor, pose):
    intent = TaskIntent(f'row/{state.version}/{gate.id}/{anchor}/{pose.x_um}/{pose.y_um}',TaskTarget(),
                        frozenset(gate.qubit_ids),gate.id,'effect',gate.id)
    p = ProgramBuilder(state,intent)
    partner = next(q for q in gate.qubit_ids if q != anchor)
    site = state.placement.atom_to_holder[partner].holder_id
    compiler.load_atom(p,partner)
    binding = p.operations[-1].transfer_bindings
    compiler.route(p,pose,depart=binding,label='Row operand to CZ')
    p.add(K.ENTANGLING_PULSE,'Row CZ effect')
    compiler.move_atom(p,partner,site)
    p.intent = replace(intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
        p.state.aod.configuration(),trap_state(p.state)))
    return p.finish('row-restoring-service-v1')


def run_row(state, *, strategy='row_greedy', terminal=None, on_event=None,
            max_decisions=10000, candidate_budget=4096, route_expansions=100000):
    env = as_environment(state)
    state = env.state
    if strategy not in {'row_symmetric','row_greedy'}:
        raise ValueError('Unknown sparse-row strategy')
    if any(type(v) is not int or v < 1 for v in (max_decisions,candidate_budget,route_expansions)):
        raise ValueError('Positive row search budgets required')
    terminal = terminal or initial_terminal(state)
    compiler = MultiTrapGreedyCompiler(adaptive_sites=True)
    from neutral_atom_strategies.motion.astar import AStarHalfGridPlanner
    compiler.planner = AStarHalfGridPlanner(max_expansions=route_expansions)
    executor = env
    log=[]; rejected=[]; decisions=0; phase='initialization'
    def drain():
        while state.event_queue:
            event=executor.step()
            if on_event:on_event(state,event)
    def submit(base,entry,started):
        nonlocal decisions
        plan, rotations = fill_raman(base,state)
        entry.update(decision=decisions,start_us=state.time_us,duration_us=plan.estimated_duration_us,
                     compile_wall_time_s=perf_counter()-started,raman_count=len(rotations))
        executor.submit(plan); log.append(entry); decisions+=1; drain()
    def result(status,error=None):
        diagnostics=() if error is None else ({'code':error.violation.code,'message':error.violation.message,
                    'phase':phase,'decisions_completed':decisions,
                    'unfinished_gates':[g.id for g in state.dag.circuit.gates if state.dag.nodes[g.id].status.value!='completed']},)
        return M4Result(status,diagnostics,tuple(rejected),decisions,tuple(log))
    try:
        drain()
        if state.dag.completed:
            try:
                validate_target(terminal,state)
                return result('completed')
            except ValidationError:
                pass
        destinations=row_assignment(state)
        phase='joint_preparation'; started=perf_counter()
        p=ProgramBuilder(state,TaskIntent(f'row-stage/{state.version}',TaskTarget(),frozenset(state.atoms),phase='prepare'))
        compiler.transfer_group(p,destinations,label='Stage complete sparse row in EZ')
        p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items()))))
        submit(p.finish('row-joint-stage-v1'),{'selected':'joint-stage','atoms':len(destinations)},started)
        while not state.dag.completed:
            if decisions>=max_decisions:
                raise ValidationError('DECISION_BUDGET_EXHAUSTED','Sparse row decision budget exhausted')
            started=perf_counter(); phase='candidate_search'
            ready=list(state.dag.ready_gates())
            rotations=[g for g in ready if g.u_parameters is not None]
            if rotations:
                gate=rotations[0]
                p=ProgramBuilder(state,TaskIntent(f'row-raman/{state.version}/{gate.id}',TaskTarget(),frozenset(gate.qubit_ids),gate.id,'effect',gate.id))
                p.add(K.RAMAN_ROTATION,'Ready single-qubit layer')
                submit(p.finish('row-raman-v1'),{'selected':gate.id,'kind':'raman'},started)
                continue
            gates=[g for g in ready if g.gate_type=='CZ']
            choices=[]
            for gate in gates:
                anchors=gate.qubit_ids if strategy=='row_greedy' else gate.qubit_ids[:1]
                for anchor in anchors:
                    point=state.placement.position(anchor,state.world,state.aod)
                    d=hypot(state.hardware.interaction_offset.x_um,state.hardware.interaction_offset.y_um)
                    offsets=((0,d),(0,-d),(-d,0),(d,0)) if strategy=='row_greedy' else ((0,d),)
                    for dx,dy in offsets:
                        pose=Position2D(point.x_um+dx,point.y_um+dy)
                        choices.append((service_lower_bound(state,gate,anchor,pose),gate.id,anchor,pose))
                if strategy=='row_symmetric':break
            choices.sort(key=lambda c:(c[0],c[1],c[2],c[3].x_um,c[3].y_um))
            best=None; attempts=0; pruned=0; refusals=0
            for i,(bound,gid,anchor,pose) in enumerate(choices):
                if best is not None and bound>=best[0]-1e-9:
                    pruned=len(choices)-i;break
                if attempts>=candidate_budget:break
                attempts+=1
                try:
                    candidate=gate_service(state,compiler,state.dag.nodes[gid].gate,anchor,pose)
                except ValidationError as error:
                    refusals+=1
                    rejected.append({'candidate':f'{gid}/{anchor}/{pose}','violation':primitive(error.violation)});continue
                key=(candidate.estimated_duration_us,candidate.estimated_distance_um,gid,anchor,pose.x_um,pose.y_um)
                if best is None or key<best[1]:best=(key[0],key,candidate)
            if best is None:
                raise ValidationError('ROW_CANDIDATES_EXHAUSTED','No valid restoring row service within the candidate budget')
            submit(best[2],{'selected':best[2].intent.effect_gate_id,'kind':'cz','ready_cz':len(gates),
                'candidate_count':len(choices),'constructed':attempts,'bound_pruned':pruned,
                'budget_omitted':max(0,len(choices)-attempts-pruned),
                'local_optimum_certified':attempts+pruned==len(choices) and refusals==0,
                'optimality_scope':'restoring_cz_base_duration'},started)
        phase='terminal'; started=perf_counter()
        try:
            validate_target(terminal,state)
            return result('completed')
        except ValidationError:
            pass
        if decisions>=max_decisions:
            raise ValidationError('DECISION_BUDGET_EXHAUSTED','Row terminal cleanup exceeds the decision budget')
        base=compiler.compile(TaskIntent(f'row-exit/{state.version}',terminal,frozenset(state.atoms),phase='cleanup'),state)
        submit(base,{'selected':'explicit-terminal'},started)
        validate_target(terminal,state)
        return result('completed')
    except ValidationError as error:
        return result('stalled',error)
