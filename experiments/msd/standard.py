"""User-selected MSD timing, vertical placement and unbounded-domain convention.

The physical compiler uses finite Region objects. A geometry-derived window is
therefore an execution representation, not a physical area/capacity budget.
Benchmark acceptance additionally checks invariance under window enlargement.
"""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from math import hypot, isfinite
from pathlib import Path
from typing import Any

from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import (
    Device,
    PairArray,
    Position,
    Region,
    SLMSite,
    Zone,
    loads_device,
)
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.serialization import (
    decode_layout,
    encode_device,
    encode_layout,
)
from nadit_physical_compiler.state import (
    COORDINATE_TOLERANCE,
    AtomLayout,
    AtomState,
    SLMHolder,
    validate_layout,
)
from nadit_physical_compiler.transport.occupancy import Occupancy

from modules.codes.contracts.component import ComponentBinding
from modules.codes.rotated_surface import SurfaceCodeDefinition, definition
from modules.codes.rotated_surface.geometry import geometry
from modules.codes.rotated_surface_d3.protocols.factory import factory_recipe
from modules.logical_compiler.src.placement import (
    BlockSpec,
    PlacementPlan,
    PlacementRequest,
    VerticalFactoryPlacement,
    place,
    validate_plan,
)

STANDARD_ID = "nadit.msd.standard/2"
_FACTORY_RECIPE = factory_recipe()
FACTORY_ROLES = (*_FACTORY_RECIPE.work_roles, _FACTORY_RECIPE.resource_role)
REFERENCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "modules/codes/rotated_surface_d3/configs/nonzoned_cnot_reference.json"
)
SITE_PITCH_UM = 10.0
PAIR_SEPARATION_UM = 2.0
HALFPLANE_GAP_UM = 50.0


