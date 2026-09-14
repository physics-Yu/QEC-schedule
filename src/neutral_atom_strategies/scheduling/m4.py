"""Rolling greedy AOD service; event-driven Raman refill on a predicted state.

An AOD service ends at its effect, not an automatic round trip. We commit a
bounded, fully audited schedule, then reconsider the frontier. Only Executor
writes live state. No live-program mutation or speculative gate effects.
"""
from neutral_atom_env.environment import as_environment
from dataclasses import dataclass, replace
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus
from neutral_atom_env.domain.operations import OperationType as K, TaskIntent
from neutral_atom_env.hardware.raman import validate_rotation, validate_rotation_sweep
from neutral_atom_env.domain.aod import motion_target
from neutral_atom_env.hardware.gate_contract import compatible_gate_types
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.program.builder import apply_operation
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4_policies import STRATEGIES, PolicySelectionError, critical_paths, candidate_features, select_candidate
from neutral_atom_strategies.scheduling.raman_windows import safe_rotation_fractions


def completed(work, gate):
    return replace(work, dag=work.dag.transitioned(gate, GateStatus.RESERVED)
                   .transitioned(gate, GateStatus.RUNNING).transitioned(gate, GateStatus.COMPLETED))


def fill_raman(base, state):
    """ASAP independent Raman pulses in the actual per-atom stable windows.

    Windows join across AOD operation boundaries when the target is unaffected.
    Identical gate types may overlap on separate qubits; different gate types
    (including CZ versus 1Q) occupy disjoint intervals. Transport can overlap.
    """
    from math import inf
    from neutral_atom_env.program.task_validation import operation_demand
    work=state;time=0.;segments=[];rotations=[];pulses=[]
    finishes={g:0. for g,n in state.dag.nodes.items() if n.status==GateStatus.COMPLETED}
    for op in base.operations:
        gate_id=op.gate_id or next(iter(base.intent.gate_ids),None)
        end=time+op.duration_us
        resources, atom_ids, *_ = operation_demand(work,op,gate_id)
        blocked = set(atom_ids)
        if 'AOD_0' in resources:
            blocked.update(work.placement.mobile_occupancy.values())
        segments.append((time,end,work,blocked,
                         motion_target(op) if op.operation_type==K.AOD_MOVE else None))
        work=apply_operation(work,op,gate_id)
        if op.operation_type in {K.ENTANGLING_PULSE,K.RAMAN_ROTATION}:
            finishes[gate_id]=end
            pulses.append((time,end,state.dag.nodes[gate_id].gate.gate_type))
        time=end
    segments.append((time,inf,work,set(),None))
    parents={g:{p for p,n in state.dag.nodes.items() if g in n.successors} for g in state.dag.nodes}
    pure=all(o.operation_type==K.RAMAN_ROTATION for o in base.operations)
    def first_window(gate,ready):
        q=gate.qubit_ids[0]; windows=[]
        for left,right,physical,blocked,target in segments:
            if q in blocked:continue
            try: fractions=safe_rotation_fractions(physical,gate.id,target)
            except ValidationError:continue
            for a,b in fractions:
                begin=left if a==0 else left+a*(right-left)
                end=right if b==1 else left+b*(right-left)
                if windows and begin<=windows[-1][1]+1e-9:
                    windows[-1]=(windows[-1][0],max(end,windows[-1][1]))
                else:windows.append((begin,end))
        for left,right in windows:
            start=max(left,ready)
            # Reconsider the whole pulse interval whenever a conflicting gate
            # pushes its start. Half-open intervals permit end/start adjacency.
            while True:
                conflicts=[end for begin,end,kind in pulses
                           if not compatible_gate_types(gate.gate_type,kind)
                           and start < end and begin < start+state.hardware.raman_duration_us]
                if not conflicts:break
                start=max(conflicts)
            if start+state.hardware.raman_duration_us<=right+1e-9:return start
        return inf
    while True:
        horizon=time
        if pure:
            cz_ready=[max((finishes[p] for p in parents[g]),default=0.) for g,n in state.dag.nodes.items()
                      if n.gate.gate_type=='CZ' and g not in finishes and parents[g]<=finishes.keys()]
            horizon=max(time,min(cz_ready)) if cz_ready else inf
        choices=[]
        for g,n in state.dag.nodes.items():
            if g in finishes or n.gate.u_parameters is None or not parents[g]<=finishes.keys():continue
            ready=max((finishes[p] for p in parents[g]),default=0.)
            start=first_window(n.gate,ready)
            if start<horizon:choices.append((start,g))
        if not choices:break
        start,g=min(choices)
        rotations.append((g,start));finishes[g]=start+state.hardware.raman_duration_us
        pulses.append((start,finishes[g],state.dag.nodes[g].gate.gate_type))
    return scheduled_program(base,state,tuple(rotations)),rotations


