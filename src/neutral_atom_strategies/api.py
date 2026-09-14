"""Replaceable external control strategies over the physical environment."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from neutral_atom_env.environment import NeutralAtomEnv


class Strategy(Protocol):
    id: str

    def run(self, env: NeutralAtomEnv, *, on_event=None): ...


@dataclass(frozen=True)
class FunctionStrategy:
    """Adapt an existing controller without changing its choices or event order."""
    id: str
    runner: Callable
    options: Mapping = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, 'options', MappingProxyType(dict(self.options)))

    def run(self, env: NeutralAtomEnv, *, on_event=None):
        if not isinstance(env, NeutralAtomEnv):
            raise TypeError('Strategy.run requires NeutralAtomEnv, not an input dictionary')
        return self.runner(env, on_event=on_event, **self.options)


def make_strategy(name='greedy', **options) -> Strategy:
    """Built-in general strategies; experimental protocol guards live elsewhere."""
    if name in {'basic', 'greedy', 'critical_path', 'lookahead'}:
        from .scheduling.m4 import run_m4
        return FunctionStrategy(name, run_m4, dict(options, strategy=name))
    if name in {'resident', 'returning'}:
        from .scheduling.m3 import run_m3
        return FunctionStrategy(name, run_m3, dict(options, compiler=name))
    raise ValueError(f'Unknown general strategy: {name}')
