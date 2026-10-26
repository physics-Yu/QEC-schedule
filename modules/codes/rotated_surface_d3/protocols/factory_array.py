"""Multiple six-patch factories in one real, explicitly budgeted device world.

All patches have the same vertical origin and retain the existing local readout
band at y + 90..110. Extra area is unused geometry, not a changed local protocol.
No component, state preparation, scheduling or noise sampling occurs here.
"""

import json
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import Device, Position, loads_device
from nadit_physical_compiler.state import (
    AtomLayout,
    AtomState,
    SLMHolder,
    validate_layout,
)

from modules.logical_compiler.src.placement import PlacementPlan

from ...contracts.component import ComponentBinding
from ..definition import REFERENCE_COORDINATES
from .factory_world import _REFERENCE, FACTORY_ROLES, FactoryPatch
from .fast_layout import legacy_factory_plan


@dataclass(frozen=True)
class FactoryArrayConfig:
    """Configure horizontal factory tiles and real shared device capacities.

    None column/readout budgets derive finite limits for all six patches per
    factory (24 columns and 48 measured atoms per factory). Smaller explicit
    budgets are legal when a local four-column/eight-result component fits;
    admission must then limit simultaneous groups. Area padding creates actual
    extra home/guest columns, while height padding adds legal operation area.
    """

    factory_count: int = 2
    origin: Position = field(default_factory=lambda: Position(0, 0))
    block_spacing_columns: int = 10
    factory_gap_columns: int = 2
    atom_id_base: int = 0
    factory_id_prefix: str = "factory"
    aod_id: str = "transport"
    shared_padding_columns: int = 2
    shared_top_margin_um: float = 15
    readout_extra_height_um: float = 20
    aod_max_rows: int = 4
    aod_max_columns: int | None = None
    max_readout_atoms: int | None = None

    def __post_init__(self) -> None:
        for name, minimum in (
            ("factory_count", 1),
            ("block_spacing_columns", 7),
            ("factory_gap_columns", 0),
            ("atom_id_base", 0),
            ("shared_padding_columns", 0),
            ("aod_max_rows", 4),
        ):
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}.")
        for name, minimum in (("aod_max_columns", 4), ("max_readout_atoms", 8)):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < minimum):
                raise ValueError(f"{name} must be None or an integer >= {minimum}.")
        for name in ("factory_id_prefix", "aod_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string.")
        if not isinstance(self.origin, Position) or not all(
            isfinite(v) for v in (self.origin.x, self.origin.y)
        ):
            raise ValueError("origin must be a finite Position.")
        for name in ("shared_top_margin_um", "readout_extra_height_um"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be finite and nonnegative.")
        if self.shared_top_margin_um >= 25:
            raise ValueError(
                "Shared height must remain strictly below the readout band."
            )


@dataclass(frozen=True)
class FactoryPlacement:
    """One named factory's disjoint participants, without its own virtual world."""

    factory_id: str
    patches: tuple[FactoryPatch, ...]

    @property
    def bindings(self) -> dict[str, ComponentBinding]:
        return {patch.role: patch.binding for patch in self.patches}

    @property
    def atom_ids(self) -> tuple[int, ...]:
        return tuple(atom for patch in self.patches for atom in patch.binding.atom_ids)

    def patch(self, role: str) -> FactoryPatch:
        for patch in self.patches:
            if patch.role == role:
                return patch
        raise KeyError(role)


@dataclass(frozen=True)
class FactoryArrayWorld:
    """One device/layout shared by every factory, including all real spectators."""

    config: FactoryArrayConfig
    device: Device
    world_state: AtomLayout
    factories: tuple[FactoryPlacement, ...]
    placement_plan: PlacementPlan

    @property
    def bindings(self) -> dict[str, ComponentBinding]:
        return {
            patch.binding.block_id: patch.binding
            for factory in self.factories
            for patch in factory.patches
        }

    def factory(self, identity: int | str) -> FactoryPlacement:
        if type(identity) is int and 0 <= identity < len(self.factories):
            return self.factories[identity]
        for factory in self.factories:
            if factory.factory_id == identity:
                return factory
        raise KeyError(identity)

    @property
    def budget(self) -> dict[str, Any]:
        """Return actual device budgets, not nominal visualization dimensions."""
        aod = self.device.aods[0]
        assert self.device.readout is not None
        return {
            "factory_count": self.config.factory_count,
            "patch_count": len(self.bindings),
            "atom_count": len(self.world_state.atoms),
            "slm_site_count": len(self.device.slm_sites),
            "aod_count": len(self.device.aods),
            "aod_max_rows": aod.max_rows,
            "aod_max_columns": aod.max_columns,
            "max_readout_atoms": self.device.readout.max_atoms,
            "shared_padding_columns": self.config.shared_padding_columns,
            "shared_top_margin_um": self.config.shared_top_margin_um,
            "readout_extra_height_um": self.config.readout_extra_height_um,
        }


def make_factory_array(config: FactoryArrayConfig | None = None) -> FactoryArrayWorld:
    """Build N horizontal factories and validate their complete physical layout."""
    config = FactoryArrayConfig() if config is None else config
    if not isinstance(config, FactoryArrayConfig):
        raise TypeError("config must be a FactoryArrayConfig.")
    plan = legacy_factory_plan(
        config.factory_count,
        origin=config.origin,
        factory_gap_columns=config.factory_gap_columns,
        block_spacing_columns=config.block_spacing_columns,
        factory_id_prefix=config.factory_id_prefix,
    )
    last = round((plan.occupied_bounds.x_max - config.origin.x) / 10)
    columns = last + 1 + 2 * config.shared_padding_columns
    left = config.origin.x - 10 * config.shared_padding_columns
    y = config.origin.y
    width = 10 * (columns - 1)
    reference = json.loads(_REFERENCE.read_text(encoding="utf-8"))
    params = reference["params"]
    params["name"] = f"d3-{config.factory_count}-factory-array-reference"
    array = params["shared_arrays"][0]
    array["position"] = {"x": left, "y": y}
    array["pairs_per_row"] = columns
    array["bounds"]["x_max"] = width + 5
    array["bounds"]["y_max"] = 65 + config.shared_top_margin_um
    params["measurement"]["position"] = {"x": left, "y": y + 90}
    params["measurement"]["bounds"]["x_max"] = width + 5
    params["measurement"]["bounds"]["y_max"] = 20 + config.readout_extra_height_um
    params["measurement"]["readout"]["max_atoms"] = (
        config.max_readout_atoms or 48 * config.factory_count
    )
    params["aod"].update(
        {
            "id": config.aod_id,
            "max_rows": config.aod_max_rows,
            "max_columns": config.aod_max_columns or 24 * config.factory_count,
            "workspace": {
                "x_min": left - 5,
                "x_max": left + width + 10,
                "y_min": y - 5,
                "y_max": y + 115 + config.readout_extra_height_um,
            },
        }
    )
    device = loads_device(json.dumps(generate(reference["family"], params)))
    factories: list[FactoryPlacement] = []
    atoms: list[AtomState] = []
    for index in range(config.factory_count):
        factory_id = f"{config.factory_id_prefix}{index}"
        patches: list[FactoryPatch] = []
        for role_index, role in enumerate(FACTORY_ROLES):
            identity = f"{factory_id}/{role}"
            origin = plan.placements[identity].origin
            column = round((origin.x - config.origin.x) / 10)
            homes = tuple(
                f"home_r{dy}_c{dx + column + config.shared_padding_columns}"
                for dx, dy in REFERENCE_COORDINATES
            )
            first = config.atom_id_base + 102 * index + 17 * role_index
            ids = tuple(range(first, first + 17))
            binding = ComponentBinding(
                identity,
                origin,
                ids,
                config.aod_id,
            )
            patches.append(FactoryPatch(role, homes, binding))
            atoms.extend(
                AtomState(atom, device.site(site).position, SLMHolder(site))
                for atom, site in zip(ids, homes, strict=True)
            )
        factories.append(FactoryPlacement(factory_id, tuple(patches)))
    world = AtomLayout(tuple(atoms), qubit_to_atom=tuple(atom.id for atom in atoms))
    validate_layout(device, world)
    return FactoryArrayWorld(config, device, world, tuple(factories), plan)
