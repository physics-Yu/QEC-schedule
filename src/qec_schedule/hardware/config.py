"""Strict, safe YAML loading for hardware geometry and action timing estimates."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import yaml

from .geometry import Bounds, Position
from .hardware_state import HardwareState
from .zones import (EntanglingGeometry, MeasurementGeometry, PairSlot, TrapSite,
                    Zone, ZoneKind)
from .timing import ActionTiming
from .aod import AODController


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


def _bounds(value, name):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{name} must be [xmin, ymin, xmax, ymax]")
    return Bounds(*value)


def _parse_entangling_geometry(value):
    _keys(value, ("bounds",), ("interaction_lanes", "preferred_axis", "pair_distance",
                                "pair_distance_tolerance", "inter_pair_guard_distance",
                                "min_atom_spacing", "max_parallel_pairs", "max_atoms"))
    lanes = value.get("interaction_lanes")
    if lanes is not None and not isinstance(lanes, list):
        raise ValueError("interaction_lanes must be a list or null")
    return EntanglingGeometry(
        _bounds(value["bounds"], "entanglement.bounds"),
        None if lanes is None else tuple(lanes),
        value.get("preferred_axis", "x"),
        value.get("pair_distance", 1.0),
        value.get("pair_distance_tolerance", 0.0),
        value.get("inter_pair_guard_distance", 0.0),
        value.get("min_atom_spacing", 1.0),
        value.get("max_parallel_pairs"),
        value.get("max_atoms"),
    )


def _parse_measurement_geometry(value):
    _keys(value, ("bounds", "imaging_bounds"),
          ("min_atom_spacing", "max_parallel_atoms", "field_of_view"))
    field = value.get("field_of_view")
    return MeasurementGeometry(
        _bounds(value["bounds"], "measurement.bounds"),
        _bounds(value["imaging_bounds"], "measurement.imaging_bounds"),
        value.get("min_atom_spacing", 1.0),
        value.get("max_parallel_atoms"),
        None if field is None else _bounds(field, "measurement.field_of_view"),
    )


@dataclass(frozen=True)
class HardwareConfig:
    zones: tuple[Zone, ...]
    min_atom_separation: float
    reservoir_atoms: int = 0
    timing: ActionTiming = field(default_factory=ActionTiming)
    aod: AODController | None = None
    device_capacities: Mapping = field(default_factory=dict)

    def __post_init__(self):
        devices = {'device/aod': 1, 'device/local_1q': 1, 'device/rydberg': 1,
                   'device/imaging': 1, 'device/state_preparation': 1}
        if not isinstance(self.device_capacities, Mapping) or set(self.device_capacities) - devices.keys():
            raise ValueError('Unknown device capacities')
        devices.update(self.device_capacities)
        if any(type(v) is not int or v < 1 for v in devices.values()):
            raise ValueError('Device capacities must be positive integers')
        object.__setattr__(self, 'device_capacities', MappingProxyType(devices))
        object.__setattr__(self, "zones", tuple(self.zones))
        if not isinstance(self.timing, ActionTiming):
            raise ValueError("timing must be ActionTiming")
        HardwareState((), self.zones, min_atom_separation=self.min_atom_separation)
        if self.aod is None:
            bounds = (Bounds(min(z.bounds.xmin for z in self.zones), min(z.bounds.ymin for z in self.zones),
                             max(z.bounds.xmax for z in self.zones), max(z.bounds.ymax for z in self.zones))
                      if self.zones else Bounds(0, 0, 1, 1))
            object.__setattr__(self, "aod", AODController(20, 20, bounds))
        elif not isinstance(self.aod, AODController):
            raise ValueError("aod must be AODController")
        if type(self.reservoir_atoms) is not int or self.reservoir_atoms < 0:
            raise ValueError("reservoir_atoms must be a nonnegative integer")
        if self.reservoir_atoms > sum(z.capacity for z in self.zones if z.kind == "RESERVOIR"):
            raise ValueError("Insufficient reservoir capacity")


def load_hardware_config(path: str | Path) -> HardwareConfig:
    try:
        raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
        _keys(raw, ("schema_version", "units", "min_atom_separation", "reservoir_atoms", "zones"),
              ("timing", "aod", "devices", "entanglement", "measurement"))
        if type(raw["schema_version"]) is not int or raw["schema_version"] not in (1, 2) or raw["units"] != {"length": "um", "time": "us"}:
            raise ValueError("Expected schema_version=1 or 2 and units length=um, time=us")
        if not isinstance(raw["zones"], list):
            raise ValueError("zones must be a list")
        entangling_geometry = (_parse_entangling_geometry(raw["entanglement"])
                               if "entanglement" in raw else None)
        measurement_geometry = (_parse_measurement_geometry(raw["measurement"])
                                if "measurement" in raw else None)
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
            kind = ZoneKind(zone["kind"])
            zone_bounds = Bounds(*zone["bounds"])
            if kind == ZoneKind.ENTANGLING and entangling_geometry is not None and entangling_geometry.bounds != zone_bounds:
                raise ValueError("entanglement.bounds must match the entangling zone bounds")
            if kind == ZoneKind.MEASUREMENT and measurement_geometry is not None and measurement_geometry.bounds != zone_bounds:
                raise ValueError("measurement.bounds must match the measurement zone bounds")
            zones.append(Zone(zone["id"], kind, zone_bounds, zone["capacity"],
                              frozenset(zone["allowed_operations"]), tuple(sites), tuple(pairs),
                              entangling_geometry if kind == ZoneKind.ENTANGLING else None,
                              measurement_geometry if kind == ZoneKind.MEASUREMENT else None))
        timing = raw.get("timing", {})
        _keys(timing, (), ActionTiming.__dataclass_fields__)
        aod = None
        if "aod" in raw:
            settings = raw["aod"]
            _keys(settings, ("max_x_tones", "max_y_tones", "allowed_region"), ("allowed_primitives", "displacement_tolerance"))
            if "allowed_primitives" in settings and not isinstance(settings["allowed_primitives"], list):
                raise ValueError("allowed_primitives must be a list")
            aod = AODController(**{**settings, "allowed_region": Bounds(*settings["allowed_region"])})
        return HardwareConfig(tuple(zones), raw["min_atom_separation"], raw["reservoir_atoms"], ActionTiming(**timing), aod, raw.get('devices', {}))
    except (yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(f"Malformed hardware configuration: {exc}") from exc
