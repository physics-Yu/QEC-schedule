"""Actual bounded compilation of equal-role work on disjoint sparse patches.

The strategy uses a rigid Cartesian AOD and validated shortest routes.
Each candidate passes ordinary ProgramBuilder, global pulse-pair validation
and Executor. No native gate is removed and no movement is a rendered hint.
"""
from collections import defaultdict
from dataclasses import replace
from itertools import combinations
from math import hypot
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, MobileCellIndex, Position2D, GateStatus, ZoneType
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.environment import as_environment
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.hardware.multi_aod import device, occupancy, supports
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_strategies.scheduling.m4 import M4Result
from neutral_atom_strategies.scheduling.rigid_readout_placement import RigidReadoutPlacementPolicy
from neutral_atom_strategies.motion.validated_rigid import (
    append_rigid_route, STANDARD_ROUTING, LEGACY_ROUTING)


def _point(state, atom):
    return state.placement.position(atom, state.world, state.aods)


def _builder(state, gates, decision):
    ids = frozenset(g.id for g in gates)
    atoms = frozenset(q for g in gates for q in g.qubit_ids)
    return ProgramBuilder(state, TaskIntent(f'parallel-patch/{state.version}/{decision}',
        TaskTarget(), atoms, phase='program', gate_effects=ids))


def _bindings(state, atoms, aod_id='AOD_0'):
    if occupancy(state, aod_id):
        raise ValidationError('PARALLEL_PATCH_LOADED', 'Begin equal-role service with the selected AOD empty')
    sites = {}
    for atom in atoms:
        holder = state.placement.atom_to_holder[atom]
        if holder.holder_type != HolderType.STATIC:
            raise ValidationError('PARALLEL_PATCH_SOURCE', 'Equal-role carriers must be supported by SLM')
        sites[atom] = state.world.traps[holder.holder_id]
    origin = Position2D(min(site.position.x_um for site in sites.values()),
        min(site.position.y_um for site in sites.values()))
    aod = device(state, aod_id)
    axes = aod.configuration()
    xs = tuple(x - aod.pose.x_um for x in axes.x_um)
    ys = tuple(y - aod.pose.y_um for y in axes.y_um)
    bindings = []
    for atom, site in sorted(sites.items()):
        col = next((i for i, offset in enumerate(xs) if abs(origin.x_um + offset - site.position.x_um) < 1e-7), None)
        row = next((i for i, offset in enumerate(ys) if abs(origin.y_um + offset - site.position.y_um) < 1e-7), None)
        if col is None or row is None:
            raise ValidationError('PARALLEL_PATCH_FOOTPRINT', 'Equal-role source does not embed in configured AOD axes')
        bindings.append(CaptureBinding(atom, MobileCellIndex(row, col, aod_id), site.id))
    return origin, tuple(bindings)


def _empty_reposition(p, target, aod_id='AOD_0', *, routing_policy=STANDARD_ROUTING):
    aod = device(p.state, aod_id)
    if aod.active_cells:
        masks = replace(supports(p.state, aod_id), rows=(False,) * aod.rows,
            columns=(False,) * aod.columns)
        p.add(K.TRAP_SWITCH, '关闭空 AOD 后定位', switch_state=masks, aod_id=aod_id)
    if device(p.state, aod_id).pose != target:
        if routing_policy == STANDARD_ROUTING:
            append_rigid_route(p, target, aod_id=aod_id, label='空 AOD 最短合法定位')
        else:
            p.add(K.AOD_MOVE, '空 AOD 定位到同角色载体', target=target, aod_id=aod_id)


