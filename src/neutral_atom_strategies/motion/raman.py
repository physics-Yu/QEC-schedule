"""Compile one addressed U effect through the common validated program interface."""
from neutral_atom_env.domain.operations import OperationType, EndDisposition
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.program.builder import ProgramBuilder


def compile_rotation(intent, state):
    if intent.end_disposition != EndDisposition.RETURN_AND_OFFLOAD:
        raise ValidationError('UNSUPPORTED_DISPOSITION', 'Serial Raman plan preserves its complete initial placement')
    gate = state.dag.nodes[next(iter(intent.gate_ids))].gate
    builder = ProgramBuilder(state, intent)
    builder.add(OperationType.RAMAN_ROTATION, f'{gate.gate_type} Raman rotation')
    return builder.finish('addressed-raman-u-v1')
