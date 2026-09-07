"""Physical epoch IR: the smallest units that acquire shared hardware."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from ..hardware.aod import AODProgram
from ..hardware.geometry import finite_number
from ..lowering.experimental_ir import ResourceRequirement
from ..planner.spatial_planner import MeasurementPlacement, PairPlacement


class EpochType(str, Enum):
    AOD_MOVEMENT = "AOD_MOVEMENT"
    RYDBERG = "RYDBERG"
    IMAGING = "IMAGING"
    LOCAL_1Q = "LOCAL_1Q"
    PREPARE = "PREPARE"
    RESET = "RESET"


def _requirements(values):
    values = tuple(values)
    if len({value.resource for value in values}) != len(values):
        raise ValueError("Epoch resource requirements must be unique")
    return values


@dataclass(frozen=True)
class PhysicalEpoch:
    id: str
    epoch_type: EpochType
    request_ids: tuple[str, ...]
    atoms: tuple[str, ...]
    duration: float
    dependencies: tuple[str, ...] = ()
    resource_requirements: tuple[ResourceRequirement, ...] = ()
    metadata: Mapping = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "epoch_type", EpochType(self.epoch_type))
        for name in ("request_ids", "atoms", "dependencies", "resource_requirements"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        duration = finite_number(self.duration, "duration")
        object.__setattr__(self, "duration", duration)
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Epoch requires a nonempty ID")
        if duration <= 0:
            raise ValueError("Epoch duration must be positive")
        if len(set(self.request_ids)) != len(self.request_ids) or len(set(self.atoms)) != len(self.atoms):
            raise ValueError("Epoch request and atom IDs must be unique")
        if len(set(self.dependencies)) != len(self.dependencies) or self.id in self.dependencies:
            raise ValueError("Invalid epoch dependencies")
        if not all(isinstance(requirement, ResourceRequirement) for requirement in self.resource_requirements):
            raise ValueError("Epoch resources must be ResourceRequirement values")
        object.__setattr__(self, "resource_requirements", _requirements(self.resource_requirements))

    @property
    def resources(self):
        return tuple(requirement.resource for requirement in self.resource_requirements)

    def to_dict(self):
        return {"id": self.id, "type": self.epoch_type.value,
                "request_ids": list(self.request_ids), "atoms": list(self.atoms),
                "duration": self.duration, "dependencies": list(self.dependencies),
                "resources": [requirement.resource for requirement in self.resource_requirements],
                "resource_requirements": [requirement.to_dict() for requirement in self.resource_requirements],
                "metadata": dict(self.metadata)}


def _atom_resources(atoms):
    return tuple(ResourceRequirement(f"atom/{atom}") for atom in atoms)


@dataclass(frozen=True)
class AODMovementEpoch(PhysicalEpoch):
    program: AODProgram | None = None

    @classmethod
    def create(cls, id_, request_ids, program: AODProgram, *, dependencies=(), metadata=None):
        atoms = program.atoms
        resources = (ResourceRequirement("device/aod"), *_atom_resources(atoms))
        return cls(id_, EpochType.AOD_MOVEMENT, tuple(request_ids), atoms, program.duration,
                   tuple(dependencies), resources, metadata or {}, program)

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.program, AODProgram) or self.program.atoms != self.atoms:
            raise ValueError("AOD epoch must carry a program matching its atom set")

    @property
    def source_positions(self):
        return self.program.atom_sources

    @property
    def target_positions(self):
        return self.program.atom_targets

    def to_dict(self):
        return {**super().to_dict(), "aod": self.program.to_dict(),
                "source_positions": {atom: position.to_list() for atom, position in self.source_positions.items()},
                "target_positions": {atom: position.to_list() for atom, position in self.target_positions.items()}}


@dataclass(frozen=True)
class RydbergEpoch(PhysicalEpoch):
    pairs: tuple[tuple[str, str], ...] = ()
    pair_placements: tuple[PairPlacement, ...] = ()

    @classmethod
    def create(cls, id_, requests, pair_placements, *, dependencies=(), duration=1.0, metadata=None):
        requests = tuple(requests)
        placements = tuple(pair_placements)
        if not requests or len(requests) != len(placements):
            raise ValueError("Rydberg epoch needs one placement per request")
        if {request.id for request in requests} != {placement.request_id for placement in placements}:
            raise ValueError("Rydberg placements must match request IDs")
        by_id = {placement.request_id: placement for placement in placements}
        ordered = tuple(by_id[request.id] for request in requests)
        pairs = tuple(placement.atoms for placement in ordered)
        atoms = tuple(atom for pair in pairs for atom in pair)
        if len(set(atoms)) != len(atoms):
            raise ValueError("Rydberg epoch pairs must be atom-disjoint")
        resources = (ResourceRequirement("device/rydberg"), *_atom_resources(atoms))
        return cls(id_, EpochType.RYDBERG, tuple(request.id for request in requests), atoms,
                   duration, tuple(dependencies), resources, metadata or {}, pairs, ordered)

    def __post_init__(self):
        super().__post_init__()
        object.__setattr__(self, "pairs", tuple(tuple(pair) for pair in self.pairs))
        object.__setattr__(self, "pair_placements", tuple(self.pair_placements))
        if len(self.pairs) != len(self.pair_placements) or tuple(atom for pair in self.pairs for atom in pair) != self.atoms:
            raise ValueError("Rydberg pairs and placements must match epoch atoms")

    def to_dict(self):
        return {**super().to_dict(), "pairs": [list(pair) for pair in self.pairs],
                "pair_placements": [placement.to_dict() for placement in self.pair_placements]}


@dataclass(frozen=True)
class ImagingEpoch(PhysicalEpoch):
    placements: tuple[MeasurementPlacement, ...] = ()
    measurement_keys: tuple[str, ...] = ()

    @classmethod
    def create(cls, id_, requests, placements, *, dependencies=(), duration=20.0, metadata=None):
        requests = tuple(requests)
        placements = tuple(placements)
        if not requests or len(requests) != len(placements):
            raise ValueError("Imaging epoch needs one placement per request")
        by_id = {placement.request_id: placement for placement in placements}
        if {request.id for request in requests} != set(by_id):
            raise ValueError("Imaging placements must match request IDs")
        ordered = tuple(by_id[request.id] for request in requests)
        atoms = tuple(placement.atom for placement in ordered)
        if len(set(atoms)) != len(atoms):
            raise ValueError("Imaging epoch atoms must be unique")
        keys = tuple(str(request.metadata.get("measurement_key", request.id)) for request in requests)
        resources = (ResourceRequirement("device/imaging"), *_atom_resources(atoms))
        return cls(id_, EpochType.IMAGING, tuple(request.id for request in requests), atoms,
                   duration, tuple(dependencies), resources, metadata or {}, ordered, keys)

    def __post_init__(self):
        super().__post_init__()
        object.__setattr__(self, "placements", tuple(self.placements))
        object.__setattr__(self, "measurement_keys", tuple(self.measurement_keys))
        if len(self.placements) != len(self.measurement_keys) or tuple(p.atom for p in self.placements) != self.atoms:
            raise ValueError("Imaging placements and keys must match epoch atoms")

    def to_dict(self):
        return {**super().to_dict(), "placements": [placement.to_dict() for placement in self.placements],
                "measurement_keys": list(self.measurement_keys)}


class LocalPulseEpoch(PhysicalEpoch):
    @classmethod
    def create(cls, id_, request_ids, atoms, *, duration=1.0, dependencies=(), metadata=None):
        atoms = tuple(atoms)
        resources = (ResourceRequirement("device/local_1q"), *_atom_resources(atoms))
        return cls(id_, EpochType.LOCAL_1Q, tuple(request_ids), atoms, duration,
                   tuple(dependencies), resources, metadata or {})


class PreparationEpoch(PhysicalEpoch):
    @classmethod
    def create(cls, id_, request_ids, atoms, *, duration=1.0, dependencies=(), metadata=None):
        atoms = tuple(atoms)
        resources = (ResourceRequirement("device/state_preparation"), *_atom_resources(atoms))
        return cls(id_, EpochType.PREPARE, tuple(request_ids), atoms, duration,
                   tuple(dependencies), resources, metadata or {})


class ResetEpoch(PhysicalEpoch):
    @classmethod
    def create(cls, id_, request_ids, atoms, *, duration=1.0, dependencies=(), metadata=None):
        atoms = tuple(atoms)
        resources = (ResourceRequirement("device/state_preparation"), *_atom_resources(atoms))
        return cls(id_, EpochType.RESET, tuple(request_ids), atoms, duration,
                   tuple(dependencies), resources, metadata or {})
