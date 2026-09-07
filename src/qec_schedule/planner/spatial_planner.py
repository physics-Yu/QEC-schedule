"""Deterministic geometry-only placement for runtime hardware batches."""
from collections.abc import Iterable
from dataclasses import dataclass
import math

from ..compiler.semantic_requests import EntangleRequest, MeasureRequest
from ..hardware.geometry import Position
from ..hardware.hardware_state import HardwareState
from ..hardware.zones import ZoneKind


class PlacementError(ValueError):
    """A batch cannot be placed in the requested dynamic working region."""

    def __init__(self, reason: str, diagnostics: dict | None = None):
        self.reason = reason
        self.diagnostics = {} if diagnostics is None else dict(diagnostics)
        detail = f"{reason}: {self.diagnostics}" if self.diagnostics else reason
        super().__init__(detail)


@dataclass(frozen=True)
class PairPlacement:
    request_id: str
    atom_a: str
    atom_b: str
    position_a: Position
    position_b: Position

    @property
    def atoms(self):
        return (self.atom_a, self.atom_b)

    @property
    def positions(self):
        return (self.position_a, self.position_b)

    def to_dict(self):
        return {"request_id": self.request_id, "atoms": list(self.atoms),
                "position_a": self.position_a.to_list(), "position_b": self.position_b.to_list()}


@dataclass(frozen=True)
class MeasurementPlacement:
    request_id: str
    atom: str
    position: Position

    def to_dict(self):
        return {"request_id": self.request_id, "atom": self.atom, "position": self.position.to_list()}


def _distance_ok(positions, minimum):
    positions = tuple(positions)
    return all(left.distance_to(right) + 1e-12 >= minimum
               for index, left in enumerate(positions) for right in positions[index + 1:])


