"""Editable Clifford circuit scheduling with physical MZ readout and reset.

No logical-code gate IDs drive execution. All gates come from the caller's DAG;
geometry groups and measurement dependencies decide each service. Measurements
travel to actual MZ SLMs, execute, and return before subsequent CZ/Raman work.
"""
from neutral_atom_env.environment import as_environment
from dataclasses import replace
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType as H, GateStatus, ZoneType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_strategies.motion.single_trap import in_zone
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import M4Result
from neutral_atom_strategies.scheduling.patch_greedy import patch_assignment, candidate_groups, preflight_group, batch_service


def readout_groups(state, gates):
    """Try a full frontier, then closed rows/columns, then individual atoms."""
    groups=[tuple(gates)]
    for axis in ('x_um','y_um'):
        buckets={}
        for gate in gates:
            point=state.placement.position(gate.qubit_ids[0],state.world,state.aod)
            buckets.setdefault(getattr(point,axis),[]).append(gate)
        groups.extend(tuple(v) for v in buckets.values())
        # Rows with identical occupied-column signatures form a closed
        # rectangle even when separated by unused rows (and vice versa).
        other='y_um' if axis=='x_um' else 'x_um'
        signatures={}
        for subset in buckets.values():
            signature=tuple(sorted(getattr(state.placement.position(g.qubit_ids[0],state.world,state.aod),other) for g in subset))
            signatures.setdefault(signature,[]).extend(subset)
        groups.extend(tuple(v) for v in signatures.values())
    groups.extend((g,) for g in gates)
    seen=set()
    for group in sorted(groups,key=lambda group:-len(group)):
        key=tuple(g.id for g in group)
        if key not in seen:
            seen.add(key)
            yield group


def qec_cz_groups(state,gates):
    """Add closed rectangles across skipped rows to the generic frontier."""
    choices=candidate_groups(state,gates,'patch_greedy')
    extra=[]
    for shift,members in choices:
        if len(members)<3:continue
        by_mobile={mobile:item for item in members for mobile in (item[2],)}
        # Reuse geometric grouping, with the mobile atom as the group key.
        from types import SimpleNamespace
        proxies=[SimpleNamespace(id=mobile,qubit_ids=(mobile,)) for mobile in by_mobile]
        for subset in readout_groups(state,proxies):
            if 1<len(subset)<len(members):
                extra.append((shift,tuple(by_mobile[g.id] for g in subset)))
    seen=set();ordered=[]
    for choice in choices+extra:
        if choice not in seen:seen.add(choice);ordered.append(choice)
    # Prioritize gate count; bounded first-valid exact validation is a
    # constructive baseline, not an exhaustive cost optimizer.
    return sorted(ordered,key=lambda choice:(-len(choice[1]),abs(choice[0][0])+abs(choice[0][1])))


def measurement_destinations(state, atoms):
    """Find the nearest free shape-preserving translation into the MZ."""
    points={q:state.placement.position(q,state.world,state.aod) for q in atoms}
    free={(t.position.x_um,t.position.y_um):t.id for t in state.world.traps.values()
          if t.id not in state.placement.static_occupancy and in_zone(state,t.position,ZoneType.MEASUREMENT)}
    # A sparse footprint need not contain its bounding-box lower-left corner.
    # Anchor on an actual atom; testing an invented corner rejects valid arrays.
    anchor=points[min(points)]
    left,bottom=anchor.x_um,anchor.y_um
    choices=[]
    for x,y in free:
        dest={q:free.get((x+p.x_um-left,y+p.y_um-bottom)) for q,p in points.items()}
        if all(dest.values()):choices.append((abs(x-left)+abs(y-bottom),x,y,dest))
    if not choices:
        raise ValidationError('QEC_MZ_CAPACITY','No free translated readout footprint fits in the measurement zone')
    return [item[3] for item in sorted(choices,key=lambda item:item[:3])]


def readout_service(state,compiler,gates):
    atoms=tuple(g.qubit_ids[0] for g in gates)
    source={q:state.placement.atom_to_holder[q].holder_id for q in atoms}
    # Each immediately ready RESET successor can share the same MZ visit.
    resets=[]
    for gate in gates:
        for key in state.dag.nodes[gate.id].successors:
            candidate=state.dag.nodes[key].gate
            parents={p for p,n in state.dag.nodes.items() if key in n.successors}
            available={g.id for g in gates}|{g for g,n in state.dag.nodes.items() if n.status==GateStatus.COMPLETED}
            if candidate.gate_type=='RESET' and candidate.qubit_ids==gate.qubit_ids and parents<=available:
                resets.append(candidate)
    all_ids=tuple(g.id for g in gates)+tuple(g.id for g in resets)
    destinations=[source] if all(in_zone(state,state.placement.position(q,state.world,state.aod),ZoneType.MEASUREMENT) for q in atoms) else measurement_destinations(state,atoms)
    last=None
    for destination in destinations:
        try:
            p=ProgramBuilder(state,TaskIntent(f'qec-readout/{state.version}/{gates[0].id}',
                TaskTarget(),frozenset(atoms),phase='program',gate_effects=frozenset(all_ids)))
            compiler.transfer_group(p,destination,'Move readout atoms to MZ')
            kind=K.MEASUREMENT if gates[0].gate_type=='MEASURE' else K.RESET
            p.add(kind,f'{gates[0].gate_type}: {len(gates)} atoms in MZ',gate_ids=tuple(g.id for g in gates))
            if resets:p.add(K.RESET,'Reset measured ancillas for reuse',gate_ids=tuple(g.id for g in resets))
            compiler.transfer_group(p,source,'Return readout atoms to their working sites')
            p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
                p.state.aod.configuration(),trap_state(p.state)))
            return p.finish('qec-measure-reset-return-v1'),len(resets)
        except ValidationError as error:last=error
    raise last


