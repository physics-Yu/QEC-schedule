"""Pure d3 execution declarations for local and translated component calls.

The local profile uses the approved seven-by-seven home/guest tile and its own
readout strip. Horizontal CNOT pairs retain both patches and their full corridor.
These profiles are narrower than arbitrary Device support; no compilation probes
eligibility. Addressed local corrections have no transport or readout claim.
"""

from dataclasses import asdict, replace
from math import isclose
from typing import Any

from nadit_physical_compiler.device import Device, Position, Region
from nadit_physical_compiler.provenance import canonical_hash

from ..._support.raw_t_round_policy import (
    RAW_T_PROTOCOL_VERSION,
    resolve_postselection_rounds,
)
from ...contracts.component import ComponentBinding
from ...contracts.parallel import ComponentExecutionSpec, SharedAODClaim, SpaceClaim
from ..components import get_component
from ..components.transversal import TransversalCNOTComponent

LOCKSTEP_COMPONENTS = frozenset(
    (
        "initialize_0",
        "initialize_plus",
        "se_round",
        "raw_t",
        "raw_t_postselection",
        "logical_s",
        "logical_x",
        "logical_z",
        "logical_mx",
        "logical_mz",
    )
)
PROFILE_ID = "rotated_surface_d3.synchronized_local_strip/2"
LOCAL_PAULIS = frozenset(("logical_x", "logical_z"))
LOCAL_PROFILE_ID = "rotated_surface_d3.local_addressed_pauli/1"
PAIR_PROFILE_ID = "rotated_surface_d3.synchronized_horizontal_pair/1"
MEASUREMENT_COMPONENTS = frozenset(("logical_mx", "logical_mz"))


def local_envelope(origin: Position) -> Region:
    """Include the home/guest array, readout strip, and conservative margins."""
    return Region(origin.x - 5, origin.y - 5, origin.x + 70, origin.y + 115)


def _contains(outer: Region, inner: Region) -> bool:
    return outer.contains(Position(inner.x_min, inner.y_min)) and outer.contains(
        Position(inner.x_max, inner.y_max)
    )


def reference_origin(device: Device) -> Position | None:
    """Choose the same fixed reference tile regardless of call visitation order."""
    points = [
        device.site(site).position
        for array in device.pair_arrays
        for row in array.left
        for site in row
    ]
    return min(points, key=lambda point: (point.y, point.x)) if points else None


def _tile(device: Device, origin: Position) -> bool:
    pairs = {
        (device.site(left).position, device.site(right).position)
        for array in device.pair_arrays
        for left, right in array.pairs
    }
    return all(
        (
            Position(origin.x + 10 * x, origin.y + 10 * y),
            Position(origin.x + 10 * x + 2, origin.y + 10 * y),
        )
        in pairs
        for y in range(7)
        for x in range(7)
    )


def local_reference_device(device: Device, aod_id: str) -> Device:
    """Constrain reference lowering and illumination to the declared local strip.

    This code-owned view retains real IDs and timing. Expansion still validates
    against the caller's full Device and complete spectator world.
    """
    origin = reference_origin(device)
    if origin is None:
        raise ValueError("Local template profile requires a reference home array.")
    envelope = local_envelope(origin)
    homes = Region(origin.x, origin.y, origin.x + 60, origin.y + 60)
    return _reference_device(device, aod_id, envelope, homes)


