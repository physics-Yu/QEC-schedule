"""Finite deterministic M3 baseline. Policy decisions are revisitable in M4."""
from dataclasses import dataclass
from neutral_atom_env.domain.operations import TaskIntent,TaskTarget,OperationType as K
from neutral_atom_env.domain.models import HolderType as H,HolderRef,GateStatus
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.hardware.raman import validate_rotation
from neutral_atom_env.motion.persistent import ResidentCompiler,ReturningCompiler,PersistentTargetCompiler
from neutral_atom_env.motion.scheduled import scheduled_program
from neutral_atom_env.motion.program import apply_operation
from neutral_atom_env.motion.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from .executor import Executor


@dataclass(frozen=True)
class M3Result:
    status:str
    diagnostics:tuple
    candidate_rejections:tuple
    decisions:int


def initial_terminal(state):
    return TaskTarget(tuple(sorted(state.placement.atom_to_holder.items())),state.aod.configuration(),trap_state(state))


def overlap_candidates(base,state,limit=16):
    """At most one new Raman per program; earliest legal move window, stable SLM."""
    candidates=[];work=state;time=0.
    for op in base.operations:
        if op.operation_type==K.AOD_MOVE and op.duration_us>=state.hardware.raman_duration_us:
            for key,node in sorted(state.dag.nodes.items()):
                if key in base.intent.gate_ids or node.gate.u_parameters is None or node.status in {GateStatus.COMPLETED,GateStatus.FAILED}:continue
                # A blocked successor is allowed only after all of its parents completed.
                parents=[p for p,n in work.dag.nodes.items() if key in n.successors]
                if any(work.dag.nodes[p].status!=GateStatus.COMPLETED for p in parents):continue
                try:validate_rotation(work,key)
                except ValidationError:continue
                if node.gate.qubit_ids[0] in work.placement.mobile_occupancy.values():continue
                candidates.append((key,time))
                if len(candidates)>=limit:return candidates
        work=apply_operation(work,op,next(iter(base.intent.gate_ids),None))
        if op.operation_type==K.RAMAN_ROTATION:
            from dataclasses import replace
            gate=next(iter(base.intent.gate_ids))
            work=replace(work,dag=work.dag.transitioned(gate,GateStatus.RESERVED).transitioned(gate,GateStatus.RUNNING).transitioned(gate,GateStatus.COMPLETED))
        time+=op.duration_us
    return candidates


def run_m3(state,*,compiler='resident',terminal=None,overlap=True,max_decisions=10000,on_event=None):
    if compiler not in {'resident','returning'}:raise ValueError('Unknown M3 compiler')
    if type(max_decisions) is not int or max_decisions<1:raise ValueError('Positive decision budget required')
    compiler_obj=ResidentCompiler() if compiler=='resident' else ReturningCompiler()
    targeter=PersistentTargetCompiler();terminal=terminal or initial_terminal(state)
    executor=Executor(state);rejected=[];decisions=0
    def drain():
        while state.event_queue:
            event=executor.step()
            if on_event:on_event(state,event)
    def fail(code,message):
        return M3Result('stalled',({'code':code,'message':message,'holders':primitive(state.placement.atom_to_holder),
            'unfinished_gates':[q for q,n in state.dag.nodes.items() if n.status!=GateStatus.COMPLETED],
            'max_decisions':max_decisions},),tuple(rejected),decisions)
    try:
        drain()  # Restore continues the committed task before making a fresh decision.
        while decisions<max_decisions:
            if state.dag.completed:
                try:validate_target(terminal,state);return M3Result('completed',(),tuple(rejected),decisions)
                except ValidationError:pass
                intent=TaskIntent(f'exit/{state.version}',terminal,frozenset(state.atoms),phase='cleanup')
                base=targeter.compile(intent,state)
            else:
                loaded=next(iter(state.placement.mobile_occupancy.values()),None)
                ready=state.dag.ready_gates();base=None
                # A ready Raman can accompany the loaded partner's return, releasing
                # its successor before the transport/cleanup is complete.
                if loaded and any(g.u_parameters is not None for g in ready):
                    desired=dict(terminal.holders).get(loaded)
                    site=desired.holder_id if desired and desired.holder_type==H.STATIC and desired.holder_id not in state.placement.static_occupancy else targeter.spare(state)
                    intent=TaskIntent(f'cleanup/{state.version}',TaskTarget(((loaded,HolderRef(H.STATIC,site)),)),frozenset({loaded}),phase='cleanup')
                    base=targeter.compile(intent,state)
                else:
                    for gate in ready:
                        try:base=compiler_obj.compile_gate(gate.id,state);break
                        except ValidationError as error:
                            rejected.append({'decision':decisions,'gate_id':gate.id,'violation':primitive(error.violation)})
                if base is None:return fail('CANDIDATES_EXHAUSTED','No legal READY gate candidate in the finite search')
            plan=base
            if overlap:
                for gate,start in overlap_candidates(base,state):
                    try:plan=scheduled_program(base,state,((gate,start),));break
                    except ValidationError as error:
                        rejected.append({'decision':decisions,'overlap_gate':gate,'start_us':start,'violation':primitive(error.violation)})
            executor.submit(plan);decisions+=1;drain()
        if state.dag.completed:
            try:
                validate_target(terminal,state)
                return M3Result('completed',(),tuple(rejected),decisions)
            except ValidationError:pass
        return fail('DECISION_BUDGET_EXHAUSTED','Finite decision budget reached before gates and terminal state completed')
    except ValidationError as error:
        return fail(error.violation.code,error.violation.message)
