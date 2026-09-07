"""Event-driven execution of semantic requests into physical epochs.

This scheduler is deliberately small and auditable.  It owns the mutable
execution cursor and is the only layer that replaces the immutable
``HardwareState`` after an epoch completes.  Placement, AOD synthesis and
resource accounting remain delegated to their respective collaborators.
"""
from dataclasses import dataclass
import heapq
import math
from types import MappingProxyType

from ..compiler.semantic_requests import (EntangleRequest, MeasureRequest,
                                          PrepareRequest, ResetRequest,
                                          SemanticRequestPlan,
                                          SingleQubitRequest)
from ..execution import (AODMovementEpoch, EpochType, ImagingEpoch,
                         PhysicalEpoch, RydbergEpoch)
from ..hardware import AtomState, AtomType, HardwareState, HardwareOperation
from ..hardware.aod import Translation
from ..hardware.geometry import Position
from ..planner import (BatchBuilder, Feasible, HardwareFeasibilityOracle,
                       Infeasible, PlacementError)
from .model import ResourceLock


@dataclass(frozen=True)
class RuntimeSchedulingError(RuntimeError):
    """Structured deadlock or unrecoverable runtime feasibility failure."""

    reason: str
    diagnostics: dict

    def __str__(self):
        return f"{self.reason}: {self.diagnostics}"


@dataclass
class _MovementStage:
    id: str
    purpose: str
    request_ids: tuple[str, ...]
    targets: dict
    placements: dict
    segments: tuple[tuple[Translation, ...], ...]
    next_segment: int = 0

    @property
    def atoms(self):
        return frozenset(self.targets)


