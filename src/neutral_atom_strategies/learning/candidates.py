"""Stage-A finite restoring actions; independent of all greedy schedulers.

Shared geometric route tools are immutable dependencies. This deliberately small
action family is not the final autoregressive learner or a complete search.
"""
from dataclasses import dataclass, replace
from itertools import combinations
from time import perf_counter

from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.models import MobileCellIndex
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.axis_hold_routes import axis_hold_routes, transfer_annotation
from neutral_atom_strategies.motion.ordered_routes import OccupiedSLMGrid


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    gate_ids: tuple
    assignments: tuple = ()  # gate, stationary atom, moving atom, target x, target y


def terminal_target(state):
    return TaskTarget(tuple(state.placement.atom_to_holder.items()), state.aod.configuration(), trap_state(state))


def builder(state, action):
    return ProgramBuilder(state, TaskIntent(action.id, TaskTarget(), frozenset(state.atoms),
        phase='program' if action.gate_ids else 'cleanup', gate_effects=frozenset(action.gate_ids)))


def empty_position(p, target):
    if p.state.placement.mobile_occupancy:
        raise ValidationError('RL_AOD_BUSY', 'Stage A requires empty AOD service boundaries')
    masks = replace(trap_state(p.state), rows=(False,)*p.state.aod.rows, columns=(False,)*p.state.aod.columns)
    if masks != trap_state(p.state):
        p.add(K.TRAP_SWITCH, 'Disable empty axes', switch_state=masks)
    for axes in (AODConfiguration(target.x_um, p.state.aod.configuration().y_um), target):
        if axes != p.state.aod.configuration():
            p.add(K.AOD_MOVE, 'Position empty ordered axes', configuration=axes)


def finish(p, target=None):
    p.intent = replace(p.intent, target=target or terminal_target(p.state))
    return p.finish('rl-stage-a-physical-realizer-v1')


