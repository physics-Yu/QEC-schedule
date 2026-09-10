"""Audit the supplied rigid parking cycle independently of route generation."""
from math import isclose,isfinite
from neutral_atom_env.domain.operations import OperationType as K,EndDisposition
from neutral_atom_env.domain.models import HolderType,ZoneType
from neutral_atom_env.domain.aod import motion_target
from neutral_atom_env.hardware import get_backend
from .validation import require


def replay_parking(intent,state,bindings,operations):
    require(state.hardware.backend=='rigid' and state.hardware.selective_transfer_enabled,'Partial-transfer capability is required')
    require(intent.end_disposition==EndDisposition.RETURN_AND_OFFLOAD and len(intent.gate_ids)==1,'Only one returning CZ cycle is supported')
    gate=state.dag.nodes.get(next(iter(intent.gate_ids)))
    require(gate is not None and gate.gate.gate_type=='CZ','Unknown or unsupported gate')
    captured={b.atom_id:b for b in bindings}
    require(bool(bindings) and len(captured)==len(bindings),'Invalid capture set')
    require(set(gate.gate.qubit_ids)<=set(captured),'Both operands must travel in the capture set')
    for atom in captured:
        p=state.placement.position(atom,state.world,state.aod)
        require(state.placement.atom_to_holder[atom].holder_type==HolderType.STATIC and any(z.zone_type==ZoneType.STORAGE and z.bounds.contains(p) for z in state.world.zones),'Joint transport must start in SZ')
    kinds=[op.operation_type for op in operations]
    stages=(K.AOD_LOAD,K.AOD_PARK,K.ENTANGLING_PULSE,K.AOD_RECAPTURE,K.AOD_OFFLOAD)
    require(all(kinds.count(k)==1 for k in stages),'Require one bulk load, park, pulse, recapture and bulk offload')
    require(all(k in (*stages,K.AOD_MOVE) for k in kinds),'Unknown operation')
    load,park,pulse,recapture,offload=(kinds.index(k) for k in stages)
    require(load+1<park<pulse-1 and pulse+1<recapture<offload-1,'Invalid parking cycle order')
    parked=operations[park].transfer_bindings
    require(len(parked)==1 and parked[0].atom_id in gate.gate.qubit_ids,'Park exactly one target operand')
    require(parked[0].cell==captured[parked[0].atom_id].cell,'Parking changed cell identity')
    require(operations[recapture].transfer_bindings==parked,'Recapture must restore the same atom/cell/trap')
    work=state;backend=get_backend(state.hardware);travel=0;parking_axes=None
    for i,op in enumerate(operations):
        kind=op.operation_type;target=motion_target(op)
        require(op.id==f'op{i:02d}' and isfinite(op.duration_us) and op.duration_us>0,'Invalid operation identity/duration')
        phase='depart' if i in (load+1,recapture+1) else 'approach' if i in (park-1,offload-1) else None
        expected_bindings=parked if i in (park-1,park,recapture,recapture+1) else ()
        require(op.transfer_phase==phase and op.transfer_bindings==expected_bindings,'Invalid transfer scope or boundary exemption')
        if kind==K.AOD_MOVE:
            require(op.target_pose is not None and op.target_configuration is None,'Rigid movement requires a translation pose')
            duration=backend.move_duration(work.aod,target,state.hardware)
            travel+=backend.move_distance(work.aod,target)
            work=backend.move(work,target,transfer=phase,bindings=op.transfer_bindings or bindings)
        else:
            require(target is None and phase is None,'Non-move contains motion fields')
            duration=state.hardware.load_duration_us if kind in (K.AOD_LOAD,K.AOD_RECAPTURE) else state.hardware.offload_duration_us if kind in (K.AOD_OFFLOAD,K.AOD_PARK) else state.hardware.pulse_duration_us
            if kind==K.AOD_LOAD:work=backend.load(work,bindings)
            elif kind==K.AOD_PARK:
                parking_axes=work.aod.configuration();work=backend.park(work,parked)
            elif kind==K.AOD_RECAPTURE:
                require(work.aod.configuration()==parking_axes,'Restore pre-gate rigid configuration before recapture')
                work=backend.recapture(work,parked)
            elif kind==K.AOD_OFFLOAD:work=backend.offload(work,bindings)
            else:backend.validate_pulse(work,gate.gate.id)
        require(isclose(op.duration_us,duration,rel_tol=0,abs_tol=1e-9),'Operation timing differs from hardware')
    require(work.placement==state.placement and work.aod.configuration()==state.aod.configuration(),'Joint return must restore the full initial capture set and AOD')
    return work,travel