def _outbound(p, source, target, bindings, *, aligned, aod_id='AOD_0', pair_offset=None,
              routing_policy=STANDARD_ROUTING):
    """Use the shared routing policy; keep old 5 um plans reproducible."""
    if routing_policy == STANDARD_ROUTING:
        return append_rigid_route(p, target, aod_id=aod_id, depart=bindings,
            approach=bindings if aligned else (), label='直达或 2.5 μm 半格最短合法运输').points
    if routing_policy != LEGACY_ROUTING:
        raise ValueError('Unknown rigid routing policy')
    offset = pair_offset or p.state.hardware.interaction_offset
    # Gate approaches terminate at a caller-declared finite pairing offset.
    # MZ service has no stationary partner; retain its old clearance path.
    delta_x, delta_y = ((-5, -5) if aligned else
        (-5-offset.x_um, -5-offset.y_um) if p.intent.gate_effects and
        any(p.state.dag.nodes[g].gate.gate_type == 'CZ' for g in p.intent.gate_effects)
        else (-2, -2))
    safe_source = Position2D(source.x_um - 5, source.y_um - 5)
    safe_target = Position2D(target.x_um + delta_x, target.y_um + delta_y)
    candidates = (safe_source, Position2D(safe_source.x_um, safe_target.y_um), safe_target, target)
    points = [source]
    for point in candidates:
        if point == points[-1]:
            continue
        last = point == target
        phase = 'depart' if len(points) == 1 else 'approach' if aligned and last else None
        p.add(K.AOD_MOVE, '同角色阵列沿明确安全通道运输', target=point,
            bindings=bindings if phase else (), phase=phase, aod_id=aod_id)
        points.append(point)
    return tuple(points)


def _return(p, points, bindings, aod_id='AOD_0', *, routing_policy=STANDARD_ROUTING):
    if routing_policy == STANDARD_ROUTING:
        append_rigid_route(p, points[0], aod_id=aod_id, approach=bindings,
                           label='脉冲后按实际状态重新求最短合法归还路径')
    else:
        for point in reversed(points[:-1]):
            last = point == points[0]
            p.add(K.AOD_MOVE, '同角色阵列返回各自原码块', target=point,
                bindings=bindings if last else (), phase='approach' if last else None, aod_id=aod_id)
    p.add(K.AOD_OFFLOAD, '卸载回原 SLM 格点', bindings=bindings, aod_id=aod_id)


def compile_cz_group(state, gates, *, decision=0, mobile_operands=None, pair_offset=None,
                     routing_policy=STANDARD_ROUTING):
    """Compile any authored pair with a finite isolated spatial pairing."""
    if not gates or any(g.gate_type != 'CZ' for g in gates):
        raise ValueError('A nonempty CZ group is required')
    mobiles = tuple(mobile_operands[g.id] if mobile_operands else g.qubit_ids[1] for g in gates)
    origin, bindings = _bindings(state, mobiles)
    offset = pair_offset or state.hardware.interaction_offset
    shifts = set()
    for gate, moving in zip(gates, mobiles):
        if moving not in gate.qubit_ids:
            raise ValueError('Moving operand must belong to its authored CZ')
        anchor = _point(state, next(q for q in gate.qubit_ids if q != moving))
        mobile = _point(state, moving)
        shifts.add((anchor.x_um + offset.x_um - mobile.x_um,
                    anchor.y_um + offset.y_um - mobile.y_um))
    if len(shifts) != 1:
        raise ValidationError('PARALLEL_PATCH_SHIFT', 'All group pairs must share one real rigid shift')
    dx, dy = shifts.pop()
    p = _builder(state, gates, decision)
    _empty_reposition(p, origin, routing_policy=routing_policy)
    p.add(K.AOD_LOAD, '装载各码块的对应 CZ 载体', bindings=bindings)
    points = _outbound(p, origin, Position2D(origin.x_um + dx, origin.y_um + dy), bindings,
                       aligned=False, pair_offset=offset, routing_policy=routing_policy)
    p.add(K.ENTANGLING_PULSE, '真实全局 CZ 脉冲；全部作用对必须匹配', gate_ids=tuple(g.id for g in gates))
    _return(p, points, bindings, routing_policy=routing_policy)
    return p.finish('parallel-patch-finite-pair-v1')


def _readout_mode(readout_placement, routing_policy):
    if routing_policy not in {STANDARD_ROUTING, LEGACY_ROUTING}:
        raise ValueError('Unknown rigid routing policy')
    mode = (('nearest_mz' if routing_policy == STANDARD_ROUTING else 'fixed_translation')
            if readout_placement is None else readout_placement)
    if mode not in {'nearest_mz', 'fixed_translation'}:
        raise ValueError('Readout placement must be nearest_mz or fixed_translation')
    return mode