def run_qec(state, *, on_event=None, terminal=None, max_decisions=10000,
            candidate_budget=4096, route_expansions=100000):
    """Deterministic bounded baseline for arbitrary edited supported gates.

    Candidate ordering seeks parallel geometry; it stops at the first exactly
    validated batch. No claims of optimal timing or circuit equivalence after
    arbitrary edits are made. Quantum observables are checked from final state.
    """
    env = as_environment(state)
    state = env.state
    terminal=terminal or initial_terminal(state)
    compiler=PatchArrayCompiler(route_expansions);executor=env
    rejected=[];log=[];decisions=0;phase='initialization'
    def drain():
        while state.event_queue:
            event=executor.step()
            if on_event:on_event(state,event)
    def submit(plan,entry,started):
        nonlocal decisions
        entry.update(decision=decisions,start_us=state.time_us,duration_us=plan.estimated_duration_us,
                     compile_wall_time_s=perf_counter()-started)
        executor.submit(plan);log.append(entry);decisions+=1;drain()
    def reject(error,entry):
        rejected.append(entry|{'violation':primitive(error.violation)})
    def result(status,error=None):
        diagnostics=() if error is None else ({'code':error.violation.code,'message':error.violation.message,
            'phase':phase,'decisions_completed':decisions,'unfinished_gates':[
                g.id for g in state.dag.circuit.gates if state.dag.nodes[g.id].status!=GateStatus.COMPLETED]},)
        return M4Result(status,diagnostics,tuple(rejected),decisions,tuple(log))
    try:
        if state.quantum_state is None:raise ValidationError('QEC_QUANTUM_STATE_REQUIRED','Enable the quantum state before recording or compiling QEC')
        drain()
        if state.dag.completed:return result('completed')
        phase='joint_preparation';started=perf_counter()
        destinations=patch_assignment(state)
        p=ProgramBuilder(state,TaskIntent(f'qec-stage/{state.version}',TaskTarget(),frozenset(state.atoms),phase='prepare'))
        compiler.transfer_group(p,destinations,'Stage data and stabilizer ancillas in EZ')
        p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items()))))
        if p.operations:submit(p.finish('qec-stage-v1'),{'kind':'stage','atoms':len(destinations)},started)
        while not state.dag.completed:
            if decisions>=max_decisions:raise ValidationError('DECISION_BUDGET_EXHAUSTED','QEC decision budget exhausted')
            ready=list(state.dag.ready_gates());started=perf_counter();phase='frontier'
            rotations=[g for g in ready if g.u_parameters is not None]
            if rotations:
                gate=rotations[0]
                same=[g for g in rotations if g.gate_type==gate.gate_type]
                p=ProgramBuilder(state,TaskIntent(f'qec-raman/{state.version}/{gate.id}',TaskTarget(),
                    frozenset(gate.qubit_ids),gate.id,'effect',gate.id))
                p.add(K.RAMAN_ROTATION,'Parallel addressed single-qubit control',gate_id=gate.id)
                plan=p.finish('qec-raman-v1')
                if len(same)>1:plan=scheduled_program(plan,state,tuple((g.id,0.) for g in same[1:]))
                submit(plan,{'kind':'raman','gate_type':gate.gate_type,'batch_size':len(same),'selected':','.join(g.id for g in same)},started)
                continue
            cz=[g for g in ready if g.gate_type=='CZ'];chosen=None
            # Finish available quantum interactions before collecting the readout
            # frontier. Classical dependencies then release correction gates.
            phase='cz_search'
            for attempt,(shift,members) in enumerate(qec_cz_groups(state,cz)):
                if attempt>=candidate_budget:break
                try:
                    preflight_group(state,compiler,shift,members)
                    plan=batch_service(state,compiler,shift,members)
                    chosen=(plan,members);break
                except ValidationError as error:reject(error,{'kind':'cz','members':members,'shift':shift})
            if chosen:
                submit(chosen[0],{'kind':'cz_batch','batch_size':len(chosen[1]),'selected':','.join(g for g,_,_ in chosen[1])},started)
                continue
            phase='readout_search'
            for kind in ('MEASURE','RESET'):
                pending=[g for g in ready if g.gate_type==kind]
                for group in readout_groups(state,pending) if pending else ():
                    try:
                        plan,count=readout_service(state,compiler,group)
                        chosen=(plan,group,count);break
                    except ValidationError as error:reject(error,{'kind':'readout','gates':[g.id for g in group]})
                if chosen:break
            if chosen:
                submit(chosen[0],{'kind':'readout','batch_size':len(chosen[1]),'reset_count':chosen[2],
                    'selected':','.join(g.id for g in chosen[1])},started)
                continue
            raise ValidationError('QEC_FRONTIER_EXHAUSTED','No ready quantum or readout group passed physical validation; inspect candidate rejections')
        phase='terminal';started=perf_counter()
        p=ProgramBuilder(state,TaskIntent(f'qec-return/{state.version}',terminal,frozenset(state.atoms),phase='cleanup'))
        compiler.restore(p,terminal)
        if p.operations:submit(p.finish('qec-terminal-v1'),{'kind':'terminal'},started)
        validate_target(terminal,state)
        return result('completed')
    except ValidationError as error:
        return result('stalled',error)
