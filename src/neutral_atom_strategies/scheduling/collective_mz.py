"""Collect addressed carriers on declared MZ SLM, then apply one service pulse.

This is the rigid ENV prefix compatibility strategy. Transport capacity limits
capture waves, not the stable SLM service cohort. All motion and handoffs are
ordinary ProgramBuilder operations, independently audited before submission.
"""
from collections import defaultdict
from itertools import combinations
from math import hypot

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus, HolderType, Position2D, ZoneType
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.hardware.multi_aod import backend_for, device, occupancy
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.validated_rigid import STANDARD_ROUTING, append_rigid_route
from .parallel_patch import _bindings, _empty_reposition


def _closed_capture(state, atoms, origin, bindings, aod_id):
    """Include every occupied crossing and every nearby static spectator."""
    aod = device(state, aod_id)
    axes = aod.configuration()
    xs = tuple(origin.x_um + axes.x_um[i] - aod.pose.x_um
               for i in {b.cell.column for b in bindings})
    ys = tuple(origin.y_um + axes.y_um[i] - aod.pose.y_um
               for i in {b.cell.row for b in bindings})
    captured = set()
    for q, holder in state.placement.atom_to_holder.items():
        if holder.holder_type != HolderType.STATIC:
            continue
        point = state.world.traps[holder.holder_id].position
        distance = hypot(min(abs(point.x_um - x) for x in xs),
                         min(abs(point.y_um - y) for y in ys))
        if distance <= state.hardware.alignment_tolerance_um:
            captured.add(q)
        elif distance + 1e-9 < state.hardware.minimum_clearance_um:
            return False
    return captured == set(atoms)


def _wave_candidates(state, pending, atom_roles):
    """Bounded complete local-role bundles, with independent device identity.

    At most nine data or eight ancillary classes are enumerated in the patch
    profile. A bundle contains all pending copies of a role; capacity never
    splits its identity or replaces the Cartesian closure check.
    """
    classes = defaultdict(lambda: defaultdict(list))
    devices = defaultdict(list)
    for index, q in enumerate(pending):
        role = atom_roles.get(q, {})
        aod_id = role.get('aod_id', 'AOD_0')
        family = role.get('kind', 'service')
        local = role.get('role', q).rsplit('.', 1)[-1]
        classes[(aod_id, family)][local].append(index)
        devices[aod_id].append(index)
    # The resource array's whole 17-carrier capture is physically distinct
    # from its data/ancillary subfamilies: all fixed spare axes must remain in
    # its narrow envelope. Try each complete device frontier without an
    # exponential enumeration across the two families.
    candidates = [(tuple(indices), aod_id) for aod_id, indices in devices.items()]
    for (aod_id, _), bundles in classes.items():
        if len(bundles) > 9:
            raise ValidationError('COLLECTIVE_MZ_SCOPE',
                                  'A service family exceeds the bounded nine local-role classes')
        values = tuple(bundles.values())
        for count in range(1, len(values) + 1):
            for subset in combinations(values, count):
                indices = tuple(sorted(i for bundle in subset for i in bundle))
                candidates.append((indices, aod_id))
    candidates = sorted(set(candidates), key=lambda item: (-len(item[0]), item[0], item[1]))
    for indices, aod_id in candidates:
        atoms = tuple(pending[i] for i in indices)
        # This prefix profile has the existing 128-carrier transport limit.
        if len(atoms) > 128:
            continue
        try:
            aod = device(state, aod_id)
            if aod.is_moving or occupancy(state, aod_id):
                continue
            origin, bindings = _bindings(state, atoms, aod_id)
            backend_for(state, aod_id).validate_pose(state, origin)
        except ValidationError:
            continue
        if _closed_capture(state, atoms, origin, bindings, aod_id):
            yield atoms, aod_id, origin, bindings


def _successor_resets(state, gates):
    if gates[0].gate_type != 'MEASURE':
        return ()
    available = {g.id for g in gates} | {
        gid for gid, node in state.dag.nodes.items() if node.status == GateStatus.COMPLETED}
    children = {child for gate in gates for child in state.dag.nodes[gate.id].successors}
    measured = {gate.qubit_ids for gate in gates}
    result = []
    for candidate in state.dag.circuit.gates:
        if candidate.id not in children or candidate.gate_type != 'RESET' or candidate.qubit_ids not in measured:
            continue
        parents = {gid for gid, node in state.dag.nodes.items() if candidate.id in node.successors}
        if parents <= available:
            result.append(candidate)
    if len({g.qubit_ids for g in result}) != len(result):
        raise ValidationError('COLLECTIVE_MZ_RESET_IDENTITY', 'Multiple successor RESETs target one carrier')
    return tuple(result)


