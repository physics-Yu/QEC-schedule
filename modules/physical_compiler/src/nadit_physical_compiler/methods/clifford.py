"""Exact native single-qubit Clifford conversion, up to global phase."""

import importlib
from cmath import exp
from functools import lru_cache
from math import cos, sin
from typing import Any


def dependency(name: str) -> Any:
    """Import a simulation dependency only when the method is used."""
    try:
        return importlib.import_module(name)
    except ImportError as error:
        raise ValueError(
            "Install the simulation extra: uv sync --extra simulation"
        ) from error


@lru_cache(maxsize=256)
def local_clifford(kind: str, values: tuple[float, ...]) -> Any:
    """Return a one-wire Stim circuit; reject non-Clifford native unitaries."""
    stim = dependency("stim")
    if kind == "U":
        theta, phi, lam = values
        c, s = cos(theta / 2), sin(theta / 2)
        matrix = [
            [c, -exp(1j * lam) * s],
            [exp(1j * phi) * s, exp(1j * (phi + lam)) * c],
        ]
    else:
        (angle,) = values
        c, s = cos(angle / 2), sin(angle / 2)
        matrices: dict[str, list[list[complex]]] = {
            "X": [[c, -1j * s], [-1j * s, c]],
            "Y": [[c, -s], [s, c]],
            "Z": [[exp(-1j * angle / 2), 0], [0, exp(1j * angle / 2)]],
        }
        matrix = matrices[kind]
    try:
        tableau = stim.Tableau.from_unitary_matrix(matrix, endian="little")
    except ValueError as error:
        raise ValueError(f"Non-Clifford native operation: {kind}{values}") from error
    exact = tableau.to_unitary_matrix(endian="little")
    row, col = max(
        ((r, c) for r in range(2) for c in range(2)), key=lambda rc: abs(exact[rc])
    )
    phase = matrix[row][col] / exact[row, col]
    if any(
        abs(matrix[r][c] - phase * exact[r, c]) > 1e-7
        for r in range(2)
        for c in range(2)
    ):
        raise ValueError(f"Non-Clifford native operation: {kind}{values}")
    return tableau.to_circuit()
