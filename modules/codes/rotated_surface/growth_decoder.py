"""Open-boundary repeated-syndrome decoding and explicit output Pauli frame.

This is a phenomenological MWPM decoder with configurable weights, not a
calibration of the circuit-level noise model. The first growth syndrome is a
gauge reference, not an assumed all-zero state. Both temporal ends are open;
errors before that reference or after the final SE are not fully protected.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from .definition import definition
from .growth import GrowthComponent


@dataclass(frozen=True)
class GrowthFrame:
    """A virtual correction on target data; caller must retain or apply it."""

    x: int
    z: int
    decoder: str = "phenomenological_mwpm_open_boundary/1"


@dataclass(frozen=True)
class GrowthDecoder:
    """Decode complete target SE histories without rejecting a nonzero syndrome.

    The default equal weights define a decoder choice, not modified physical
    noise parameters. Fault IDs retain data corrections and measurement-error
    estimates so first-round gauge canonicalization uses corrected outcomes.
    """

    distance: int
    data_weight: float = 1.0
    measurement_weight: float = 1.0

    def __post_init__(self) -> None:
        GrowthComponent(self.distance)
        if any(
            not isfinite(w) or w <= 0
            for w in (self.data_weight, self.measurement_weight)
        ):
            raise ValueError("Decoder weights must be finite and positive.")

    def decode(self, history: Sequence[Sequence[int]]) -> GrowthFrame:
        """Return a decoded frame; raise for missing, malformed or nonbinary bits."""
        import numpy as np
        import pymatching

        code = definition(self.distance)
        rounds, count, n = len(history), code.check_count, code.data_count
        if rounds < 2 or any(
            len(row) != count or any(type(v) is not int or v not in (0, 1) for v in row)
            for row in history
        ):
            raise ValueError(
                "Growth decoding needs at least two complete binary rounds."
            )
        data = {"X": 0, "Z": 0}
        initial = list(history[0])
        for basis in ("X", "Z"):
            checks = [j for j, (b, _) in enumerate(code.checks) if b == basis]
            width = len(checks)
            graph = pymatching.Matching()
            # Data errors between two sampled rounds change the next syndrome.
            for t in range(rounds - 1):
                for q in range(n):
                    nodes = [
                        t * width + k
                        for k, j in enumerate(checks)
                        if q in code.checks[j][1]
                    ]
                    if len(nodes) == 1:
                        graph.add_boundary_edge(
                            nodes[0],
                            fault_ids={q},
                            weight=self.data_weight,
                            merge_strategy="smallest-weight",
                        )
                    elif len(nodes) == 2:
                        graph.add_edge(
                            *nodes,
                            fault_ids={q},
                            weight=self.data_weight,
                            merge_strategy="smallest-weight",
                        )
            # Readout faults at the first/final round terminate on open time ends.
            for t in range(rounds):
                for k in range(width):
                    nodes = [u * width + k for u in (t - 1, t) if 0 <= u < rounds - 1]
                    fault = n + t * width + k
                    if len(nodes) == 1:
                        graph.add_boundary_edge(
                            nodes[0],
                            fault_ids={fault},
                            weight=self.measurement_weight,
                            merge_strategy="smallest-weight",
                        )
                    else:
                        graph.add_edge(
                            *nodes,
                            fault_ids={fault},
                            weight=self.measurement_weight,
                            merge_strategy="smallest-weight",
                        )
            detectors = np.array(
                [
                    history[t][j] ^ history[t + 1][j]
                    for t in range(rounds - 1)
                    for j in checks
                ],
                dtype=np.uint8,
            )
            prediction = graph.decode(detectors)
            data["Z" if basis == "X" else "X"] = sum(
                int(prediction[q]) << q for q in range(n)
            )
            for k, j in enumerate(checks):
                if n + k < len(prediction):
                    initial[j] ^= int(prediction[n + k])
        x, z = data["X"], data["Z"]
        for bit, term in zip(
            initial, GrowthComponent(self.distance).correction_terms, strict=True
        ):
            if bit:
                for role, basis in term.pauli_roles:
                    q = int(role[5:-1])
                    if basis in ("X", "Y"):
                        x ^= 1 << q
                    if basis in ("Z", "Y"):
                        z ^= 1 << q
        return GrowthFrame(x, z)