class RestoringCandidates:
    def __init__(self, *, ready_limit=8, candidate_budget=24, route_budget=16, planning_seconds=30):
        self.ready_limit = ready_limit
        self.candidate_budget = candidate_budget
        self.route_budget = route_budget
        self.planning_seconds = planning_seconds

    def proposals(self, state):
        ready_all = sorted(state.dag.ready_gates(), key=lambda g: g.id)
        ready = ready_all[:self.ready_limit]
        raw = []
        for kind in ('H', 'X', 'Y', 'Z', 'T'):
            ids = tuple(g.id for g in ready if g.gate_type == kind)
            if ids:
                raw.append((kind, ids, ()))
                raw.extend((kind, (gid,), ()) for gid in ids if len(ids)>1)
        shifts = {}
        for gate in ready:
            if gate.gate_type != 'CZ':
                continue
            a, b = gate.qubit_ids
            distance = state.hardware.interaction_distance_um
            for anchor, mobile in ((a,b),(b,a)):
                pa = state.placement.position(anchor,state.world,state.aod)
                pm = state.placement.position(mobile,state.world,state.aod)
                for dx,dy in ((0,-distance),(0,distance),(-distance,0),(distance,0)):
                    assignment = (gate.id,anchor,mobile,pa.x_um+dx,pa.y_um+dy)
                    key = (round(pa.x_um+dx-pm.x_um,7),round(pa.y_um+dy-pm.y_um,7))
                    shifts.setdefault(key,[]).append(assignment)
        cz = []
        for members in shifts.values():
            for size in range(min(len(members),4),0,-1):
                for group in combinations(members,size):
                    operands = [q for a in group for q in a[1:3]]
                    if len(set(operands)) != len(operands):
                        continue
                    cz.append(('CZ',tuple(a[0] for a in group),group))
        # Explicit bounded ordering, not a learned mask or a completeness claim.
        raw.extend(sorted(set(cz),key=lambda item:(-len(item[1]),item[2])))
        actions = tuple(Action(f'rl/{state.version}/{i}',*item) for i,item in enumerate(raw))
        return actions, len(ready_all)-len(ready)

    def realize(self, state, action, deadline):
        p = builder(state, action)
        if action.kind != 'CZ':
            p.add(K.RAMAN_ROTATION, 'Learning sandbox same-kind pulse', gate_ids=action.gate_ids)
            return finish(p)
        positions = {a[2]:state.placement.position(a[2],state.world,state.aod) for a in action.assignments}
        xs = tuple(sorted({p.x_um for p in positions.values()}))
        ys = tuple(sorted({p.y_um for p in positions.values()}))
        if len(xs)>state.aod.columns or len(ys)>state.aod.rows:
            raise ValidationError('RL_AXIS_CAPACITY','Selected group exceeds axis capacity')
        fullx = xs+tuple(xs[-1]+10*i for i in range(1,state.aod.columns-len(xs)+1))
        fully = ys+tuple(ys[-1]+10*i for i in range(1,state.aod.rows-len(ys)+1))
        pickup = AODConfiguration(fullx,fully)
        a = action.assignments[0]
        dx,dy = a[3]-positions[a[2]].x_um,a[4]-positions[a[2]].y_um
        target = AODConfiguration(tuple(x+dx for x in fullx),tuple(y+dy for y in fully))
        bindings = tuple(CaptureBinding(q,MobileCellIndex(ys.index(pos.y_um),xs.index(pos.x_um)),
                         state.placement.atom_to_holder[q].holder_id) for q,pos in sorted(positions.items()))
        empty_position(p,pickup)
        p.add(K.AOD_LOAD,'Capture selected operands',bindings=bindings)
        grid = OccupiedSLMGrid(p.state)
        backend = get_backend(state.hardware)
        paths = [path for path in axis_hold_routes(pickup,target) if grid.allows(path)]
        paths.sort(key=lambda path:(sum(backend.move_duration(p.state.aod.configured(a),b,state.hardware)
                                       for a,b in zip(path,path[1:])),len(path)))
        codes = []
        for path in paths[:self.route_budget]:
            if perf_counter()>deadline:
                raise TimeoutError('Candidate realization time budget exhausted')
            trial = builder(state,action)
            trial.state=p.state;trial.operations=list(p.operations);trial.bindings=dict(p.bindings);trial.distance=p.distance
            try:
                for i,axes in enumerate(path[1:]):
                    phase,bs = transfer_annotation(trial.state,trial.state.aod.configuration(),axes,bindings,'depart') if i==0 else (None,())
                    trial.add(K.AOD_MOVE,'Move to CZ target',configuration=axes,phase=phase,bindings=bs)
                trial.add(K.ENTANGLING_PULSE,'Learning sandbox CZ batch',gate_ids=action.gate_ids)
                back = list(reversed(path[:-1]))
                for i,axes in enumerate(back):
                    phase,bs = transfer_annotation(trial.state,trial.state.aod.configuration(),axes,bindings,'approach') if i==len(back)-1 else (None,())
                    trial.add(K.AOD_MOVE,'Return CZ operands',configuration=axes,phase=phase,bindings=bs)
                trial.add(K.AOD_OFFLOAD,'Restore original SLM holders',bindings=bindings)
                return finish(trial)
            except ValidationError as error:
                codes.append(error.violation.code)
        raise ValidationError('RL_ROUTE_EXHAUSTED',f'Finite routes exhausted; checked {min(len(paths),self.route_budget)}; reasons {sorted(set(codes))}')

    def cleanup(self,state,terminal):
        p = builder(state,Action(f'rl/{state.version}/cleanup','CLEANUP',()))
        empty_position(p,terminal.aod_configuration)
        if trap_state(p.state)!=terminal.traps:
            p.add(K.TRAP_SWITCH,'Restore terminal switches',switch_state=terminal.traps)
        return finish(p,terminal)

    def build(self,env,terminal):
        started = perf_counter()
        log = {'generated':0,'attempted':0,'not_attempted':0,'ready_omitted':0,'rejections':[], 'budget_exhausted':False}
        if env.state.dag.completed:
            plan = self.cleanup(env.state,terminal)
            env.validate(plan)
            action = Action(f'rl/{env.state.version}/cleanup','CLEANUP',())
            return [(action,plan)], dict(log,generated=1,attempted=1,planning_seconds=perf_counter()-started)
        actions, omitted = self.proposals(env.state)
        log.update(generated=len(actions),ready_omitted=omitted)
        # A one-row AOD can never pick up operands on two distinct rows.
        # Such necessary-condition failures must not consume the expensive
        # realization budget and starve valid smaller services.
        eligible=[];capacity_rejections=[]
        for action in actions:
            positions=[env.state.placement.position(a[2],env.state.world,env.state.aod) for a in action.assignments]
            if action.kind=='CZ' and (len({p.x_um for p in positions})>env.state.aod.columns
                    or len({p.y_um for p in positions})>env.state.aod.rows):
                capacity_rejections.append(action.id)
            else:eligible.append(action)
        log.update(capacity_pruned=len(capacity_rejections),capacity_rejected_ids=capacity_rejections)
        legal = []
        deadline = started+self.planning_seconds
        for action in eligible[:self.candidate_budget]:
            if perf_counter()>deadline:
                log['budget_exhausted']=True
                break
            log['attempted']+=1
            try:
                plan = self.realize(env.state,action,deadline)
                env.validate(plan)
                legal.append((action,plan))
            except ValidationError as error:
                log['rejections'].append({'action_id':action.id,'code':error.violation.code,'message':str(error)})
            except TimeoutError as error:
                log['budget_exhausted']=True
                log['rejections'].append({'action_id':action.id,'code':'PLANNING_BUDGET','message':str(error)})
                break
        log['not_attempted']=len(eligible)-log['attempted']
        log['planning_seconds']=perf_counter()-started
        return legal,log
