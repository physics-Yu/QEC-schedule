"""Exact Pauli detector signatures around an explicit, proven-independent T seed.

This propagates detector observables, not a Clifford approximation to a T state.
The actual T pulse is retained as an explicit proof checkpoint: every propagated
detector must be identity on its seed wire at that point. Other non-Clifford
operations, nondeterministic detectors and unsupported channels are rejected.
"""

from collections import defaultdict
from dataclasses import dataclass
from math import fsum, isclose, isfinite, pi
from typing import Any

from nadit_physical_compiler.activity import ActivityEvent, AtomActivity
from nadit_physical_compiler.cost.noise.report import PAULI_2_ORDER
from nadit_physical_compiler.methods.clifford import dependency, local_clifford

from .detector_probability import FaultChannel


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
        if event.kind == "CZPulse" and event.pairs:
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
    seed_atom: int,
    world_atom_ids: tuple[int, ...] | None = None,
) -> tuple[tuple[FaultChannel, ...], dict[str, Any]]:
    """Prove ideal detectors and obtain each actual noise branch's exact signature.

    Reverse measurement/reset maps reject any nondeterministic observable.
    Identity on the seed wire proves the T pulse has no effect on these detector
    probabilities. This statement does not extend to the logical output state.
    ``wire_atoms`` retains arbitrary participant roles; ``world_atom_ids``
    includes all occupied atoms, including spectators with independent noise.
    Omission assumes the participant-only world. Actual ideal operations
    must be confined to the participants; spectator CZ illumination is allowed,
    but cross-block ideal interactions and unrelated operations are rejected.
    """
    if not wire_atoms or not detectors:
        raise ValueError("Participant wires and detector list must be nonempty.")
    world_atom_ids = wire_atoms if world_atom_ids is None else world_atom_ids
    if (
        len(set(wire_atoms)) != len(wire_atoms)
        or len(set(world_atom_ids)) != len(world_atom_ids)
        or len(activity.per_atom) != len(world_atom_ids)
        or any(type(atom) is not int or atom < 0 for atom in wire_atoms)
        or any(type(atom) is not int or atom < 0 for atom in world_atom_ids)
        or not set(wire_atoms) <= set(world_atom_ids)
        or set(world_atom_ids) != {atom.atom_id for atom in activity.per_atom}
    ):
        raise ValueError("Raw participant and complete-world atom identities disagree.")
    if type(seed_atom) is not int or seed_atom not in wire_atoms:
        raise ValueError("The actual T seed atom must be a participant identity.")
    participants = set(wire_atoms)
    occupied = set(world_atom_ids)
    measured: dict[int, int] = {}
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
        if event.kind == "Measure":
            for atom, identity in zip(event.atoms, event.measurement_ids, strict=True):
                if type(identity) is not int or identity < 0 or identity in measured:
                    raise ValueError(
                        "Measurement identities must be unique nonnegative integers."
                    )
                measured[identity] = atom
    if any(not set(channel["atoms"]) <= occupied for channel in channels):
        raise ValueError("Noise channel names atoms outside the complete world.")
    for channel in channels:
        probabilities = channel["probabilities"]
        if any(
            isinstance(p, bool)
            or not isinstance(p, int | float)
            or not isfinite(p)
            or not 0 <= p <= 1
            for p in probabilities
        ):
            raise ValueError("Fault branch probability must be finite in [0,1].")
        if fsum(probabilities) > 1:
            raise ValueError("Exclusive fault branch probabilities exceed one.")
        if (
            channel["instruction"] == "M"
            or channel["placement"] == "measurement_argument"
        ):
            readout_identity = channel.get("measurement_id")
            if (
                channel["instruction"] != "M"
                or channel["placement"] != "measurement_argument"
                or readout_identity not in measured
                or tuple(channel["atoms"]) != (measured[readout_identity],)
            ):
                raise ValueError(
                    "Readout noise must match its actual measurement atom and identity."
                )
    stim = dependency("stim")
    # Every ideal gate/measurement acts only on these participants. Tracing out
    # spectators therefore drops only their Pauli tensor factors, while retaining
    # each complete-world channel and its exclusive branch probabilities.
    wires = {atom: index for index, atom in enumerate(wire_atoms)}
    width = len(wire_atoms)
    tokens = _timeline(activity, channels, wires, seed_atom)
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
        if len(set(channel["atoms"])) != len(channel["atoms"]):
            raise ValueError("A Pauli channel must use distinct atom identities.")
        current = []
        for label in labels:
            error = stim.PauliString(width)
            for atom, axis in zip(channel["atoms"], label, strict=True):
                if atom in wires:
                    error[wires[atom]] = axis
            current.append(error if error.weight else None)
        errors.append(current)
        weights.append(channel["probabilities"])
    signatures = [[0] * len(items) for items in errors]
    seed_checks = 0
    for detector_index, identities in enumerate(detectors):
        if any(type(identity) is not int or identity < 0 for identity in identities):
            raise ValueError("Detector identities must be nonnegative integers.")
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
                        else error is not None and not observable.commutes(error)
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
        "world_atom_count": len(world_atom_ids),
        "participant_atom_count": len(wire_atoms),
        "propagated_wire_count": width,
        "seed_atom": seed_atom,
        "spectator_projection": (
            "Trace spectator Pauli factors after checking isolated participant "
            "ideal operations; "
            "retain every complete-world channel and its exclusive probabilities"
        ),
        "zero_signature_channel_count": sum(not any(masks) for masks in signatures),
        "isolated_participant_operations_checked": True,
        "proof": (
            "Backward detector observables are identity on the seed at the real T pulse"
        ),
        "stim_version": stim.__version__,
        "logical_state_replaced_by_clifford_proxy": False,
    }
