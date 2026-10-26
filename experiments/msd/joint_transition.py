"""Explicit same-atom endpoint contracts for stateful joint calibration.

Ordinary frontiers must still return to their entry world. Only declared native
transport goals may change positions; this module does not route, schedule,
transfer token ownership or infer transported logical quality.
"""

from collections.abc import Mapping
from dataclasses import asdict, replace
from typing import Any

from nadit_physical_compiler.cost.base import require_validated
from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import (
    decode_layout,
    encode_device,
    encode_layout,
)
from nadit_physical_compiler.state import AtomLayout, SLMHolder, validate_layout

from modules.codes.rotated_surface.definition import SurfaceCodeDefinition, definition
from modules.codes.rotated_surface.geometry import SITE_PITCH_UM

from .standard import (
    ExperimentWorld,
    FactoryPatch,
    _decode_binding,
    _validate_current_world,
)

TransportTargets = Mapping[str, tuple[Position, tuple[str, ...]]]


def member_definition(
    world: ExperimentWorld, component: str, participants: tuple[FactoryPatch, ...]
) -> SurfaceCodeDefinition:
    """Resolve actual carrier codes; one CNOT cannot cross code or distance."""
    if len(participants) != (2 if component == "transversal_cnot" else 1) or len(
        {patch.binding.block_id for patch in participants}
    ) != len(participants):
        raise ValueError("JOINT_COMPONENT_PARTICIPANTS_MISMATCH")
    codes = tuple(
        world.block_definition(patch.binding.block_id) for patch in participants
    )
    if any(code != codes[0] for code in codes[1:]):
        raise ValueError("JOINT_COMPONENT_CODE_DISTANCE_MISMATCH")
    if any(
        len(patch.binding.atom_ids) != code.atom_count
        for patch, code in zip(participants, codes, strict=True)
    ):
        raise ValueError("JOINT_COMPONENT_BINDING_CODE_MISMATCH")
    return codes[0]


def member_code_contract(
    world: ExperimentWorld, code: SurfaceCodeDefinition
) -> dict[str, Any]:
    """Make mixed member identities explicit without changing uniform cache shape."""
    return (
        {"code_id": f"rotated_surface_d{code.distance}", "distance": code.distance}
        if world.spec.mixed_distances
        else {}
    )


def target_document(targets: TransportTargets | None) -> dict[str, Any]:
    """Serialize exact requested endpoints, without replacing current bindings."""
    return {
        member: {"origin": {"x": origin.x, "y": origin.y}, "home_sites": list(sites)}
        for member, (origin, sites) in sorted((targets or {}).items())
    }


def check_members(members: tuple[str, ...], targets: TransportTargets | None) -> None:
    """Require one explicit endpoint for every single-block translation member."""
    expected = {m for m in members if m.startswith("block_translation:")}
    if set(targets or {}) != expected or any(
        not m.split(":", 1)[1] or "," in m.split(":", 1)[1] for m in expected
    ):
        raise ValueError("JOINT_TRANSLATION_TARGET_COVERAGE_MISMATCH")


def expected_exit(
    entry: AtomLayout, device: Device, targets: Mapping[int, str]
) -> AtomLayout:
    """Derive an exact full-world endpoint independently of emitted actions.

    Atom identity, wire binding and all nonmoving atoms are retained. Unknown or
    colliding sites and atom identities fail rather than moving spectators.
    """
    if not set(targets) <= {atom.id for atom in entry.atoms}:
        raise ValueError("JOINT_TRANSLATION_UNKNOWN_ATOM")
    result = replace(
        entry,
        atoms=tuple(
            replace(
                atom,
                position=device.site(targets[atom.id]).position,
                holder=SLMHolder(targets[atom.id]),
            )
            if atom.id in targets
            else atom
            for atom in entry.atoms
        ),
    )
    validate_layout(device, result)
    return result


