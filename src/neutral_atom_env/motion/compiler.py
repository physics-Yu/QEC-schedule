from hashlib import sha256
from neutral_atom_env.domain.models import GateStatus, HolderType, Position2D, ZoneType
from neutral_atom_env.domain.operations import CompiledPlan, EndDisposition, Operation, OperationType
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend


def fingerprint(state):
    return sha256(state.snapshot().encode('utf-8')).hexdigest()


class MotionCompiler:
    """Serial eager routing between storage sources and prepositioned static EZ partners."""
    def __init__(self,planner=None):
        from .planners import HalfGridPlanner
        self.planner=planner or HalfGridPlanner()

    def compile(self,intent,state,*,target_configuration=None):
        if intent.end_disposition!=EndDisposition.RETURN_AND_OFFLOAD:
            raise ValidationError('UNSUPPORTED_DISPOSITION','Eager supports RETURN_AND_OFFLOAD only')
        if len(intent.gate_ids)!=1:raise ValidationError('UNSUPPORTED_BATCH','Eager requires exactly one gate')
        if state.active_plan or state.reservations or state.event_queue or state.placement.mobile_occupancy:
            raise ValidationError('RESOURCE_BUSY','AOD cycle requires no active plan, queued event or loaded atoms')
        gate_id=next(iter(intent.gate_ids));node=state.dag.nodes.get(gate_id)
        if not node or node.status!=GateStatus.READY:
            raise ValidationError('GATE_NOT_READY','A single READY gate is required')
        if node.gate.gate_type!='CZ':
            raise ValidationError('UNSUPPORTED_GATE','Physical eager execution supports CZ only; parameterized gates and measurement are not implemented')
        requested=frozenset(node.gate.qubit_ids)
        anchors=[]
        for atom in sorted(requested):
            h=state.placement.atom_to_holder[atom];p=state.placement.position(atom,state.world,state.aod)
            if h.holder_type==HolderType.STATIC and any(z.zone_type==ZoneType.ENTANGLEMENT and z.bounds.contains(p) for z in state.world.zones):anchors.append(atom)
        if state.hardware.backend=='rigid' and state.hardware.selective_transfer_enabled and not anchors:
            if target_configuration is not None:
                raise ValidationError('UNSUPPORTED_TARGET_OVERRIDE','Parking targets are selected from real EZ SLM traps; arbitrary target override is unsupported')
            from .rigid_parking_compiler import compile_parked_pair
            return compile_parked_pair(intent,state,fingerprint(state),self.planner)
        if state.hardware.backend=='row_column' and len(anchors)!=1:
            from .row_column_compiler import compile_mobile_pair
            return compile_mobile_pair(intent,state,fingerprint(state),self.planner,target_configuration)
        if len(anchors)!=1:
            raise ValidationError('STATIC_PARTNER_REQUIRED','Eager requires one prepositioned static EZ partner; no implicit relocation',atom_ids=tuple(sorted(requested)))
        moving=next(iter(requested-{anchors[0]}))
        if state.placement.atom_to_holder[moving].holder_type!=HolderType.STATIC:
            raise ValidationError('STATIC_SOURCE_REQUIRED','Source atom must be static',atom_ids=(moving,))
        backend=get_backend(state.hardware)
        before=fingerprint(state);work=state;operations=[];total_distance=0.
        def add(kind,label,duration,target=None):
            operations.append(Operation(f'op{len(operations):02d}',kind,label,duration,target))
        initial_pose=state.aod.pose
        initial_config=state.aod.configuration()
        source_position=state.placement.position(moving,state.world,state.aod)
        # Preserve the current footprint when it already covers the requested source.
        inside=(initial_pose.x_um<=source_position.x_um<=initial_config.x_um[-1]
                and initial_pose.y_um<=source_position.y_um<=initial_config.y_um[-1])
        source=initial_pose if inside else source_position
        if source!=initial_pose:
            d=backend.move_distance(work.aod,source)
            duration=backend.move_duration(work.aod,source,state.hardware)
            work=backend.move(work,source);total_distance+=d
            add(OperationType.AOD_MOVE,'Empty reposition to source',duration,source)
        bindings=backend.capture_closure(work,source)
        captured={b.atom_id for b in bindings}
        if moving not in captured or anchors[0] in captured:
            raise ValidationError('NO_LOAD_FOOTPRINT','Source footprint must capture moving operand and leave EZ partner static',atom_ids=(moving,))
        add(OperationType.AOD_LOAD,'Load',state.hardware.load_duration_us)
        work=backend.load(work,bindings)
        cell=next(b.cell for b in bindings if b.atom_id==moving)
        anchor=state.placement.position(anchors[0],state.world,state.aod)
        offset=state.hardware.interaction_offset
        target=Position2D(anchor.x_um+offset.x_um-(initial_config.x_um[cell.column]-initial_pose.x_um),
                          anchor.y_um+offset.y_um-(initial_config.y_um[cell.row]-initial_pose.y_um))
        from .routing import plan_transport
        if target_configuration is not None:
            if backend.name=='rigid':
                pose=Position2D(target_configuration.x_um[0],target_configuration.y_um[0])
                if backend.target_aod(work.aod,pose).configuration()!=target_configuration:
                    raise ValidationError('UNSUPPORTED_DEFORMATION','Rigid target must preserve spacing')
                target=pose
            else:target=target_configuration
        work,moves,travel=plan_transport(self.planner,work,target,bindings,gate_id,len(operations))
        operations.extend(moves);total_distance+=travel
        work=backend.offload(work,bindings)
        add(OperationType.AOD_OFFLOAD,'Offload',state.hardware.offload_duration_us)
        if source!=initial_pose:
            d=backend.move_distance(work.aod,initial_pose)
            duration=backend.move_duration(work.aod,initial_pose,state.hardware)
            work=backend.move(work,initial_pose);total_distance+=d
            add(OperationType.AOD_MOVE,'Empty return to initial pose',duration,initial_pose)
        resources=('AOD_0','ENTANGLING_LASER_0',state.hardware.interaction_slot_id)+tuple('atom:'+a for a in sorted(requested|captured))+tuple('trap:'+b.static_trap_id for b in bindings)
        plan=CompiledPlan('plan_'+before[:12],state.version,before,intent,bindings,requested,frozenset(captured-requested),
            tuple(operations),resources,sum(o.duration_us for o in operations),total_distance,
            tuple(sorted(work.placement.atom_to_holder.items())),initial_config,self.planner.id)
        exact_validate(plan,state)
        return plan


def exact_validate(plan,state):
    from .validation import validate_plan
    validate_plan(plan,state)
