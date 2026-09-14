"""Compilation strategy plugins are separate from physical hardware backends."""
from typing import Protocol
from neutral_atom_env.domain.operations import CompiledPlan, ExecuteGateBatchIntent, TaskIntent


class GateCompiler(Protocol):
    def compile(self, intent: ExecuteGateBatchIntent, state) -> CompiledPlan: ...


class TaskCompiler(Protocol):
    def compile(self, intent: TaskIntent, state) -> CompiledPlan: ...


def make_compiler(name='single_trap', **options):
    if name == 'single_trap':
        from neutral_atom_strategies.motion.single_trap import SingleTrapCompiler
        return SingleTrapCompiler(**options)
    if name == 'legacy_eager':
        from neutral_atom_strategies.motion.compiler import MotionCompiler
        return MotionCompiler(**options)
    raise ValueError(f'Unknown compilation strategy: {name}')
