"""Strategy-independent physical program validation and read-only construction.

Transfers declare their actual source/destination on each operation. No prescribed
load count, transport order, EZ residency duration, or inverse-path template.
"""
from dataclasses import replace
from math import isclose, isfinite
from neutral_atom_env.domain.models import HolderType, GateStatus
from neutral_atom_env.domain.operations import OperationType as K, Operation, CompiledPlan, EndDisposition, TaskIntent
from neutral_atom_env.domain.aod import motion_target
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.program.validation import require, plan_resources


def predict_cz_completion(state, gate_id):
    """Pure effect prediction: subsequent geometry sees the next CZ partner.

    This changes only the private DAG view, never clocks, metrics or live state.
    Executor still owns the actual effect event and exactly-once commitment.
    """
    return predict_cz_batch_completion(state,(gate_id,))


def predict_cz_batch_completion(state,gate_ids):
    require(all(state.dag.nodes[g].gate.gate_type=='CZ' for g in gate_ids),'CZ prediction requires CZ gates')
    return predict_effect_completion(state,gate_ids)


def predict_effect_completion(state,gate_ids):
    dag=state.dag
    require(all(dag.nodes[g].status in {GateStatus.READY,GateStatus.RESERVED,GateStatus.RUNNING} for g in gate_ids),
            'Predicted CZ effect is blocked or already completed')
    for gate_id in gate_ids:
        if dag.nodes[gate_id].status==GateStatus.READY:dag=dag.transitioned(gate_id,GateStatus.RESERVED)
        if dag.nodes[gate_id].status==GateStatus.RESERVED:dag=dag.transitioned(gate_id,GateStatus.RUNNING)
        dag=dag.transitioned(gate_id,GateStatus.COMPLETED)
    return replace(state,dag=dag)


def apply_operation(state, op, gate_id):
    if op.operation_type == K.RAMAN_ROTATION:
        from neutral_atom_env.hardware.raman import validate_rotation_batch
        gate_ids=op.effect_gate_ids or (gate_id,)
        validate_rotation_batch(state, gate_ids)
        if state.quantum_state is not None or op.gate_ids:
            from neutral_atom_env.simulation.quantum_effects import complete_effects
            work,_=complete_effects(state,op if op.effect_gate_ids else replace(op,gate_id=gate_id))
            return predict_effect_completion(work,gate_ids)
        return state
    if op.operation_type in {K.MEASUREMENT,K.RESET}:
        from neutral_atom_env.hardware.readout import validate_readout
        from neutral_atom_env.simulation.quantum_effects import complete_effects
        validate_readout(state,op.effect_gate_ids,op.operation_type)
        work,_=complete_effects(state,op)
        return predict_effect_completion(work,op.effect_gate_ids)
    backend = get_backend(state.hardware)
    if op.operation_type == K.TRAP_SWITCH:
        from neutral_atom_env.hardware.dynamic_traps import switch_traps
        return switch_traps(state, op.switch_state)
    if op.operation_type == K.AOD_MOVE:
        return backend.move(state, motion_target(op), transfer=op.transfer_phase, bindings=op.transfer_bindings)
    if op.operation_type == K.AOD_LOAD:
        return backend.load(state, op.transfer_bindings)
    if op.operation_type == K.AOD_OFFLOAD:
        return backend.offload(state, op.transfer_bindings)
    if op.operation_type == K.AOD_PARK:
        return backend.park(state, op.transfer_bindings)
    if op.operation_type == K.AOD_RECAPTURE:
        return backend.recapture(state, op.transfer_bindings)
    require(op.operation_type == K.ENTANGLING_PULSE, 'Unknown program operation')
    gate_ids=op.effect_gate_ids or (gate_id,)
    backend.validate_pulse_batch(state, gate_ids)
    if state.quantum_state is not None:
        from neutral_atom_env.simulation.quantum_effects import complete_effects
        state,_=complete_effects(state,op if op.effect_gate_ids else replace(op,gate_id=gate_id))
    return predict_cz_batch_completion(state, gate_ids)


def operation_duration(state, kind, target=None):
    if kind == K.AOD_MOVE:
        return get_backend(state.hardware).move_duration(state.aod, target, state.hardware)
    return {K.MEASUREMENT:state.hardware.measurement_duration_us,K.RESET:state.hardware.reset_duration_us,
            K.RAMAN_ROTATION: state.hardware.raman_duration_us, K.TRAP_SWITCH: state.hardware.switch_duration_us, K.AOD_LOAD: state.hardware.load_duration_us, K.AOD_RECAPTURE: state.hardware.load_duration_us,
            K.AOD_OFFLOAD: state.hardware.offload_duration_us, K.AOD_PARK: state.hardware.offload_duration_us,
            K.ENTANGLING_PULSE: state.hardware.pulse_duration_us}[kind]