def _realize_readout(state, gates, resets, origin, bindings, target, *, decision, aod_id,
                     routing_policy):
    """Realize one target from a fresh private builder, including restoration."""
    p = _builder(state, (*gates, *resets), decision)
    _empty_reposition(p, origin, aod_id, routing_policy=routing_policy)
    p.add(K.AOD_LOAD, '装载各码块的对应测量载体', bindings=bindings, aod_id=aod_id)
    # This MZ visit holds the carriers in stationary AOD; it does not offload
    # them into an invented measurement holder or skip native RESETs.
    points = _outbound(p, origin, target, bindings, aligned=False, aod_id=aod_id,
                       routing_policy=routing_policy)
    p.add(K.MEASUREMENT if gates[0].gate_type == 'MEASURE' else K.RESET,
        '在实际 MZ 内执行原生读出/复位', gate_ids=tuple(g.id for g in gates), aod_id=aod_id)
    if resets:
        p.add(K.RESET, '同次 MZ 访问实际复位读出的辅助载体', gate_ids=tuple(g.id for g in resets), aod_id=aod_id)
    _return(p, points, bindings, aod_id, routing_policy=routing_policy)
    return p.finish('parallel-patch-mz-return-v1')


def _fixed_readout_log(state, plan, origin, target, bindings, aod_id):
    aod = device(state, aod_id)
    axes = aod.configuration()
    positions = tuple(sorted((b.atom_id, (target.x_um + axes.x_um[b.cell.column] - aod.pose.x_um,
                                         target.y_um + axes.y_um[b.cell.row] - aod.pose.y_um))
                             for b in bindings))
    zones = [z.id for z in state.world.zones if z.zone_type == ZoneType.MEASUREMENT and
             all(z.bounds.contains(Position2D(*p)) for _, p in positions)]
    selected = {'status': 'accepted', 'support': 'aod', 'positions': positions,
        'aod_id': aod_id, 'zone_id': zones[0] if zones else None,
        'target_pose_um': [target.x_um, target.y_um],
        'proxy_distance_um': hypot(target.x_um-origin.x_um, target.y_um-origin.y_um),
        'actual_us': plan.estimated_duration_us, 'actual_distance_um': plan.estimated_distance_um}
    return {'schema': 'rigid-readout-placement-decision/1', 'aod_id': aod_id,
        'atom_ids': [b.atom_id for b in bindings], 'source_origin_um': [origin.x_um, origin.y_um],
        'support': 'aod', 'generated': 1, 'generation_rejections': {},
        'candidate_budget': 1, 'top_k': 1, 'candidates': [selected], 'selected': selected,
        'accepted': 1, 'optimality_claim': False,
        'selection_scope': 'fixed historical translation with complete service validation'}


def compile_readout_group(state, gates, *, decision=0, translation_um=-300., aod_id='AOD_0',
                          routing_policy=STANDARD_ROUTING, readout_placement=None,
                          readout_placement_log=None):
    """Choose legal MZ support; read/reset there; return the original holders.

    Standard routing defaults to bounded nearest-MZ placement. Explicit
    ``fixed_translation`` and the legacy default preserve historical plans.
    ``readout_placement_log`` is an optional list receiving decision evidence;
    it does not change the returned ``(plan, included_resets)`` contract.
    """
    if not gates or any(g.gate_type != gates[0].gate_type for g in gates) or gates[0].gate_type not in {'MEASURE', 'RESET'}:
        raise ValueError('A same-type MEASURE/RESET group is required')
    resets = []
    completed = {key for key, node in state.dag.nodes.items() if node.status == GateStatus.COMPLETED}
    allowed = completed | {g.id for g in gates}
    if gates[0].gate_type == 'MEASURE':
        for gate in gates:
            for child in state.dag.nodes[gate.id].successors:
                candidate = state.dag.nodes[child].gate
                parents = {key for key, node in state.dag.nodes.items() if child in node.successors}
                if candidate.gate_type == 'RESET' and candidate.qubit_ids == gate.qubit_ids and parents <= allowed:
                    resets.append(candidate)
    atoms = tuple(g.qubit_ids[0] for g in gates)
    origin, bindings = _bindings(state, atoms, aod_id)
    mode = _readout_mode(readout_placement, routing_policy)
    def realize(target):
        return _realize_readout(state, gates, resets, origin, bindings, target,
            decision=decision, aod_id=aod_id, routing_policy=routing_policy)
    if mode == 'fixed_translation':
        target = Position2D(origin.x_um, origin.y_um + translation_um)
        plan = realize(target)
        entries = [_fixed_readout_log(state, plan, origin, target, bindings, aod_id)] if readout_placement_log is not None else []
    else:
        policy = RigidReadoutPlacementPolicy(candidate_budget=16, top_k=3)
        try:
            plan = policy.choose(state, atoms, realize, aod_id=aod_id, origin=origin).plan
        finally:
            if readout_placement_log is not None:
                for entry in policy.log:
                    entry.update(policy=mode, decision=decision, kind=gates[0].gate_type,
                        gate_ids=[g.id for g in gates], included_reset_gate_ids=[g.id for g in resets],
                        status='selected' if entry['selected'] is not None else 'failed')
                readout_placement_log.extend(policy.log)
        entries = []
    for entry in entries:
        entry.update(policy=mode, decision=decision, kind=gates[0].gate_type,
            gate_ids=[g.id for g in gates], included_reset_gate_ids=[g.id for g in resets], status='selected')
    if readout_placement_log is not None:
        readout_placement_log.extend(entries)
    return plan, tuple(resets)


