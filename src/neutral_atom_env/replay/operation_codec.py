from neutral_atom_env.domain.operations import (CompiledPlan, ExecuteGateBatchIntent, EndDisposition,
    CaptureBinding, Operation, OperationType, HardwareConfig, PlanRuntime)
from neutral_atom_env.domain.models import (Position2D, MobileCellIndex, HolderRef, HolderType, SimulationEvent, EventType)


from neutral_atom_env.domain.aod import AODConfiguration


def holder(value):
    return HolderRef(HolderType(value['holder_type']), MobileCellIndex(**value['holder_id'])
        if value['holder_type']=='mobile' else value['holder_id'])


def plan_from_dict(value):
    intent=ExecuteGateBatchIntent(frozenset(value['intent']['gate_ids']),EndDisposition(value['intent']['end_disposition']))
    bindings=tuple(CaptureBinding(b['atom_id'],MobileCellIndex(**b['cell']),b['static_trap_id']) for b in value['bindings'])
    operations=tuple(Operation(o['id'],OperationType(o['operation_type']),o['label'],o['duration_us'],
        Position2D(**o['target_pose']) if o['target_pose'] else None,
        AODConfiguration(**o['target_configuration']) if o['target_configuration'] else None,o['transfer_phase'],
        tuple(CaptureBinding(b['atom_id'],MobileCellIndex(**b['cell']),b['static_trap_id']) for b in o['transfer_bindings'])) for o in value['operations'])
    return CompiledPlan(value['id'],value['state_version'],value['state_fingerprint'],intent,bindings,
        frozenset(value['requested_atom_ids']),frozenset(value['incidental_atom_ids']),operations,tuple(value['resources']),
        value['estimated_duration_us'],value['estimated_distance_um'],
        tuple((key,holder(h)) for key,h in value['predicted_placement']),
        AODConfiguration(**value['initial_aod_configuration']) if value['initial_aod_configuration'] else None,value['planner_id'])


def event_from_dict(value):
    return SimulationEvent(value['time_us'],EventType(value['event_type']),value['gate_id'],
        value['plan_id'],value['operation_id'],plan_from_dict(value['plan']) if value['plan'] else None)


def hardware_from_dict(value):
    return HardwareConfig(**(value|{'interaction_offset':Position2D(**value['interaction_offset']), 'mobile_pair_center':Position2D(**value['mobile_pair_center'])}))


def runtime_from_dict(value):
    return PlanRuntime(plan_from_dict(value['plan']),value['started_us'],value['operation_index'],value['operation_started_us']) if value else None
