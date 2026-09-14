from dataclasses import dataclass
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K, CaptureBinding
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.program.builder import ProgramBuilder, apply_operation
from neutral_atom_env.program.validation import require
from neutral_atom_env.program.task_validation import EFFECTS
from neutral_atom_strategies.motion.single_trap import route
from neutral_atom_strategies.motion.planners import HalfGridPlanner
from neutral_atom_env.program.tasks import idle, append, TaskProgram, split_gate_program

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