def compile_dual_reset_prologue(state, algorithm_gates, magic_gates, *, translation_um=-300.,
                                routing_policy=STANDARD_ROUTING, readout_placement=None,
                                readout_placement_log=None):
    """Two real concurrent transport lanes, one shared native RESET pulse.

    Separate RESET operations would contend for the global readout resource.
    Both arrays therefore arrive in MZ before one combined pulse, then return
    concurrently. Each lane retains Cartesian capture closure and its own IDs.
    """
    from neutral_atom_env.domain.operations import OperationInterval
    from neutral_atom_env.program.scheduled import build_scheduled_program
    lanes = []
    for aod_id, gates in (('AOD_0', algorithm_gates), ('AOD_MAGIC', magic_gates)):
        plan, resets = compile_readout_group(state, gates, decision=0, aod_id=aod_id,
            translation_um=translation_um, routing_policy=routing_policy,
            readout_placement=readout_placement, readout_placement_log=readout_placement_log)
        assert not resets
        pulse = next(i for i, op in enumerate(plan.operations) if op.operation_type == K.RESET)
        lanes.append((plan.operations[:pulse], plan.operations[pulse], plan.operations[pulse + 1:]))
    operations, intervals, ends = [], [], []
    def append(op, start, parents):
        new = replace(op, id=f'op{len(operations):02d}', depends_on=tuple(parents))
        operations.append(new)
        intervals.append(OperationInterval(new.id, start, start + new.duration_us, (), ()))
        return new.id, start + new.duration_us
    for before, pulse, after in lanes:
        time, parent = 0., None
        for op in before:
            parent, time = append(op, time, (parent,) if parent else ())
        ends.append((parent, time))
    all_gates = (*algorithm_gates, *magic_gates)
    pulse = replace(lanes[0][1], label='两台 AOD 均在 MZ 后的真实联合 RESET',
        gate_ids=tuple(g.id for g in all_gates), gate_id=None)
    pulse_id, pulse_end = append(pulse, max(time for _, time in ends), [parent for parent, _ in ends])
    for before, pulse, after in lanes:
        time, parent = pulse_end, pulse_id
        for op in after:
            parent, time = append(op, time, (parent,))
    intent = TaskIntent(f'parallel-patch-dual-reset/{state.version}', TaskTarget(),
        frozenset(q for g in all_gates for q in g.qubit_ids), phase='program',
        gate_effects=frozenset(g.id for g in all_gates))
    return build_scheduled_program(state, intent, operations, intervals, planner_id='parallel-patch-dual-mz-v1')