def replay_program(plan, state):
    task = isinstance(plan.intent, TaskIntent)
    require(len(plan.intent.gate_ids) <= 1 and (task or len(plan.intent.gate_ids) == 1), 'Program supports at most one gate effect')
    gate_id = next(iter(plan.intent.gate_ids), None)
    gate = state.dag.nodes[gate_id].gate if gate_id else None
    effect = (K.ENTANGLING_PULSE if gate.gate_type == 'CZ' else K.RAMAN_ROTATION) if gate else None
    require(gate is None or gate.gate_type == 'CZ' or gate.u_parameters is not None, 'Unsupported physical gate')
    require(plan.initial_placement == tuple(sorted(state.placement.atom_to_holder.items())), 'Program origin mismatch')
    operations = plan.operations
    require(bool(operations) and sum(o.operation_type == effect for o in operations) == int(gate is not None)
            and all(o.operation_type not in {K.ENTANGLING_PULSE, K.RAMAN_ROTATION} or o.operation_type == effect for o in operations),
            'A task must realize exactly its declared gate effects')
    transfers = {K.AOD_LOAD, K.AOD_OFFLOAD, K.AOD_PARK, K.AOD_RECAPTURE}
    loads = {K.AOD_LOAD, K.AOD_RECAPTURE}
    unloads = {K.AOD_OFFLOAD, K.AOD_PARK}
    work = state
    travel = 0.
    first_capture = {}
    for i, op in enumerate(operations):
        require(op.id == f'op{i:02d}' and isfinite(op.duration_us) and op.duration_us > 0, 'Invalid operation identity/duration')
        kind, target = op.operation_type, motion_target(op)
        bindings = op.transfer_bindings
        require((kind == K.TRAP_SWITCH) == (op.switch_state is not None), 'Switch target belongs only to a switch operation')
        if kind in transfers:
            require(bool(bindings) and len({b.atom_id for b in bindings}) == len(bindings)
                    and len({b.cell for b in bindings}) == len(bindings)
                    and len({b.static_trap_id for b in bindings}) == len(bindings), 'Invalid operation transfer set')
            require(target is None and op.transfer_phase is None, 'Transfer contains motion fields')
            if kind in loads:
                for b in bindings:
                    first_capture.setdefault(b.atom_id, b)
        elif kind == K.AOD_MOVE:
            require((op.target_pose is None) != (op.target_configuration is None), 'Move needs exactly one target')
            require(op.transfer_phase in (None, 'depart', 'approach'), 'Invalid transfer phase')
            if op.transfer_phase:
                neighbor = operations[i-1] if op.transfer_phase == 'depart' and i else (
                    operations[i+1] if op.transfer_phase == 'approach' and i+1 < len(operations) else None)
                require(neighbor is not None and neighbor.operation_type in (loads if op.transfer_phase == 'depart' else unloads)
                        and bindings == neighbor.transfer_bindings, 'Exemption must match an adjacent actual transfer')
            else:
                require(not bindings, 'Unscoped transfer exemption')
            travel += get_backend(work.hardware).move_distance(work.aod, target)
        elif kind == K.TRAP_SWITCH:
            require(target is None and op.transfer_phase is None and not bindings, 'Invalid switch fields')
        else:
            require(kind == effect and target is None and op.transfer_phase is None and not bindings,
                    'Invalid pulse fields')
        duration = operation_duration(work, kind, target)
        require(isclose(duration, op.duration_us, rel_tol=0, abs_tol=1e-9), 'Operation hardware timing mismatch')
        work = apply_operation(work, op, gate_id)
    require(plan.bindings == tuple(first_capture[k] for k in sorted(first_capture)), 'Capture metadata must match actual first loads')
    if task:
        from neutral_atom_env.program.task_validation import validate_target
        validate_target(plan.intent.target, work)
    elif plan.intent.end_disposition == EndDisposition.RETURN_AND_OFFLOAD:
        require(work.placement == state.placement and work.aod.configuration() == state.aod.configuration(),
                'Requested return must restore origin')
    elif plan.intent.end_disposition == EndDisposition.KEEP_LOADED:
        require(bool(work.placement.mobile_occupancy), 'KEEP_LOADED must leave a loaded atom')
    else:
        require(False, 'Unsupported end disposition')
    return work, travel


