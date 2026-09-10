"""Explicit schema decoding; never pickle or execute checkpoint content."""
import json
from neutral_atom_env.domain.models import (Position2D, Rectangle, StaticTrap, GridCoord, Zone, ZoneType,
    Atom, HolderRef, HolderType, MobileCellIndex, PhysicalGate, SimulationEvent, EventType)
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.simulation.event_queue import EventQueue
from .trace import Trace
from .serializer import canonical_json
from .operation_codec import event_from_dict, hardware_from_dict, runtime_from_dict
from neutral_atom_env.domain.operations import ResourceReservation, PhysicalMetrics


def _tuple_tree(value):
    return tuple(_tuple_tree(v) for v in value) if isinstance(value, list) else value


def restore(snapshot):
    from neutral_atom_env.simulation.state import SimulationState
    def rect(value):
        return Rectangle(Position2D(**value['lower']), Position2D(**value['upper']))
    try:
        data = json.loads(snapshot)
        if data['schema_version'] != 8:
            raise ValueError('Only checkpoint schema 8 (explicit partial transfer bindings) is supported; regenerate older checkpoints')
        w = data['world']
        world = WorldState(rect(w['bounds']), {key: StaticTrap(t['id'], GridCoord(**t['grid']),
            Position2D(**t['position']), t['enabled']) for key,t in w['traps'].items()},
            tuple(Zone(z['id'],ZoneType(z['zone_type']),rect(z['bounds'])) for z in w['zones']),
            w['grid_spacing_um'], Position2D(**w['grid_origin']), tuple(ZoneType(t) for t in w['static_zone_types']))
        placement = PlacementState({key: HolderRef(HolderType(h['holder_type']),
            MobileCellIndex(**h['holder_id']) if h['holder_type']=='mobile' else h['holder_id'])
            for key,h in data['placement']['atom_to_holder'].items()})
        circuit = PhysicalCircuit(tuple(PhysicalGate(**g) for g in data['circuit']['gates']))
        dag = DynamicGateDAG.restored(circuit, data['dag'])
        aod = AODRuntimeState(**(data['aod'] | {'pose': Position2D(**data['aod']['pose'])}))
        pending = data['event_queue']
        queue = EventQueue(tuple((t,seq,event_from_dict(e))
                                for t,seq,e in pending['pending']),pending['next_sequence'])
        if any(t < data['time_us'] for t,_,_ in queue.entries):
            raise ValueError('Pending event precedes current time')
        trace = Trace(tuple(data['trace']))
        previous_time = 0
        for i,record in enumerate(trace.records):
            entry = json.loads(record)
            if entry['sequence'] != i or entry['state_version'] != i+1:
                raise ValueError('Trace sequence/version mismatch')
            event = entry['event']
            event_from_dict(event)
            if not previous_time <= event['time_us'] <= data['time_us']:
                raise ValueError('Trace time regression')
            previous_time = event['time_us']
        if len(trace.records) != data['version']:
            raise ValueError('Trace length/version mismatch')
        state = SimulationState(world,placement,{key: Atom(**a) for key,a in data['atoms'].items()},aod,dag,
            seed=data['seed'],version=data['version'],time_us=data['time_us'],event_queue=queue,trace=trace,
            committed_events=data['metrics']['committed_events'],rng_state=_tuple_tree(data['rng_state']),
            hardware=hardware_from_dict(data['hardware']),active_plan=runtime_from_dict(data['active_plan']),
            reservations=tuple(ResourceReservation(**r) for r in data['reservations']),
            physical_metrics=PhysicalMetrics(**data['physical_metrics']))
        from neutral_atom_env.simulation.runtime_validation import validate_runtime
        validate_runtime(state)
        if state.snapshot() != canonical_json(data):
            raise ValueError('Checkpoint fields or derived data inconsistent')
        return state
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise ValidationError('INVALID_CHECKPOINT', str(error)) from error
