from dataclasses import dataclass
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K, CaptureBinding
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.program.builder import ProgramBuilder, apply_operation
from neutral_atom_env.program.validation import require
from neutral_atom_env.program.task_validation import EFFECTS
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


def split_gate_program(plan, state, *, task_prefix):
    """Return independently compilable stages without committing predicted state.

    Split only at the pulse boundaries: transfer approach/departure adjacency
    remains inside each stage. Terminal states are explicit, including axes/masks.
    """
    from neutral_atom_env.program.binding import exact_validate
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
