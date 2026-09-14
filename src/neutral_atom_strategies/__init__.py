"""External route, placement and scheduling strategies; never physical truth."""
from .api import Strategy, FunctionStrategy, make_strategy

__all__ = ['Strategy', 'FunctionStrategy', 'make_strategy']