def _destinations(state, atoms):
    homes, targets = {}, {}
    for q in atoms:
        home = state.placement.atom_to_holder[q]
        if home.holder_type != HolderType.STATIC:
            raise ValidationError('COLLECTIVE_MZ_SOURCE', 'Collective service requires actual SLM sources', atom_ids=(q,))
        target = 'mz.' + home.holder_id
        trap = state.world.traps.get(target)
        if trap is None:
            raise ValidationError('COLLECTIVE_MZ_SLOT_UNDECLARED', 'Declare each MZ SLM destination before compilation', holder_id=target)
        if not any(z.zone_type == ZoneType.MEASUREMENT and z.bounds.contains(trap.position)
                   for z in state.world.zones):
            raise ValidationError('COLLECTIVE_MZ_SLOT_OUTSIDE', 'Declared target SLM is outside measurement zones', holder_id=target)
        if target in state.placement.static_occupancy:
            raise ValidationError('COLLECTIVE_MZ_SLOT_OCCUPIED', 'Declared MZ destination is occupied', holder_id=target)
        homes[q], targets[q] = home, target
    if len(set(targets.values())) != len(atoms):
        raise ValidationError('COLLECTIVE_MZ_SLOT_IDENTITY', 'Each carrier needs a distinct declared MZ slot')
    return homes, targets


def _transport(builder, atoms, aod_id, origin, source_bindings, destinations, direction, number):
    source_points = {b.atom_id: builder.state.world.traps[b.static_trap_id].position for b in source_bindings}
    target_points = {q: builder.state.world.traps[destinations[q]].position for q in atoms}
    first = atoms[0]
    dx = target_points[first].x_um - source_points[first].x_um
    dy = target_points[first].y_um - source_points[first].y_um
    tolerance = builder.state.hardware.alignment_tolerance_um
    if any(hypot(target_points[q].x_um - source_points[q].x_um - dx,
                 target_points[q].y_um - source_points[q].y_um - dy) > tolerance for q in atoms):
        raise ValidationError('COLLECTIVE_MZ_RIGID_TARGET', 'Declared destinations must preserve each capture wave footprint')
    target_origin = Position2D(origin.x_um + dx, origin.y_um + dy)
    target_bindings = tuple(CaptureBinding(b.atom_id, b.cell, destinations[b.atom_id]) for b in source_bindings)
    start_index = len(builder.operations)
    start_us = sum(op.duration_us for op in builder.operations)
    _empty_reposition(builder, origin, aod_id, routing_policy=STANDARD_ROUTING)
    builder.add(K.AOD_LOAD, '集合服务：装载实际 SLM 来源', bindings=source_bindings, aod_id=aod_id)
    route = append_rigid_route(builder, target_origin, aod_id=aod_id,
        depart=source_bindings, approach=target_bindings, label='集合服务：完整来源与目标交接路径')
    builder.add(K.AOD_OFFLOAD, '集合服务：卸载到声明的稳定 SLM', bindings=target_bindings, aod_id=aod_id)
    return {'wave': number, 'direction': direction, 'aod_id': aod_id, 'atom_ids': list(atoms),
        'source_traps': {b.atom_id: b.static_trap_id for b in source_bindings},
        'target_traps': {q: destinations[q] for q in atoms},
        'source_positions_um': {q: [p.x_um, p.y_um] for q, p in source_points.items()},
        'target_positions_um': {q: [p.x_um, p.y_um] for q, p in target_points.items()},
        'capture_cells': {b.atom_id: [b.cell.row, b.cell.column, b.cell.aod_id] for b in source_bindings},
        'source_origin_um': [origin.x_um, origin.y_um],
        'target_origin_um': [target_origin.x_um, target_origin.y_um],
        'loaded_route_um': [[p.x_um, p.y_um] for p in route.points],
        'route_scope': route.optimality_scope,
        'operation_ids': [op.id for op in builder.operations[start_index:]],
        'start_us': start_us, 'end_us': sum(op.duration_us for op in builder.operations)}