class ProgramBuilder:
    """Predict operations without mutating the live state; finalize audits independently."""
    def __init__(self, state, intent):
        self.origin = state
        self.state = state
        self.intent = (replace(intent,phase='program',effect_gate_id=None,gate_effects=intent.gate_ids)
                       if state.quantum_state is not None and isinstance(intent,TaskIntent) and intent.phase!='program' else intent)
        self.operations = []
        self.bindings = {}
        self.distance = 0.

    def add(self, kind, label, *, target=None, bindings=(), phase=None, switch_state=None, configuration=None, gate_id=None, gate_ids=()):
        task = isinstance(self.intent, TaskIntent)
        gate_ids=tuple(gate_ids)
        gate_id = gate_id or (next(iter(self.intent.gate_ids)) if len(self.intent.gate_ids)==1 and not gate_ids else None)
        if kind in {K.ENTANGLING_PULSE, K.RAMAN_ROTATION,K.MEASUREMENT,K.RESET}:
            require(bool(gate_ids) or gate_id is not None, 'Gateless task cannot contain a pulse')
            require(set(gate_ids or (gate_id,))<=self.intent.gate_ids,'Unauthorized program effect')
        op = Operation(f'op{len(self.operations):02d}', kind, label,
                       operation_duration(self.state, kind, configuration or target), target_pose=target,
                       target_configuration=configuration, transfer_phase=phase, transfer_bindings=tuple(bindings), switch_state=switch_state,
                       gate_id=gate_id if task and kind in {K.ENTANGLING_PULSE, K.RAMAN_ROTATION,K.MEASUREMENT,K.RESET} else None,
                       depends_on=(self.operations[-1].id,) if task and self.operations else (),gate_ids=gate_ids)
        next_state = apply_operation(self.state, op, gate_id)
        if kind == K.AOD_MOVE:
            self.distance += get_backend(self.state.hardware).move_distance(self.state.aod, configuration or target)
        if kind in (K.AOD_LOAD, K.AOD_RECAPTURE):
            for b in bindings:
                self.bindings.setdefault(b.atom_id, b)
        self.operations.append(op)
        self.state = next_state

    def finish(self, strategy_id):
        from neutral_atom_env.program.binding import fingerprint, exact_validate
        state = self.origin
        from neutral_atom_env.hardware.dynamic_traps import trap_state
        from neutral_atom_env.program.task_validation import requested_atoms, task_intervals
        from neutral_atom_env.replay.serializer import canonical_json
        requested = requested_atoms(self.intent, state)
        bindings = tuple(self.bindings[k] for k in sorted(self.bindings))
        digest = fingerprint(state)
        plan = CompiledPlan('plan_'+digest[:12], state.version, digest, self.intent, bindings, requested,
                            frozenset(self.bindings)-requested, tuple(self.operations),
                            plan_resources(state, requested, bindings, self.operations),
                            sum(o.duration_us for o in self.operations), self.distance,
                            tuple(sorted(self.state.placement.atom_to_holder.items())), state.aod.configuration(),
                            strategy_id, tuple(sorted(state.placement.atom_to_holder.items())),
                            trap_state(state), trap_state(self.state))
        if isinstance(self.intent, TaskIntent):
            from hashlib import sha256
            plan = replace(plan, id='plan_' + sha256((self.intent.task_id + digest).encode()).hexdigest()[:20],
                           initial_dag=canonical_json(state.dag.nodes))
            if self.intent.phase=='program':
                from neutral_atom_env.domain.operations import OperationInterval
                from neutral_atom_env.simulation.operation_program import audit
                time=0.;intervals=[]
                for op in self.operations:
                    intervals.append(OperationInterval(op.id,time,time+op.duration_us,(),()))
                    time+=op.duration_us
                plan=replace(plan,execution_mode='scheduled',initial_time_us=state.time_us,initial_metrics=state.physical_metrics,
                             operation_intervals=tuple(intervals),initial_atoms=tuple(sorted(state.atoms.items())),
                             initial_quantum_state=canonical_json(state.quantum_state.to_dict()) if state.quantum_state is not None else None,
                             initial_measurement_results=tuple(sorted(state.measurement_results.items())),initial_rng_state=state.rng_state)
                final,intervals,actual_bindings,travel=audit(plan,state,metadata=False)
                affected=frozenset(q for i in intervals for q in i.atom_ids)
                # Event completion must use the exact interval endpoint. Python
                # float sum and incremental interval accumulation can differ by
                # an ULP, placing PLAN_COMPLETED before the final operation.
                plan=replace(plan,operation_intervals=intervals,bindings=actual_bindings,estimated_distance_um=travel,
                    estimated_duration_us=max(i.end_us for i in intervals),
                    incidental_atom_ids=affected-requested,resources=tuple(sorted({r for i in intervals for r in i.resources})),
                    predicted_placement=tuple(sorted(final.placement.atom_to_holder.items())),predicted_traps=trap_state(final))
                exact_validate(plan,state)
                return plan
            intervals = task_intervals(plan, state)
            affected = frozenset(q for interval in intervals for q in interval.atom_ids)
            plan = replace(plan, operation_intervals=intervals, incidental_atom_ids=affected-requested,
                           resources=tuple(sorted({r for interval in intervals for r in interval.resources})))
        exact_validate(plan, state)
        return plan