def validate_transition(action: Mapping[str, Any], trace: Mapping[str, Any]) -> None:
    """Check declared endpoint identity; native legality remains separately checked.

    Return-home records keep the historical strict equality rule. Stateful
    records must name the exact native goals, unchanged IDs and target SLM sites,
    as well as explicit binding updates. A trace hash alone is insufficient.
    """
    transition = action.get("state_transition")
    if transition is None:
        if trace.get("entry_state") != trace.get("exit_state"):
            raise ValueError("JOINT_UNDECLARED_WORLD_TRANSITION")
        if trace.get("transport_goals"):
            raise ValueError("JOINT_UNDECLARED_TRANSPORT_GOALS")
        return
    if (
        transition.get("schema") != "nadit.joint_world_transition/1"
        or "transport_goals" not in trace.get("validation", {}).get("checks", ())
        or not trace.get("transport_goals")
        or transition.get("entry_state_sha256") != canonical_hash(trace["entry_state"])
        or transition.get("exit_state_sha256") != canonical_hash(trace["exit_state"])
    ):
        raise ValueError("INVALID_JOINT_WORLD_TRANSITION")
    entry, exit_state = (
        decode_layout(trace["entry_state"]),
        decode_layout(trace["exit_state"]),
    )
    atoms = {atom.id: atom for atom in entry.atoms}
    targets = {}
    for goal in trace["transport_goals"]:
        for wire, site in goal["targets"]:
            atom = entry.qubit_to_atom[wire]
            if atom in targets:
                raise ValueError("JOINT_TRANSLATION_DUPLICATE_ATOM")
            targets[atom] = site
    declared = {}
    expected_members = {
        m for m in action["members"] if m.startswith("block_translation:")
    }
    if set(transition.get("bindings", {})) != expected_members:
        raise ValueError("JOINT_TRANSLATION_MEMBER_MISMATCH")
    sites = {site["id"]: site["position"] for site in trace["device"]["slm_sites"]}
    for member, update in transition.get("bindings", {}).items():
        if member not in action["members"] or not member.startswith(
            "block_translation:"
        ):
            raise ValueError("JOINT_TRANSLATION_MEMBER_MISMATCH")
        before, after = update["entry"], update["exit"]
        if any(before[key] != after[key] for key in ("block_id", "atom_ids", "aod_id")):
            raise ValueError("JOINT_TRANSLATION_IDENTITY_CHANGED")
        if before["block_id"] != member.split(":", 1)[1]:
            raise ValueError("JOINT_TRANSLATION_MEMBER_MISMATCH")
        coordinates = definition(update["distance"]).reference_coordinates
        renamed_homes = {}
        for atom, site, (x, y) in zip(
            after["atom_ids"], update["home_sites"], coordinates, strict=True
        ):
            if atom in declared or atom not in atoms:
                raise ValueError("JOINT_TRANSLATION_DUPLICATE_OR_UNKNOWN_ATOM")
            source = Position(
                before["origin"]["x"] + x * SITE_PITCH_UM,
                before["origin"]["y"] + y * SITE_PITCH_UM,
            )
            destination = Position(
                after["origin"]["x"] + x * SITE_PITCH_UM,
                after["origin"]["y"] + y * SITE_PITCH_UM,
            )
            if atoms[atom].position != source or Position(**sites[site]) != destination:
                raise ValueError("JOINT_TRANSLATION_BINDING_GEOMETRY_MISMATCH")
            holder = atoms[atom].holder
            if not isinstance(holder, SLMHolder) or holder.site_id in renamed_homes:
                raise ValueError("JOINT_TRANSLATION_INVALID_SOURCE_HOMES")
            renamed_homes[holder.site_id] = site
            declared[atom] = site
        try:
            source_aliases = dict(before["site_ids"])
            destination_aliases = dict(after["site_ids"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("JOINT_TRANSLATION_SITE_ALIAS_MISMATCH") from error
        if (
            len(source_aliases) != len(before["site_ids"])
            or len(destination_aliases) != len(after["site_ids"])
            or any(site not in renamed_homes for site in source_aliases.values())
            or destination_aliases
            != {name: renamed_homes[site] for name, site in source_aliases.items()}
        ):
            raise ValueError("JOINT_TRANSLATION_SITE_ALIAS_MISMATCH")
    if not targets or targets != declared:
        raise ValueError("JOINT_TRANSLATION_GOAL_BINDING_MISMATCH")
    expected = replace(
        entry,
        atoms=tuple(
            replace(
                atom,
                position=Position(**sites[targets[atom.id]]),
                holder=SLMHolder(targets[atom.id]),
            )
            if atom.id in targets
            else atom
            for atom in entry.atoms
        ),
    )
    if exit_state != expected or encode_layout(expected) != trace["exit_state"]:
        raise ValueError("JOINT_TRANSLATION_ENDPOINT_MISMATCH")


def apply_joint_transition(
    world: ExperimentWorld, action: Mapping[str, Any], trace: Mapping[str, Any]
) -> ExperimentWorld:
    """Apply verified same-atom endpoints without changing roles or token ownership.

    Saved native validation, the trace hash and the full current entry must agree.
    A compact trace wire map is local to the wave; the returned world retains its
    original map, Device and PlacementPlan objects. A return-home wave returns
    ``world`` itself. Invalid, stale or inconsistent evidence raises ValueError.
    No compiler, router, layout generator or token ledger is invoked.
    """
    try:
        require_validated(trace)
        if (
            action.get("schema") != "nadit.joint_actions/1"
            or action.get("validation_ok") is not True
            or action.get("trace_sha256") != canonical_hash(trace)
        ):
            raise ValueError("JOINT_TRANSITION_INVALID_ACTION_PROOF")
        validate_transition(action, trace)
        entry = decode_layout(trace["entry_state"])
        if (
            trace["device"] != encode_device(world.device)
            or entry.atoms != world.state.atoms
            or entry.aod_grids != world.state.aod_grids
        ):
            raise ValueError("JOINT_TRANSITION_CURRENT_WORLD_MISMATCH")
        transition = action.get("state_transition")
        if transition is None:
            return world
        patches = {patch.binding.block_id: patch for patch in world.patches}
        for member, update in transition["bindings"].items():
            identity = member.split(":", 1)[1]
            patch = patches[identity]
            if update["distance"] != world.block_definition(
                identity
            ).distance or canonical_hash(update["entry"]) != canonical_hash(
                asdict(patch.binding)
            ):
                raise ValueError("JOINT_TRANSITION_CURRENT_BINDING_MISMATCH")
            patches[identity] = replace(
                patch,
                binding=_decode_binding(update["exit"]),
                home_sites=tuple(update["home_sites"]),
            )
        result = replace(
            world,
            state=replace(
                decode_layout(trace["exit_state"]),
                qubit_to_atom=world.state.qubit_to_atom,
            ),
            patches=tuple(patches[patch.binding.block_id] for patch in world.patches),
        )
        _validate_current_world(result)
        return result
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        raise ValueError(f"JOINT_TRANSITION_APPLICATION_FAILED: {error}") from error
