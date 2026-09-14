from neutral_atom_env.domain.operations import CompiledPlan, ExecuteGateBatchIntent, EndDisposition, CaptureBinding, Operation, OperationType, HardwareConfig, PlanRuntime, TrapState, TransferRuntime, TaskIntent, TaskTarget, OperationInterval, PhysicalMetrics
from neutral_atom_env.domain.models import Position2D, MobileCellIndex, HolderRef, HolderType, SimulationEvent, EventType, Atom


from neutral_atom_env.domain.aod import AODConfiguration


def holder(value):
    return HolderRef(HolderType(value['holder_type']), MobileCellIndex(**value['holder_id'])
        if value['holder_type']=='mobile' else value['holder_id'])


def traps_from_dict(value):
    return TrapState(**value) if value is not None else None


def transfer_from_dict(value):
    return TransferRuntime(OperationType(value['kind']),
        tuple(CaptureBinding(b['atom_id'],MobileCellIndex(**b['cell']),b['static_trap_id']) for b in value['bindings']),
        traps_from_dict(value['source_traps']),traps_from_dict(value['target_traps']),value['stage']) if value is not None else None


def plan_from_dict(value):
    def tuple_tree(v):return tuple(tuple_tree(x) for x in v) if isinstance(v,(list,tuple)) else v
    data=value['intent']
    if 'task_id' in data:
        target=data['target']
        intent=TaskIntent(**(data|{'target':TaskTarget(tuple((q,holder(h)) for q,h in target['holders']),
            AODConfiguration(**target['aod_configuration']) if target['aod_configuration'] else None,
            traps_from_dict(target['traps']))}))
    else:
        intent=ExecuteGateBatchIntent(frozenset(data['gate_ids']),EndDisposition(data['end_disposition']))
    bindings=tuple(CaptureBinding(b['atom_id'],MobileCellIndex(**b['cell']),b['static_trap_id']) for b in value['bindings'])
    operations=tuple(Operation(o['id'],OperationType(o['operation_type']),o['label'],o['duration_us'],
        Position2D(**o['target_pose']) if o['target_pose'] else None,
        AODConfiguration(**o['target_configuration']) if o['target_configuration'] else None,o['transfer_phase'],
        tuple(CaptureBinding(b['atom_id'],MobileCellIndex(**b['cell']),b['static_trap_id']) for b in o['transfer_bindings']),
        traps_from_dict(o['switch_state']),o['gate_id'],tuple(o['depends_on']),o['task_phase'],tuple(o.get('gate_ids',()))) for o in value['operations'])
    return CompiledPlan(value['id'],value['state_version'],value['state_fingerprint'],intent,bindings,
        frozenset(value['requested_atom_ids']),frozenset(value['incidental_atom_ids']),operations,tuple(value['resources']),
        value['estimated_duration_us'],value['estimated_distance_um'],
        tuple((key,holder(h)) for key,h in value['predicted_placement']),
        AODConfiguration(**value['initial_aod_configuration']) if value['initial_aod_configuration'] else None,value['planner_id'],
        tuple((key,holder(h)) for key,h in value['initial_placement']) if value['initial_placement'] is not None else None,
        traps_from_dict(value['initial_traps']),traps_from_dict(value['predicted_traps']),
        tuple(OperationInterval(**i) for i in value['operation_intervals']),value['initial_dag'],value['execution_mode'],
        value['initial_time_us'],PhysicalMetrics(**value['initial_metrics']) if value['initial_metrics'] is not None else None,
        tuple((q,Atom(**a)) for q,a in value['initial_atoms']) if value.get('initial_atoms') is not None else None,
        value.get('initial_quantum_state'),tuple(tuple(p) for p in value.get('initial_measurement_results',())),
        tuple_tree(value.get('initial_rng_state')))


def event_from_dict(value):
    return SimulationEvent(value['time_us'],EventType(value['event_type']),value['gate_id'],
        value['plan_id'],value['operation_id'],plan_from_dict(value['plan']) if value['plan'] else None)


def hardware_from_dict(value):
    return HardwareConfig(**(value|{'interaction_offset':Position2D(**value['interaction_offset']), 'mobile_pair_center':Position2D(**value['mobile_pair_center'])}))


def runtime_from_dict(value):
    return PlanRuntime(plan_from_dict(value['plan']),value['started_us'],value['operation_index'],value['operation_started_us'],
                       tuple(value['completed_operation_ids']),tuple(tuple(p) for p in value['running_operations'])) if value else None