def _reference_device(
    device: Device, aod_id: str, envelope: Region, homes: Region
) -> Device:
    zones = []
    for zone in device.zones:
        left, bottom = (
            max(zone.bounds.x_min, envelope.x_min),
            max(zone.bounds.y_min, envelope.y_min),
        )
        right, top = (
            min(zone.bounds.x_max, envelope.x_max),
            min(zone.bounds.y_max, envelope.y_max),
        )
        if left <= right and bottom <= top:
            zones.append(replace(zone, bounds=Region(left, bottom, right, top)))
    arrays = []
    for array in device.pair_arrays:
        selected = [
            tuple(
                (left, right)
                for left, right in zip(ls, rs, strict=True)
                if homes.contains(device.site(left).position)
                and envelope.contains(device.site(right).position)
            )
            for ls, rs in zip(array.left, array.right, strict=True)
        ]
        selected = [row for row in selected if row]
        if selected:
            arrays.append(
                replace(
                    array,
                    left=tuple(tuple(left for left, _ in row) for row in selected),
                    right=tuple(tuple(right for _, right in row) for row in selected),
                )
            )
    return replace(
        device,
        name=device.name + ".local-component-profile",
        zones=tuple(zones),
        slm_sites=tuple(
            site for site in device.slm_sites if envelope.contains(site.position)
        ),
        pair_arrays=tuple(arrays),
        aods=(replace(device.aod(aod_id), workspace=envelope),),
    )


def pair_reference_origins(
    device: Device, control: ComponentBinding, target: ComponentBinding
) -> tuple[Position, Position]:
    """Anchor a horizontal pair independently of visitation order.

    Return control and target origins with the same signed displacement. The
    left patch starts at the first reference tile. Raise ValueError when the
    device has no reference tile or the input pair is not horizontal.
    """
    origin = reference_origin(device)
    if origin is None or not isclose(
        control.origin.y, target.origin.y, rel_tol=0, abs_tol=1e-9
    ):
        raise ValueError(
            "Pair profile requires reference tiles and horizontal patches."
        )
    displacement = target.origin.x - control.origin.x
    return (
        Position(origin.x + max(-displacement, 0), origin.y),
        Position(origin.x + max(displacement, 0), origin.y),
    )


def _pair_envelope(control: Position, target: Position) -> Region:
    return Region(
        min(control.x, target.x) - 5,
        control.y - 5,
        max(control.x, target.x) + 70,
        control.y + 65,
    )


