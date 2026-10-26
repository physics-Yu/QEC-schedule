"""Bounded exact detector probabilities for the approved raw-T Pauli model.

This propagates detector observables, not a Clifford approximation to a T state.
The actual T pulse is retained as an explicit proof checkpoint: every propagated
detector must be identity on its seed wire at that point. Other non-Clifford
operations, nondeterministic detectors and unsupported channels are rejected.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import fsum, isclose, isfinite, pi
from typing import Any

import numpy as np
from nadit_physical_compiler.activity import ActivityEvent, AtomActivity
from nadit_physical_compiler.cost.noise.report import PAULI_2_ORDER
from nadit_physical_compiler.methods.clifford import dependency, local_clifford

MAX_DETECTORS = 20
type FaultChannel = tuple[tuple[int, float], ...]


def xor_distribution(
    detector_count: int, channels: Sequence[Sequence[tuple[int, float]]]
) -> tuple[float, ...]:
    """Convolve independent channels, preserving exclusive alternatives within each.

    Each branch is (detector-flip bitmask, probability); the residual channel
    weight is identity. Repeated masks are combined exactly as alternatives.
    No probabilities are renormalized. More than 20 detectors is rejected.
    """
    if type(detector_count) is not int or not 1 <= detector_count <= MAX_DETECTORS:
        raise ValueError(f"Detector count must be between 1 and {MAX_DETECTORS}.")
    size = 1 << detector_count
    indices = np.arange(size)
    distribution = np.zeros(size)
    distribution[0] = 1
    for channel in channels:
        grouped: dict[int, list[float]] = defaultdict(list)
        total = []
        for mask, probability in channel:
            if type(mask) is not int or not 0 <= mask < size:
                raise ValueError("Fault branch mask is outside the detector space.")
            if (
                isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not isfinite(probability)
                or not 0 <= probability <= 1
            ):
                raise ValueError("Fault branch probability must be finite in [0,1].")
            total.append(probability)
            if mask:
                grouped[mask].append(probability)
        if fsum(total) > 1:
            raise ValueError("Exclusive fault branch probabilities exceed one.")
        weights = {mask: fsum(values) for mask, values in grouped.items()}
        if not weights:
            continue
        updated = (1 - fsum(weights.values())) * distribution
        for mask, probability in weights.items():
            updated += probability * distribution[indices ^ mask]
        distribution = updated
    if not isclose(float(distribution.sum()), 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError("Detector convolution lost probability mass.")
    return tuple(float(value) for value in distribution)


@dataclass(frozen=True)
class _Token:
    kind: str
    value: Any


def _ideal_tokens(
    event: ActivityEvent, wires: dict[int, int], *, center_atom: int, entangled: bool
) -> list[_Token]:
    stim = dependency("stim")
    if event.kind in ("Rotation", "GlobalRY", "LocalU"):
        p = event.parameters
        kind = "U" if event.kind == "LocalU" else p["axis"]
        values = (p["theta"], p["phi"], p["lam"]) if kind == "U" else (p["angle"],)
        try:
            local = local_clifford(kind, values)
        except ValueError as error:
            if (
                event.kind != "Rotation"
                or kind != "Z"
                or event.atoms != (center_atom,)
                or not isclose(values[0], pi / 4, rel_tol=0, abs_tol=1e-12)
                or entangled
            ):
                raise ValueError(
                    "Unsupported non-Clifford action or seed location."
                ) from error
            return [_Token("seed_t", wires[center_atom])]
        tableau = stim.Tableau.from_circuit(local)
        return [_Token("unitary", (tableau, (wires[a],))) for a in event.atoms]
    if event.kind == "CZPulse":
        return [
            _Token(
                "unitary", (stim.Tableau.from_named_gate("CZ"), (wires[a], wires[b]))
            )
            for a, b in event.pairs
        ]
    if event.kind == "Reset":
        return [_Token("reset", wires[a]) for a in event.atoms]
    if event.kind == "Measure":
        return [
            _Token("measure", (wires[a], mid))
            for a, mid in zip(event.atoms, event.measurement_ids, strict=True)
        ]
    if event.kind not in ("Load", "Move", "Store", "Wait"):
        raise ValueError(f"Unsupported action {event.kind!r}.")
    return []


def _timeline(
    activity: AtomActivity,
    channels: list[dict[str, Any]],
    wires: dict[int, int],
    center_atom: int,
) -> list[_Token]:
    before: dict[int, list[int]] = defaultdict(list)
    after: dict[int, list[int]] = defaultdict(list)
    readout: dict[int, int] = {}
    schedule: list[tuple[float, int, int, str, Any]] = []
    for index, channel in enumerate(channels):
        if channel["placement"] == "measurement_argument":
            readout[channel["measurement_id"]] = index
        elif "event_id" in channel:
            table = before if channel["placement"] == "before" else after
            table[channel["event_id"]].append(index)
        else:
            schedule.append(
                (channel["start_us"] + channel["duration_us"], -1, 0, "noise", index)
            )
    for index, event in enumerate(activity.events):
        schedule.append(
            (
                event.start_us + event.duration_us,
                event.step_index,
                event.action_index,
                "action",
                (index, event),
            )
        )
    tokens, entangled = [], False
    for _, _, _, kind, value in sorted(schedule, key=lambda item: item[:3]):
        if kind == "noise":
            tokens.append(_Token("noise", value))
            continue
        index, event = value
        tokens.extend(_Token("noise", i) for i in before[index])
        tokens.extend(
            _ideal_tokens(event, wires, center_atom=center_atom, entangled=entangled)
        )
        if event.kind == "CZPulse":
            entangled = True
        if event.kind == "Measure":
            tokens.extend(
                _Token("noise", readout[mid])
                for mid in event.measurement_ids
                if mid in readout
            )
        tokens.extend(_Token("noise", i) for i in after[index])
    consumed = sorted(token.value for token in tokens if token.kind == "noise")
    if consumed != list(range(len(channels))):
        raise ValueError(
            "Every noise channel must map to exactly one timeline location."
        )
    if sum(token.kind == "seed_t" for token in tokens) != 1:
        raise ValueError(
            "The approved raw-T profile requires exactly one seed T pulse."
        )
    return tokens


def detector_fault_channels(
    activity: AtomActivity,
    channels: list[dict[str, Any]],
    detectors: tuple[tuple[int, ...], ...],
    *,
    wire_atoms: tuple[int, ...],
    world_atom_ids: tuple[int, ...] | None = None,
) -> tuple[tuple[FaultChannel, ...], dict[str, Any]]:
    """Prove ideal detectors and obtain each actual noise branch's exact signature.

    Reverse measurement/reset maps reject any nondeterministic observable.
    Identity on the seed wire proves the T pulse has no effect on these detector
    probabilities. This statement does not extend to the logical output state.
    ``wire_atoms`` retains the seventeen protocol roles; ``world_atom_ids``
    includes all occupied atoms, including spectators with independent noise.
    Omission retains the original seventeen-atom API. Actual ideal operations
    must be confined to the participants; spectator CZ illumination is allowed,
    but cross-block ideal interactions and unrelated operations are rejected.
    """
    if len(wire_atoms) != 17 or not 1 <= len(detectors) <= MAX_DETECTORS:
        raise ValueError(
            "Only seventeen-wire raw-T profiles "
            "with at most 20 detectors are supported."
        )
    world_atom_ids = wire_atoms if world_atom_ids is None else world_atom_ids
    if (
        len(set(wire_atoms)) != 17
        or len(set(world_atom_ids)) != len(world_atom_ids)
        or len(activity.per_atom) != len(world_atom_ids)
        or any(type(atom) is not int or atom < 0 for atom in wire_atoms)
        or any(type(atom) is not int or atom < 0 for atom in world_atom_ids)
        or not set(wire_atoms) <= set(world_atom_ids)
        or set(world_atom_ids) != {atom.atom_id for atom in activity.per_atom}
    ):
        raise ValueError("Raw participant and complete-world atom identities disagree.")
    participants = set(wire_atoms)
    occupied = set(world_atom_ids)
    for event in activity.events:
        if not set(event.atoms) <= occupied:
            raise ValueError("Activity names atoms outside the complete world.")
        if event.kind == "CZPulse":
            if any(not set(pair) <= participants for pair in event.pairs):
                raise ValueError(
                    "Isolated raw preparation requires participant-only CZ."
                )
        elif not set(event.atoms) <= participants:
            raise ValueError(
                "Isolated raw preparation has an unexpected participant action."
            )
    if any(not set(channel["atoms"]) <= occupied for channel in channels):
        raise ValueError("Noise channel names atoms outside the complete world.")
    stim = dependency("stim")
    wires = {atom: index for index, atom in enumerate(world_atom_ids)}
    width = len(world_atom_ids)
    tokens = _timeline(activity, channels, wires, wire_atoms[4])
    errors: list[list[Any]] = []
    weights: list[list[float]] = []
    for channel in channels:
        name = channel["instruction"]
        labels = {
            "PAULI_CHANNEL_1": ["X", "Y", "Z"],
            "PAULI_CHANNEL_2": PAULI_2_ORDER,
            "X_ERROR": ["X"],
            "Z_ERROR": ["Z"],
            "M": ["I"],
        }.get(name)
        if labels is None or len(labels) != len(channel["probabilities"]):
            raise ValueError(f"Unsupported noise instruction {name!r}.")
        current = []
        for label in labels:
            error = stim.PauliString(width)
            for atom, axis in zip(channel["atoms"], label, strict=True):
                error[wires[atom]] = axis
            current.append(error)
        errors.append(current)
        weights.append(channel["probabilities"])
    signatures = [[0] * len(items) for items in errors]
    seed_checks = 0
    for detector_index, identities in enumerate(detectors):
        selected = set(identities)
        if len(selected) != len(identities):
            raise ValueError("A detector must not repeat a measurement identity.")
        observable = stim.PauliString(width)
        visited = set()
        for token in reversed(tokens):
            if token.kind == "noise":
                index = token.value
                channel = channels[index]
                for branch, error in enumerate(errors[index]):
                    flips = (
                        channel["measurement_id"] in selected
                        if channel["instruction"] == "M"
                        else not observable.commutes(error)
                    )
                    if flips:
                        signatures[index][branch] |= 1 << detector_index
            elif token.kind == "unitary":
                tableau, targets = token.value
                observable = observable.before(tableau, targets)
            elif token.kind == "seed_t":
                if observable[token.value] != 0:
                    raise ValueError("Detector depends on the non-Clifford seed state.")
                seed_checks += 1
            elif token.kind == "reset":
                if observable[token.value] not in (0, 3):
                    raise ValueError("Detector is not deterministic through reset.")
                observable[token.value] = 0
            elif token.kind == "measure":
                wire, identity = token.value
                if observable[wire] not in (0, 3):
                    raise ValueError(
                        "Detector crosses incompatible projective measurement."
                    )
                if identity in selected:
                    factor = stim.PauliString(width)
                    factor[wire] = "Z"
                    observable *= factor
                    visited.add(identity)
        if visited != selected or observable != stim.PauliString(width):
            raise ValueError(
                "Detector is not an ideal zero parity of this action sequence."
            )
    result = tuple(
        tuple(zip(masks, ps, strict=True))
        for masks, ps in zip(signatures, weights, strict=True)
    )
    return result, {
        "center_t_identity_checks": seed_checks,
        "non_clifford_seed_gates": 1,
        "detector_count": len(detectors),
        "world_atom_count": width,
        "participant_atom_count": len(wire_atoms),
        "isolated_participant_operations_checked": True,
        "proof": (
            "Backward detector observables are identity on the seed at the real T pulse"
        ),
        "stim_version": stim.__version__,
        "logical_state_replaced_by_clifford_proxy": False,
    }
