"""Legacy d3 bounds over the shared actual-T detector-signature engine."""

from typing import Any

from nadit_physical_compiler.activity import AtomActivity

from modules.codes._support.detector_probability import (
    MAX_DETECTORS,
    FaultChannel,
    xor_distribution,
)
from modules.codes._support.pauli_detector_events import (
    detector_fault_channels as _detector_fault_channels,
)

__all__ = [
    "MAX_DETECTORS",
    "FaultChannel",
    "detector_fault_channels",
    "xor_distribution",
]


def detector_fault_channels(
    activity: AtomActivity,
    channels: list[dict[str, Any]],
    detectors: tuple[tuple[int, ...], ...],
    *,
    wire_atoms: tuple[int, ...],
    world_atom_ids: tuple[int, ...] | None = None,
) -> tuple[tuple[FaultChannel, ...], dict[str, Any]]:
    """Retain the original seventeen-wire and twenty-detector d3 admission limits.

    The common engine proves identity at the real central T pulse and preserves
    full-world channel evidence. This wrapper keeps the previous public API.
    """
    if len(wire_atoms) != 17 or not 1 <= len(detectors) <= MAX_DETECTORS:
        raise ValueError(
            "Only seventeen-wire raw-T profiles "
            "with at most 20 detectors are supported."
        )
    return _detector_fault_channels(
        activity,
        channels,
        detectors,
        wire_atoms=wire_atoms,
        seed_atom=wire_atoms[4],
        world_atom_ids=world_atom_ids,
    )