@dataclass(frozen=True)
class ExperimentSpec:
    """Independent distance/pipeline controls with explicit physical gaps.

    Odd distances and positive pipeline counts are accepted. Gaps and window
    padding are positive micrometers. Resource limits belong to a run manifest.
    """

    distance: int = 3
    pipelines: int = 1
    patch_gap_um: float = 40.0
    factory_gap_um: float = 40.0
    window_padding_um: float = 20.0
    factory_distances: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if (
            type(self.distance) is not int
            or self.distance < 3
            or self.distance % 2 != 1
        ):
            raise ValueError("Distance must be an odd integer >= 3.")
        if type(self.pipelines) is not int or self.pipelines < 1:
            raise ValueError("Pipeline count must be a positive integer.")
        if self.factory_distances is not None:
            if (
                not isinstance(self.factory_distances, (tuple, list))
                or len(self.factory_distances) != self.pipelines
                or any(
                    type(d) is not int or d < 3 or d % 2 != 1
                    for d in self.factory_distances
                )
                or max(self.factory_distances) != self.distance
            ):
                raise ValueError(
                    "Factory distances must match pipelines and declared maximum distance."
                )
            object.__setattr__(self, "factory_distances", tuple(self.factory_distances))
        for name in ("patch_gap_um", "factory_gap_um", "window_padding_um"):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        if self.patch_gap_um % SITE_PITCH_UM:
            raise ValueError("Patch gap must be a multiple of the 10 um site pitch.")

    def factory_distance(self, index: int) -> int:
        """Return one factory's initial distance; reject an absent factory index."""
        if type(index) is not int or not 0 <= index < self.pipelines:
            raise ValueError("INVALID_FACTORY_DISTANCE_INDEX")
        return (
            self.distance
            if self.factory_distances is None
            else self.factory_distances[index]
        )

    @property
    def mixed_distances(self) -> bool:
        """Whether configured factories have distinct initial code distances."""
        return (
            self.factory_distances is not None and len(set(self.factory_distances)) > 1
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize parameters while retaining the exact historical uniform shape.

        distance is the declared maximum when factory_distances is provided.
        Use this method rather than asdict when constructing persisted payloads.
        """
        result = asdict(self)
        if self.factory_distances is None:
            del result["factory_distances"]
        else:
            result["factory_distances"] = list(self.factory_distances)
        return result


@dataclass(frozen=True)
class FactoryPatch:
    """One explicitly placed code block and its retained atom identities."""

    factory_index: int
    role: str
    binding: ComponentBinding
    home_sites: tuple[str, ...]
    code: str | None = None
    distance: int | None = None

    def __post_init__(self) -> None:
        if self.code is None and self.distance is None:
            return
        if (
            type(self.distance) is not int
            or self.distance < 3
            or self.distance % 2 != 1
            or self.code != f"rotated_surface_d{self.distance}"
        ):
            raise ValueError("MSD_PATCH_CODE_DISTANCE_MISMATCH")

    def to_dict(self) -> dict[str, Any]:
        """Retain old uniform fields, adding current code metadata only explicitly."""
        result = asdict(self)
        if self.code is None:
            del result["code"], result["distance"]
        return result


@dataclass(frozen=True)
class ExperimentWorld:
    """An unprepared complete atom world; no parallel execution is implied."""

    spec: ExperimentSpec
    device: Device
    state: AtomLayout
    patches: tuple[FactoryPatch, ...]
    placement_plan: PlacementPlan

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "ExperimentWorld":
        """Restore an exact current world without generating a default placement.

        The original plan remains provenance: current bindings may be translated,
        and explicitly vacant receiving slots may have no patch or atoms. Device
        values and the complete saved wire map are retained. Raises ValueError
        for inconsistent schema, metadata, geometry, homes or binding identities.
        """
        try:
            data = json.loads(json.dumps(dict(document), allow_nan=False))
            if (
                data.get("schema") != "nadit.msd.world/1"
                or data.get("standard") != STANDARD_ID
            ):
                raise ValueError("INVALID_MSD_WORLD_SCHEMA")
            world = cls(
                ExperimentSpec(**data["parameters"]),
                loads_device(json.dumps(data["device"], allow_nan=False)),
                decode_layout(data["entry_state"]),
                tuple(
                    FactoryPatch(
                        row["factory_index"],
                        row["role"],
                        _decode_binding(row["binding"]),
                        tuple(row["home_sites"]),
                        row.get("code"),
                        row.get("distance"),
                    )
                    for row in data["patches"]
                ),
                PlacementPlan.from_dict(data["placement"]),
            )
            _validate_current_world(world)
            if json.loads(json.dumps(world.document(), allow_nan=False)) != data:
                raise ValueError("MSD_WORLD_DOCUMENT_METADATA_MISMATCH")
            return world
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"INVALID_MSD_WORLD_DOCUMENT: {error}") from error

    def patch(self, factory_index: int, role: str) -> FactoryPatch:
        """Return one patch; raise KeyError for an absent index/role."""
        for patch in self.patches:
            if (patch.factory_index, patch.role) == (factory_index, role):
                return patch
        raise KeyError((factory_index, role))

    def block_definition(self, block_id: str) -> SurfaceCodeDefinition:
        """Resolve a member's current code, independent of the world's maximum.

        Explicit converted bindings are accepted only within the declared maximum;
        this queries code metadata, not proof that a conversion protocol executed.
        """
        for patch in self.patches:
            if patch.binding.block_id == block_id:
                return _patch_definition(self.spec, patch)
        raise KeyError(block_id)

    def document(self) -> dict[str, Any]:
        """Export exact physical interfaces and the independent model convention."""
        return {
            "schema": "nadit.msd.world/1",
            "standard": STANDARD_ID,
            "parameters": self.spec.to_dict(),
            "domain": {
                "coordinates": "Cartesian y increases upward",
                "storage_and_gates": "y <= 0; x and negative y unbounded",
                "readout": "y >= 50 um; x and positive y unbounded",
                "gap_um": HALFPLANE_GAP_UM,
                "execution_window": "finite, geometry-derived; not a hardware budget",
                "readout_count_limit": None,
            },
            "reference_sha256": sha256(REFERENCE_PATH.read_bytes()).hexdigest(),
            "compiler": {"strategy": "nonzoned", "layout": "explicit"},
            "physical_execution": False,
            "device": encode_device(self.device),
            "entry_state": encode_layout(self.state),
            "patches": [patch.to_dict() for patch in self.patches],
            "placement": self.placement_plan.to_dict(),
        }


def reference_device() -> Device:
    """Load the existing d3 CNOT reference without changing its parameters."""
    value = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    return loads_device(json.dumps(generate(value["family"], value["params"])))


def _decode_binding(document: Mapping[str, Any]) -> ComponentBinding:
    """Read binding values without changing atom IDs, role order or site aliases."""
    return ComponentBinding(
        document["block_id"],
        Position(**document["origin"]),
        tuple(document["atom_ids"]),
        document["aod_id"],
        tuple(tuple(pair) for pair in document["site_ids"]),
    )


def _patch_definition(
    spec: ExperimentSpec, patch: FactoryPatch
) -> SurfaceCodeDefinition:
    initial = spec.factory_distance(patch.factory_index)
    if patch.distance is None:
        if spec.factory_distances is not None or patch.code is not None:
            raise ValueError("MSD_WORLD_PATCH_CODE_METADATA_REQUIRED")
        return definition(initial)
    if (
        patch.code != f"rotated_surface_d{patch.distance}"
        or patch.distance > spec.distance
    ):
        raise ValueError("MSD_WORLD_PATCH_CODE_DISTANCE_MISMATCH")
    return definition(patch.distance)


def _validate_current_world(world: ExperimentWorld) -> None:
    """Check current code bindings independently of the original slot locations."""
    validate_layout(world.device, world.state)
    validate_plan(world.placement_plan)
    request = placement_request(world.spec)
    if {block.block_id: block for block in world.placement_plan.blocks} != {
        block.block_id: block for block in request.blocks
    } or world.placement_plan.geometries != request.geometries:
        raise ValueError("MSD_WORLD_PLAN_SPEC_MISMATCH")
    atoms = {atom.id: atom for atom in world.state.atoms}
    bound = set(world.state.qubit_to_atom)
    identities: set[str] = set()
    claimed: set[int] = set()
    for patch in world.patches:
        code = _patch_definition(world.spec, patch)
        binding = patch.binding
        if (
            type(patch.factory_index) is not int
            or not 0 <= patch.factory_index < world.spec.pipelines
            or patch.role not in FACTORY_ROLES
            or binding.block_id != f"factory{patch.factory_index}/{patch.role}"
            or binding.block_id in identities
            or len(binding.atom_ids) != code.atom_count
            or any(type(atom) is not int or atom < 0 for atom in binding.atom_ids)
            or len(set(binding.atom_ids)) != code.atom_count
            or not set(binding.atom_ids) <= bound
            or claimed.intersection(binding.atom_ids)
            or len(patch.home_sites) != code.atom_count
            or len(set(patch.home_sites)) != code.atom_count
        ):
            raise ValueError("MSD_WORLD_PATCH_IDENTITY_MISMATCH")
        world.device.aod(binding.aod_id)
        aliases = dict(binding.site_ids)
        if len(aliases) != len(binding.site_ids) or any(
            not isinstance(name, str) or not name or site not in patch.home_sites
            for name, site in aliases.items()
        ):
            raise ValueError("MSD_WORLD_PATCH_ALIAS_MISMATCH")
        for atom_id, home, (x, y) in zip(
            binding.atom_ids, patch.home_sites, code.reference_coordinates, strict=True
        ):
            atom = atoms[atom_id]
            expected = Position(
                binding.origin.x + x * SITE_PITCH_UM,
                binding.origin.y + y * SITE_PITCH_UM,
            )
            if (
                atom.holder != SLMHolder(home)
                or abs(atom.position.x - expected.x) > COORDINATE_TOLERANCE
                or abs(atom.position.y - expected.y) > COORDINATE_TOLERANCE
            ):
                raise ValueError("MSD_WORLD_PATCH_GEOMETRY_OR_HOME_MISMATCH")
        identities.add(binding.block_id)
        claimed.update(binding.atom_ids)


def add_buffer_sites(
    world: ExperimentWorld,
    origins: Mapping[str, Position],
    *,
    distances: Mapping[str, int] | None = None,
) -> tuple[ExperimentWorld, dict[str, tuple[Position, tuple[str, ...]]]]:
    """Add explicit empty same-code parking grids without allocating atoms.

    Each slot gets the existing 10 um home grid, 2 um guest pairs and code-role
    ordered home IDs. Only finite shared/readout regions and AOD workspace grow;
    controls, timing, capacity, atoms, patches and the original plan are retained.
    Raises ValueError for identity/position conflicts, interacting gate pairs,
    unsupported world domains or a grid crossing above the storage halfplane.
    Mixed worlds require an explicit distance for every requested slot; each must
    be a supported odd distance no larger than the declared world maximum. An
    omitted distance retains the historical uniform behavior. This declares vacant
    sites; it does not route, grow or transfer any state.
    """
    requested = dict(origins)
    if distances is None:
        if requested and world.spec.mixed_distances:
            raise ValueError("BUFFER_EXPLICIT_DISTANCES_REQUIRED")
        slot_distances = {slot: world.spec.distance for slot in requested}
    else:
        slot_distances = dict(distances)
        if set(slot_distances) != set(requested) or any(
            type(d) is not int or d < 3 or d % 2 != 1 or d > world.spec.distance
            for d in slot_distances.values()
        ):
            raise ValueError("BUFFER_INVALID_DISTANCES")
    if not requested:
        return world, {}
    if any(not isinstance(slot, str) or not slot.strip() for slot in requested):
        raise ValueError("BUFFER_INVALID_SLOT_ID")
    if any(not isinstance(origin, Position) for origin in requested.values()):
        raise TypeError("BUFFER_ORIGIN_REQUIRES_POSITION")
    device = world.device
    zones = {zone.id: zone for zone in device.zones}
    if (
        "shared" not in zones
        or "readout" not in zones
        or zones["shared"].bounds.y_max != 0
        or zones["readout"].bounds.y_min != HALFPLANE_GAP_UM
        or len(device.aods) != 1
        or device.readout is None
        or device.cz is None
    ):
        raise ValueError("BUFFER_REQUIRES_SINGLE_AOD_STANDARD_DOMAINS")
    sites = list(device.slm_sites)
    arrays = list(device.pair_arrays)
    used = (
        {site.id for site in sites}
        | {array.id for array in arrays}
        | set(world.placement_plan.placements)
        | {patch.binding.block_id for patch in world.patches}
    )
    if set(requested) & used:
        raise ValueError("BUFFER_SLOT_ID_CONFLICT")
    used.update(requested)
    try:
        occupied = Occupancy({index: site.position for index, site in enumerate(sites)})
    except ValueError as error:
        raise ValueError("BUFFER_EXISTING_SLM_POSITION_CONFLICT") from error
    atom_positions = Occupancy({atom.id: atom.position for atom in world.state.atoms})
    targets = {}
    radius = device.cz.radius_um
    for slot, origin in sorted(requested.items()):
        distance = slot_distances[slot]
        size = 2 * distance
        if origin.y + size * SITE_PITCH_UM > 0:
            raise ValueError("BUFFER_OUTSIDE_STORAGE_HALFPLANE")
        new_sites, array, homes = _buffer_grid(slot, origin, distance)
        if used.intersection(site.id for site in new_sites):
            raise ValueError("BUFFER_SITE_ID_CONFLICT")
        nearby_bounds = Region(
            origin.x - radius,
            origin.y - radius,
            origin.x + size * SITE_PITCH_UM + PAIR_SEPARATION_UM + radius,
            origin.y + size * SITE_PITCH_UM + radius,
        )
        nearby = [
            site.position for site in sites if nearby_bounds.contains(site.position)
        ]
        for site in new_sites:
            if occupied.at(site.position) or atom_positions.at(site.position):
                raise ValueError("BUFFER_SLM_POSITION_CONFLICT")
            if any(
                hypot(site.position.x - other.x, site.position.y - other.y) <= radius
                for other in nearby
            ):
                raise ValueError("BUFFER_GATE_PAIR_INTERACTION")
            occupied.add(len(sites), site.position)
            sites.append(site)
        used.update(site.id for site in new_sites)
        arrays.append(array)
        targets[slot] = origin, homes
    padding = world.spec.window_padding_um
    left = min(
        zones["shared"].bounds.x_min, min(site.position.x for site in sites) - padding
    )
    right = max(
        zones["shared"].bounds.x_max, max(site.position.x for site in sites) + padding
    )
    bottom = min(
        zones["shared"].bounds.y_min, min(site.position.y for site in sites) - padding
    )
    readout = zones["readout"].bounds
    top = max(
        readout.y_max,
        HALFPLANE_GAP_UM
        + len({site.position.y for site in sites})
        * max(device.readout.min_spacing_um, device.aods[0].min_spacing)
        + padding,
    )
    bounds = {
        "shared": Region(left, bottom, right, 0),
        "readout": Region(
            min(readout.x_min, left), HALFPLANE_GAP_UM, max(readout.x_max, right), top
        ),
    }
    workspace = device.aods[0].workspace
    enlarged = replace(
        device,
        zones=tuple(
            replace(zone, bounds=bounds[zone.id]) if zone.id in bounds else zone
            for zone in device.zones
        ),
        slm_sites=tuple(sites),
        pair_arrays=tuple(arrays),
        aods=(
            replace(
                device.aods[0],
                workspace=Region(
                    min(workspace.x_min, bounds["readout"].x_min),
                    min(workspace.y_min, bottom),
                    max(workspace.x_max, bounds["readout"].x_max),
                    max(workspace.y_max, top),
                ),
            ),
        ),
    )
    for array in arrays[len(device.pair_arrays) :]:
        try:
            GatePairCatalog.from_device(enlarged, "shared", array.pairs)
        except ValueError as error:
            raise ValueError(f"BUFFER_INVALID_GATE_GRID: {error}") from error
    validate_layout(enlarged, world.state)
    return replace(world, device=enlarged), targets


def _buffer_grid(
    slot: str, origin: Position, distance: int
) -> tuple[tuple[SLMSite, ...], PairArray, tuple[str, ...]]:
    """Use the same local full-grid convention as explicit factory placement."""
    size = 2 * distance + 1
    left = tuple(
        tuple(f"buffer:{slot}:home:r{row}:c{col}" for col in range(size))
        for row in range(size)
    )
    right = tuple(
        tuple(f"buffer:{slot}:guest:r{row}:c{col}" for col in range(size))
        for row in range(size)
    )
    sites = tuple(
        SLMSite(
            names[row][col],
            Position(
                origin.x + col * SITE_PITCH_UM + shift, origin.y + row * SITE_PITCH_UM
            ),
        )
        for row in range(size)
        for col in range(size)
        for names, shift in ((left, 0), (right, PAIR_SEPARATION_UM))
    )
    homes = tuple(left[y][x] for x, y in definition(distance).reference_coordinates)
    return sites, PairArray(slot, "shared", left, right), homes


def placement_request(spec: ExperimentSpec) -> PlacementRequest:
    """Describe the existing factory roles using code-owned geometry only."""
    distances = tuple(spec.factory_distance(index) for index in range(spec.pipelines))
    return PlacementRequest(
        tuple(
            BlockSpec(
                f"factory{index}/{role}",
                f"rotated_surface_d{distances[index]}",
                distances[index],
                f"factory{index}",
                role,
            )
            for index in range(spec.pipelines)
            for role in FACTORY_ROLES
        ),
        {
            f"rotated_surface_d{d}": geometry(f"rotated_surface_d{d}", d)
            for d in sorted(set(distances))
        },
    )


def build_world(
    spec: ExperimentSpec, *, placement_plan: PlacementPlan | None = None
) -> ExperimentWorld:
    """Place N six-block factories from top to bottom below y=0.

    Retains existing 10 um grid, 2 um pairs, gate/reset/movement capabilities.
    Sets readout=100 us, feedback=0 us, LOAD=STORE=10 us. All atom states are
    unspecified until preparation; the world is not a factory execution result.
    """
    request = placement_request(spec)
    default_plan = place(
        request,
        VerticalFactoryPlacement(FACTORY_ROLES, spec.patch_gap_um, spec.factory_gap_um),
    )
    plan = default_plan if placement_plan is None else placement_plan
    validate_plan(plan)
    if {block.block_id: block for block in plan.blocks} != {
        block.block_id: block for block in request.blocks
    }:
        raise ValueError("STANDARD_PLACEMENT_BLOCKS_MISMATCH")
    if plan.geometries != request.geometries:
        raise ValueError("STANDARD_CODE_GEOMETRY_MISMATCH")
    if plan.occupied_bounds.y_max > 0:
        raise ValueError("STANDARD_PLACEMENT_OUTSIDE_STORAGE_HALFPLANE")
    if plan.placements != default_plan.placements:
        return _build_explicit_world(spec, plan)
    columns = round(plan.occupied_bounds.x_max / SITE_PITCH_UM) + 1
    sites: list[SLMSite] = []
    arrays: list[PairArray] = []
    patches: list[FactoryPatch] = []
    atoms: list[AtomState] = []
    for factory_index in range(spec.pipelines):
        distance = spec.factory_distance(factory_index)
        code = definition(distance)
        size = 2 * distance
        y_origin = plan.placements[
            f"factory{factory_index}/{FACTORY_ROLES[0]}"
        ].origin.y
        left_rows, right_rows = [], []
        for row in range(size + 1):
            left: list[str] = []
            right: list[str] = []
            for col in range(columns):
                for prefix, shift, names in (
                    ("home", 0, left),
                    ("guest", PAIR_SEPARATION_UM, right),
                ):
                    name = f"{prefix}_f{factory_index}_r{row}_c{col}"
                    names.append(name)
                    sites.append(
                        SLMSite(
                            name,
                            Position(
                                col * SITE_PITCH_UM + shift,
                                y_origin + row * SITE_PITCH_UM,
                            ),
                        )
                    )
            left_rows.append(tuple(left))
            right_rows.append(tuple(right))
        arrays.append(
            PairArray(
                f"factory{factory_index}", "shared", tuple(left_rows), tuple(right_rows)
            )
        )
        for index, role in enumerate(FACTORY_ROLES):
            column = round(
                plan.placements[f"factory{factory_index}/{role}"].origin.x
                / SITE_PITCH_UM
            )
            homes = tuple(
                f"home_f{factory_index}_r{y}_c{column + x}"
                for x, y in code.reference_coordinates
            )
            ids = tuple(range(len(atoms), len(atoms) + code.atom_count))
            origin = plan.placements[f"factory{factory_index}/{role}"].origin
            binding = ComponentBinding(
                f"factory{factory_index}/{role}", origin, ids, "transport"
            )
            patches.append(
                FactoryPatch(
                    factory_index,
                    role,
                    binding,
                    homes,
                    f"rotated_surface_d{distance}"
                    if spec.factory_distances is not None
                    else None,
                    distance if spec.factory_distances is not None else None,
                )
            )
            for atom_id, home, (x, y) in zip(
                ids, homes, code.reference_coordinates, strict=True
            ):
                atoms.append(
                    AtomState(
                        atom_id,
                        Position(
                            origin.x + x * SITE_PITCH_UM, origin.y + y * SITE_PITCH_UM
                        ),
                        SLMHolder(home),
                    )
                )
    return _finish_world(spec, sites, arrays, patches, atoms, plan)


def _build_explicit_world(spec: ExperimentSpec, plan: PlacementPlan) -> ExperimentWorld:
    """Bind a validated user plan using local grids; routing remains physical."""
    sites: list[SLMSite] = []
    arrays: list[PairArray] = []
    patches: list[FactoryPatch] = []
    atoms: list[AtomState] = []
    for factory_index in range(spec.pipelines):
        distance = spec.factory_distance(factory_index)
        code = definition(distance)
        size = 2 * distance
        for role in FACTORY_ROLES:
            placement = plan.placements[f"factory{factory_index}/{role}"]
            origin = placement.origin
            left_rows, right_rows = [], []
            for row in range(size + 1):
                left: list[str] = []
                right: list[str] = []
                for col in range(size + 1):
                    for prefix, shift, names in (
                        ("home", 0, left),
                        ("guest", PAIR_SEPARATION_UM, right),
                    ):
                        name = f"{prefix}_f{factory_index}_{role}_r{row}_c{col}"
                        names.append(name)
                        sites.append(
                            SLMSite(
                                name,
                                Position(
                                    origin.x + col * SITE_PITCH_UM + shift,
                                    origin.y + row * SITE_PITCH_UM,
                                ),
                            )
                        )
                left_rows.append(tuple(left))
                right_rows.append(tuple(right))
            arrays.append(
                PairArray(
                    f"factory{factory_index}_{role}",
                    "shared",
                    tuple(left_rows),
                    tuple(right_rows),
                )
            )
            homes = tuple(
                f"home_f{factory_index}_{role}_r{y}_c{x}"
                for x, y in code.reference_coordinates
            )
            ids = tuple(range(len(atoms), len(atoms) + code.atom_count))
            binding = ComponentBinding(
                f"factory{factory_index}/{role}", origin, ids, "transport"
            )
            patches.append(
                FactoryPatch(
                    factory_index,
                    role,
                    binding,
                    homes,
                    f"rotated_surface_d{distance}"
                    if spec.factory_distances is not None
                    else None,
                    distance if spec.factory_distances is not None else None,
                )
            )
            for atom_id, home, (x, y) in zip(
                ids, homes, code.reference_coordinates, strict=True
            ):
                atoms.append(
                    AtomState(
                        atom_id,
                        Position(
                            origin.x + x * SITE_PITCH_UM, origin.y + y * SITE_PITCH_UM
                        ),
                        SLMHolder(home),
                    )
                )
    return _finish_world(spec, sites, arrays, patches, atoms, plan)


def _finish_world(
    spec: ExperimentSpec,
    sites: list[SLMSite],
    arrays: list[PairArray],
    patches: list[FactoryPatch],
    atoms: list[AtomState],
    plan: PlacementPlan,
) -> ExperimentWorld:
    """Construct the unchanged Device standard around already placed blocks."""
    padding = spec.window_padding_um
    right_edge = max(site.position.x for site in sites) + padding
    bottom = min(site.position.y for site in sites) - padding
    left_edge = min(0.0, min(site.position.x for site in sites)) - padding
    # Enough distinct rows for every source row at readout spacing, even if an
    # entire array is measured together. The upper region initially has no atoms.
    reference = reference_device()
    assert reference.readout is not None
    row_spacing = max(reference.readout.min_spacing_um, reference.aods[0].min_spacing)
    top = (
        HALFPLANE_GAP_UM
        + len({site.position.y for site in sites}) * row_spacing
        + padding
    )
    device = replace(
        reference,
        name=f"msd-d{spec.distance}-n{spec.pipelines}-standard-v1",
        zones=(
            Zone(
                "shared",
                Region(left_edge, bottom, right_edge, 0),
                ("cz", "rotate", "reset"),
            ),
            Zone(
                "readout",
                Region(left_edge, HALFPLANE_GAP_UM, right_edge, top),
                ("measure",),
                "measurement",
            ),
        ),
        slm_sites=tuple(sites),
        pair_arrays=tuple(arrays),
        aods=(
            replace(
                reference.aods[0],
                id="transport",
                workspace=Region(left_edge, bottom, right_edge, top),
            ),
        ),
        timing=replace(reference.timing, load_us=10, store_us=10),
        readout=replace(reference.readout, duration_us=100, latency_us=0),
    )
    state = AtomLayout(tuple(atoms), qubit_to_atom=tuple(a.id for a in atoms))
    validate_layout(device, state)
    return ExperimentWorld(spec, device, state, tuple(patches), plan)
