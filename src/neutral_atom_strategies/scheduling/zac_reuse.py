"""Realize ZAC placement targets through the unchanged physical environment.

The upstream frontend owns ASAP layers, bipartite reuse and dynamic placement.
This adapter owns bounded, capacity-aware SLM transfers and full cleanup. It
does not replay ZAIR endpoint animation or use the author's timing estimates.
"""
from time import perf_counter
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer
from neutral_atom_strategies.scheduling.ordered_greedy import build_batch, new_builder, finish, restore
from neutral_atom_strategies.scheduling.m3 import initial_terminal


def site_id(site):
    return 'Z%s_R%s_C%s' % tuple(site)


class ZACPlacementStrategy:
    id = 'zac_reuse'

    def __init__(self, placement, *, timeout_s=300, route_budget=128, terminal_target=None, bounded_spares=False):
        self.placement = placement
        self.timeout_s = timeout_s
        self.route_budget = route_budget
        self.terminal_target = terminal_target
        self.bounded_spares = bounded_spares
        self.plans = []
        self.decisions = []
        self.rejections = []
        self.boundaries = []

    def run(self, env, *, on_event=None):
        initial = env.state
        terminal = self.terminal_target or initial_terminal(initial)
        deadline = perf_counter() + self.timeout_s
        transport = OrderedTransfer(deadline, self.route_budget, 'axis_hold', bounded_spares=self.bounded_spares)

        def check():
            if perf_counter() > deadline:
                raise TimeoutError('ZAC realization budget exhausted')

        def execute(plan, **decision):
            if plan is None:
                return
            check()
            start = env.state.time_us
            env.submit(plan)
            self.plans.append(plan)
            env.run(on_event=on_event)
            self.decisions.append(dict(decision, start_us=start, end_us=env.state.time_us))

        def transfer(destinations, stage, phase):
            pending = dict(destinations)
            buffered = set()
            while True:
                check()
                pending = {q: t for q, t in pending.items()
                           if env.state.placement.atom_to_holder[q].holder_id != t}
                if not pending:
                    return
                occupancy = env.state.placement.static_occupancy
                free = {q: t for q, t in pending.items() if t not in occupancy}
                if not free:
                    # A permutation cycle uses an explicit, empty storage buffer.
                    choices = [t for t in env.state.world.traps if t.startswith('BUFFER') and t not in occupancy]
                    q = next((q for q in sorted(pending) if q not in buffered), None)
                    if not choices or q is None:
                        raise ValidationError('ZAC_PLACEMENT_CYCLE', 'No free storage buffer for target permutation')
                    free = {q: choices[0]}
                    buffered.add(q)
                assignments = []
                groups = []
                for q, t in sorted(free.items()):
                    point = env.state.world.traps[t].position
                    trial = assignments + [(q, q, q, point.x_um, point.y_um)]
                    try:
                        build_batch(env.state, trial, check_closure=False, check_interactions=False,
                                    bounded_spares=self.bounded_spares)
                    except ValidationError:
                        continue
                    assignments = trial
                    groups.append({item[2]: free[item[2]] for item in assignments})
                groups = list(reversed(groups)) + [{q: t} for q, t in sorted(free.items())]
                tried = set()
                for group in groups:
                    key = tuple(sorted(group.items()))
                    if key in tried:
                        continue
                    tried.add(key)
                    check()
                    p = new_builder(env.state)
                    try:
                        transport.transfer_group(p, group, f'ZAC stage {stage}: {phase}')
                        plan = finish(p)
                    except ValidationError as error:
                        self.rejections.append(dict(stage=stage, phase=phase, atoms=list(group),
                                                    violation=primitive(error.violation)))
                        continue
                    execute(plan, kind='transfer', phase=phase, stage=stage, destinations=group)
                    break
                else:
                    raise ValidationError('ZAC_TRANSFER_EXHAUSTED',
                        'No legal transfer in bounded groups/routes; see rejections, not a proof of impossibility')

        mappings = self.placement['mappings']
        layers = self.placement['gate_layers']
        if len(mappings) != 2 * len(layers) + 1:
            raise ValueError('Unexpected ZAC mapping sequence')
        expected = {f'Q{q:03d}': site_id(s) for q, s in enumerate(mappings[0])}
        if expected != {q: h.holder_id for q, h in initial.placement.atom_to_holder.items()}:
            raise ValueError('ZAC mapping does not match the supplied initial state')
        for stage, indices in enumerate(layers):
            transfer({f'Q{q:03d}': site_id(s) for q, s in enumerate(mappings[2 * stage + 1])}, stage, 'prepare')
            ids = tuple(f'g{i:04d}' for i in indices)
            p = new_builder(env.state, ids)
            p.add(K.ENTANGLING_PULSE, f'ZAC CZ stage {stage}', gate_ids=ids)
            execute(finish(p), kind='CZ', stage=stage, gate_ids=ids)
            start = env.state.time_us
            retained = self.placement['selected_reuse'][stage]
            before = {f'Q{q:03d}': env.state.placement.atom_to_holder[f'Q{q:03d}'].holder_id for q in retained}
            transfer({f'Q{q:03d}': site_id(s) for q, s in enumerate(mappings[2 * stage + 2])}, stage, 'return non-reuse')
            if any(env.state.placement.atom_to_holder[q].holder_id != t for q, t in before.items()):
                raise AssertionError('Selected reuse atom was moved out of its SLM site')
            self.boundaries.append(dict(stage=stage, start_us=start, end_us=env.state.time_us,
                retained=before, matching_reuse=self.placement['matching_reuse'][stage]))
        # Both policies include the SAME explicit original holders and light/axis state.
        transfer({q: h.holder_id for q, h in terminal.holders}, len(layers), 'terminal return')
        execute(restore(env.state, terminal), kind='terminal', stage=len(layers))
        validate_target(terminal, env.state)
        if not env.state.dag.completed:
            raise AssertionError('ZAC adapter left unfinished circuit gates')
        return dict(status='completed', decisions=self.decisions, boundaries=self.boundaries)
