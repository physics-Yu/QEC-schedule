"""Axis-safe partial handoffs, gated by the explicit hardware capability."""
from .dynamic_traps import transfer as handoff
from neutral_atom_env.domain.operations import OperationType as K


def transfer(backend, state, bindings, *, recapture=False):
    return handoff(backend, state, bindings, K.AOD_RECAPTURE if recapture else K.AOD_PARK)
