"""Actual bounded compilation of equal-role work on disjoint sparse patches.

The strategy uses a rigid Cartesian AOD and explicit half-spacing corridors.
Each candidate passes ordinary ProgramBuilder, global pulse-pair validation
and Executor. No native gate is removed and no movement is a rendered hint.
"""
from collections import defaultdict
from dataclasses import replace
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, MobileCellIndex, Position2D, GateStatus
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.environment import as_environment
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.hardware.multi_aod import device, supports
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_strategies.scheduling.m4 import M4Result


def _point(state, atom):
    return state.placement.position(atom, state.world, state.aod)


def _builder(state, gates, decision):
    ids = frozenset(g.id for g in gates)
    atoms = frozenset(q for g in gates for q in g.qubit_ids)
    return ProgramBuilder(state, TaskIntent(f'parallel-patch/{state.version}/{decision}',
        TaskTarget(), atoms, phase='program', gate_effects=ids))


def _bindings(state, atoms, aod_id='AOD_0'):
    if state.placement.mobile_occupancy:
        raise ValidationError('PARALLEL_PATCH_LOADED', 'Begin equal-role service with an empty algorithm AOD')
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


def _empty_reposition(p, target, aod_id='AOD_0'):
    aod = device(p.state, aod_id)
    if aod.active_cells:
        masks = replace(supports(p.state, aod_id), rows=(False,) * aod.rows,
            columns=(False,) * aod.columns)
        p.add(K.TRAP_SWITCH, '关闭空 AOD 后定位', switch_state=masks, aod_id=aod_id)
    if device(p.state, aod_id).pose != target:
        p.add(K.AOD_MOVE, '空 AOD 定位到同角色载体', target=target, aod_id=aod_id)


def _outbound(p, source, target, bindings, *, aligned, aod_id='AOD_0'):
    """Explicit 5 um corridors around the 10 um occupied lattice subset."""
    delta = -5 if aligned else -2  # (-3,-3) CZ target clears to anchor+(-5,-5).
    safe_source = Position2D(source.x_um - 5, source.y_um - 5)
    safe_target = Position2D(target.x_um + delta, target.y_um + delta)
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


def _return(p, points, bindings, aod_id='AOD_0'):
    for point in reversed(points[:-1]):
        last = point == points[0]
        p.add(K.AOD_MOVE, '同角色阵列返回各自原码块', target=point,
            bindings=bindings if last else (), phase='approach' if last else None, aod_id=aod_id)
    p.add(K.AOD_OFFLOAD, '卸载回原 SLM 格点', bindings=bindings, aod_id=aod_id)


def compile_cz_group(state, gates, *, decision=0):
    """Compile any authored pair with a finite isolated spatial pairing."""
    if not gates or any(g.gate_type != 'CZ' for g in gates):
        raise ValueError('A nonempty CZ group is required')
    mobiles = tuple(g.qubit_ids[1] for g in gates)
    origin, bindings = _bindings(state, mobiles)
    offset = state.hardware.interaction_offset
    shifts = set()
    for gate in gates:
        anchor, mobile = map(lambda q: _point(state, q), gate.qubit_ids)
        shifts.add((anchor.x_um + offset.x_um - mobile.x_um,
                    anchor.y_um + offset.y_um - mobile.y_um))
    if len(shifts) != 1:
        raise ValidationError('PARALLEL_PATCH_SHIFT', 'All group pairs must share one real rigid shift')
    dx, dy = shifts.pop()
    p = _builder(state, gates, decision)
    _empty_reposition(p, origin)
    p.add(K.AOD_LOAD, '装载各码块的对应 CZ 载体', bindings=bindings)
    points = _outbound(p, origin, Position2D(origin.x_um + dx, origin.y_um + dy), bindings, aligned=False)
    p.add(K.ENTANGLING_PULSE, '真实全局 CZ 脉冲；全部作用对必须匹配', gate_ids=tuple(g.id for g in gates))
    _return(p, points, bindings)
    return p.finish('parallel-patch-finite-pair-v1')


