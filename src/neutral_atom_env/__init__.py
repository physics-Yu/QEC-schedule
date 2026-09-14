"""Neutral-atom physical simulation platform, independent of algorithms/apps."""

# Lazy export keeps importing a domain submodule lightweight and avoids cycles.
__all__ = ['NeutralAtomEnv', 'Observation']


def __getattr__(name):
    if name in __all__:
        from .environment import NeutralAtomEnv, Observation
        return {'NeutralAtomEnv': NeutralAtomEnv, 'Observation': Observation}[name]
    raise AttributeError(name)
