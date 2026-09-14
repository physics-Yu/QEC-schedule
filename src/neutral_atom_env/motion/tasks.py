"""Serial target-task compiler and deferred prepare/effect/cleanup recipes.

Recipes are recompiled against the latest committed state, never submitted as
stale predictions. Routing is bounded and uses the existing physical backend.
"""
from dataclasses import dataclass
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K, CaptureBinding
from neutral_atom_env.hardware.dynamic_traps import trap_state
from .program import ProgramBuilder, apply_operation
from .validation import require
from .task_validation import EFFECTS
from .single_trap import route
from .planners import HalfGridPlanner


def idle(state):
    if state.active_plan or state.event_queue or state.reservations or state.transfer is not None:
        raise ValidationError('RESOURCE_BUSY', 'Compile a task against a stable idle boundary')


def append(builder, operation):
    builder.add(operation.operation_type, operation.label, target=operation.target_pose,
                configuration=operation.target_configuration, bindings=operation.transfer_bindings,
                phase=operation.transfer_phase, switch_state=operation.switch_state)


@dataclass(frozen=True)
class TaskProgram:
    """Immutable operation recipe. Validation is mandatory again at compile/submit."""
    intent: TaskIntent
    operations: tuple
    compiler_id: str = 'serial-task-program-v1'

    def __post_init__(self):
        object.__setattr__(self, 'operations', tuple(self.operations))

    def compile(self, state):
        idle(state)
        builder = ProgramBuilder(state, self.intent)
        for operation in self.operations:
            append(builder, operation)
        return builder.finish(self.compiler_id)


class TargetTaskCompiler:
    """Bounded 1-trap SLM-to-SLM transport, dark reposition or in-place effect.

    General loaded routing/terminal allocation is M3-C; TaskProgram already
    permits validated loaded boundaries in split CZ recipes.
    """
    id = 'single-trap-target-task-v1'

    def __init__(self, planner=None):
        self.planner = planner or HalfGridPlanner()

    def compile(self, intent, state):
        idle(state)
        require(isinstance(intent, TaskIntent), 'TargetTaskCompiler requires TaskIntent')
        require(intent.atom_ids <= state.atoms.keys(), 'Unknown task atom')
        builder = ProgramBuilder(state, intent)
        if intent.effect_gate_id:
            node = state.dag.nodes.get(intent.effect_gate_id)
            if node is None or node.status.value != 'ready':
                raise ValidationError('GATE_NOT_READY', 'Task effect requires a READY gate')
            if node.gate.gate_type != 'CZ' and node.gate.u_parameters is None:
                raise ValidationError('UNSUPPORTED_GATE', 'Task effect supports CZ or U')
            builder.add(K.ENTANGLING_PULSE if node.gate.gate_type == 'CZ' else K.RAMAN_ROTATION, 'Task gate effect')
        else:
            if state.hardware.backend != 'rigid' or (state.aod.rows, state.aod.columns) != (1, 1):
                raise ValidationError('SINGLE_TRAP_REQUIRED', 'Target routing requires one rigid trap')
            if state.placement.mobile_occupancy:
                raise ValidationError('UNSUPPORTED_TASK_ORIGIN', 'Generic loaded target routing belongs to M3-C')
            changed = [(q,h) for q,h in intent.target.holders if state.placement.atom_to_holder.get(q) != h]
            if len(changed) > 1:
                raise ValidationError('UNSUPPORTED_TASK_TARGET', 'One transported atom per target task')
            for q, target in changed:
                source = state.placement.atom_to_holder.get(q)
                if source is None or source.holder_type != HolderType.STATIC or target.holder_type != HolderType.STATIC:
                    raise ValidationError('UNSUPPORTED_TASK_TARGET', 'Target routing requires SLM source and destination')
                if target.holder_id not in state.world.traps:
                    raise ValidationError('UNKNOWN_TRAP', 'Unknown task destination')
                if target.holder_id in state.placement.static_occupancy:
                    raise ValidationError('OCCUPIED_TASK_TARGET', 'Destination must be empty')
                cell = MobileCellIndex(0,0)
                load = CaptureBinding(q,cell,source.holder_id)
                offload = CaptureBinding(q,cell,target.holder_id)
                route(builder,state.world.traps[source.holder_id].position,self.planner)
                builder.add(K.AOD_LOAD,'Task load',bindings=(load,))
                route(builder,state.world.traps[target.holder_id].position,self.planner,
                      depart=(load,),approach=(offload,),label='Task transport')
                builder.add(K.AOD_OFFLOAD,'Task offload',bindings=(offload,))
            if intent.target.aod_configuration is not None:
                from neutral_atom_env.domain.models import Position2D
                target=intent.target.aod_configuration
                require(len(target.x_um)==len(target.y_um)==1, 'Target axes must match single trap')
                route(builder,Position2D(target.x_um[0],target.y_um[0]),self.planner)
            if intent.target.traps is not None and trap_state(builder.state)!=intent.target.traps:
                builder.add(K.TRAP_SWITCH,'Task terminal supports',switch_state=intent.target.traps)
        if not builder.operations:
            raise ValidationError('TASK_ALREADY_SATISFIED', 'No physical operation required; do not submit an empty plan')
        return builder.finish(self.id)


def split_gate_program(plan, state, *, task_prefix):
    """Return independently compilable stages without committing predicted state.

    Split only at the pulse boundaries: transfer approach/departure adjacency
    remains inside each stage. Terminal states are explicit, including axes/masks.
    """
    from .compiler import exact_validate
    exact_validate(plan,state)
    require(plan.initial_placement is not None, 'Split requires a general operation program')
    indices=[i for i,op in enumerate(plan.operations) if op.operation_type in EFFECTS]
    require(len(indices)==1, 'Split requires exactly one gate effect')
    pulse=indices[0]
    gate=next(iter(plan.intent.gate_ids))
    parts=(('prepare',plan.operations[:pulse]),('effect',plan.operations[pulse:pulse+1]),
           ('cleanup',plan.operations[pulse+1:]))
    work=state; result=[]
    for phase, operations in parts:
        if not operations:
            continue
        for op in operations:
            work=apply_operation(work,op,gate)
        target=TaskTarget(tuple(sorted(work.placement.atom_to_holder.items())),work.aod.configuration(),trap_state(work))
        intent=TaskIntent(f'{task_prefix}/{phase}',target,plan.requested_atom_ids,
                          gate if phase=='effect' else None,phase,gate)
        # Explicit terminal constraints include spectators without declaring
        # that they are transported or part of the pulse's effect.
        result.append(TaskProgram(intent,operations,'split-gate-program-v1'))
    return tuple(result)
