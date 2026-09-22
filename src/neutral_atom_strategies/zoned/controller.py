"""Circuit-independent layered compilation through the public environment API."""
from time import perf_counter
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import OperationType as K, TaskTarget
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import M4Result
from neutral_atom_strategies.motion.ordered_primitives import new_builder, finish, restore
from neutral_atom_strategies.scheduling.readout_placement import ReadoutPlacementPolicy
from neutral_atom_strategies.scheduling.qec import readout_groups, readout_service
from neutral_atom_strategies.ir import InteractionBlock
from .codegen import PhysicalCodegen
from .interaction import InteractionCompiler
from .placement import IDSPlacer
from .schedule import LayerScheduler


class _CompleteFrontierResolver:
    """Adapt IDS's partial fallback to the strict full-request IR contract.

    A partial prefix is a search result, not permission to drop requested gates.
    The controller retries a smaller explicit block instead. Other mismatches
    remain visible to InteractionCompiler's normal binding validation.
    """
    def __init__(self, placer):
        self.placer = placer

    def search(self, state, gates, deadline):
        candidates = self.placer.search(state, gates, deadline)
        expected = tuple((g.id, frozenset(g.qubit_ids)) for g in gates)
        complete = []
        for candidate in candidates:
            actual = tuple((c.gate_id, frozenset((c.anchor, c.mobile))) for c in candidate.choices)
            if 0 < len(actual) < len(expected) and actual == expected[:len(actual)]:
                continue
            complete.append(candidate)
        self.placer.stats['partial_candidates_deferred'] = len(candidates)-len(complete)
        return tuple(complete)


