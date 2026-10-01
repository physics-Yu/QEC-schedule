"""Hermitian Pauli products for the QEC measurement intermediate representation.

These values describe signed Pauli observables on named qubit roles.  They are
an algebraic building block for QEC protocols, not a compiler from a complete
algorithm to Pauli-based computation.  They carry no atom placement, timing,
noise, or hardware execution state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


# The ordering matters: X Y = i Z, whereas Y X = -i Z.
_DISTINCT_PRODUCTS: dict[tuple[str, str], tuple[complex, str]] = {
    ("X", "Y"): (1j, "Z"),
    ("Y", "X"): (-1j, "Z"),
    ("Y", "Z"): (1j, "X"),
    ("Z", "Y"): (-1j, "X"),
    ("Z", "X"): (1j, "Y"),
    ("X", "Z"): (-1j, "Y"),
}


@dataclass(frozen=True, slots=True)
class PauliProduct:
    """A signed Hermitian tensor product, canonicalized by qubit role name.

    Identity factors are omitted; an empty ``factors`` tuple represents the
    identity observable.  Multiplication returns its possibly imaginary phase
    separately so every stored ``PauliProduct`` remains Hermitian.
    """

    factors: tuple[tuple[str, str], ...]
    sign: int = 1

    def __post_init__(self) -> None:
        if type(self.sign) is not int or self.sign not in (-1, 1):
            raise ValueError("Pauli product sign must be the integer +1 or -1")
        if not isinstance(self.factors, (tuple, list)):
            raise ValueError("Pauli product factors must be a sequence of role/basis pairs")

        canonical: list[tuple[str, str]] = []
        seen: set[str] = set()
        for factor in self.factors:
            if not isinstance(factor, (tuple, list)) or len(factor) != 2:
                raise ValueError("Each Pauli factor must be a role/basis pair")
            role, basis = factor
            if not isinstance(role, str) or not role.strip():
                raise ValueError("Each Pauli factor must have a nonempty string role")
            if not isinstance(basis, str) or basis not in ("X", "Y", "Z"):
                raise ValueError("Pauli factor basis must be X, Y, or Z")
            if role in seen:
                raise ValueError(f"Duplicate Pauli factor role: {role!r}")
            seen.add(role)
            canonical.append((role, basis))
        object.__setattr__(self, "factors", tuple(sorted(canonical)))

    @property
    def support(self) -> tuple[str, ...]:
        """Return the canonical nonidentity qubit roles."""

        return tuple(role for role, _ in self.factors)

    def commutes_with(self, other: PauliProduct) -> bool:
        """Whether the observables commute, independent of their signs."""

        if not isinstance(other, PauliProduct):
            raise TypeError("Pauli commutation requires another PauliProduct")
        other_factors = dict(other.factors)
        disagreements = sum(
            role in other_factors and basis != other_factors[role]
            for role, basis in self.factors
        )
        return disagreements % 2 == 0

    def multiply(self, other: PauliProduct) -> tuple[complex, PauliProduct]:
        """Return ``self * other`` as a phase and an unsigned product.

        The returned phase includes both operand signs and is exactly one of
        ``1``, ``-1``, ``1j``, or ``-1j``.  Noncommuting Hermitian operands can
        therefore be multiplied without storing an anti-Hermitian observable.
        """

        if not isinstance(other, PauliProduct):
            raise TypeError("Pauli multiplication requires another PauliProduct")
        result = dict(self.factors)
        phase = complex(self.sign * other.sign)
        for role, right_basis in other.factors:
            left_basis = result.get(role)
            if left_basis is None:
                result[role] = right_basis
            elif left_basis == right_basis:
                del result[role]
            else:
                local_phase, result_basis = _DISTINCT_PRODUCTS[(left_basis, right_basis)]
                phase *= local_phase
                result[role] = result_basis
        return phase, PauliProduct(tuple(result.items()))

    def mapped(self, bindings: Mapping[str, str]) -> PauliProduct:
        """Bind supported roles to unique qubit names, preserving the sign.

        All supported roles must be present.  A collision is rejected instead
        of silently multiplying factors belonging to distinct protocol roles.
        Extra bindings have no effect on this observable.
        """

        if not isinstance(bindings, Mapping):
            raise TypeError("Pauli role bindings must be a mapping")
        return PauliProduct(
            tuple((bindings[role], basis) for role, basis in self.factors),
            sign=self.sign,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready canonical observable description."""

        return {"sign": self.sign, "factors": [[role, basis] for role, basis in self.factors]}
