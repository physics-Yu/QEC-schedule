"""A complete six-patch physical world for batched d3 factory compositions.

The builder widens the approved two-patch nonzoned reference device. It creates
real spectator atoms, rather than composing independent seventeen-atom worlds.
No quantum initialization, component compilation, scheduling or sampling occurs.
"""

import json
from dataclasses import dataclass, field, replace
from math import isfinite
from pathlib import Path
from typing import ClassVar

from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import Device, Position, loads_device
from nadit_physical_compiler.state import (
    AtomLayout,
    AtomState,
    SLMHolder,
    validate_layout,
)

from ...contracts.component import ComponentBinding
from ..definition import REFERENCE_COORDINATES

FACTORY_ROLES = ("W1", "W2", "W3", "W4", "W5", "R")
_PATCH_ATOMS = 17
_PATCH_COLUMNS = 7
_SITE_PITCH_UM = 10
_REFERENCE = Path(__file__).parents[1] / "configs/nonzoned_cnot_reference.json"


@dataclass(frozen=True)
class FactoryWorldConfig:
    """Configure six equally oriented patches and explicit transport resources.

    Args:
        origin: Absolute translation of the whole device and patch arrangement.
        block_spacing_columns: Horizontal patch separation in ten-micrometer
            columns; at least seven prevents overlapping local layouts.
        atom_id_base: First of 102 consecutive physical atom identities.
        factory_id: Identity prefix for participant blocks, independent of time.
        aod_ids: Available flexible AOD identities. All initial bindings use the
            first AOD unless role_aod_ids assigns another default resource.
        role_aod_ids: Explicit role-to-AOD defaults for component bindings.
            Compatible components share configured resources when admitted.

    Raises:
        ValueError: If geometry, identity or inventory values are invalid.
    """

    origin: Position = field(default_factory=lambda: Position(0, 0))
    block_spacing_columns: int = 10
    atom_id_base: int = 0
    factory_id: str = "factory"
    aod_ids: tuple[str, ...] = ("transport",)
    role_aod_ids: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.origin, Position) or not all(
            isfinite(value) for value in (self.origin.x, self.origin.y)
        ):
            raise ValueError("Factory origin must be a finite Position.")
        if (
            type(self.block_spacing_columns) is not int
            or self.block_spacing_columns < _PATCH_COLUMNS
        ):
            raise ValueError("Factory block spacing requires at least seven columns.")
        if type(self.atom_id_base) is not int or self.atom_id_base < 0:
            raise ValueError("Factory atom_id_base must be a nonnegative integer.")
        if not isinstance(self.factory_id, str) or not self.factory_id.strip():
            raise ValueError("Factory identity must be a nonempty string.")
        if (
            not isinstance(self.aod_ids, tuple)
            or not self.aod_ids
            or any(
                not isinstance(value, str) or not value.strip()
                for value in self.aod_ids
            )
            or len(set(self.aod_ids)) != len(self.aod_ids)
        ):
            raise ValueError("Factory AOD inventory requires distinct nonempty IDs.")
        if (
            not isinstance(self.role_aod_ids, tuple)
            or any(
                not isinstance(item, tuple)
                or len(item) != 2
                or item[0] not in FACTORY_ROLES
                or item[1] not in self.aod_ids
                for item in self.role_aod_ids
            )
            or len({item[0] for item in self.role_aod_ids}) != len(self.role_aod_ids)
        ):
            raise ValueError(
                "Role AOD assignments require unique known roles and AOD identities."
            )


@dataclass(frozen=True)
class FactoryPatch:
    """One participant's same-orientation homes and explicit physical binding."""

    role: str
    home_sites: tuple[str, ...]
    binding: ComponentBinding