def _collect_or_return(builder, atoms, atom_roles, destinations, direction):
    pending, waves = tuple(atoms), []
    while pending:
        # A candidate is validated on a fresh private builder. A physical
        # refusal leaves the accumulated plan intact and allows another
        # bounded capture bundle, rather than weakening the backend checks.
        rejections, selected = [], None
        for cohort, aod_id, origin, bindings in _wave_candidates(builder.state, pending, atom_roles):
            trial = ProgramBuilder(builder.state, builder.intent)
            try:
                item = _transport(trial, cohort, aod_id, origin, bindings, destinations, direction, len(waves))
            except ValidationError as error:
                rejections.append({'atom_ids': list(cohort), 'aod_id': aod_id, 'code': error.violation.code})
                continue
            # Replay these already validated physical primitives in the main
            # builder to retain global IDs and the complete operation chain.
            begin = len(builder.operations)
            start = sum(op.duration_us for op in builder.operations)
            for op in trial.operations:
                builder.add(op.operation_type, op.label, target=op.target_pose,
                    configuration=op.target_configuration, bindings=op.transfer_bindings,
                    phase=op.transfer_phase, switch_state=op.switch_state, aod_id=op.aod_id)
            item.update(operation_ids=[op.id for op in builder.operations[begin:]], start_us=start,
                        end_us=sum(op.duration_us for op in builder.operations), rejected_candidates=rejections)
            waves.append(item)
            selected = set(cohort)
            break
        if selected is None:
            codes = ','.join(dict.fromkeys(r['code'] for r in rejections)) or 'no exact capture bundle'
            raise ValidationError('COLLECTIVE_MZ_NO_WAVE',
                                  f'No legal {direction} wave for remaining carriers ({codes})', atom_ids=pending)
        pending = tuple(q for q in pending if q not in selected)
    return waves


def compile_collective_mz(state, gates, atom_roles, *, decision=0, routing_policy=STANDARD_ROUTING):
    """Return ``(plan, included_resets, evidence)`` without changing live state.

    All supplied gates must be authored READY operations of one service kind.
    Every carrier reaches a real declared MZ SLM slot before the single batch
    pulse. Eligible authored successor RESETs run after the entire MEASURE
    batch, then every carrier is physically returned to its actual origin.
    """
    gates = tuple(gates)
    if routing_policy != STANDARD_ROUTING:
        raise ValueError('Collective MZ requires the validated standard rigid routing policy')
    if not gates or gates[0].gate_type not in {'MEASURE', 'RESET'} or any(g.gate_type != gates[0].gate_type for g in gates):
        raise ValueError('A nonempty same-type MEASURE/RESET frontier is required')
    if len({g.id for g in gates}) != len(gates) or len({g.qubit_ids[0] for g in gates}) != len(gates):
        raise ValueError('Service gates and carriers must have unique identities')
    for gate in gates:
        node = state.dag.nodes.get(gate.id)
        if node is None or node.gate != gate or node.status != GateStatus.READY:
            raise ValidationError('COLLECTIVE_MZ_FRONTIER', 'Service must preserve the authored READY frontier')
    atoms = tuple(g.qubit_ids[0] for g in gates)
    homes, targets = _destinations(state, atoms)
    resets = _successor_resets(state, gates)
    ids = frozenset(g.id for g in (*gates, *resets))
    intent = TaskIntent(f'collective-mz/{state.version}/{decision}',
        TaskTarget(holders=tuple(homes.items())), frozenset(atoms), phase='program', gate_effects=ids)
    builder = ProgramBuilder(state, intent)
    outward = _collect_or_return(builder, atoms, atom_roles, targets, 'collect')
    pulses = []
    for kind, effects in ((K.MEASUREMENT if gates[0].gate_type == 'MEASURE' else K.RESET, gates),
                          (K.RESET, resets)):
        if not effects:
            continue
        start = sum(op.duration_us for op in builder.operations)
        builder.add(kind, '全部目标已在稳定 MZ SLM 后的统一原生服务', gate_ids=tuple(g.id for g in effects))
        op = builder.operations[-1]
        pulses.append({'operation_id': op.id, 'kind': kind.value, 'gate_ids': list(op.effect_gate_ids),
            'atom_ids': [g.qubit_ids[0] for g in effects], 'support': 'declared_stable_slm',
            'start_us': start, 'end_us': start + op.duration_us})
    inward = _collect_or_return(builder, atoms, atom_roles,
                              {q: holder.holder_id for q, holder in homes.items()}, 'return')
    plan = builder.finish('collective-mz-slm-rigid-prefix-v1')
    evidence = {'schema': 'collective-mz-service/1', 'decision': decision, 'kind': gates[0].gate_type,
        'backend': 'rigid_env_prefix_compatibility', 'full_enola_kernel_claimed': False,
        'plan_id': plan.id, 'gate_ids': [g.id for g in gates],
        'included_reset_gate_ids': [g.id for g in resets],
        'measurement_report_ids': [g.id for g in gates if g.gate_type == 'MEASURE'],
        'atom_ids': list(atoms), 'target_traps': targets,
        'original_holder_ids': {q: h.holder_id for q, h in homes.items()},
        'transport_capacity': {key: a.rows * a.columns for key, a in state.aods.items()},
        'service_cohort_size': len(atoms), 'service_pulses': pulses,
        'collection_waves': outward, 'return_waves': inward,
        'transport_wave_count': len(outward) + len(inward),
        'transport_waves_are_not_service_batches': True,
        'routing_policy': routing_policy, 'physical_thresholds_changed': False,
        'actual_us': plan.estimated_duration_us, 'actual_distance_um': plan.estimated_distance_um}
    return plan, resets, evidence