def run_zoned(env, *, strategy='zoned_ids', max_decisions=10000, compile_timeout_s=300,
              beam_width=64, plan_budget=4, site_limit=8, route_budget=128,
              solver_timeout_ms=5000, model_budget=24, motion_router='axis_hold',
              readout_mode='adaptive', readout_candidate_budget=16, readout_top_k=3,
              on_event=None, terminal_target=None, restore_layout=True):
    if strategy != 'zoned_ids':
        raise ValueError('Unknown zoned strategy')
    if type(restore_layout) is not bool or (not restore_layout and terminal_target is not None):
        raise ValueError('Stable completion cannot request a fixed terminal')
    if min(beam_width,plan_budget,site_limit,route_budget,max_decisions) < 1:
        raise ValueError('Search budgets must be positive')
    deadline = perf_counter()+compile_timeout_s
    terminal = terminal_target if terminal_target is not None else initial_terminal(env.state)
    scheduler = LayerScheduler(env.state.dag)
    placer = IDSPlacer(trials=plan_budget,queue_capacity=beam_width,site_limit=site_limit)
    lower = PhysicalCodegen(deadline,route_budget,motion_router)
    interactions = InteractionCompiler(_CompleteFrontierResolver(placer), lower, deadline)
    readout = ReadoutPlacementPolicy(readout_mode,readout_candidate_budget,readout_top_k,bounded_spares=True)
    log, rejections = [], []
    phase = 'initialization'

    def check():
        lower.check()
        if len(log) >= max_decisions:
            raise ValidationError('DECISION_LIMIT','Zoned controller decision budget exhausted')

    def execute(plan, detail):
        if plan is None:
            return
        check()
        row = dict(detail,decision=len(log),start_us=env.state.time_us,duration_us=plan.estimated_duration_us,
                   strategy=strategy,backend=env.state.hardware.backend,motion_router=motion_router)
        env.submit(plan)
        env.run(on_event=on_event)
        log.append(primitive(row))

    try:
        if env.state.hardware.backend not in {'row_column','row_column_orthogonal'}:
            raise ValidationError('ORDERED_BACKEND_REQUIRED','Zoned compiler requires ordered AOD axes')
        if env.state.placement.mobile_occupancy or env.state.aod.is_moving:
            raise ValidationError('ZONED_INITIAL_SUPPORT','Start from stable SLM holders and an empty stationary AOD')
        while not env.state.dag.completed:
            check()
            gates = scheduler.frontier(env.state)
            if not gates:
                raise ValidationError('ZONED_FRONTIER_EMPTY','No supported ready operation')
            kind = gates[0].gate_type
            phase = kind
            if gates[0].u_parameters is not None:
                ids = tuple(g.id for g in gates)
                p = new_builder(env.state,ids)
                p.add(K.RAMAN_ROTATION,kind+' batch',gate_ids=ids)
                execute(finish(p,compiler='zoned-ids-v1'),dict(kind=kind,gate_ids=ids,batch_size=len(ids)))
            elif kind == 'CZ':
                tick = perf_counter()
                plan = None
                placement_seconds = 0.
                codegen_seconds = 0.
                audit_seconds = 0.
                candidates = 0
                # Smaller fronts are a bounded recovery from geometric failure,
                # not removal of logical gates or disabling physical constraints.
                widths = list(dict.fromkeys((len(gates),max(1,len(gates)//2),1)))
                for width in widths:
                    block = InteractionBlock.for_gates(gates[:width],
                                id=f'interaction/{env.state.version}/{len(log)}/{width}')
                    started = perf_counter()
                    resolved = interactions.resolve(env.state,block.move)
                    placement_seconds += perf_counter()-started
                    candidates += len(resolved)
                    for binding in resolved:
                        placement = binding.placement
                        check()
                        try:
                            before = len(lower.stats['cz_batches'])
                            lowered = interactions.lower(env.state,binding,block.apply)
                            codegen_seconds += lowered.codegen_seconds
                            audit_seconds += lowered.audit_seconds
                            plan = lowered.plan
                        except ValidationError as error:
                            rejections.append(dict(phase='physical_lowering',code=error.violation.code,
                                                   message=error.violation.message,estimated_cost=placement.estimated_cost))
                            continue
                        detail = dict(kind='CZ',gate_ids=[c.gate_id for c in placement.choices],
                                      batch_size=len(placement.choices),placements=primitive(placement.choices),
                                      cz_batches=lower.stats['cz_batches'][before:],
                                      estimated_cost=placement.estimated_cost,placement_search=dict(placer.stats),
                                      candidate_count=candidates,planning_seconds=perf_counter()-tick,
                                      placement_seconds=placement_seconds,codegen_seconds=codegen_seconds,
                                      audit_seconds=audit_seconds,codegen=dict(lower.stats),
                                      staging=placement.staging,
                                      interaction_ir=block.to_dict(),resolved_interaction=binding.to_dict())
                        break
                    if plan is not None:
                        break
                if plan is None:
                    raise ValidationError('ZONED_LAYER_EXHAUSTED','Bounded placement and physical routes exhausted')
                execute(plan,detail)
            elif kind in {'MEASURE','RESET'}:
                plan = None
                last = None
                for group in readout_groups(env.state,gates):
                    try:
                        plan,_ = readout_service(env.state,lower,group,placement_policy=readout)
                    except ValidationError as error:
                        last = error
                        continue
                    break
                if plan is None:
                    raise last or ValidationError('ZONED_READOUT_EXHAUSTED','No readout group')
                execute(plan,dict(kind=kind,gate_ids=[g.id for g in group],readout_target=readout.log[-1]['selected'],
                                  readout_search=readout.log[-1]))
            else:
                raise ValidationError('ZONED_GATE_UNSUPPORTED',kind)
        if restore_layout:
            phase = 'terminal_restore'
            p = new_builder(env.state)
            lower.restore_destinations(p,{q:h.holder_id for q,h in terminal.holders})
            if p.operations:
                execute(finish(p,compiler='zoned-ids-v1'),dict(kind='Return to initial SLM'))
            execute(restore(env.state,terminal,compiler='zoned-ids-v1'),dict(kind='terminal',selected='explicit-terminal'))
        validate_target(terminal if restore_layout else TaskTarget(),env.state)
        return M4Result('completed',(),tuple(rejections),len(log),tuple(log))
    except (ValidationError,TimeoutError) as error:
        violation = getattr(error,'violation',None)
        diagnostic = dict(phase=phase,code=violation.code if violation else 'COMPILE_TIMEOUT',
                          message=violation.message if violation else str(error),placement_search=placer.stats,
                          codegen=lower.stats,route_rejections=lower.rejections[-20:],readout_log=readout.log,
                          unfinished_gates=[g for g,n in env.state.dag.nodes.items() if n.status.value!='completed'])
        return M4Result('stalled',(diagnostic,),tuple(rejections),len(log),tuple(log))
