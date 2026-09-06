"""Strict, safe YAML loading for the step-4 static hardware configuration."""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from .geometry import Bounds, Position
from .hardware_state import HardwareState
from .zones import PairSlot, TrapSite, Zone


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError(f"YAML mapping key must be a unique string: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _keys(value, required, optional=()):
    if not isinstance(value, Mapping) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError(f"Expected keys {sorted(required)}, optional {sorted(optional)}")


@dataclass(frozen=True)
class HardwareConfig:
    zones: tuple[Zone, ...]
    min_atom_separation: float
    reservoir_atoms: int = 0

    def __post_init__(self):
        object.__setattr__(self, "zones", tuple(self.zones))
        HardwareState((), self.zones, min_atom_separation=self.min_atom_separation)
        if type(self.reservoir_atoms) is not int or self.reservoir_atoms < 0:
            raise ValueError("reservoir_atoms must be a nonnegative integer")
        if self.reservoir_atoms > sum(z.capacity for z in self.zones if z.kind == "RESERVOIR"):
            raise ValueError("Insufficient reservoir capacity")


def load_hardware_config(path: str | Path) -> HardwareConfig:
    try:
        raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
        _keys(raw, ("schema_version", "units", "min_atom_separation", "reservoir_atoms", "zones"))
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1 or raw["units"] != {"length": "um", "time": "us"}:
            raise ValueError("Expected schema_version=1 and units length=um, time=us")
        if not isinstance(raw["zones"], list):
            raise ValueError("zones must be a list")
        zones = []
        for zone in raw["zones"]:
            _keys(zone, ("id", "kind", "bounds", "capacity", "allowed_operations", "sites"), ("pair_slots",))
            if not isinstance(zone["sites"], list) or not isinstance(zone["allowed_operations"], list) or not isinstance(zone.get("pair_slots", []), list):
                raise ValueError("sites, allowed_operations and pair_slots must be lists")
            sites, pairs = [], []
            for site in zone["sites"]:
                _keys(site, ("id", "position"))
                sites.append(TrapSite(site["id"], Position(*site["position"])))
            for pair in zone.get("pair_slots", []):
                _keys(pair, ("id", "sites"))
                if not isinstance(pair["sites"], list):
                    raise ValueError("Pair slot sites must be a list")
                pairs.append(PairSlot(pair["id"], pair["sites"]))
            zones.append(Zone(zone["id"], zone["kind"], Bounds(*zone["bounds"]), zone["capacity"],
                              frozenset(zone["allowed_operations"]), tuple(sites), tuple(pairs)))
        return HardwareConfig(tuple(zones), raw["min_atom_separation"], raw["reservoir_atoms"])
    except (yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(f"Malformed hardware configuration: {exc}") from exc
