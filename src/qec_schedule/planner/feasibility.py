"""Structured hardware feasibility decisions for runtime batches."""
from dataclasses import dataclass

from ..compiler.semantic_requests import (EntangleRequest, MeasureRequest,
                                          PrepareRequest, ResetRequest,
                                          SingleQubitRequest)
from ..hardware import HardwareOperation
from ..hardware.aod import Translation
from .spatial_planner import PlacementError, SpatialPlanner


@dataclass(frozen=True)
class Feasible:
    epoch: object

    @property
    def ok(self):
        return True


@dataclass(frozen=True)
class Infeasible:
    reason: str
    diagnostics: dict

    @property
    def ok(self):
        return False

    epoch = None


def _reason(exc):
    if isinstance(exc, PlacementError):
        return exc.reason, dict(exc.diagnostics)
    text = str(exc)
    return text.split(":", 1)[0] or "PLACEMENT_FAILURE", {}


class HardwareFeasibilityOracle:
    """Build epochs or return an explainable rejection, never a bare bool."""

    def __init__(self, config, *, spatial_planner=None, rydberg_parallel_pairs=None):
        self.config = config
        self.spatial = spatial_planner or SpatialPlanner()
        self.rydberg_parallel_pairs = rydberg_parallel_pairs

    def _fail(self, exc):
        reason, diagnostics = _reason(exc)
        return Infeasible(reason, diagnostics)

    def _atoms(self, requests, state):
        atoms = []
        for request in requests:
            atoms.extend(request.atoms if isinstance(request, EntangleRequest) else (request.atom,))
        if len(atoms) != len(set(atoms)):
            raise ValueError("ATOM_CONFLICT")
        unknown = sorted(set(atoms) - state.atoms_by_id.keys())
        if unknown:
            raise ValueError(f"ATOM_UNKNOWN: {unknown}")
        return tuple(atoms)

    @staticmethod
    def _check_operation(requests, state, operation):
        for request in requests:
            atoms = request.atoms if isinstance(request, EntangleRequest) else (request.atom,)
            for atom_id in atoms:
                atom = state.atoms_by_id[atom_id]
                zone = state.zones_by_id.get(atom.zone)
                if zone is None or not zone.allows(operation):
                    raise ValueError("ZONE_UNAVAILABLE")

    def plan_entanglement_batch(self, requests, state, *, epoch_id, dependencies=()):
        from ..execution import RydbergEpoch
        requests = tuple(requests)
        try:
            self._atoms(requests, state)
            placements = self.spatial.plan_entanglement(requests, state)
            if (self.rydberg_parallel_pairs is not None
                    and len(requests) > self.rydberg_parallel_pairs):
                raise ValueError("ZONE_CAPACITY")
            epoch = RydbergEpoch.create(epoch_id, requests, placements,
                                        dependencies=dependencies,
                                        duration=self.config.timing.entangle_duration,
                                        metadata={"batch_family": "ENTANGLE"})
            return Feasible(epoch)
        except (ValueError, KeyError) as exc:
            return self._fail(exc)

    def plan_measurement_batch(self, requests, state, *, epoch_id, dependencies=()):
        from ..execution import ImagingEpoch
        requests = tuple(requests)
        try:
            self._atoms(requests, state)
            placements = self.spatial.plan_measurement(requests, state)
            epoch = ImagingEpoch.create(epoch_id, requests, placements,
                                        dependencies=dependencies,
                                        duration=self.config.timing.measurement_duration,
                                        metadata={"batch_family": "MEASURE"})
            return Feasible(epoch)
        except (ValueError, KeyError) as exc:
            return self._fail(exc)

    def plan_transport(self, translations, *, epoch_id, request_ids=(), dependencies=(), metadata=None):
        from ..execution import AODMovementEpoch
        try:
            program = self.config.aod.build_program(tuple(translations))
            return Feasible(AODMovementEpoch.create(epoch_id, tuple(request_ids), program,
                                                    dependencies=dependencies, metadata=metadata or {}))
        except (ValueError, KeyError) as exc:
            return self._fail(exc)

    def _plan_atom_batch(self, requests, state, *, epoch_id, dependencies, kind):
        from ..execution import LocalPulseEpoch, PreparationEpoch, ResetEpoch
        requests = tuple(requests)
        try:
            self._atoms(requests, state)
            operation = {"SINGLE_QUBIT": HardwareOperation.LOCAL_1Q,
                         "PREPARE": HardwareOperation.PREPARE,
                         "RESET": HardwareOperation.RESET}[kind]
            self._check_operation(requests, state, operation)
            atoms = tuple(request.atom for request in requests)
            duration = {"SINGLE_QUBIT": self.config.timing.single_qubit_duration,
                        "PREPARE": self.config.timing.prepare_duration,
                        "RESET": self.config.timing.reset_duration}[kind]
            if kind == "SINGLE_QUBIT":
                epoch = LocalPulseEpoch.create(epoch_id, [r.id for r in requests], atoms,
                                               duration=duration, dependencies=dependencies,
                                               metadata={"batch_family": kind,
                                                         "operations": [r.operation for r in requests]})
            elif kind == "PREPARE":
                epoch = PreparationEpoch.create(epoch_id, [r.id for r in requests], atoms,
                                                duration=duration, dependencies=dependencies,
                                                metadata={"batch_family": kind})
            else:
                epoch = ResetEpoch.create(epoch_id, [r.id for r in requests], atoms,
                                          duration=duration, dependencies=dependencies,
                                          metadata={"batch_family": kind})
            return Feasible(epoch)
        except (ValueError, KeyError) as exc:
            return self._fail(exc)

    def plan_single_qubit_batch(self, requests, state, *, epoch_id, dependencies=()):
        return self._plan_atom_batch(requests, state, epoch_id=epoch_id,
                                     dependencies=dependencies, kind="SINGLE_QUBIT")

    def plan_prepare_batch(self, requests, state, *, epoch_id, dependencies=()):
        return self._plan_atom_batch(requests, state, epoch_id=epoch_id,
                                     dependencies=dependencies, kind="PREPARE")

    def plan_reset_batch(self, requests, state, *, epoch_id, dependencies=()):
        return self._plan_atom_batch(requests, state, epoch_id=epoch_id,
                                     dependencies=dependencies, kind="RESET")


__all__ = ["Feasible", "Infeasible", "HardwareFeasibilityOracle"]
