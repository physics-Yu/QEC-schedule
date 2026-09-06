"""Explicit factory registry; callers may also inject any QECCode directly."""
from collections.abc import Callable
from .code import QECCode
from .surface_code import RotatedSurfaceCode


class CodeRegistry:
    def __init__(self):
        self._factories: dict[str, Callable[..., QECCode]] = {}

    def register(self, name: str, factory: Callable[..., QECCode]) -> None:
        if not isinstance(name, str) or not name.strip() or not callable(factory):
            raise ValueError("A code name and callable factory are required")
        if name in self._factories:
            raise ValueError(f"Code already registered: {name}")
        self._factories[name] = factory

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def create(self, name: str = "rotated_surface", **parameters) -> QECCode:
        if name not in self._factories:
            raise ValueError(f"Unknown code {name!r}; available: {', '.join(self.names())}")
        code = self._factories[name](**parameters)
        if not isinstance(code, QECCode):
            raise TypeError("Registered factory must return a QECCode")
        code.validate()
        return code


def default_registry() -> CodeRegistry:
    registry = CodeRegistry()
    registry.register("rotated_surface", RotatedSurfaceCode)
    return registry


def create_code(name: str = "rotated_surface", **parameters) -> QECCode:
    return default_registry().create(name, **parameters)
