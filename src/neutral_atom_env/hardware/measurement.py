from neutral_atom_env.domain.models import ZoneType
from neutral_atom_env.domain.errors import ValidationError


def validate_atoms_in_zone(state, gate, zone_type):
    for qubit in gate.qubit_ids:
        atom = state.atoms[qubit]
        position = state.placement.position(atom.id, state.world, state.aod)
        if not atom.alive or position is None or not any(
                z.zone_type == zone_type and z.bounds.contains(position) for z in state.world.zones):
            raise ValidationError('WRONG_OPERATION_ZONE', f"{gate.id}: {atom.id} must be in {zone_type.value} zone", atom_ids=(atom.id,), position=position)
        holder = state.placement.atom_to_holder[atom.id]
        if holder.holder_type.value == 'mobile' and state.aod.is_moving:
            raise ValidationError('ATOM_MOVING', f"{gate.id}: {atom.id} is moving", atom_ids=(atom.id,), position=position)


class MeasurementDevice:
    """Measurement permission belongs to hardware, not the logical DAG."""
    def validate(self, state, gate):
        if gate.gate_type != 'MEASURE':
            raise ValueError('MeasurementDevice requires MEASURE')
        validate_atoms_in_zone(state, gate, ZoneType.MEASUREMENT)
