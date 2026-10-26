"""Parameterized copies of the existing N/Z and real half-cycle S circuits."""

from .definition import SurfaceCodeDefinition

BASE_NAMES = (
    "initialize_0",
    "initialize_plus",
    "se_round",
    "logical_x",
    "logical_y",
    "logical_z",
)
PHASE_NAMES = ("logical_s", "logical_sdag", "prepare_y")
MEASUREMENT_NAMES = ("logical_mx", "logical_mz")
SINGLE_BLOCK_NAMES = (*BASE_NAMES, *PHASE_NAMES, *MEASUREMENT_NAMES, "raw_t")


def se_layers(
    code: SurfaceCodeDefinition, *, phase: bool = False
) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Return four N/Z slots, with the phase protocol's separate corner order."""
    orders = (
        {
            "X": ((1, -1), (-1, -1), (1, 1), (-1, 1)),
            "Z": ((1, -1), (1, 1), (-1, -1), (-1, 1)),
        }
        if phase
        else {
            "X": ((-1, -1), (1, -1), (-1, 1), (1, 1)),
            "Z": ((-1, -1), (-1, 1), (1, -1), (1, 1)),
        }
    )
    positions = {xy: q for q, xy in enumerate(code.data_coordinates)}
    layers = []
    for slot in range(4):
        pairs = []
        for i, ((basis, support), (x, y)) in enumerate(
            zip(code.checks, code.check_coordinates, strict=True)
        ):
            dx, dy = orders[basis][slot]
            data = positions.get((x + dx, y + dy))
            if data is not None:
                if data not in support:
                    raise ValueError(
                        "Extraction geometry disagrees with stabilizer support."
                    )
                ancilla = code.data_count + i
                pairs.append((ancilla, data) if basis == "X" else (data, ancilla))
        layers.append(tuple(pairs))
    return tuple(layers)


def fold_gates(
    code: SurfaceCodeDefinition, *, adjoint: bool = False
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Reflect the interior through x=y, applying S/data and Sdag/check diagonal.

    This is the pinned CCLP author's fold after coordinate rotation, including
    syndrome atoms, not transversal S on the final rotated surface code.
    """
    coordinates = code.reference_coordinates
    positions = {xy: q for q, xy in enumerate(coordinates)}
    interior = [
        (q, x, y)
        for q, (x, y) in enumerate(coordinates)
        if 1 <= x <= 2 * code.distance - 1 and 1 <= y <= 2 * code.distance - 1
    ]
    upper = sorted(
        ((q, x, y) for q, x, y in interior if x > y), key=lambda p: (p[2] - p[1], p[0])
    )
    gates: list[tuple[str, tuple[int, ...]]] = [
        ("cz", (q, positions[y, x])) for q, x, y in upper
    ]
    gates += [
        ("sdg" if adjoint else "s", (q,))
        for q, x, y in interior
        if x == y and q < code.data_count
    ]
    gates += [
        ("s" if adjoint else "sdg", (q,))
        for q, x, y in interior
        if x == y and q >= code.data_count
    ]
    return tuple(gates)


def phase_unitary(
    code: SurfaceCodeDefinition, *, adjoint: bool = False
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Return the unitary portion between ancilla reset and final measurement."""
    hs: list[tuple[str, tuple[int, ...]]] = [
        ("h", (q,))
        for q in range(code.data_count, code.data_count + code.check_count // 2)
    ]
    gates = list(hs)
    for slot, layer in enumerate(se_layers(code, phase=True)):
        gates.extend(("cx", pair) for pair in layer)
        if slot == 1:
            gates.extend(fold_gates(code, adjoint=adjoint))
    return tuple(gates + hs)


def raw_plus_qubits(code: SurfaceCodeDefinition) -> tuple[int, ...]:
    """Return NW/SE product sectors and center; central X/Z carry seed Paulis."""
    d, center = code.distance, code.distance // 2
    return tuple(
        q
        for q in range(code.data_count)
        if (q // d < center and q % d <= center)
        or (q // d > center and q % d >= center)
        or q == code.data_count // 2
    )


def extraction_body(
    code: SurfaceCodeDefinition,
    *,
    phase: bool = False,
    adjoint: bool = False,
    offset: int = 0,
) -> list[str]:
    """Emit one full measured round, preserving every result identity."""
    n, count = code.data_count, code.check_count
    lines = [f"reset q[{q}];" for q in range(n, code.atom_count)]
    lines.extend(f"h q[{q}];" for q in range(n, n + count // 2))
    lines.append("barrier q;")
    for slot, layer in enumerate(se_layers(code, phase=phase)):
        lines.extend(f"cx q[{a}], q[{b}];" for a, b in layer)
        lines.append("barrier q;")
        if phase and slot == 1:
            for gate, targets in fold_gates(code, adjoint=adjoint):
                lines.append(f"{gate} " + ", ".join(f"q[{q}]" for q in targets) + ";")
            lines.append("barrier q;")
    lines.extend(f"h q[{q}];" for q in range(n, n + count // 2))
    lines.append("barrier q;")
    lines.extend(f"m[{offset + i}] = measure q[{n + i}];" for i in range(count))
    return lines


def source_qasm(name: str, code: SurfaceCodeDefinition) -> str:
    """Generate a supported concrete circuit, rejecting unimplemented gates."""
    if name not in SINGLE_BLOCK_NAMES:
        raise ValueError(
            f"Unsupported surface component {name!r}; choose from {SINGLE_BLOCK_NAMES}."
        )
    n, count = code.data_count, code.check_count
    lines = ["OPENQASM 3.0;", 'include "stdgates.inc";', f"qubit[{code.atom_count}] q;"]
    if name in ("logical_x", "logical_y", "logical_z"):
        xs = set(code.logical_x) if name != "logical_z" else set()
        zs = set(code.logical_z) if name != "logical_x" else set()
        lines += [
            f"{'y' if q in xs and q in zs else 'x' if q in xs else 'z'} q[{q}];"
            for q in sorted(xs | zs)
        ]
    elif name in MEASUREMENT_NAMES:
        lines.append(f"bit[{n}] m;")
        if name == "logical_mx":
            lines.extend(f"h q[{q}];" for q in range(n))
            lines.append("barrier q;")
        lines.extend(f"m[{q}] = measure q[{q}];" for q in range(n))
    elif name in ("logical_s", "logical_sdag"):
        lines.append(f"bit[{count}] m;")
        lines.extend(extraction_body(code, phase=True, adjoint=name == "logical_sdag"))
    else:
        lines.append(f"bit[{count * (2 if name == 'prepare_y' else 1)}] m;")
        if name != "se_round":
            lines.extend(f"reset q[{q}];" for q in range(n))
            plus = (
                raw_plus_qubits(code)
                if name == "raw_t"
                else range(n)
                if name in ("initialize_plus", "prepare_y")
                else ()
            )
            lines.extend(f"h q[{q}];" for q in plus)
            if name == "raw_t":
                lines.append(f"t q[{n // 2}];")
            lines.append("barrier q;")
        lines.extend(extraction_body(code))
        if name == "prepare_y":
            lines.append("barrier q;")
            lines.extend(extraction_body(code, phase=True, offset=count))
    return "\n".join(lines) + "\n"