def _select_cz_group(state, ready, atom_roles, *, nonpair_spacing_um=10., pair_search=False):
    """Choose a closed, equal-shift matching without changing protocol edges.

    Enumerate subsets of at most six local-role classes, copied over patches.
    Prefer X/Z ancillas as mobile operands; pair_search may move the data instead.
    Capturing extra intersections or bringing any non-pair below the declared
    design spacing rejects a proposal before ordinary physical compilation.
    """
    shifts = defaultdict(lambda: defaultdict(list))
    for g in ready:
        ancillary = [q for q in g.qubit_ids if atom_roles[q]['kind'] == 'syndrome_ancilla']
        preferred = ancillary[0] if len(ancillary) == 1 else g.qubit_ids[1]
        mobiles = (preferred, next(q for q in g.qubit_ids if q != preferred)) if pair_search else (preferred,)
        offsets = tuple(Position2D(x, y) for x, y in ((-3, 0), (3, 0), (0, -3), (0, 3),
            (-3, -3), (-3, 3), (3, -3), (3, 3))) if pair_search else (state.hardware.interaction_offset,)
        for mobile in mobiles:
            anchor = next(q for q in g.qubit_ids if q != mobile)
            a, m = _point(state, anchor), _point(state, mobile)
            for o in offsets:
                shift = (a.x_um+o.x_um-m.x_um, a.y_um+o.y_um-m.y_um, o.x_um, o.y_um)
                signature = tuple(atom_roles[q]['role'].split('.')[-1] for q in g.qubit_ids)
                shifts[shift][signature].append((g, mobile))
    best = None
    positions = {q: _point(state, q) for q in state.atoms}
    for shift, classes in shifts.items():
        values = list(classes.values())
        if len(values) > 6:
            raise ValidationError('PATCH_LAYER_SCOPE', 'Only canonical layers of up to six role classes are supported')
        for count in range(len(values), 0, -1):
            for subset in combinations(values, count):
                records = tuple(item for group in subset for item in group)
                gates = tuple(g for g, _ in records)
                if best and len(gates) <= len(best[0]):
                    continue
                moving = {g.id: q for g, q in records}
                mobiles = set(moving.values())
                try:
                    origin, bindings = _bindings(state, mobiles)
                except ValidationError:
                    continue
                xs = {positions[q].x_um for q in mobiles}
                ys = {positions[q].y_um for q in mobiles}
                if {q for q, p in positions.items() if p.x_um in xs and p.y_um in ys} != mobiles:
                    continue
                intended = {frozenset(g.qubit_ids) for g in gates}
                if len({q for g in gates for q in g.qubit_ids}) != 2*len(gates):
                    continue
                endpoints = {q: Position2D(p.x_um+shift[0], p.y_um+shift[1]) if q in mobiles else p
                             for q, p in positions.items()}
                valid = True
                items = list(endpoints.items())
                for i, (a, p) in enumerate(items):
                    for b, q in items[i+1:]:
                        if frozenset((a, b)) in intended:
                            continue
                        if hypot(p.x_um-q.x_um, p.y_um-q.y_um) < nonpair_spacing_um-1e-7:
                            valid = False
                            break
                    if not valid:
                        break
                if valid:
                    best = (gates, moving, Position2D(shift[2], shift[3]))
    if best is None:
        raise ValidationError('PATCH_CAPTURE_OR_SPACING', 'No closed finite-CZ matching satisfies the 10 um non-pair design spacing')
    return best


def select_intrapatch_cz_group(state, ready, atom_roles, *, nonpair_spacing_um=10.):
    gates, moving, _ = _select_cz_group(state, ready, atom_roles, nonpair_spacing_um=nonpair_spacing_um)
    return gates, moving


def select_geometric_cz_group(state, ready, atom_roles):
    """Search both moving operands and eight explicit finite 3 um offsets."""
    return _select_cz_group(state, ready, atom_roles, pair_search=True)


