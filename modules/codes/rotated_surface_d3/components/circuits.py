"""Measured initialization, fixed N/Z extraction, and physical Pauli strings."""

from ..definition import (
    CHECK_COORDINATES,
    CHECKS,
    DATA_COORDINATES,
    LOGICAL_X,
    LOGICAL_Z,
)

PAULI_STRINGS = {
    "logical_x": tuple((q, "X") for q in LOGICAL_X),
    # Y_L = i X_L Z_L; i X0 Z0 = Y0 fixes the positive logical-Y phase.
    "logical_y": ((0, "Y"), (1, "Z"), (2, "Z"), (3, "X"), (6, "X")),
    "logical_z": tuple((q, "Z") for q in LOGICAL_Z),
}
NAMES = ("initialize_0", "initialize_plus", "se_round", *PAULI_STRINGS)


def se_layers() -> tuple[tuple[tuple[int, int], ...], ...]:
    """Return fixed N/Z slots; missing boundary corners stay empty."""
    orders = {
        "X": ((-1, -1), (1, -1), (-1, 1), (1, 1)),
        "Z": ((-1, -1), (-1, 1), (1, -1), (1, 1)),
    }
    positions = {xy: q for q, xy in enumerate(DATA_COORDINATES)}
    layers = []
    for slot in range(4):
        pairs = []
        for i, ((basis, support), (x, y)) in enumerate(
            zip(CHECKS, CHECK_COORDINATES, strict=True)
        ):
            dx, dy = orders[basis][slot]
            data = positions.get((x + dx, y + dy))
            if data is not None:
                if data not in support:
                    raise ValueError("N/Z geometry disagrees with stabilizer support.")
                pairs.append((9 + i, data) if basis == "X" else (data, 9 + i))
        layers.append(tuple(pairs))
    return tuple(layers)


def source_qasm(name: str) -> str:
    """Return an approved concrete protocol; unknown operations are rejected."""
    if name not in NAMES:
        raise ValueError(f"Unknown surface d3 component {name!r}.")
    lines = ["OPENQASM 3.0;", 'include "stdgates.inc";', "qubit[17] q;"]
    if name in PAULI_STRINGS:
        lines.extend(f"{basis.lower()} q[{q}];" for q, basis in PAULI_STRINGS[name])
        return "\n".join(lines) + "\n"
    lines.append("bit[8] m;")
    if name != "se_round":
        lines.extend(f"reset q[{q}];" for q in range(9))
        if name == "initialize_plus":
            lines.extend(f"h q[{q}];" for q in range(9))
        lines.append("barrier q;")
    lines.extend(f"reset q[{q}];" for q in range(9, 17))
    lines.extend(f"h q[{q}];" for q in range(9, 13))
    lines.append("barrier q;")
    for layer in se_layers():
        lines.extend(f"cx q[{a}], q[{b}];" for a, b in layer)
        lines.append("barrier q;")
    lines.extend(f"h q[{q}];" for q in range(9, 13))
    lines.append("barrier q;")
    lines.extend(f"m[{i}] = measure q[{9 + i}];" for i in range(8))
    return "\n".join(lines) + "\n"