def compile_readout_group(state, gates, *, decision=0, translation_um=-300., aod_id='AOD_0'):
    """Move actual carriers to MZ; read/reset there; return their holders."""
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
    p = _builder(state, (*gates, *resets), decision)
    _empty_reposition(p, origin, aod_id)
    p.add(K.AOD_LOAD, '装载各码块的对应测量载体', bindings=bindings, aod_id=aod_id)
    target = Position2D(origin.x_um, origin.y_um + translation_um)
    # This MZ visit holds the carriers in stationary AOD; it does not offload
    # them into an invented measurement holder or skip native RESETs.
    points = _outbound(p, origin, target, bindings, aligned=False, aod_id=aod_id)
    p.add(K.MEASUREMENT if gates[0].gate_type == 'MEASURE' else K.RESET,
        '在实际 MZ 内执行原生读出/复位', gate_ids=tuple(g.id for g in gates), aod_id=aod_id)
    if resets:
        p.add(K.RESET, '同次 MZ 访问实际复位读出的辅助载体', gate_ids=tuple(g.id for g in resets), aod_id=aod_id)
    _return(p, points, bindings, aod_id)
    return p.finish('parallel-patch-mz-return-v1'), tuple(resets)


def compile_dual_reset_prologue(state, algorithm_gates, magic_gates):
    """Two real concurrent transport lanes, one shared native RESET pulse.

    Separate RESET operations would contend for the global readout resource.
    Both arrays therefore arrive in MZ before one combined pulse, then return
    concurrently. Each lane retains Cartesian capture closure and its own IDs.
    """
    from neutral_atom_env.domain.operations import OperationInterval
    from neutral_atom_env.program.scheduled import build_scheduled_program
    lanes = []
    for aod_id, gates in (('AOD_0', algorithm_gates), ('AOD_MAGIC', magic_gates)):
        plan, resets = compile_readout_group(state, gates, decision=0, aod_id=aod_id)
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


def run_parallel_patch(env, *, atom_roles, on_event=None, on_plan=None,
                       max_decisions=512, wall_budget_s=1800.):
    """Run the caller's supported DAG; return structured failure evidence."""
    env = as_environment(env)
    started = perf_counter()
    log = []
    phase = 'initialization'
    try:
        if env.state.quantum_state is None:
            raise ValidationError('PARALLEL_PATCH_QUANTUM', 'Enable tracked Clifford state before physical execution')
        if env.state.hardware.backend != 'rigid':
            raise ValidationError('PARALLEL_PATCH_BACKEND', 'This bounded translation compiler requires rigid axes')
        if 'AOD_MAGIC' in env.state.aods:
            ready = env.state.dag.ready_gates()
            magic = tuple(g for g in ready if g.gate_type == 'RESET' and atom_roles[g.qubit_ids[0]]['aod_id'] == 'AOD_MAGIC')
            algorithm = tuple(g for g in ready if g.gate_type == 'RESET' and atom_roles[g.qubit_ids[0]]['aod_id'] == 'AOD_0'
                and atom_roles[g.qubit_ids[0]]['role'].split('.')[-1] == 'd0')
            if not magic or not algorithm:
                raise ValidationError('PARALLEL_PATCH_DUAL_PREFIX', 'Both actual source RESET arrays are required at the initial dual-lane boundary')
            tick = perf_counter()
            phase = 'dual_reset_prologue'
            plan = compile_dual_reset_prologue(env.state, algorithm, magic)
            entry = {'decision': 0, 'kind': 'RESET', 'gate_ids': [g.id for g in (*algorithm, *magic)],
                'batch_size': len(algorithm) + len(magic), 'start_us': env.state.time_us,
                'duration_us': plan.estimated_duration_us, 'compile_wall_seconds': perf_counter() - tick,
                'plan_id': plan.id, 'actual_concurrent_aods': ['AOD_0', 'AOD_MAGIC']}
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
                    plan = compile_cz_group(state, gates, decision=len(log))
                    extra = {}
                else:
                    plan, resets = compile_readout_group(state, gates, decision=len(log))
                    extra = {'included_reset_gate_ids': [g.id for g in resets]}
            entry = {'decision': len(log), 'kind': phase, 'gate_ids': [g.id for g in gates],
                'batch_size': len(gates), 'start_us': state.time_us,
                'duration_us': plan.estimated_duration_us, 'compile_wall_seconds': perf_counter() - tick,
                'plan_id': plan.id, **extra}
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
        return M4Result('stalled', (diagnostic,), (), len(log), tuple(log))