def run_parallel_patch(env, *, atom_roles, on_event=None, on_plan=None,
                       max_decisions=512, wall_budget_s=1800., intra_patch=False,
                       mz_translation_um=-300., intra_services=False, pair_search=False,
                       routing_policy=STANDARD_ROUTING, readout_placement=None,
                       collective_mz=False):
    """Run the caller's supported DAG; return structured failure evidence."""
    env = as_environment(env)
    started = perf_counter()
    log = []
    placement_log = []
    phase = 'initialization'
    try:
        if routing_policy not in {STANDARD_ROUTING, LEGACY_ROUTING}:
            raise ValueError('Unknown rigid routing policy')
        readout_placement = _readout_mode(readout_placement, routing_policy)
        if env.state.quantum_state is None:
            raise ValidationError('PARALLEL_PATCH_QUANTUM', 'Enable tracked Clifford state before physical execution')
        if env.state.hardware.backend != 'rigid':
            raise ValidationError('PARALLEL_PATCH_BACKEND', 'This bounded translation compiler requires rigid axes')
        if collective_mz:
            from .collective_mz import compile_collective_mz
            gates = tuple(g for g in env.state.dag.ready_gates() if g.gate_type == 'RESET')
            if {q for g in gates for q in g.qubit_ids} != set(env.state.atoms):
                raise ValidationError('COLLECTIVE_MZ_INITIAL', 'All initial atom RESET targets must be ready together')
            tick = perf_counter()
            phase = 'collective_initial_reset'
            plan, resets, evidence = compile_collective_mz(env.state, gates, atom_roles,
                decision=0, routing_policy=routing_policy)
            entry = {'decision': 0, 'kind': 'RESET', 'gate_ids': [g.id for g in gates],
                'batch_size': len(gates), 'start_us': env.state.time_us,
                'duration_us': plan.estimated_duration_us, 'compile_wall_seconds': perf_counter()-tick,
                'plan_id': plan.id, 'routing_policy': routing_policy,
                'collective_mz_evidence': evidence, 'included_reset_gate_ids': [g.id for g in resets]}
            env.submit(plan)
            if on_plan:
                on_plan(plan, entry)
            env.run(on_event=on_event)
            entry['end_us'] = env.state.time_us
            log.append(entry)
        elif 'AOD_MAGIC' in env.state.aods:
            ready = env.state.dag.ready_gates()
            magic = tuple(g for g in ready if g.gate_type == 'RESET' and atom_roles[g.qubit_ids[0]]['aod_id'] == 'AOD_MAGIC')
            algorithm = tuple(g for g in ready if g.gate_type == 'RESET' and atom_roles[g.qubit_ids[0]]['aod_id'] == 'AOD_0'
                and atom_roles[g.qubit_ids[0]]['role'].split('.')[-1] == 'd0')
            if intra_services:
                from .patch_service_groups import select_readout_group
                algorithm = select_readout_group(env.state, ready, atom_roles)
            if not magic or not algorithm:
                raise ValidationError('PARALLEL_PATCH_DUAL_PREFIX', 'Both actual source RESET arrays are required at the initial dual-lane boundary')
            tick = perf_counter()
            phase = 'dual_reset_prologue'
            plan = compile_dual_reset_prologue(env.state, algorithm, magic,
                translation_um=mz_translation_um, routing_policy=routing_policy,
                readout_placement=readout_placement, readout_placement_log=placement_log)
            entry = {'decision': 0, 'kind': 'RESET', 'gate_ids': [g.id for g in (*algorithm, *magic)],
                'batch_size': len(algorithm) + len(magic), 'start_us': env.state.time_us,
                'duration_us': plan.estimated_duration_us, 'compile_wall_seconds': perf_counter() - tick,
                'plan_id': plan.id, 'actual_concurrent_aods': ['AOD_0', 'AOD_MAGIC'],
                'routing_policy': routing_policy, 'readout_placement': readout_placement,
                'readout_placement_decisions': placement_log}
            env.submit(plan)
            if on_plan:
                on_plan(plan, entry)
            env.run(on_event=on_event)
            entry['end_us'] = env.state.time_us
            log.append(entry)
        while not env.state.dag.completed:
            if len(log) >= max_decisions or perf_counter() - started > wall_budget_s:
                raise ValidationError('PARALLEL_PATCH_BUDGET', 'Bounded compile/execute budget exhausted')
            state = env.state
            placement_log = []
            ready = state.dag.ready_gates()
            if not ready:
                raise ValidationError('PARALLEL_PATCH_EMPTY', 'Unfinished DAG has no ready supported operation')
            rotations = [g for g in ready if g.u_parameters is not None]
            tick = perf_counter()
            if rotations:
                kind = rotations[0].gate_type
                phase = kind
                gates = tuple(g for g in rotations if g.gate_type == kind)
                p = _builder(state, gates, len(log))
                p.add(K.RAMAN_ROTATION, '对应码块同门型寻址并行', gate_ids=tuple(g.id for g in gates))
                plan = p.finish('parallel-patch-addressed-v1')
                extra = {}
            else:
                cz = [g for g in ready if g.gate_type == 'CZ']
                phase = 'CZ' if cz else ready[0].gate_type
                candidates = cz or [g for g in ready if g.gate_type == phase]
                buckets = defaultdict(list)
                for gate in candidates:
                    signature = tuple(atom_roles[q]['role'].split('.')[-1] for q in gate.qubit_ids)
                    buckets[signature].append(gate)
                gates = tuple(next(iter(buckets.values())))
                if phase == 'CZ':
                    mobile_operands = None
                    pair_offset = None
                    if pair_search:
                        gates, mobile_operands, pair_offset = select_geometric_cz_group(state, cz, atom_roles)
                    elif intra_patch:
                        gates, mobile_operands = select_intrapatch_cz_group(state, cz, atom_roles)
                    plan = compile_cz_group(state, gates, decision=len(log), mobile_operands=mobile_operands,
                                            pair_offset=pair_offset, routing_policy=routing_policy)
                    per_patch = defaultdict(int)
                    for g in gates:
                        per_patch[atom_roles[g.qubit_ids[0]]['patch']] += 1
                    extra = {'pairs_per_patch': dict(per_patch), 'intra_patch_enabled': intra_patch,
                        'pair_search_enabled': pair_search,
                        'moving_operands': mobile_operands,
                        'pair_offset_um': [pair_offset.x_um, pair_offset.y_um] if pair_offset else
                                          [state.hardware.interaction_offset.x_um, state.hardware.interaction_offset.y_um]}
                elif collective_mz and phase in {'MEASURE', 'RESET'}:
                    from .collective_mz import compile_collective_mz
                    gates = tuple(candidates)
                    plan, resets, evidence = compile_collective_mz(state, gates, atom_roles,
                        decision=len(log), routing_policy=routing_policy)
                    extra = {'included_reset_gate_ids': [g.id for g in resets],
                        'collective_mz_evidence': evidence}
                else:
                    if intra_services:
                        from .patch_service_groups import select_readout_group
                        gates = select_readout_group(state, candidates, atom_roles)
                    plan, resets = compile_readout_group(state, gates, decision=len(log),
                        translation_um=mz_translation_um, routing_policy=routing_policy,
                        readout_placement=readout_placement, readout_placement_log=placement_log)
                    extra = {'included_reset_gate_ids': [g.id for g in resets],
                        'readout_placement': readout_placement, 'readout_placement_decisions': placement_log}
            entry = {'decision': len(log), 'kind': phase, 'gate_ids': [g.id for g in gates],
                'batch_size': len(gates), 'start_us': state.time_us,
                'duration_us': plan.estimated_duration_us, 'compile_wall_seconds': perf_counter() - tick,
                'plan_id': plan.id, 'routing_policy': routing_policy, **extra}
            env.submit(plan)
            if on_plan:
                on_plan(plan, entry)
            env.run(on_event=on_event)
            entry['end_us'] = env.state.time_us
            log.append(entry)
        validate_target(TaskTarget(), env.state)
        return M4Result('completed', (), (), len(log), tuple(log))
    except (ValidationError, TimeoutError) as error:
        violation = getattr(error, 'violation', None)
        diagnostic = {'phase': phase, 'code': violation.code if violation else 'PARALLEL_PATCH_TIMEOUT',
            'message': violation.message if violation else str(error), 'wall_seconds': perf_counter() - started,
            'unfinished_gate_ids': [g.id for g in env.state.dag.circuit.gates
                if env.state.dag.nodes[g.id].status != GateStatus.COMPLETED]}
        if placement_log:
            diagnostic['readout_placement_decisions'] = placement_log
        return M4Result('stalled', (diagnostic,), (), len(log), tuple(log))
