"""Finite rigid joint-transport planner with explicit EZ SLM handoff."""
from itertools import islice
from math import hypot
from neutral_atom_env.domain.models import Position2D,MobileCellIndex,ZoneType,HolderType
from neutral_atom_env.domain.operations import Operation,OperationType as K,CaptureBinding,CompiledPlan
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from .planners import RouteRequest
from .validation import plan_resources,validate_plan


def compile_parked_pair(intent,state,fingerprint,planner):
    backend=get_backend(state.hardware)
    requested=frozenset(state.dag.nodes[next(iter(intent.gate_ids))].gate.qubit_ids)
    source_positions={a:state.placement.position(a,state.world,state.aod) for a in requested}
    if any(state.placement.atom_to_holder[a].holder_type!=HolderType.STATIC or not any(z.zone_type==ZoneType.STORAGE and z.bounds.contains(p) for z in state.world.zones) for a,p in source_positions.items()):
        raise ValidationError('PAIR_SOURCE_UNSUPPORTED','Joint rigid pair routing requires both operands initially in SZ')
    # Prefer existing footprint; otherwise align either operand to each existing cell.
    sources=[state.aod.pose]
    for a in sorted(requested):
        p=source_positions[a]
        for row in range(state.aod.rows):
            for col in range(state.aod.columns):
                pose=Position2D(p.x_um-col*state.aod.spacing_um,p.y_um-row*state.aod.spacing_um)
                if pose not in sources:sources.append(pose)
    traps=[t for _,t in sorted(state.world.traps.items()) if t.enabled and not state.placement.static_occupancy.get(t.id) and any(z.zone_type==ZoneType.ENTANGLEMENT and z.bounds.contains(t.position) for z in state.world.zones)]
    errors=[];attempts=0
    for source in sources[:64]:
        try:
            initial=backend.move(state,source) if source!=state.aod.pose else state
            bindings=backend.capture_closure(initial,source)
            if not requested<={b.atom_id for b in bindings}:continue
            loaded=backend.load(initial,bindings)
        except ValidationError as error:errors.append(error);continue
        for anchor in sorted(requested):
            anchor_binding=next(b for b in bindings if b.atom_id==anchor)
            other=next(iter(requested-{anchor}));other_binding=next(b for b in bindings if b.atom_id==other)
            for trap in traps[:16]:
                target=Position2D(trap.position.x_um-anchor_binding.cell.column*state.aod.spacing_um,trap.position.y_um-anchor_binding.cell.row*state.aod.spacing_um)
                parked=(CaptureBinding(anchor,anchor_binding.cell,trap.id),)
                request=RouteRequest(loaded.aod.configuration(),backend.target_aod(loaded.aod,target).configuration(),state.world.grid_spacing_um,state.world.grid_origin.x_um,bindings,state.world,state.hardware)
                for raw in islice(planner.candidates(request),16):
                    attempts+=1
                    if attempts>256:break
                    try:
                        route=[]
                        for config in raw:
                            if not route or route[-1]!=config:route.append(config)
                        if len(route)<3 or route[0]!=request.start or route[-1]!=request.target:
                            raise ValidationError('INVALID_ROUTE','Parking transport requires start, departure and aligned arrival')
                        work=initial;ops=[];travel=0
                        def add(kind,label,duration,**fields):
                            ops.append(Operation(f'op{len(ops):02d}',kind,label,duration,**fields))
                        def move(pose,label,phase=None,scope=()):
                            nonlocal work,travel
                            if pose==work.aod.pose:return
                            duration=backend.move_duration(work.aod,pose,state.hardware)
                            travel+=backend.move_distance(work.aod,pose)
                            work=backend.move(work,pose,transfer=phase,bindings=scope or bindings)
                            add(K.AOD_MOVE,label,duration,target_pose=pose,transfer_phase=phase,transfer_bindings=scope)
                        if source!=state.aod.pose:
                            add(K.AOD_MOVE,'Empty reposition to source',backend.move_duration(state.aod,source,state.hardware),target_pose=source)
                            travel+=backend.move_distance(state.aod,source)
                        work=backend.load(work,bindings);add(K.AOD_LOAD,'Joint load in SZ',state.hardware.load_duration_us)
                        for i,config in enumerate(route[1:],1):
                            pose=Position2D(config.x_um[0],config.y_um[0])
                            if backend.target_aod(work.aod,pose).configuration()!=config:raise ValidationError('UNSUPPORTED_DEFORMATION','Rigid route changed spacing')
                            move(pose,'Joint transport to EZ','depart' if i==1 else 'approach' if i==len(route)-1 else None,parked if i==len(route)-1 else ())
                        work=backend.park(work,parked);add(K.AOD_PARK,'Park operand in EZ SLM',state.hardware.offload_duration_us,transfer_bindings=parked)
                        p=work.aod.position(other_binding.cell)
                        dx,dy=p.x_um-trap.position.x_um,p.y_um-trap.position.y_um
                        original=hypot(dx,dy);separation=hypot(state.hardware.interaction_offset.x_um,state.hardware.interaction_offset.y_um)
                        if original<=separation:raise ValidationError('PAIR_GEOMETRY_UNSUPPORTED','Local approach expects separated source cells')
                        gate_pose=Position2D(target.x_um+dx*(separation/original-1),target.y_um+dy*(separation/original-1))
                        move(gate_pose,'Local approach to parked operand')
                        backend.validate_pulse(work,next(iter(intent.gate_ids)));add(K.ENTANGLING_PULSE,'CZ pulse',state.hardware.pulse_duration_us)
                        move(target,'Restore joint transport configuration')
                        work=backend.recapture(work,parked);add(K.AOD_RECAPTURE,'Recapture parked operand',state.hardware.load_duration_us,transfer_bindings=parked)
                        for i,config in enumerate(reversed(route[:-1])):
                            move(Position2D(config.x_um[0],config.y_um[0]),'Joint return to SZ','depart' if i==0 else 'approach' if config==route[0] else None,parked if i==0 else ())
                        work=backend.offload(work,bindings);add(K.AOD_OFFLOAD,'Joint offload in SZ',state.hardware.offload_duration_us)
                        move(state.aod.pose,'Empty return to initial pose')
                        captured=frozenset(b.atom_id for b in bindings)
                        plan=CompiledPlan('plan_'+fingerprint[:12],state.version,fingerprint,intent,bindings,requested,captured-requested,tuple(ops),plan_resources(state,requested,bindings,ops),sum(op.duration_us for op in ops),travel,tuple(sorted(work.placement.atom_to_holder.items())),state.aod.configuration(),'rigid-parking/'+planner.id)
                        validate_plan(plan,state);return plan
                    except ValidationError as error:errors.append(error)
                if attempts>256:break
            if attempts>256:break
        if attempts>256:break
    first=errors[0].violation if errors else None
    raise ValidationError('PAIR_PARKING_ROUTE_UNSUPPORTED',f'No joint rigid parking cycle in finite search ({attempts} routes, {len(traps)} EZ traps). '+(f'First failure: {first.code}: {first.message}' if first else 'Both operands must fit an aligned capture footprint and an empty EZ parking trap is required.'),atom_ids=tuple(sorted(requested)))