@dataclass(frozen=True)
class M4Result:
    status: str
    diagnostics: tuple
    candidate_rejections: tuple
    decisions: int
    decision_log: tuple


def run_m4(state, *, terminal=None, max_decisions=10000, ready_limit=16, site_limit=4,
           adaptive_sites=False, on_event=None, strategy='greedy', lookahead_depth=2,
           beam_width=3, rollout_budget=12):
    env = as_environment(state)
    state = env.state
    if any(type(v) is not int or v < 1 for v in (max_decisions, ready_limit, site_limit,
                                               lookahead_depth, beam_width, rollout_budget)):
        raise ValueError('Positive integer search budgets required')
    if strategy not in STRATEGIES:
        raise ValueError('Unknown M4 strategy')
    if lookahead_depth>8 or beam_width>32 or rollout_budget>4096:
        raise ValueError('M4 lookahead limits are depth <= 8, beam <= 32, rollout nodes <= 4096')
    terminal = terminal or initial_terminal(state)
    from neutral_atom_strategies.motion.multi_trap import MultiTrapGreedyCompiler
    compiler_type=GreedyCompiler if (state.aod.rows,state.aod.columns)==(1,1) else MultiTrapGreedyCompiler
    compiler = compiler_type(adaptive_sites=adaptive_sites); executor = env
    rejected = []; log = []; decisions = 0
    phase='resume'; search_log=[]; failed_policy_search=None

    def drain():
        while state.event_queue:
            event = executor.step()
            if on_event: on_event(state, event)

    def result(status, code=None, message=None):
        diagnostics = () if code is None else ({'code': code, 'message': message,
            'holders': primitive(state.placement.atom_to_holder),
            'unfinished_gates': [g for g,n in state.dag.nodes.items() if n.status != GateStatus.COMPLETED],
            'max_decisions': max_decisions, 'ready_limit': ready_limit, 'site_limit': site_limit,
            'phase':phase, 'search_log':search_log, 'decisions_completed':decisions,
            'strategy':strategy,'lookahead_depth':lookahead_depth,'beam_width':beam_width,
            'rollout_budget':rollout_budget,
            **({'policy_search':failed_policy_search} if failed_policy_search is not None else {})},)
        return M4Result(status, diagnostics, tuple(rejected), decisions, tuple(log))

    try:
        drain()
        while True:
            phase='terminal' if state.dag.completed else 'candidate_search'
            if state.dag.completed:
                try:
                    validate_target(terminal, state)
                    return result('completed')
                except ValidationError: pass
            if decisions >= max_decisions:
                return result('stalled', 'DECISION_BUDGET_EXHAUSTED', 'Gates and declared terminal not both complete')
            started = perf_counter()
            entry = {'decision': decisions, 'start_us': state.time_us, 'strategy':strategy}
            if state.dag.completed:
                base = compiler.compile(TaskIntent(f'm4-exit/{state.version}', terminal,
                    frozenset(state.atoms), phase='cleanup'), state)
                entry.update(selected='explicit-terminal', candidates=[], truncated=0)
            else:
                ready = list(state.dag.ready_gates())
                # One nonpreemptive AOD service at a time. Static Raman uses its
                # independent lane during that service; no Raman-triggered return.
                cz = [g for g in ready if g.gate_type == 'CZ']
                search = ready if strategy in {'critical_path','lookahead'} else (cz or ready)
                if strategy=='critical_path':
                    paths=critical_paths(state)
                    search.sort(key=lambda gate:(-paths[gate.id],gate.id))
                candidates = []; truncated = max(0, len(search)-ready_limit)
                for gate in search[:ready_limit]:
                    choices, errors, cut = compiler.alternatives(gate.id, state, site_limit=site_limit)
                    search_log.append({'decision':decisions,'gate_id':gate.id,'offset':0,
                        'attempted':len(choices)+len(errors),'omitted':cut})
                    if adaptive_sites and not choices and cut:
                        extra, failures, cut=compiler.alternatives(gate.id,state,site_limit=site_limit*3,site_offset=site_limit)
                        search_log.append({'decision':decisions,'gate_id':gate.id,'offset':site_limit,
                            'attempted':len(extra)+len(failures),'omitted':cut})
                        choices.extend(extra); errors.extend(failures)
                    candidates.extend(choices); truncated += cut
                    rejected.extend(dict(e, decision=decisions) for e in errors)
                # Explicitly consider Raman if all searched CZ choices fail.
                if not candidates and cz:
                    raman = [g for g in ready if g.u_parameters is not None]
                    truncated += max(0, len(raman)-ready_limit)
                    for gate in raman[:ready_limit]:
                        choices, errors, cut = compiler.alternatives(gate.id, state, site_limit=site_limit)
                        search_log.append({'decision':decisions,'gate_id':gate.id,'offset':0,
                            'attempted':len(choices)+len(errors),'omitted':cut})
                        candidates.extend(choices); truncated += cut
                        rejected.extend(dict(e, decision=decisions) for e in errors)
                if not candidates:
                    return result('stalled', 'CANDIDATES_EXHAUSTED', 'Finite greedy search found no legal READY service')
                candidates.sort(key=lambda c: c.cost)
                def future_alternatives(physical):
                    future_ready=list(physical.dag.ready_gates())
                    values=[]
                    for gate in future_ready[:ready_limit]:
                        found, failures, cut=compiler.alternatives(gate.id,physical,site_limit=site_limit)
                        search_log.append({'decision':decisions,'gate_id':gate.id,'scope':'lookahead',
                                           'offset':0,'attempted':len(found)+len(failures),'omitted':cut})
                        rejected.extend(dict(e,decision=decisions,scope='lookahead') for e in failures)
                        values.extend(found)
                    return values
                phase='policy_selection'
                try:
                    choice,policy_search,policy_errors=select_candidate(candidates,state,compiler,terminal,
                        strategy=strategy,depth=lookahead_depth,beam_width=beam_width,rollout_budget=rollout_budget,
                        alternatives=future_alternatives,schedule=fill_raman)
                except PolicySelectionError as error:
                    rejected.extend(dict(e,decision=decisions) for e in error.rejections)
                    failed_policy_search=error.report
                    raise
                rejected.extend(dict(e,decision=decisions) for e in policy_errors)
                base=choice.plan
                paths=critical_paths(state)
                summaries=[dict(c.summary(),features=candidate_features(c,state,paths)) for c in candidates]
                if choice.key not in {c.key for c in candidates}:
                    summaries.append(dict(choice.summary(),features=candidate_features(choice,state,paths)))
                entry.update(selected=choice.key, candidates=summaries, truncated=truncated,
                             policy_search=policy_search,selected_features=candidate_features(choice,state,paths))
            phase='schedule_validation'
            plan, rotations = fill_raman(base, state)
            entry['search']=[s for s in search_log if s['decision']==decisions]
            masks=dict(state.slm_enabled); changes=[]
            # Includes support transitions inside handoff operations, not just
            # standalone TRAP_SWITCH. Record precisely which sites change.
            work=state
            for op in plan.operations:
                # Appended Raman operations occur inside earlier physical
                # segments. They never change supports; replaying them at the
                # final pose would incorrectly revalidate the wrong instant.
                if op.operation_type==K.RAMAN_ROTATION:continue
                work=apply_operation(work,op,op.gate_id or base.intent.effect_gate_id)
                for site,enabled in work.slm_enabled.items():
                    if site.startswith('EZ') and masks[site]!=enabled:
                        changes.append({'site':site,'enabled':enabled,'operation':op.operation_type.value})
                masks=dict(work.slm_enabled)
            entry['ez_changes']=changes
            entry.update(duration_us=plan.estimated_duration_us,
                ez_switch_operations=sum(o.label=='Disable empty EZ SLM for routing' for o in plan.operations),
                switch_operations=sum(o.operation_type==K.TRAP_SWITCH for o in plan.operations), raman_slots=[
                {'gate_id': g, 'start_us': state.time_us+t, 'end_us': state.time_us+t+state.hardware.raman_duration_us}
                for g,t in rotations])
            phase='execution'
            entry['compile_wall_time_s']=perf_counter()-started
            executor.submit(plan); log.append(entry); decisions += 1; drain()
    except ValidationError as error:
        return result('stalled', error.violation.code, error.violation.message)
