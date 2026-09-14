"""Independent audits for serial target tasks, including gateless programs."""
import json
from dataclasses import replace
from neutral_atom_env.domain.models import HolderType, GateStatus
from neutral_atom_env.domain.operations import TaskIntent, OperationInterval, OperationType as K
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.replay.serializer import canonical_json
from .validation import require


EFFECTS = {K.RAMAN_ROTATION, K.ENTANGLING_PULSE,K.MEASUREMENT,K.RESET}


def requested_atoms(intent, state):
    if isinstance(intent, TaskIntent):
        return intent.atom_ids | frozenset(q for g in intent.gate_ids for q in state.dag.nodes[g].gate.qubit_ids)
    return frozenset(state.dag.nodes[next(iter(intent.gate_ids))].gate.qubit_ids)


def validate_target(target, state):
    require(all(state.placement.atom_to_holder.get(q) == h for q, h in target.holders),
            'Task terminal holder requirement not satisfied')
    require(target.aod_configuration is None or state.aod.configuration() == target.aod_configuration,
            'Task terminal AOD configuration not satisfied')
    require(target.traps is None or trap_state(state) == target.traps, 'Task terminal supports not satisfied')
    require(state.transfer is None and not state.aod.is_moving, 'Task terminal state must be stable')


def validate_task_origin(plan, state, restoring):
    intent = plan.intent
    require(isinstance(intent, TaskIntent) and plan.initial_placement is not None, 'Task needs explicit origin')
    require(intent.atom_ids <= state.atoms.keys(), 'Task references unknown atom')
    require(all(q in state.atoms for q, _ in intent.target.holders), 'Unknown target atom')
    require(intent.related_gate_id is None or intent.related_gate_id in state.dag.nodes, 'Unknown related gate')
    require(all(g in state.dag.nodes for g in intent.gate_ids), 'Unknown effect gate')
    require(bool(intent.target.holders) or intent.target.aod_configuration is not None
            or intent.target.traps is not None or bool(intent.gate_ids), 'Task needs a target or effect')
    if intent.allowed_atom_ids is not None:
        require(intent.allowed_atom_ids <= state.atoms.keys(), 'Unknown allowed atom')
    if intent.allowed_site_ids is not None:
        require(intent.allowed_site_ids <= state.world.traps.keys(), 'Unknown allowed site')
    origin = origin_dag(plan, state)
    require(all(origin.nodes[g].status == GateStatus.READY for g in intent.gate_ids), 'Effect gate was not READY')
    if not restoring:
        require(plan.initial_dag == canonical_json(state.dag.nodes), 'Task origin DAG mismatch')
        for record in state.trace.records:
            event = json.loads(record)['event']
            if event['event_type'] == 'plan_started':
                old = event['plan']['intent']
                require(old.get('task_id') != intent.task_id, 'Task ID already executed')


def origin_dag(plan, state):
    from neutral_atom_env.circuit import DynamicGateDAG
    require(isinstance(plan.initial_dag, str), 'Task requires origin DAG')
    data = json.loads(plan.initial_dag)
    result = DynamicGateDAG.restored(state.dag.circuit, data)
    require(canonical_json(result.nodes) == plan.initial_dag, 'Invalid task origin DAG')
    return result


def operation_demand(state, op, gate_id):
    """Derive affected atoms/resources from actual holders and operation, not intent."""
    kind = op.operation_type
    atoms = {b.atom_id for b in op.transfer_bindings}
    sites = {b.static_trap_id for b in op.transfer_bindings}
    resources = set()
    if kind in {K.MEASUREMENT,K.RESET}:
        atoms.update(q for gid in op.effect_gate_ids for q in state.dag.nodes[gid].gate.qubit_ids)
        resources.update(('AOD_0','READOUT_0' if kind==K.MEASUREMENT else 'RESET_0'))
    elif kind == K.RAMAN_ROTATION:
        from neutral_atom_env.simulation.quantum_effects import condition_applies
        for gid in op.effect_gate_ids or (gate_id,):
            gate=state.dag.nodes[gid].gate
            targets=set(gate.qubit_ids);atoms.update(targets)
            applied=condition_applies(state,gate)
            resources.update(('RAMAN:' if applied else 'CONTROL:')+q for q in targets)
            if applied and any(state.placement.atom_to_holder[q].holder_type==HolderType.MOBILE for q in targets):
                # One batch holds transport once for all its lit mobile targets.
                resources.add('AOD_0')
    else:
        resources.add('AOD_0')
        atoms.update(state.placement.mobile_occupancy.values())
        if kind == K.ENTANGLING_PULSE:
            resources.update(('ENTANGLING_LASER_0', state.hardware.interaction_slot_id))
            atoms.update(q for gid in (op.effect_gate_ids or (gate_id,)) for q in state.dag.nodes[gid].gate.qubit_ids)
        if kind == K.TRAP_SWITCH:
            sites.update(k for k, v in op.switch_state.slm if state.slm_enabled[k] != v)
            atoms.update(state.placement.static_occupancy[k] for k in sites if k in state.placement.static_occupancy)
    sites.update(state.placement.atom_to_holder[q].holder_id for q in atoms
                 if state.placement.atom_to_holder[q].holder_type == HolderType.STATIC)
    resources.update('atom:' + q for q in atoms)
    resources.update('trap:' + s for s in sites)
    return tuple(sorted(resources)), tuple(sorted(atoms)), sites


def task_intervals(plan, state):
    from .program import apply_operation
    work = state
    result = []
    time = 0.
    for i, op in enumerate(plan.operations):
        require(op.depends_on == ((plan.operations[i-1].id,) if i else ()),
                'Serial task dependencies must form the declared operation chain')
        effect = op.operation_type in EFFECTS
        require(not op.gate_ids,'Batch CZ requires a scheduled program')
        require(op.gate_id == (plan.intent.effect_gate_id if effect else None),
                'Only the actual effect operation may reference its gate')
        resources, atoms, sites = operation_demand(work, op, op.gate_id)
        allowed = plan.intent.allowed_atom_ids
        require(allowed is None or set(atoms) <= allowed, 'Task affects a forbidden atom')
        allowed_sites = plan.intent.allowed_site_ids
        require(allowed_sites is None or sites <= allowed_sites, 'Task uses a forbidden SLM site')
        result.append(OperationInterval(op.id, time, time + op.duration_us, resources, atoms))
        time += op.duration_us
        work = apply_operation(work, op, op.gate_id)
    require(plan.intent.max_duration_us is None or time <= plan.intent.max_duration_us,
            'Task duration budget exceeded')
    return tuple(result)


def validate_task_dag(plan, state, status=None):
    """Gateless tasks leave the entire DAG intact, including independent gates."""
    expected = origin_dag(plan, state)
    gate = plan.intent.effect_gate_id
    if gate and status is not None:
        for target in (GateStatus.RESERVED, GateStatus.RUNNING, GateStatus.COMPLETED):
            expected = expected.transitioned(gate, target)
            if target == status:
                break
    require(canonical_json(expected.nodes) == canonical_json(state.dag.nodes), 'Task changed unexpected DAG state')