class RuntimeScheduler:
    """RESST-style event scheduler for semantic requests and physical epochs."""

    _family_order = ("PREPARE", "SINGLE_QUBIT", "ENTANGLE", "MEASURE", "RESET")

    def __init__(self, config, *, device_capacities=None,
                 rydberg_parallel_pairs=None, spatial_planner=None):
        self.config = config
        capacities = dict(config.device_capacities)
        if device_capacities:
            if set(device_capacities) - capacities.keys():
                raise ValueError("Unknown device capacity")
            capacities.update(device_capacities)
        if any(type(value) is not int or value < 1 for value in capacities.values()):
            raise ValueError("Device capacities must be positive integers")
        self.device_capacities = capacities
        self.batch_builder = BatchBuilder()
        self.oracle = HardwareFeasibilityOracle(
            config, spatial_planner=spatial_planner,
            rydberg_parallel_pairs=rydberg_parallel_pairs)

    def _reset_runtime(self, plan, initial_state):
        if not isinstance(plan, SemanticRequestPlan):
            raise ValueError("RuntimeScheduler requires a SemanticRequestPlan")
        if not isinstance(initial_state, HardwareState):
            raise ValueError("RuntimeScheduler requires a HardwareState")
        initial_state.validate()
        if any(atom.state not in (AtomState.IDLE, AtomState.HELD_STATIC)
               for atom in initial_state.atoms):
            raise ValueError("Runtime execution requires a stationary initial snapshot")
        if any(request.atom not in initial_state.atoms_by_id
               for request in plan.requests
               if not isinstance(request, EntangleRequest)):
            raise ValueError("Semantic request references an unknown atom")
        for request in plan.requests:
            if isinstance(request, EntangleRequest) and any(atom not in initial_state.atoms_by_id for atom in request.atoms):
                raise ValueError("Semantic request references an unknown atom")
        self.plan = plan
        self.initial_state = initial_state
        self.state = initial_state
        self.completed = set()
        self.active_requests = set()
        self.staging_requests = set()
        self.staged_entangle = {}
        self.staged_measure = {}
        self.reserved_atoms = set()
        self.homes = {}
        for atom in initial_state.atoms:
            if atom.zone is not None and atom.site_id is not None:
                self.homes[atom.atom_id] = {
                    "position": atom.position,
                    "zone": atom.zone,
                    "site": atom.site_id,
                }
        if any(request.atom not in self.homes for request in plan.requests
               if not isinstance(request, EntangleRequest)):
            raise ValueError("Every semantic atom needs a fixed home site")
        if any(atom not in self.homes for request in plan.requests if isinstance(request, EntangleRequest)
               for atom in request.atoms):
            raise ValueError("Every semantic atom needs a fixed home site")

        capacities = dict(self.device_capacities)
        capacities.update({f"atom/{atom.atom_id}": 1 for atom in initial_state.atoms})
        self.locks = ResourceLock(capacities)
        self.resource_capacities = capacities
        self.events = []
        self.active_epochs = {}
        self.stages = {}
        self.epoch_serial = 0
        self.stage_serial = 0
        self.last_epoch_by_request = {}
        self.epochs = []
        self.resource_spans = []
        self.decisions = []
        self.diagnostics = []
        self.state_snapshots = [{"time": initial_state.current_time,
                                 "epoch_id": None,
                                 "state": initial_state.to_dict()}]
        self.measurement_results = {}
        self.now = float(initial_state.current_time)
        self.final_cleanup_started = False

    @staticmethod
    def _request_atoms(request):
        return request.atoms if isinstance(request, EntangleRequest) else (request.atom,)

    def _epoch_dependencies(self, requests=(), *, extra=()):
        request_by_id = self.plan.requests_by_id
        dependencies = set(extra)
        for request in requests:
            for dependency in request.dependencies:
                previous = self.last_epoch_by_request.get(dependency)
                if previous is not None:
                    dependencies.add(previous)
            previous = self.last_epoch_by_request.get(request.id)
            if previous is not None:
                dependencies.add(previous)
        # An epoch ID is always an actual previous epoch, never a semantic ID.
        return tuple(sorted(dependency for dependency in dependencies if dependency in self.active_epochs or
                            any(record["id"] == dependency for record in self.epochs)))

    def _new_epoch_id(self, family):
        epoch_id = f"epoch/{family.lower()}/{self.epoch_serial:06d}"
        self.epoch_serial += 1
        return epoch_id

    def _new_stage_id(self, purpose):
        stage_id = f"stage/{purpose.lower()}/{self.stage_serial:06d}"
        self.stage_serial += 1
        return stage_id

    def _ready(self):
        requests = []
        for request in self.plan.ready_requests(self.completed):
            if request.id in self.active_requests or request.id in self.staging_requests:
                continue
            if self.reserved_atoms.intersection(self._request_atoms(request)):
                continue
            if isinstance(request, EntangleRequest) and request.id in self.staged_entangle:
                continue
            if isinstance(request, MeasureRequest) and request.id in self.staged_measure:
                continue
            requests.append(request)
        return tuple(requests)

    def _record_rejection(self, family, request_ids, result):
        if isinstance(result, Infeasible):
            entry = {"family": family, "request_ids": list(request_ids),
                     "reason": result.reason, "diagnostics": dict(result.diagnostics)}
        else:
            entry = {"family": family, "request_ids": list(request_ids),
                     "reason": "UNKNOWN", "diagnostics": {}}
        self.diagnostics.append(entry)
        if hasattr(self, "current_decision"):
            self.current_decision["rejections"].append(entry)

    def _mark_selected(self, request_ids):
        """Accumulate semantic requests selected during one dispatch pass."""
        selected = self.current_decision.setdefault("selected", [])
        for request_id in request_ids:
            if request_id not in selected:
                selected.append(request_id)

    def _target_map(self, target_by_atom):
        result = {}
        for atom_id, target in target_by_atom.items():
            result[atom_id] = {"position": target["position"],
                               "zone": target["zone"],
                               "site": target.get("site")}
        return result

    def _target_metadata(self, targets):
        return {
            "target_zones": {atom: value["zone"] for atom, value in targets.items()},
            "target_sites": {atom: value.get("site") for atom, value in targets.items()},
        }

    def _check_target_occupancy(self, targets):
        moving_atoms = set(targets)
        occupied_sites = {atom.site_id: atom.atom_id for atom in self.state.atoms
                          if atom.site_id is not None and atom.atom_id not in moving_atoms}
        for atom_id, target in targets.items():
            site = target.get("site")
            if site is not None and site in occupied_sites:
                raise PlacementError("SITE_OCCUPIED", {"site": site, "atom": atom_id})
        stationary = [atom.position for atom in self.state.atoms if atom.atom_id not in moving_atoms
                      and atom.state != AtomState.LOST]
        for atom_id, target in targets.items():
            if any(target["position"].distance_to(position) < self.state.min_atom_separation - 1e-12
                   for position in stationary):
                raise PlacementError("MIN_SPACING", {"atom": atom_id, "stationary_atoms": len(stationary)})
        positions = [target["position"] for target in targets.values()]
        for index, left in enumerate(positions):
            if any(left.distance_to(right) < self.state.min_atom_separation - 1e-12
                   for right in positions[index + 1:]):
                raise PlacementError("MIN_SPACING", {"moving_atoms": len(positions)})

    def _compatible_segments(self, translations):
        remaining = list(translations)
        segments = []
        while remaining:
            segment = []
            for translation in tuple(remaining):
                candidate = tuple(segment) + (translation,)
                if self.config.aod.compatible(candidate):
                    segment.append(translation)
                    remaining.remove(translation)
            if not segment:
                reason = self.config.aod.incompatibility((remaining[0],)) or "AOD_INFEASIBLE"
                raise PlacementError(reason, {"atom": remaining[0].atom})
            segments.append(tuple(segment))
        return tuple(segments)

    def _start_transport(self, targets, *, purpose, request_ids=(), placements=None):
        targets = self._target_map(targets)
        if not targets:
            if purpose == "ENTANGLE":
                self.staged_entangle.update(placements or {})
            elif purpose == "MEASURE":
                self.staged_measure.update(placements or {})
            return True
        self._check_target_occupancy(targets)
        translations = tuple(
            Translation(atom_id, self.state.atoms_by_id[atom_id].position, target["position"])
            for atom_id, target in targets.items()
            if self.state.atoms_by_id[atom_id].position != target["position"]
        )
        if not translations:
            if purpose == "ENTANGLE":
                self.staged_entangle.update(placements or {})
            elif purpose == "MEASURE":
                self.staged_measure.update(placements or {})
            return True
        # A logical stage reserves all of its atoms for the complete staged
        # move.  Check the shared device and that full reservation before
        # publishing the stage; a busy device is a normal scheduling wait, not
        # a runtime error.
        reservation = {"device/aod": 1}
        reservation.update({f"atom/{atom_id}": 1 for atom_id in targets})
        if not self.locks.can_acquire({"stage-probe": reservation}):
            return False
        segments = self._compatible_segments(translations)
        stage_id = self._new_stage_id(purpose)
        stage = _MovementStage(stage_id, purpose, tuple(request_ids), targets,
                               dict(placements or {}), segments)
        self.stages[stage_id] = stage
        self.staging_requests.update(request_ids)
        self.reserved_atoms.update(targets)
        self._launch_stage_segment(stage, extra_dependencies=self._epoch_dependencies(
            self.plan.requests_by_id[request_id] for request_id in request_ids
            if request_id in self.plan.requests_by_id))
        return True

    def _launch_stage_segment(self, stage, *, extra_dependencies=()):
        segment = stage.segments[stage.next_segment]
        epoch_id = self._new_epoch_id("AOD_MOVEMENT")
        result = self.oracle.plan_transport(
            segment, epoch_id=epoch_id, request_ids=stage.request_ids,
            dependencies=extra_dependencies,
            metadata={"stage_id": stage.id, "purpose": stage.purpose,
                      **self._target_metadata({atom: stage.targets[atom] for atom in stage.targets
                                               if atom in {translation.atom for translation in segment}})})
        if not result.ok:
            raise RuntimeSchedulingError("AOD_INFEASIBLE", {
                "stage": stage.id, "reason": result.reason,
                "diagnostics": result.diagnostics})
        self._start_epoch(result.epoch, stage=stage)

    def _start_epoch(self, epoch: PhysicalEpoch, *, stage=None):
        requirements = {requirement.resource: requirement.units
                        for requirement in epoch.resource_requirements}
        if not self.locks.can_acquire({epoch.id: requirements}):
            raise RuntimeSchedulingError("DEVICE_BUSY", {"epoch": epoch.id,
                                                          "resources": requirements})
        if not self.locks.acquire({epoch.id: requirements}):
            raise RuntimeSchedulingError("DEVICE_BUSY", {"epoch": epoch.id})
        start_time = self.now
        end_time = self.now + epoch.duration
        epoch_record = self._serialize_epoch(epoch, start_time, end_time, stage=stage)
        self.epochs.append(epoch_record)
        self.resource_spans.append({"owner": epoch.id, "resources": requirements,
                                    "start_time": start_time, "end_time": end_time})
        self.active_epochs[epoch.id] = {"epoch": epoch, "stage": stage,
                                        "record": epoch_record}
        for request_id in epoch.request_ids:
            self.active_requests.add(request_id)
            self.last_epoch_by_request[request_id] = epoch.id
        heapq.heappush(self.events, (end_time, self.epoch_serial, epoch.id))
        self.epoch_serial += 1

    def _serialize_epoch(self, epoch, start_time, end_time, *, stage=None):
        data = epoch.to_dict()
        data.update({"start_time": start_time, "end_time": end_time,
                     "batch_size": len(epoch.request_ids),
                     "stage_id": stage.id if stage is not None else None,
                     "purpose": stage.purpose if stage is not None else None})
        # Keep logical provenance on the same trace record as the physical
        # epoch.  The runtime remains responsible only for scheduling; this
        # small denormalized view lets experiment reports and visualizations
        # identify a concurrent logical layer without rebuilding a schedule.
        request_metadata = {}
        logical_operations = set()
        interaction_groups = set()
        for request_id in epoch.request_ids:
            request = self.plan.requests_by_id.get(request_id)
            if request is None:
                continue
            metadata = dict(request.metadata)
            request_metadata[request_id] = metadata
            for key in ("logical_operation_id", "logical_operation"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    logical_operations.add(value)
            value = metadata.get("interaction_group_id")
            if isinstance(value, str) and value:
                interaction_groups.add(value)
        if request_metadata:
            data["request_metadata"] = request_metadata
        if logical_operations:
            data["logical_ops"] = sorted(logical_operations)
        if interaction_groups:
            data["interaction_group_ids"] = sorted(interaction_groups)
        positions = {atom.atom_id: atom.position.to_list() for atom in self.state.atoms
                     if atom.atom_id in epoch.atoms}
        zones = {atom.atom_id: atom.zone for atom in self.state.atoms
                 if atom.atom_id in epoch.atoms}
        data["source_positions"] = {atom: value for atom, value in positions.items()}
        data["target_positions"] = {atom: value for atom, value in positions.items()}
        data["source_zones"] = zones
        data["target_zones"] = zones
        if isinstance(epoch, AODMovementEpoch):
            data["source_positions"] = {atom: position.to_list()
                                         for atom, position in epoch.source_positions.items()}
            data["target_positions"] = {atom: position.to_list()
                                         for atom, position in epoch.target_positions.items()}
            target_zones = epoch.metadata.get("target_zones", {})
            target_sites = epoch.metadata.get("target_sites", {})
            data["target_zones"] = dict(target_zones)
            data["target_sites"] = dict(target_sites)
            data["batch_size"] = len(epoch.atoms)
        elif isinstance(epoch, RydbergEpoch):
            data["batch_size"] = len(epoch.pairs)
            data["pair_count"] = len(epoch.pairs)
        elif isinstance(epoch, ImagingEpoch):
            data["batch_size"] = len(epoch.atoms)
            data["measurement_batch_size"] = len(epoch.atoms)
        return data

    def _apply_movement(self, epoch):
        target_zones = dict(epoch.metadata.get("target_zones", {}))
        target_sites = dict(epoch.metadata.get("target_sites", {}))
        updates = {}
        for atom_id, position in epoch.target_positions.items():
            atom = self.state.atoms_by_id[atom_id]
            zone_id = target_zones.get(atom_id)
            if zone_id is None:
                zone_id = self._infer_zone(position)
            zone = self.state.zones_by_id[zone_id]
            site_id = target_sites.get(atom_id)
            if zone.kind.name == "ENTANGLING":
                state = AtomState.IN_ENTANGLING_REGION
                site_id = None
            elif zone.kind.name == "MEASUREMENT":
                state = AtomState.IN_MEASUREMENT_REGION
                site_id = None
            elif atom.atom_type == AtomType.RESERVOIR:
                state = AtomState.IDLE
            else:
                state = AtomState.IDLE
            updates[atom_id] = (position, zone_id, site_id, state)
        atoms = []
        for atom in self.state.atoms:
            if atom.atom_id not in updates:
                atoms.append(atom)
                continue
            position, zone, site, state = updates[atom.atom_id]
            atoms.append(type(atom)(atom.atom_id, atom.assigned_qubit, atom.atom_type,
                                    position, zone, site, state, atom.syndrome_basis))
        self.state = HardwareState(tuple(atoms), self.state.zones,
                                   current_time=self.now,
                                   min_atom_separation=self.state.min_atom_separation)

    def _infer_zone(self, position):
        candidates = [zone.id for zone in self.state.zones if zone.bounds.contains(position)]
        if len(candidates) != 1:
            raise RuntimeSchedulingError("ZONE_UNAVAILABLE", {"position": position.to_list(),
                                                                "candidates": candidates})
        return candidates[0]

    def _complete_epoch(self, epoch_id):
        active = self.active_epochs.pop(epoch_id)
        epoch, stage = active["epoch"], active["stage"]
        self.locks.release(epoch.id)
        self.now = active["record"]["end_time"]
        if isinstance(epoch, AODMovementEpoch):
            self._apply_movement(epoch)
            self.state_snapshots.append({"time": self.now, "epoch_id": epoch.id,
                                         "state": self.state.to_dict()})
            if stage is not None:
                stage.next_segment += 1
                if stage.next_segment < len(stage.segments):
                    self._launch_stage_segment(stage, extra_dependencies=(epoch.id,))
                    return
                self.reserved_atoms.difference_update(stage.atoms)
                self.staging_requests.difference_update(stage.request_ids)
                self.active_requests.difference_update(stage.request_ids)
                self.stages.pop(stage.id, None)
                if stage.purpose == "ENTANGLE":
                    self.staged_entangle.update(stage.placements)
                elif stage.purpose == "MEASURE":
                    self.staged_measure.update(stage.placements)
            return

        self.active_requests.difference_update(epoch.request_ids)
        for request_id in epoch.request_ids:
            request = self.plan.requests_by_id[request_id]
            for atom_id in self._request_atoms(request):
                atom = self.state.atoms_by_id[atom_id]
                if isinstance(epoch, ImagingEpoch):
                    state = AtomState.MEASURED
                    key = next(key for key, placement in zip(epoch.measurement_keys, epoch.placements)
                               if placement.atom == atom_id)
                    self.measurement_results[key] = 0
                elif self.state.zones_by_id[atom.zone].kind.name == "ENTANGLING":
                    state = AtomState.IN_ENTANGLING_REGION
                elif self.state.zones_by_id[atom.zone].kind.name == "MEASUREMENT":
                    state = AtomState.IN_MEASUREMENT_REGION
                else:
                    state = AtomState.IDLE
                replacement = type(atom)(atom.atom_id, atom.assigned_qubit, atom.atom_type,
                                         atom.position, atom.zone, atom.site_id,
                                         state, atom.syndrome_basis)
                self.state = HardwareState(tuple(replacement if item.atom_id == atom_id else item
                                                  for item in self.state.atoms),
                                            self.state.zones, current_time=self.now,
                                            min_atom_separation=self.state.min_atom_separation)

        if isinstance(epoch, RydbergEpoch):
            for request_id in epoch.request_ids:
                self.staged_entangle.pop(request_id, None)
            self.completed.update(epoch.request_ids)
        elif isinstance(epoch, ImagingEpoch):
            for request_id in epoch.request_ids:
                self.staged_measure.pop(request_id, None)
                self.completed.add(request_id)
        else:
            self.completed.update(epoch.request_ids)

        self.state_snapshots.append({"time": self.now, "epoch_id": epoch.id,
                                     "state": self.state.to_dict()})

    def _complete_ready_events(self):
        completed_any = False
        while self.events and self.events[0][0] <= self.now + 1e-12:
            _, _, epoch_id = heapq.heappop(self.events)
            if epoch_id in self.active_epochs:
                self._complete_epoch(epoch_id)
                completed_any = True
        return completed_any

    def _home_targets(self, atom_ids):
        return {atom_id: self.homes[atom_id] for atom_id in atom_ids}

    def _needs_home_for_operation(self, batch, operation):
        needs = []
        for request in batch.requests:
            for atom_id in self._request_atoms(request):
                atom = self.state.atoms_by_id[atom_id]
                zone = self.state.zones_by_id[atom.zone]
                if not zone.allows(operation):
                    home = self.state.zones_by_id[self.homes[atom_id]["zone"]]
                    if not home.allows(operation):
                        raise RuntimeSchedulingError("ZONE_UNAVAILABLE", {
                            "atom": atom_id, "operation": operation.value})
                    needs.append(atom_id)
        return tuple(dict.fromkeys(needs))

    def _start_entangle(self, ready):
        for batch in self.batch_builder.candidates(ready, "ENTANGLE"):
            requests = batch.requests
            requested_atoms = set(batch.atoms)
            entangling_zone = self.oracle.spatial.entangling_zone
            outgoing = tuple(sorted(atom.atom_id for atom in self.state.atoms
                                    if atom.zone == entangling_zone and atom.atom_id not in requested_atoms))
            if outgoing:
                try:
                    if not self._start_transport(self._home_targets(outgoing), purpose="RETIRE_RESIDENTS"):
                        continue
                    self._mark_selected(batch.request_ids)
                    self.current_decision["started"] += 1
                    return True
                except PlacementError as exc:
                    self._record_rejection("TRANSPORT", outgoing,
                                           Infeasible(exc.reason, exc.diagnostics))
                    continue
            result = self.oracle.plan_entanglement_batch(
                requests, self.state, epoch_id=self._new_epoch_id("RYDBERG"),
                dependencies=self._epoch_dependencies(requests))
            if not result.ok:
                self._record_rejection("ENTANGLE", batch.request_ids, result)
                continue
            placements = {placement.request_id: placement
                           for placement in result.epoch.pair_placements}
            targets = {}
            for placement in result.epoch.pair_placements:
                for atom_id, position in zip(placement.atoms, placement.positions):
                    targets[atom_id] = {"position": position, "zone": "entangling", "site": None}
            try:
                if not self._start_transport(targets, purpose="ENTANGLE",
                                              request_ids=batch.request_ids, placements=placements):
                    continue
            except PlacementError as exc:
                self._record_rejection("TRANSPORT", batch.request_ids,
                                       Infeasible(exc.reason, exc.diagnostics))
                continue
            if not self.staged_entangle.keys() >= set(batch.request_ids):
                self._mark_selected(batch.request_ids)
                self.current_decision["started"] += 1
                return True
            # No movement was needed; the staged requests can be pulsed below
            # on the next scheduler pass, after this decision is recorded.
            self._mark_selected(batch.request_ids)
            self.current_decision["started"] += 1
            return True
        return False

    def _start_measurement(self, ready):
        if not any(isinstance(request, MeasureRequest) for request in ready):
            return False
        # Keep the intended split visible in the trace before imaging ancillas.
        entangling_zone = self.oracle.spatial.entangling_zone
        data_to_home = tuple(sorted(atom.atom_id for atom in self.state.atoms
                                    if atom.atom_type == AtomType.DATA and atom.zone == entangling_zone))
        if data_to_home:
            try:
                if not self._start_transport(self._home_targets(data_to_home), purpose="RETURN_DATA"):
                    return False
                self.current_decision["started"] += 1
                return True
            except PlacementError as exc:
                self._record_rejection("TRANSPORT", data_to_home,
                                       Infeasible(exc.reason, exc.diagnostics))

        for batch in self.batch_builder.candidates(ready, "MEASURE"):
            requested_atoms = set(batch.atoms)
            measurement_zone = self.oracle.spatial.measurement_zone
            outgoing = tuple(sorted(atom.atom_id for atom in self.state.atoms
                                    if atom.zone == measurement_zone and atom.atom_id not in requested_atoms))
            if outgoing:
                try:
                    if not self._start_transport(self._home_targets(outgoing), purpose="RETIRE_MEASUREMENT"):
                        continue
                    self._mark_selected(batch.request_ids)
                    self.current_decision["started"] += 1
                    return True
                except PlacementError as exc:
                    self._record_rejection("TRANSPORT", outgoing,
                                           Infeasible(exc.reason, exc.diagnostics))
                    continue
            result = self.oracle.plan_measurement_batch(
                batch.requests, self.state, epoch_id=self._new_epoch_id("IMAGING"),
                dependencies=self._epoch_dependencies(batch.requests))
            if not result.ok:
                self._record_rejection("MEASURE", batch.request_ids, result)
                continue
            placements = {placement.request_id: placement
                           for placement in result.epoch.placements}
            targets = {placement.atom: {"position": placement.position,
                                        "zone": "measurement", "site": None}
                       for placement in result.epoch.placements}
            try:
                if not self._start_transport(targets, purpose="MEASURE",
                                              request_ids=batch.request_ids, placements=placements):
                    continue
            except PlacementError as exc:
                self._record_rejection("TRANSPORT", batch.request_ids,
                                       Infeasible(exc.reason, exc.diagnostics))
                continue
            self._mark_selected(batch.request_ids)
            self.current_decision["started"] += 1
            return True
        return False

    def _start_operation(self, ready, kind):
        batch = self.batch_builder.build(ready, kind)
        if batch is None:
            return False
        operation = {"PREPARE": HardwareOperation.PREPARE,
                     "RESET": HardwareOperation.RESET,
                     "SINGLE_QUBIT": HardwareOperation.LOCAL_1Q}[kind]
        try:
            needs_home = self._needs_home_for_operation(batch, operation)
            if needs_home:
                if not self._start_transport(self._home_targets(needs_home), purpose=f"STAGE_{kind}",
                                              request_ids=batch.request_ids):
                    return False
                self._mark_selected(batch.request_ids)
                self.current_decision["started"] += 1
                return True
        except RuntimeSchedulingError as exc:
            self._record_rejection(kind, batch.request_ids,
                                   Infeasible(exc.reason, exc.diagnostics))
            return False
        epoch_id = self._new_epoch_id(kind)
        dependencies = self._epoch_dependencies(batch.requests)
        result = {
            "PREPARE": self.oracle.plan_prepare_batch,
            "RESET": self.oracle.plan_reset_batch,
            "SINGLE_QUBIT": self.oracle.plan_single_qubit_batch,
        }[kind](batch.requests, self.state, epoch_id=epoch_id, dependencies=dependencies)
        if not result.ok:
            self._record_rejection(kind, batch.request_ids, result)
            return False
        try:
            self._start_epoch(result.epoch)
        except RuntimeSchedulingError as exc:
            self._record_rejection(kind, batch.request_ids,
                                   Infeasible(exc.reason, exc.diagnostics))
            return False
        self._mark_selected(batch.request_ids)
        self.current_decision["started"] += 1
        return True

    def _start_staged_entangle(self):
        ready_ids = [request_id for request_id in sorted(self.staged_entangle)
                     if request_id not in self.active_requests]
        if not ready_ids:
            return False
        # All staged requests for the same runtime layer are already disjoint;
        # preserve the request order recorded by the placement planner.
        requests = tuple(self.plan.requests_by_id[request_id] for request_id in ready_ids)
        epoch_id = self._new_epoch_id("RYDBERG")
        result = self.oracle.plan_entanglement_batch(
            requests, self.state, epoch_id=epoch_id,
            dependencies=self._epoch_dependencies(requests))
        if not result.ok:
            self._record_rejection("ENTANGLE", ready_ids, result)
            return False
        try:
            self._start_epoch(result.epoch)
        except RuntimeSchedulingError as exc:
            self._record_rejection("ENTANGLE", ready_ids,
                                   Infeasible(exc.reason, exc.diagnostics))
            return False
        self._mark_selected(ready_ids)
        self.current_decision["started"] += 1
        return True

    def _start_staged_measurement(self):
        ready_ids = [request_id for request_id in sorted(self.staged_measure)
                     if request_id not in self.active_requests]
        if not ready_ids:
            return False
        requests = tuple(self.plan.requests_by_id[request_id] for request_id in ready_ids)
        epoch_id = self._new_epoch_id("IMAGING")
        result = self.oracle.plan_measurement_batch(
            requests, self.state, epoch_id=epoch_id,
            dependencies=self._epoch_dependencies(requests))
        if not result.ok:
            self._record_rejection("MEASURE", ready_ids, result)
            return False
        try:
            self._start_epoch(result.epoch)
        except RuntimeSchedulingError as exc:
            self._record_rejection("MEASURE", ready_ids,
                                   Infeasible(exc.reason, exc.diagnostics))
            return False
        self._mark_selected(ready_ids)
        self.current_decision["started"] += 1
        return True

    def _start_final_cleanup(self):
        non_home = tuple(sorted(atom.atom_id for atom in self.state.atoms
                                if atom.atom_id in self.homes and (
                                    atom.position != self.homes[atom.atom_id]["position"]
                                    or atom.zone != self.homes[atom.atom_id]["zone"]
                                    or atom.site_id != self.homes[atom.atom_id]["site"])))
        self.final_cleanup_started = True
        if not non_home:
            return False
        if not self._start_transport(self._home_targets(non_home), purpose="FINAL_RETURN"):
            return False
        self.current_decision["started"] += 1
        return True

    def _dispatch(self):
        ready = self._ready()
        self.current_decision = {
            "time": self.now,
            "ready_requests": len(ready),
            "ready_by_family": {family: sum(self._family_matches(request, family) for request in ready)
                                 for family in self._family_order},
            "selected": [], "started": 0, "rejections": []}
        started = False
        if self._start_staged_entangle():
            started = True
        if self._start_staged_measurement():
            started = True
        for family in self._family_order:
            if family == "ENTANGLE":
                started = self._start_entangle(ready) or started
            elif family == "MEASURE":
                started = self._start_measurement(ready) or started
            else:
                started = self._start_operation(ready, family) or started
        self.current_decision["started_any"] = started
        self.current_decision["selected_count"] = len(self.current_decision["selected"])
        self.current_decision["scheduled_request_count"] = len(self.current_decision["selected"])
        self.current_decision["successful_batch_count"] = self.current_decision["started"]
        self.current_decision["batch_size"] = len(self.current_decision["selected"])
        self.current_decision["rejection_count"] = len(self.current_decision["rejections"])
        self.decisions.append(self.current_decision)
        return started

    @staticmethod
    def _family_matches(request, family):
        return ((family == "ENTANGLE" and isinstance(request, EntangleRequest)) or
                (family == "MEASURE" and isinstance(request, MeasureRequest)) or
                (family == "SINGLE_QUBIT" and isinstance(request, SingleQubitRequest)) or
                (family == "PREPARE" and isinstance(request, PrepareRequest)) or
                (family == "RESET" and isinstance(request, ResetRequest)))

    def run(self, plan, initial_state):
        self._reset_runtime(plan, initial_state)
        iterations = 0
        while True:
            iterations += 1
            if iterations > max(10000, 200 * (len(self.plan.requests) + 1)):
                raise RuntimeSchedulingError("ITERATION_LIMIT", {
                    "time": self.now, "completed": len(self.completed),
                    "requests": len(self.plan.requests),
                    "active_epochs": sorted(self.active_epochs),
                    "events": len(self.events),
                    "stages": sorted(self.stages),
                    "stage_info": {key: {"purpose": value.purpose,
                                         "next_segment": value.next_segment,
                                         "segment_count": len(value.segments),
                                         "requests": list(value.request_ids)}
                                   for key, value in self.stages.items()},
                })
            self._complete_ready_events()
            if len(self.completed) == len(self.plan.requests):
                if self.active_epochs or self.events or self.stages:
                    # A stage may still have a final completion event.
                    pass
                elif not self.final_cleanup_started:
                    self.current_decision = {"time": self.now, "ready_requests": 0,
                                             "ready_by_family": {}, "selected": [],
                                             "started": 0, "rejections": [],
                                             "selected_count": 0,
                                             "scheduled_request_count": 0,
                                             "successful_batch_count": 0,
                                             "batch_size": 0,
                                             "rejection_count": 0}
                    self._start_final_cleanup()
                    self.current_decision["started_any"] = bool(self.active_epochs)
                    self.current_decision["selected_count"] = len(self.current_decision["selected"])
                    self.current_decision["scheduled_request_count"] = len(self.current_decision["selected"])
                    self.current_decision["successful_batch_count"] = self.current_decision["started"]
                    self.current_decision["batch_size"] = len(self.current_decision["selected"])
                    self.current_decision["rejection_count"] = len(self.current_decision["rejections"])
                    self.decisions.append(self.current_decision)
                    if not self.active_epochs:
                        break
                elif not self.active_epochs and not self.events and not self.stages:
                    break

            started = self._dispatch()
            if self.events:
                next_time = self.events[0][0]
                if next_time < self.now - 1e-12:
                    raise RuntimeSchedulingError("TIME_ORDER", {"now": self.now, "next": next_time})
                self.now = next_time
                continue
            if len(self.completed) == len(self.plan.requests) and not self.stages:
                continue
            if not started:
                ready = self._ready()
                diagnostics = {
                    "time": self.now,
                    "ready_requests": [request.id for request in ready],
                    "active_epochs": sorted(self.active_epochs),
                    "staged_entangle": sorted(self.staged_entangle),
                    "staged_measure": sorted(self.staged_measure),
                    "rejections": self.current_decision.get("rejections", []),
                }
                self.diagnostics.append({"reason": "DEADLOCK", "diagnostics": diagnostics})
                raise RuntimeSchedulingError("DEADLOCK", diagnostics)

        final_atoms = []
        for atom in self.state.atoms:
            if atom.atom_id in self.homes:
                home = self.homes[atom.atom_id]
                final_atoms.append(type(atom)(atom.atom_id, atom.assigned_qubit, atom.atom_type,
                                              home["position"], home["zone"], home["site"],
                                              AtomState.IDLE, atom.syndrome_basis))
            else:
                final_atoms.append(atom)
        self.state = HardwareState(tuple(final_atoms), self.state.zones,
                                   current_time=self.now,
                                   min_atom_separation=self.state.min_atom_separation)
        self.state_snapshots.append({"time": self.now, "epoch_id": None,
                                     "state": self.state.to_dict()})
        trace = {
            "schema_version": 2,
            "kind": "execution_trace",
            "units": {"length": "um", "time": "us"},
            "initial_state": initial_state.to_dict(),
            "final_state": self.state.to_dict(),
            "duration": self.now,
            "epochs": sorted(self.epochs, key=lambda epoch: (epoch["start_time"], epoch["id"])),
            "resource_spans": self.resource_spans,
            "resource_capacities": self.resource_capacities,
            "decisions": self.decisions,
            "diagnostics": self.diagnostics,
            "state_snapshots": self.state_snapshots,
            "measurement_results": self.measurement_results,
            "gate_completion": {key: list(value) for key, value in self.plan.gate_completion.items()},
            "aod": self.config.aod.to_dict(),
            "model_limits": [
                "Straight-line endpoint planning is used; continuous collision-free optimal control is not modeled.",
                "No quantum state, noise, loss, decoder, or pulse-shape simulation.",
                "AOD ordering is conservative when ordering_rule=preserve_order; incompatible sets are split greedily.",
            ],
        }
        # Keep the trace self-describing for callers that use RuntimeScheduler
        # directly.  The public simulation wrapper recomputes the same report
        # after adding its user-facing configuration block.
        from ..trace import epoch_metrics
        trace["metrics"] = epoch_metrics(trace)
        return trace


EventDrivenScheduler = RuntimeScheduler


__all__ = ["RuntimeSchedulingError", "RuntimeScheduler", "EventDrivenScheduler"]
