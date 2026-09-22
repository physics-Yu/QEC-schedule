"""Immutable placement contracts. A mapping proposal is NOT an executable plan."""
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.operations import HardwareConfig


@dataclass(frozen=True)
class Site:
    id: str
    x_um: float
    y_um: float

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('Site requires a nonempty string ID')
        if any(type(v) not in (int, float) or not isfinite(v) for v in (self.x_um, self.y_um)):
            raise ValueError('Site coordinates must be finite')


@dataclass(frozen=True)
class PlacementProblem:
    circuit: PhysicalCircuit
    qubits: tuple[str, ...]
    storage: tuple[Site, ...]
    interaction_sites: tuple[Site, ...]
    initial_mapping: tuple[tuple[str, str], ...]
    locked: tuple[tuple[str, str], ...] = ()
    aod_rows: int = 16
    aod_columns: int = 16
    hardware: HardwareConfig = HardwareConfig(backend='row_column_orthogonal')

    def __post_init__(self):
        for name in ('qubits', 'storage', 'interaction_sites', 'initial_mapping', 'locked'):
            value = tuple(getattr(self, name))
            if name in {'initial_mapping', 'locked'}:
                value = tuple(tuple(pair) for pair in value)
            object.__setattr__(self, name, value)
        if not self.qubits or any(not isinstance(q, str) or not q for q in self.qubits):
            raise ValueError('Explicit nonempty qubit IDs required, including idle atoms')
        if len(set(self.qubits)) != len(self.qubits):
            raise ValueError('Duplicate qubit ID')
        for sites in (self.storage, self.interaction_sites):
            if len({s.id for s in sites}) != len(sites) or len({(s.x_um, s.y_um) for s in sites}) != len(sites):
                raise ValueError('Duplicate site ID or coordinates')
        if len(self.storage) < len(self.qubits):
            raise ValueError('Insufficient storage sites')
        if any(type(v) is not int or v < 1 for v in (self.aod_rows, self.aod_columns)):
            raise ValueError('AOD axis capacities must be positive integers')
        if any(q not in self.qubits for g in self.circuit.gates for q in g.qubit_ids):
            raise ValueError('Circuit references an unknown qubit')
        if any(g.gate_type not in {'H', 'X', 'Y', 'Z', 'T', 'CZ', 'MEASURE', 'RESET'} for g in self.circuit.gates):
            raise ValueError('Placement supports H/X/Y/Z/T/CZ/MEASURE/RESET circuits')
        if any(g.is_two_qubit for g in self.circuit.gates) and not self.interaction_sites:
            raise ValueError('CZ placement needs interaction site reference coordinates')
        if len(dict(self.locked)) != len(self.locked):
            raise ValueError('Duplicate locked qubit')
        self.validate_mapping(self.initial_mapping)

    def validate_mapping(self, mapping):
        pairs = tuple(mapping.items()) if isinstance(mapping, dict) else tuple(mapping)
        result = dict(pairs)
        if len(result) != len(pairs) or set(result) != set(self.qubits):
            raise ValueError('Mapping must contain every qubit exactly once')
        if len(set(result.values())) != len(result) or not set(result.values()) <= {s.id for s in self.storage}:
            raise ValueError('Mapping must be injective into storage sites')
        if any(q not in result or result[q] != s for q, s in self.locked):
            raise ValueError('Mapping violates locked positions')
        return tuple((q, result[q]) for q in self.qubits)


@dataclass(frozen=True)
class SearchConfig:
    iterations: int = 1000
    seed: int = 7
    top_k: int = 3
    lookahead_layers: int = 8
    decay: float = .8
    objective: str = 'parking_aware'
    exact_limit: int = 0

    def __post_init__(self):
        for name in ('iterations', 'seed', 'top_k', 'lookahead_layers', 'exact_limit'):
            if type(getattr(self, name)) is not int:
                raise ValueError(f'{name} must be an integer')
        if not 0 <= self.iterations <= 100000 or not 1 <= self.top_k <= 32 or not 1 <= self.lookahead_layers <= 64:
            raise ValueError('Search budget out of bounds')
        if not 0 <= self.exact_limit <= 100000:
            raise ValueError('Exact search limit must be in 0..100000')
        if type(self.decay) not in (int, float) or not isfinite(self.decay) or not 0 < self.decay <= 1:
            raise ValueError('Decay must be in (0,1]')
        if self.objective not in {'distance', 'parking_aware'}:
            raise ValueError('Unknown placement objective')


@dataclass(frozen=True)
class CostEstimate:
    score_us: float
    transport_proxy_us: float
    capture_proxy_us: float
    layer_details: tuple[dict, ...]
    scope: str = 'static-initial-map proxy; not physical time or a lower bound'


@dataclass(frozen=True)
class PlacementCandidate:
    mapping: tuple[tuple[str, str], ...]
    cost: CostEstimate
    origin: str


@dataclass(frozen=True)
class PlacementResult:
    selected: PlacementCandidate
    baseline: PlacementCandidate
    candidates: tuple[PlacementCandidate, ...]
    diagnostics: dict
    status: str = 'estimated'


@dataclass(frozen=True)
class LandingProposal:
    destinations: tuple[tuple[str, str], ...]
    reason: str
    status: str = 'proposed_not_executed'

    def __post_init__(self):
        pairs = tuple(tuple(p) for p in self.destinations)
        object.__setattr__(self, 'destinations', pairs)
        if len(dict(pairs)) != len(pairs) or len({s for _, s in pairs}) != len(pairs):
            raise ValueError('Landing destinations must be injective')


@dataclass(frozen=True)
class PhysicalEvaluation:
    """Returned only by an external runner after full execution and replay."""
    valid: bool
    total_time_us: float | None = None
    failure: str | None = None
    evidence: str | None = None

    def __post_init__(self):
        if type(self.valid) is not bool:
            raise ValueError('valid must be boolean')
        if self.valid and (type(self.total_time_us) not in (int, float) or not isfinite(self.total_time_us) or self.total_time_us < 0):
            raise ValueError('Valid execution requires finite nonnegative duration')
        if not self.valid and not self.failure:
            raise ValueError('Failed evaluation requires a reason')


class InitialPlacementPolicy(Protocol):
    def __call__(self, problem: PlacementProblem, config: SearchConfig) -> PlacementResult: ...
