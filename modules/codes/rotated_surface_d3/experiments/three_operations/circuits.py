"""Concrete d3 circuits for a bounded compilation study, not a component API."""

from __future__ import annotations

from typing import Any

# Coordinates describe code roles; physical homes use 10 um per coordinate unit.
DATA = {q: (2 * (q % 3) + 1, 2 * (q // 3) + 1) for q in range(9)}
CHECKS = (
    ("X", (0, 1), (2, 0)),
    ("X", (1, 2, 4, 5), (4, 2)),
    ("X", (3, 4, 6, 7), (2, 4)),
    ("X", (7, 8), (4, 6)),
    ("Z", (3, 6), (0, 4)),
    ("Z", (0, 1, 3, 4), (2, 2)),
    ("Z", (4, 5, 7, 8), (4, 4)),
    ("Z", (2, 5), (6, 2)),
)
COORDINATES = {**DATA, **{9 + i: c for i, (_, _, c) in enumerate(CHECKS)}}
INITIAL_LAYERS = {
    "initialize_0": (
        ((0, 1), (2, 4), (6, 3), (8, 7)),
        ((2, 1), (6, 7)),
        ((2, 5), (6, 4)),
    ),
    "initialize_plus": (
        ((1, 0), (4, 8), (3, 6), (5, 2)),
        ((3, 0), (5, 8)),
        ((4, 0), (7, 8)),
    ),
}
H_TARGETS = {"initialize_0": (0, 2, 6, 8), "initialize_plus": (1, 3, 4, 5, 7)}
type Operation = tuple[str, tuple[int, ...]]


def se_layers() -> list[tuple[tuple[int, int], ...]]:
    """Return four N/Z slots, keeping missing boundary corners empty.

    Coordinates increase rightward/downward in the code diagram. X checks use
    NW, NE, SW, SE; Z checks use NW, SW, NE, SE. Both orders reverse Stim 1.16's
    convention together. Correctness is checked independently in verify.py.
    """
    orders = {
        "X": ((-1, -1), (1, -1), (-1, 1), (1, 1)),
        "Z": ((-1, -1), (-1, 1), (1, -1), (1, 1)),
    }
    by_coordinate = {xy: q for q, xy in DATA.items()}
    layers = []
    for slot in range(4):
        pairs = []
        for i, (basis, support, (x, y)) in enumerate(CHECKS):
            dx, dy = orders[basis][slot]
            data = by_coordinate.get((x + dx, y + dy))
            if data is not None:
                assert data in support
                pairs.append((9 + i, data) if basis == "X" else (data, 9 + i))
        wires = [q for pair in pairs for q in pair]
        assert len(wires) == len(set(wires)), (slot, pairs)
        layers.append(tuple(pairs))
    return layers


def operations(name: str) -> list[Operation]:
    """Build one of the three explicit circuits; reject unknown names."""
    result: list[Operation] = []
    if name in INITIAL_LAYERS:
        result += [("R", (q,)) for q in range(9)]
        result += [("H", (q,)) for q in H_TARGETS[name]]
        layers = INITIAL_LAYERS[name]
    elif name == "se_round":
        result += [("R", (q,)) for q in range(9, 17)]
        result += [("H", (q,)) for q in range(9, 13)]
        layers = se_layers()
    else:
        raise ValueError(f"Unknown d3 operation: {name}")
    result.append(("TICK", ()))
    for layer in layers:
        result += [("CX", pair) for pair in layer]
        result.append(("TICK", ()))
    if name == "se_round":
        result += [("H", (q,)) for q in range(9, 13)]
        result.append(("TICK", ()))
        result += [("M", (q,)) for q in range(9, 17)]
    return result


def qasm(name: str) -> str:
    """Emit OpenQASM 3 with explicit all-wire barriers between source slots."""
    lines = ["OPENQASM 3.0;", 'include "stdgates.inc";', "qubit[17] q;"]
    if name == "se_round":
        lines.append("bit[8] m;")
    for gate, qs in operations(name):
        if gate == "TICK":
            lines.append("barrier q;")
        elif gate == "R":
            lines.append(f"reset q[{qs[0]}];")
        elif gate == "M":
            lines.append(f"m[{qs[0] - 9}] = measure q[{qs[0]}];")
        else:
            targets = ", ".join(f"q[{q}]" for q in qs)
            lines.append(f"{gate.lower()} {targets};")
    return "\n".join(lines) + "\n"


def architecture(origin: tuple[float, float] = (0, 0)) -> dict[str, Any]:
    """Return an illustrative shared/v1 device with co-translated readout.

    Not calibrated hardware. A translated origin moves the entire resource
    tile; this is not a claim about translating a patch beside fixed readout.
    """
    x, y = origin
    return {
        "family": "shared/v1",
        "params": {
            "name": "d3-three-operations-reference",
            "cz": {
                "channel": "rydberg",
                "radius_um": 4.6,
                "duration_us": 0.5,
                "holder_pairs": [["slm", "slm"]],
                "allow_spectators": True,
            },
            "local": {
                "channel": "local",
                "rotation_us": 1,
                "reset_us": 5,
                "holders": ["slm", "aod"],
            },
            "timing": {"load_us": 10, "store_us": 10, "move_us_per_um": 1},
            "shared_arrays": [
                {
                    "id": "shared",
                    "array_id": "cells",
                    "position": {"x": x, "y": y},
                    "rows": 7,
                    "pairs_per_row": 7,
                    "separation": 2,
                    "pitch": {"x": 10, "y": 10},
                    "bounds": {"x_min": -2, "y_min": -2, "x_max": 65, "y_max": 65},
                    "left_prefix": "home",
                    "right_prefix": "guest",
                }
            ],
            "measurement": {
                "id": "readout",
                "position": {"x": x, "y": y + 90},
                "bounds": {"x_min": 0, "y_min": 0, "x_max": 65, "y_max": 20},
                "readout": {
                    "channel": "camera",
                    "duration_us": 10,
                    "latency_us": 500,
                    "min_spacing_um": 5,
                    "max_atoms": None,
                    "retain_atoms": True,
                    "holders": ["aod"],
                },
            },
            "aod": {
                "id": "transport",
                "motion": "flexible",
                "min_spacing": 1,
                "workspace": {
                    "x_min": x - 5,
                    "y_min": y - 5,
                    "x_max": x + 70,
                    "y_max": y + 115,
                },
            },
        },
    }


def job(name: str, origin: tuple[float, float] = (0, 0)) -> dict[str, Any]:
    """Bind the same 17-role layout to a nonzoned compilation job."""
    return {
        "schema": "nadit.job/1",
        "circuit": {"qasm": f"{name}.qasm3"},
        "device": {"architecture": architecture(origin)},
        "aod": "transport",
        "strategy": {"kind": "nonzoned"},
        "entry": {
            "kind": "explicit",
            "atoms": [[q, f"home_r{y}_c{x}", q] for q, (x, y) in COORDINATES.items()],
        },
        "case": {"seed": 17},
    }