def pair_reference_device(
    device: Device,
    aod_id: str,
    control_origin: Position,
    target_origin: Position,
) -> Device:
    """Restrict pair compilation and CZ illumination to its declared corridor.

    Origins must be a supported canonical pair. Timing, capabilities and actual
    trap IDs are retained; later expansion validates the complete real world.
    """
    if not isclose(control_origin.y, target_origin.y, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Pair reference origins must share one row origin.")
    homes = Region(
        min(control_origin.x, target_origin.x),
        control_origin.y,
        max(control_origin.x, target_origin.x) + 60,
        control_origin.y + 60,
    )
    return _reference_device(
        device, aod_id, _pair_envelope(control_origin, target_origin), homes
    )


def _zone(device: Device, operation: str, region: Region) -> bool:
    return any(
        operation in zone.operations and _contains(zone.bounds, region)
        for zone in device.zones
    )


def supports_local_profile(
    device: Device,
    binding: ComponentBinding,
    *,
    peak_readout_atoms: int = 8,
    peak_grid_lines: int = 4,
) -> bool:
    """Check static geometry/capabilities, never inspect or generate atom actions."""
    if binding.site_ids:
        # Explicit per-template keys retain their existing serial semantics.
        return False
    reference = reference_origin(device)
    aod = device.aod(binding.aod_id)
    if (
        reference is None
        or device.cz is None
        or device.local is None
        or device.readout is None
    ):
        return False
    if (
        aod.motion != "flexible"
        or aod.min_spacing > 1
        or any(
            capacity is not None and capacity < peak_grid_lines
            for capacity in (aod.max_rows, aod.max_columns)
        )
        or not 2 <= device.cz.radius_um < 8
        or ("slm", "slm") not in device.cz.holder_pairs
        or not device.cz.allow_spectators
        or "slm" not in device.local.holders
        or not device.readout.retain_atoms
        or "aod" not in device.readout.holders
        or (
            device.readout.max_atoms is not None
            and device.readout.max_atoms < peak_readout_atoms
        )
        or device.readout.min_spacing_um > 5
        or not isclose(binding.origin.y, reference.y, rel_tol=0, abs_tol=1e-9)
    ):
        return False
    for origin in (reference, binding.origin):
        if not _contains(aod.workspace, local_envelope(origin)) or not _tile(
            device, origin
        ):
            return False
        homes = Region(origin.x, origin.y, origin.x + 62, origin.y + 60)
        if any(
            not _zone(device, operation, homes)
            for operation in ("cz", "rotate", "reset")
        ):
            return False
        if not _zone(
            device,
            "measure",
            Region(origin.x, origin.y + 90, origin.x + 60, origin.y + 110),
        ):
            return False
    return True


def _supports_pair_profile(
    device: Device, participants: tuple[ComponentBinding, ...]
) -> bool:
    if len(participants) != 2 or any(p.site_ids for p in participants):
        return False
    control, target = participants
    reference = reference_origin(device)
    aod = device.aod(control.aod_id)
    if (
        reference is None
        or device.local is None
        or device.cz is None
        or device.readout is None
        or aod.motion != "flexible"
        or aod.min_spacing > 1
        or any(
            capacity is not None and capacity < 3
            for capacity in (aod.max_rows, aod.max_columns)
        )
        or not 2 <= device.cz.radius_um < 8
        or ("slm", "slm") not in device.cz.holder_pairs
        or not device.cz.allow_spectators
        or "slm" not in device.local.holders
        or abs(target.origin.x - control.origin.x) < 70
        or any(
            not isclose(p.origin.y, reference.y, rel_tol=0, abs_tol=1e-9)
            for p in participants
        )
    ):
        return False
    for left, right in (
        (control.origin, target.origin),
        pair_reference_origins(device, control, target),
    ):
        if (
            not _contains(aod.workspace, _pair_envelope(left, right))
            or not _tile(device, left)
            or not _tile(device, right)
        ):
            return False
        homes = Region(
            min(left.x, right.x), left.y, max(left.x, right.x) + 62, left.y + 60
        )
        if any(not _zone(device, op, homes) for op in ("cz", "rotate")):
            return False
    return True


def _describe_pair(
    device: Device, participants: tuple[ComponentBinding, ...]
) -> ComponentExecutionSpec:
    control, target = participants
    aod = device.aod(control.aod_id)
    if not _supports_pair_profile(device, participants):
        return ComponentExecutionSpec(
            "rotated_surface_d3",
            "transversal_cnot",
            None,
            tuple(p.block_id for p in participants),
            (SpaceClaim(aod.workspace, "exclusive_transport"),),
            (f"aod:{aod.id}",),
            "exclusive",
            0,
        )
    assert (
        device.readout is not None
        and device.local is not None
        and device.cz is not None
    )
    waveform = (
        PAIR_PROFILE_ID
        + ":"
        + canonical_hash(
            {
                "source": TransversalCNOTComponent().source_qasm,
                "displacement_x": float(target.origin.x - control.origin.x),
                "timing": asdict(device.timing),
                "cz": asdict(device.cz),
                "local": asdict(device.local),
                "aod": {
                    "motion": aod.motion,
                    "min_spacing": aod.min_spacing,
                    "max_rows": aod.max_rows,
                    "max_columns": aod.max_columns,
                },
            }
        )
    )
    claim = SharedAODClaim(
        aod.id,
        canonical_hash(
            {"waveform_key": waveform, "row_origin_y": float(control.origin.y)}
        ),
        min(control.origin.x, target.origin.x),
        max(control.origin.x, target.origin.x) + 62,
        3,
        3,
        aod.max_rows,
        aod.max_columns,
        device.readout.channel,
        0,
        device.readout.max_atoms,
        aod.min_spacing,
    )
    return ComponentExecutionSpec(
        "rotated_surface_d3",
        "transversal_cnot",
        waveform,
        tuple(p.block_id for p in participants),
        (SpaceClaim(_pair_envelope(control.origin, target.origin), "pair_transport"),),
        (),
        "shared_aod_lockstep",
        0,
        claim,
    )


def describe_execution(
    device: Device,
    component_id: str,
    participants: tuple[ComponentBinding, ...],
    parameters: dict[str, Any],
) -> ComponentExecutionSpec:
    """Declare a known call after the backend has checked identity/home bindings."""
    first = participants[0]
    aod = device.aod(first.aod_id)
    if component_id == "transversal_cnot":
        return _describe_pair(device, participants)
    source: tuple[str, ...]
    rounds: int | None = None
    if component_id.endswith("/canonicalize"):
        result_count, source = 0, ()
    elif component_id == "raw_t_postselection":
        rounds = resolve_postselection_rounds(3, parameters.get("extra_rounds"))
        result_count = 8 * (1 + rounds)
        source = (
            get_component("raw_t").source_qasm,
            get_component("se_round").source_qasm,
        )
    else:
        component = get_component(component_id)
        result_count, source = (
            len(component.description.measurements),
            (component.source_qasm,),
        )
    local_pauli = component_id in LOCAL_PAULIS
    local_addressing = local_pauli or component_id.endswith("/canonicalize")
    local_parallel = local_addressing and (
        device.local is not None
        and device.cz is not None
        and device.readout is not None
        and "slm" in device.local.holders
        and aod.motion == "flexible"
        and reference_origin(device) is not None
        and not first.site_ids
    )
    peak_readout = 9 if component_id in MEASUREMENT_COMPONENTS else 8
    peak_grid = 3 if component_id in MEASUREMENT_COMPONENTS else 4
    parallel = local_parallel or (
        component_id in LOCKSTEP_COMPONENTS
        and not local_addressing
        and supports_local_profile(
            device,
            first,
            peak_readout_atoms=peak_readout,
            peak_grid_lines=peak_grid,
        )
    )
    waveform = None
    if local_parallel:
        assert device.local is not None
        waveform = (
            LOCAL_PROFILE_ID
            + ":"
            + canonical_hash(
                {"timing": asdict(device.timing), "local": asdict(device.local)}
            )
        )
    elif parallel:
        waveform = (
            PROFILE_ID
            + ":"
            + canonical_hash(
                {
                    "component_id": component_id,
                    "source": source,
                    "extra_rounds": rounds,
                    "raw_protocol_version": RAW_T_PROTOCOL_VERSION
                    if rounds is not None
                    else None,
                    "raw_round_policy": "distance" if rounds is not None else None,
                    "timing": asdict(device.timing),
                    "cz": asdict(device.cz) if device.cz is not None else None,
                    "local": asdict(device.local) if device.local is not None else None,
                    "readout": asdict(device.readout)
                    if device.readout is not None
                    else None,
                    "aod": {
                        "motion": aod.motion,
                        "min_spacing": aod.min_spacing,
                        "max_rows": aod.max_rows,
                        "max_columns": aod.max_columns,
                    },
                }
            )
        )
    shared = None
    if parallel and not local_addressing:
        assert device.readout is not None and waveform is not None
        shared = SharedAODClaim(
            first.aod_id,
            canonical_hash({"waveform_key": waveform, "row_origin_y": first.origin.y}),
            first.origin.x,
            first.origin.x + 62,
            peak_grid,
            peak_grid,
            aod.max_rows,
            aod.max_columns,
            device.readout.channel,
            peak_readout,
            device.readout.max_atoms,
            aod.min_spacing,
        )
    return ComponentExecutionSpec(
        "rotated_surface_d3",
        component_id,
        waveform,
        tuple(participant.block_id for participant in participants),
        (
            SpaceClaim(
                Region(
                    first.origin.x,
                    first.origin.y,
                    first.origin.x + 60,
                    first.origin.y + 60,
                ),
                "local_addressing",
            ),
        )
        if local_addressing
        else (SpaceClaim(local_envelope(first.origin), "local_transport_and_readout"),)
        if parallel
        else (SpaceClaim(aod.workspace, "exclusive_transport"),),
        () if local_addressing or shared is not None else (f"aod:{first.aod_id}",),
        "local_parallel"
        if local_parallel
        else "shared_aod_lockstep"
        if shared is not None
        else "exclusive",
        result_count,
        shared,
    )