class SpatialPlanner:
    """MVP planner using stable row/lane packing, never global optimization."""

    def __init__(self, *, entangling_zone="entangling", measurement_zone="measurement"):
        self.entangling_zone = entangling_zone
        self.measurement_zone = measurement_zone

    def _zone(self, state: HardwareState, zone_id: str, kind: ZoneKind):
        try:
            zone = state.zones_by_id[zone_id]
        except KeyError as exc:
            raise PlacementError("ZONE_UNAVAILABLE", {"zone": zone_id}) from exc
        if zone.kind != kind:
            raise PlacementError("ZONE_UNAVAILABLE", {"zone": zone_id, "kind": zone.kind.value})
        return zone

    @staticmethod
    def _as_entangles(requests: Iterable[EntangleRequest]):
        requests = tuple(requests)
        if not requests or not all(isinstance(request, EntangleRequest) for request in requests):
            raise PlacementError("EMPTY_OR_INVALID_BATCH")
        atoms = [atom for request in requests for atom in request.atoms]
        if len(atoms) != len(set(atoms)):
            raise PlacementError("ATOM_CONFLICT", {"atoms": atoms})
        return tuple(sorted(requests, key=lambda request: (request.metadata.get("slot", 0), request.id)))

    @staticmethod
    def _as_measurements(requests: Iterable[MeasureRequest]):
        requests = tuple(requests)
        if not requests or not all(isinstance(request, MeasureRequest) for request in requests):
            raise PlacementError("EMPTY_OR_INVALID_BATCH")
        atoms = [request.atom for request in requests]
        if len(atoms) != len(set(atoms)):
            raise PlacementError("ATOM_CONFLICT", {"atoms": atoms})
        return tuple(sorted(requests, key=lambda request: request.id))

    def plan_entanglement(self, requests: Iterable[EntangleRequest], state: HardwareState):
        requests = self._as_entangles(requests)
        zone = self._zone(state, self.entangling_zone, ZoneKind.ENTANGLING)
        geometry = zone.entangling_geometry
        count = len(requests)
        max_pairs = geometry.max_parallel_pairs
        max_atoms = geometry.max_atoms
        if max_pairs is not None and count > max_pairs:
            raise PlacementError("ZONE_CAPACITY", {"requested_pairs": count, "max_parallel_pairs": max_pairs})
        if max_atoms is not None and 2 * count > max_atoms:
            raise PlacementError("ZONE_CAPACITY", {"requested_atoms": 2 * count, "max_atoms": max_atoms})
        if 2 * count > zone.capacity:
            raise PlacementError("ZONE_CAPACITY", {"requested_atoms": 2 * count, "capacity": zone.capacity})

        distance = geometry.pair_distance
        guard = geometry.inter_pair_guard_distance
        axis = geometry.preferred_axis
        lanes = geometry.interaction_lanes or ((geometry.bounds.ymin + geometry.bounds.ymax) / 2
                                               if axis == "x" else (geometry.bounds.xmin + geometry.bounds.xmax) / 2,)
        along_min, along_max = ((geometry.bounds.xmin, geometry.bounds.xmax)
                                if axis == "x" else (geometry.bounds.ymin, geometry.bounds.ymax))
        total_span = distance + max(0, count - 1) * (distance + guard)
        margin = (along_max - along_min - total_span) / 2
        if margin < -1e-12:
            raise PlacementError("PLACEMENT_FAILURE", {"requested_pairs": count, "required_span": total_span,
                                                        "available_span": along_max - along_min})
        start = along_min + max(0.0, margin)
        requested_atoms = {atom for request in requests for atom in request.atoms}
        resident = [atom.position for atom in state.atoms_in_zone(zone.id) if atom.atom_id not in requested_atoms]
        current_positions = {atom.atom_id: atom.position for atom in state.atoms}
        for lane in lanes:
            placements = []
            for index, request in enumerate(requests):
                first = start + index * (distance + guard)
                second = first + distance
                if axis == "x":
                    positions = (Position(first, lane), Position(second, lane))
                else:
                    positions = (Position(lane, first), Position(lane, second))
                if any(not geometry.bounds.contains(position) for position in positions):
                    raise PlacementError("OUT_OF_BOUNDS", {"request_id": request.id})
                placements.append(PairPlacement(request.id, request.atoms[0], request.atoms[1], *positions))
            all_positions = [position for placement in placements for position in placement.positions]
            if not _distance_ok(all_positions, geometry.min_atom_spacing):
                raise PlacementError("MIN_SPACING", {"minimum": geometry.min_atom_spacing})
            if not resident or _distance_ok((*all_positions, *resident), geometry.min_atom_spacing):
                # AOD segments may be split by tone/order constraints.  Do
                # not select a target that is occupied by a different atom at
                # the current snapshot, even when both atoms belong to the
                # requested batch; this keeps every intermediate completion
                # snapshot valid while the batch is reconfigured.
                atom_targets = {atom: position for placement in placements
                                for atom, position in zip(placement.atoms, placement.positions)}
                if all(atom == other or target.distance_to(position) + 1e-12 >= geometry.min_atom_spacing
                       for atom, target in atom_targets.items()
                       for other, position in current_positions.items()):
                    return tuple(placements)
        raise PlacementError("MIN_SPACING", {"resident_atoms": len(resident), "lanes_tried": len(lanes)})

    def plan_measurement(self, requests: Iterable[MeasureRequest], state: HardwareState):
        requests = self._as_measurements(requests)
        zone = self._zone(state, self.measurement_zone, ZoneKind.MEASUREMENT)
        geometry = zone.measurement_geometry
        count = len(requests)
        if geometry.max_parallel_atoms is not None and count > geometry.max_parallel_atoms:
            raise PlacementError("ZONE_CAPACITY", {"requested_atoms": count,
                                                    "max_parallel_atoms": geometry.max_parallel_atoms})
        if count > zone.capacity:
            raise PlacementError("ZONE_CAPACITY", {"requested_atoms": count, "capacity": zone.capacity})

        field = geometry.field_of_view
        spacing = geometry.min_atom_spacing
        columns = max(1, int(math.floor((field.xmax - field.xmin) / spacing + 1e-12)) + 1)
        rows = max(1, int(math.floor((field.ymax - field.ymin) / spacing + 1e-12)) + 1)
        if count > columns * rows:
            raise PlacementError("IMAGING_FOV", {"requested_atoms": count, "grid_capacity": columns * rows})
        placements = []
        for index, request in enumerate(requests):
            row, column = divmod(index, columns)
            position = Position(field.xmin + column * spacing, field.ymin + row * spacing)
            if not field.contains(position):
                raise PlacementError("IMAGING_FOV", {"request_id": request.id})
            placements.append(MeasurementPlacement(request.id, request.atom, position))
        positions = [placement.position for placement in placements]
        if not _distance_ok(positions, spacing):
            raise PlacementError("MIN_SPACING", {"minimum": spacing})
        requested_atoms = {request.atom for request in requests}
        resident = [atom.position for atom in state.atoms_in_zone(zone.id) if atom.atom_id not in requested_atoms]
        if resident and not _distance_ok((*positions, *resident), spacing):
            raise PlacementError("MIN_SPACING", {"resident_atoms": len(resident)})
        return tuple(placements)
