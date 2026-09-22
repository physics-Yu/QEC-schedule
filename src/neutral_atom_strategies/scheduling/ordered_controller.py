"""Circuit-independent controller for ordered-axis strategies on a supplied env.

No demo factory, gate IDs, fixed atom count or protocol is owned here. Generic
SLM layouts are staged into the existing EZ, splitting transfers to AOD capacity.
"""
from time import perf_counter
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import ZoneType
from neutral_atom_env.domain.operations import OperationType as K, TaskTarget
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import M4Result
from neutral_atom_strategies.scheduling.patch_greedy import patch_assignment
from neutral_atom_strategies.motion.single_trap import in_zone
from neutral_atom_strategies.scheduling.ordered_greedy import OrderedAxisGreedy, new_builder, finish, restore, build_batch
from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer
from neutral_atom_strategies.scheduling.readout_placement import ReadoutPlacementPolicy
from neutral_atom_strategies.scheduling.qec import readout_groups, readout_service


def run_ordered(env, *, strategy='ordered_greedy', max_decisions=10000, compile_timeout_s=300,
                beam_width=64, plan_budget=4, route_budget=128, solver_timeout_ms=5000,
                model_budget=24, motion_router='axis_hold', readout_mode='adaptive',
                readout_candidate_budget=16, readout_top_k=3, on_event=None, terminal_target=None,
                restore_layout=True):
    if strategy not in {'ordered_greedy','smt_ordered'}:
        raise ValueError('Unknown ordered strategy')
    if type(restore_layout) is not bool or (not restore_layout and terminal_target is not None):
        raise ValueError('Stable completion must not also request a fixed terminal layout')
    state=env.state
    terminal=terminal_target if terminal_target is not None else initial_terminal(state)
    deadline=perf_counter()+compile_timeout_s
    if strategy=='smt_ordered':
        from .smt_ordered import SMTOrderedAxisPlanner
        planner=SMTOrderedAxisPlanner(solver_timeout_ms,model_budget,route_budget,motion_router)
    else:
        planner=OrderedAxisGreedy(beam_width=beam_width,plan_budget=plan_budget,
                                  route_budget=route_budget,motion_router=motion_router)
    transport=OrderedTransfer(deadline,route_budget,motion_router)
    readout=ReadoutPlacementPolicy(readout_mode,readout_candidate_budget,readout_top_k)
    log=[]; rejections=[]; phase='initialization'

    def check_budget():
        if perf_counter()>deadline:raise TimeoutError('Ordered controller compile deadline')
        if len(log)>=max_decisions:raise ValidationError('DECISION_LIMIT','Ordered controller decision budget exhausted')

    def execute(plan, decision):
        if plan is None:return
        check_budget()
        entry=dict(decision,decision=len(log),start_us=env.state.time_us,
                   duration_us=plan.estimated_duration_us,strategy=strategy,
                   backend=env.state.hardware.backend,motion_router=motion_router)
        env.submit(plan);env.run(on_event=on_event);log.append(primitive(entry))

    def transfer(destinations, label):
        """Try a closed, capacity-fitting group; split after a physical rejection.

        All attempts use private builders. An accepted plan is submitted before
        recalculating remaining groups from the new authoritative state.
        """
        pending=dict(destinations)
        while pending:
            check_budget()
            pending={q:t for q,t in pending.items() if env.state.placement.atom_to_holder[q].holder_id!=t}
            if not pending:break
            assignments=[]; groups=[]
            for q,t in sorted(pending.items()):
                point=env.state.world.traps[t].position
                candidate=assignments+[(q,q,q,point.x_um,point.y_um)]
                try:build_batch(env.state,candidate,check_closure=False,check_interactions=False)
                except ValidationError:continue
                assignments=candidate
                groups.append({a[2]:pending[a[2]] for a in assignments})
            groups=list(reversed(groups))+[{q:t} for q,t in sorted(pending.items())]
            tried=set(); accepted=False
            for group in groups:
                signature=tuple(group)
                if signature in tried:continue
                tried.add(signature);check_budget();p=new_builder(env.state)
                try:transport.transfer_group(p,group,label)
                except ValidationError as error:
                    rejections.append({'phase':phase,'atoms':list(group),'violation':primitive(error.violation)})
                    continue
                execute(finish(p),{'kind':label,'atom_ids':list(group)})
                accepted=True;break
            if not accepted:raise ValidationError('ORDERED_STAGING_EXHAUSTED','No validated transport group within axis capacity and route budget')

    try:
        if state.hardware.backend not in {'row_column','row_column_orthogonal'}:
            raise ValidationError('ORDERED_BACKEND_REQUIRED','Select row_column or row_column_orthogonal hardware')
        if any(n.gate.gate_type=='CZ' for n in state.dag.nodes.values()) and not all(
                in_zone(state,state.placement.position(q,state.world,state.aod),ZoneType.ENTANGLEMENT) for q in state.atoms):
            phase='stage_to_EZ';transfer(patch_assignment(state),'Stage to EZ')
        while not env.state.dag.completed:
            check_budget();ready=sorted(env.state.dag.ready_gates(),key=lambda g:g.id)
            rotations=[g for g in ready if g.u_parameters is not None]
            if rotations:
                phase='single_qubit';kind=rotations[0].gate_type
                ids=tuple(g.id for g in rotations if g.gate_type==kind)
                p=new_builder(env.state,ids);p.add(K.RAMAN_ROTATION,kind+' batch',gate_ids=ids)
                execute(finish(p),{'kind':kind,'gate_ids':ids,'batch_size':len(ids)})
            elif any(g.gate_type=='CZ' for g in ready):
                phase='CZ';decision,plan=planner.propose(env.state,deadline)
                execute(plan,decision)
            else:
                phase='readout';gates=[g for g in ready if g.gate_type in {'MEASURE','RESET'}]
                if not gates:raise ValidationError('ORDERED_FRONTIER_EMPTY','No supported ready operation')
                gates=[g for g in gates if g.gate_type==gates[0].gate_type];plan=None;last=None
                for group in readout_groups(env.state,gates):
                    try:plan,_=readout_service(env.state,transport,group,placement_policy=readout)
                    except ValidationError as error:last=error;continue
                    break
                if plan is None:raise last
                execute(plan,{'kind':group[0].gate_type,'gate_ids':[g.id for g in group],
                              'readout_target':readout.log[-1]['selected'],'readout_search':readout.log[-1]})
        if restore_layout:
            phase='terminal_restore'
            transfer({q:h.holder_id for q,h in terminal.holders},'Return to initial SLM')
            execute(restore(env.state,terminal),{'kind':'terminal','selected':'explicit-terminal'})
        validate_target(terminal if restore_layout else TaskTarget(),env.state)
        return M4Result('completed',(),tuple(rejections),len(log),tuple(log))
    except (ValidationError,TimeoutError) as error:
        violation=getattr(error,'violation',None)
        rejections.extend({'phase':'search','violation':{'code':r.get('code','SEARCH_REJECTION'),'message':r.get('message','')},'details':r}
                          for r in getattr(planner,'rejections',[])+transport.rejections)
        diagnostic={'phase':phase,'code':violation.code if violation else 'COMPILE_TIMEOUT',
                    'message':violation.message if violation else str(error),
                    'unfinished_gates':[g for g,n in env.state.dag.nodes.items() if n.status.value!='completed'],
                    'search_log':getattr(planner,'log',[]),'readout_log':readout.log}
        return M4Result('stalled',(diagnostic,),tuple(rejections),len(log),tuple(log))
