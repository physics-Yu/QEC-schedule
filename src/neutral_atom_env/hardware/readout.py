"""Addressed, non-destructive ideal Z readout/reset on stable supports.

No readout fidelity, heating, loss or crosstalk model is inferred. The 500/100 us
defaults are explicit simulation assumptions, not a hardware calibration.
"""
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType,ZoneType
from neutral_atom_env.domain.operations import OperationType as K


def validate_readout(state,gate_ids,kind):
    ids=tuple(gate_ids)
    if kind not in {K.MEASUREMENT,K.RESET} or not ids or len(set(ids))!=len(ids) or any(g not in state.dag.nodes for g in ids):
        raise ValidationError('INVALID_READOUT','Readout needs known distinct gate IDs')
    expected={'MEASURE','MZ'} if kind==K.MEASUREMENT else {'RESET'}
    gates=tuple(state.dag.nodes[g].gate for g in ids)
    if any(g.gate_type not in expected for g in gates):
        raise ValidationError('INVALID_READOUT','Readout/reset operation and declared gate types differ')
    qubits=tuple(g.qubit_ids[0] for g in gates)
    if len(set(qubits))!=len(qubits):raise ValidationError('OVERLAPPING_READOUT','Parallel readout/reset targets must be distinct')
    if state.quantum_state is None:raise ValidationError('QUANTUM_STATE_REQUIRED','Readout/reset requires ideal quantum state tracking')
    if state.transfer is not None or state.aod.is_moving:
        raise ValidationError('READOUT_UNSTABLE','Readout/reset requires stationary atoms and completed handoffs')
    for q in qubits:
        h=state.placement.atom_to_holder[q]
        enabled=(state.slm_enabled[h.holder_id] if h.holder_type==HolderType.STATIC else
                 state.aod.is_enabled(h.holder_id) if h.holder_type==HolderType.MOBILE else False)
        if not state.atoms[q].alive or not enabled:
            raise ValidationError('READOUT_TARGET_UNAVAILABLE','Readout/reset target must be alive and supported',atom_ids=(q,))
        position=state.placement.position(q,state.world,state.aod)
        if not any(z.zone_type==ZoneType.MEASUREMENT and z.bounds.contains(position) for z in state.world.zones):
            raise ValidationError('READOUT_ZONE_UNAVAILABLE','Readout/reset target must be in the measurement zone',atom_ids=(q,))
    return gates