@dataclass(frozen=True)
class FactoryWorld:
    """Six real patches in one checked world; their quantum states are unspecified.

    Consumers carry the latest expansion's exit world and participant bindings
    into subsequent calls. ``world_state`` is only the initial physical layout;
    it is not a mutable execution context or a promise of initialized qubits.
    """

    config: FactoryWorldConfig
    device: Device
    world_state: AtomLayout
    patches: tuple[FactoryPatch, ...]
    execution_mode: ClassVar[str] = "batched"

    @property
    def bindings(self) -> dict[str, ComponentBinding]:
        """Return a fresh role-to-binding mapping without mutable shared state."""
        return {patch.role: patch.binding for patch in self.patches}

    def patch(self, role: str) -> FactoryPatch:
        """Return a named participant, raising KeyError for an unknown role."""
        for patch in self.patches:
            if patch.role == role:
                return patch
        raise KeyError(f"Unknown factory role {role!r}; expected {FACTORY_ROLES}.")


def _device(config: FactoryWorldConfig) -> Device:
    """Widen the existing reference while retaining its operation capabilities."""
    reference = json.loads(_REFERENCE.read_text(encoding="utf-8"))
    params = reference["params"]
    params["name"] = "d3-six-patch-factory-reference"
    last_column = (len(FACTORY_ROLES) - 1) * config.block_spacing_columns + 6
    right = _SITE_PITCH_UM * last_column
    x, y = config.origin.x, config.origin.y
    array = params["shared_arrays"][0]
    array["position"] = {"x": x, "y": y}
    array["pairs_per_row"] = last_column + 1
    array["bounds"]["x_max"] = right + 5
    params["measurement"]["position"] = {"x": x, "y": y + 90}
    params["measurement"]["bounds"]["x_max"] = right + 5
    params["aod"]["id"] = config.aod_ids[0]
    params["aod"]["workspace"] = {
        "x_min": x - 5,
        "y_min": y - 5,
        "x_max": x + right + 10,
        "y_max": y + 115,
    }
    device = loads_device(json.dumps(generate(reference["family"], params)))
    return replace(
        device,
        aods=tuple(replace(device.aods[0], id=aod_id) for aod_id in config.aod_ids),
    )


def make_factory_world(config: FactoryWorldConfig | None = None) -> FactoryWorld:
    """Build the complete initial six-patch world without compiling any actions.

    Args:
        config: Geometry, physical identities and AOD inventory; omission selects
            the illustrative reference with 100-micrometer patch separation.

    Returns:
        The device, all 102 atoms and six disjoint role bindings. Data and ancilla
        quantum states remain unspecified until a preparation component executes.

    Raises:
        ValueError: If the reference device or complete physical layout is invalid.
        TypeError: If config is not a FactoryWorldConfig.
    """
    if config is None:
        config = FactoryWorldConfig()
    if not isinstance(config, FactoryWorldConfig):
        raise TypeError("config must be a FactoryWorldConfig.")
    device = _device(config)
    patches: list[FactoryPatch] = []
    atoms: list[AtomState] = []
    for index, role in enumerate(FACTORY_ROLES):
        column = index * config.block_spacing_columns
        homes = tuple(f"home_r{y}_c{x + column}" for x, y in REFERENCE_COORDINATES)
        first_atom = config.atom_id_base + index * _PATCH_ATOMS
        atom_ids = tuple(range(first_atom, first_atom + _PATCH_ATOMS))
        binding = ComponentBinding(
            f"{config.factory_id}/{role}",
            Position(config.origin.x + column * _SITE_PITCH_UM, config.origin.y),
            atom_ids,
            dict(config.role_aod_ids).get(role, config.aod_ids[0]),
        )
        patches.append(FactoryPatch(role, homes, binding))
        atoms.extend(
            AtomState(atom, device.site(site).position, SLMHolder(site))
            for atom, site in zip(atom_ids, homes, strict=True)
        )
    world = AtomLayout(tuple(atoms), qubit_to_atom=tuple(atom.id for atom in atoms))
    validate_layout(device, world)
    return FactoryWorld(config, device, world, tuple(patches))
