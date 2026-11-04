"""Small exact GF(2) and Clifford helpers; no simulator or decoder dependency."""

from collections.abc import Iterable, Sequence


def mask(support: Iterable[int]) -> int:
    """Encode a binary support as an integer bit mask."""
    return sum(1 << q for q in support)


def solve(rows: Sequence[int], values: Sequence[int], width: int) -> int:
    """Solve binary parity equations deterministically with free variables zero.

    Raises:
        ValueError: If the equations are inconsistent or have wrong dimensions.
    """
    if len(rows) != len(values):
        raise ValueError("Binary equations and values have different lengths.")
    work = [row | ((bit & 1) << width) for row, bit in zip(rows, values, strict=True)]
    pivots: list[int] = []
    for column in range(width):
        selected = next(
            (i for i in range(len(pivots), len(work)) if work[i] & (1 << column)), None
        )
        if selected is None:
            continue
        index = len(pivots)
        work[index], work[selected] = work[selected], work[index]
        for i in range(len(work)):
            if i != index and work[i] & (1 << column):
                work[i] ^= work[index]
        pivots.append(column)
    if any(row == (1 << width) for row in work):
        raise ValueError("Inconsistent binary parity equations.")
    return sum(((work[i] >> width) & 1) << q for i, q in enumerate(pivots))


def combination(generators: Sequence[int], target: int, width: int) -> int:
    """Express a binary vector as a generator combination, or fail explicitly."""
    rows = [
        sum(((g >> bit) & 1) << j for j, g in enumerate(generators))
        for bit in range(width)
    ]
    return solve(rows, [(target >> bit) & 1 for bit in range(width)], len(generators))


def conjugate(
    pauli: tuple[int, int, int],
    gates: Sequence[tuple[str, tuple[int, ...]]],
    *,
    inverse: bool = False,
) -> tuple[int, int, int]:
    """Conjugate i**phase X**x Z**z through a concrete Clifford gate list.

    This tracks Pauli signs exactly. Reset and measurement are not unitary and
    must be excluded by the caller.
    """
    x, z, phase = pauli
    for name, targets in reversed(gates) if inverse else gates:
        a = 1 << targets[0]
        xa, za = bool(x & a), bool(z & a)
        if name == "h":
            phase += 2 * (xa and za)
            if xa != za:
                x ^= a
                z ^= a
        elif name in ("s", "sdg"):
            phase += (1 if (name == "s") != inverse else -1) * xa
            if xa:
                z ^= a
        elif name == "cx":
            b = 1 << targets[1]
            if xa:
                x ^= b
            if z & b:
                z ^= a
        elif name == "cz":
            b = 1 << targets[1]
            xb = bool(x & b)
            phase += 2 * (xa and xb)
            if xa:
                z ^= b
            if xb:
                z ^= a
        else:
            raise ValueError(f"Unsupported Clifford gate {name!r}.")
    return x, z, phase % 4
