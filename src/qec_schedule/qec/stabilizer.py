"""Abstract qubit labels and positive Hermitian Pauli products; no atom positions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PauliProduct:
    terms: tuple[tuple[str, str], ...]

    def __post_init__(self):
        object.__setattr__(self, "terms", tuple(tuple(t) for t in self.terms))
        if not self.terms or len({q for q, _ in self.terms}) != len(self.terms):
            raise ValueError("Pauli product must have nonempty, unique support")
        if any(not q or p not in ("X", "Y", "Z") for q, p in self.terms):
            raise ValueError("Invalid Pauli term")

    @property
    def support(self) -> tuple[str, ...]:
        return tuple(q for q, _ in self.terms)

    def commutes_with(self, other: "PauliProduct") -> bool:
        right = dict(other.terms)
        return sum(q in right and p != right[q] for q, p in self.terms) % 2 == 0


@dataclass(frozen=True)
class Stabilizer:
    id: str
    ancilla: str
    operator: PauliProduct
    # Ordered (circuit ordering slot, data-qubit ID), not hardware time/layers.
    interactions: tuple[tuple[int, str], ...]

    def __post_init__(self):
        object.__setattr__(self, "interactions", tuple(tuple(t) for t in self.interactions))
        if not self.id or not self.ancilla:
            raise ValueError("Stabilizer and ancilla IDs are required")
        slots = [s for s, _ in self.interactions]
        qubits = [q for _, q in self.interactions]
        if set(qubits) != set(self.operator.support) or len(qubits) != len(set(qubits)):
            raise ValueError("Interaction order must cover support exactly once")
        if any(type(s) is not int or s < 0 for s in slots) or slots != sorted(set(slots)):
            raise ValueError("Interaction slots must be strictly increasing nonnegative integers")

    @property
    def basis(self) -> str:
        bases = {p for _, p in self.operator.terms}
        return next(iter(bases)) if len(bases) == 1 else "MIXED"
