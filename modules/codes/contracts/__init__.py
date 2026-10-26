"""Code-owned operation sets, independent of compiler implementation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodeEntry:
    """A translation scheme and its intended component operation names.

    Component implementations are not supplied by these translation declarations.
    """

    code: str
    scheme: str
    gates: tuple[str, ...]
    components: tuple[tuple[str, str], ...]
    initializers: tuple[str, ...] = ("initialize_0", "initialize_plus")
    components_implemented: bool = False

    def component_for(self, operation: str) -> str | None:
        """Return the intended component identity, or None for compiler metadata."""
        if operation in ("barrier", "global_phase"):
            return None
        if operation not in self.gates + self.initializers + ("measure",):
            raise ValueError(f"Unsupported operation {operation!r} for {self.code}.")
        mapping = dict(self.components)
        if operation not in mapping:
            raise ValueError(f"No component binding for {operation!r} in {self.code}.")
        name = mapping[operation]
        return f"{self.code}/{name}"
