"""Pure canonical-layer requests; neither geometry planning nor execution.

Preflight is a necessary capability check, never a physical validity proof.
The existing backend/Executor remains responsible for trajectories and timing.
"""
from dataclasses import dataclass
from itertools import combinations
from math import hypot, isfinite
from typing import Mapping

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate


@dataclass(frozen=True)
class CouplingLayer:
    id: str
    cnot_pairs: tuple[tuple[str, str], ...]

    def __post_init__(self):
        pairs = tuple(tuple(p) for p in self.cnot_pairs)
        object.__setattr__(self, 'cnot_pairs', pairs)
        wires = [q for p in pairs for q in p]
        if (not isinstance(self.id, str) or not self.id or not pairs or any(len(p) != 2 for p in pairs)
                or any(not isinstance(q, str) or not q for q in wires)
                or len(set(wires)) != len(wires)):
            raise ValueError('A coupling layer requires disjoint directed CNOT pairs')


@dataclass(frozen=True)
class BackendCapabilities:
    atom_capacity: int
    measurement_zone: bool
    reset: bool
    aod_count: int = 1
    aod_mode: str = 'rigid'
    global_cz: bool = True

    def __post_init__(self):
        if (type(self.atom_capacity) is not int or self.atom_capacity < 1
                or type(self.aod_count) is not int or self.aod_count < 1
                or self.aod_mode not in {'rigid', 'row_column'}
                or any(type(v) is not bool for v in
                       (self.measurement_zone, self.reset, self.global_cz))):
            raise ValueError('Invalid explicit backend capabilities')


@dataclass(frozen=True)
class AncillaLifecycle:
    data_count: int
    checks_per_round: int
    rounds: int
    mode: str = 'reuse'

    def __post_init__(self):
        if (any(type(n) is not int or n < 1 for n in
                (self.data_count, self.checks_per_round, self.rounds))
                or self.mode not in {'reuse', 'fresh'}):
            raise ValueError('Invalid ancilla lifecycle')

    @property
    def minimum_atoms(self):
        return self.data_count + self.checks_per_round * (
            self.rounds if self.mode == 'fresh' else 1)


@dataclass(frozen=True)
class PreflightReport:
    issues: tuple[str, ...]
    minimum_atoms: int
    claim: str = 'capability-only; geometry, timing and fault tolerance unverified'

    @property
    def compatible(self):
        return not self.issues


def preflight(capabilities: BackendCapabilities, lifecycle: AncillaLifecycle):
    issues = []
    if lifecycle.minimum_atoms > capabilities.atom_capacity:
        issues.append('insufficient_atoms')
    if not capabilities.measurement_zone:
        issues.append('measurement_zone_required')
    if lifecycle.mode == 'reuse' and not capabilities.reset:
        issues.append('reuse_requires_reset')
    if not capabilities.global_cz:
        issues.append('global_cz_backend_required')
    return PreflightReport(tuple(issues), lifecycle.minimum_atoms)


@dataclass(frozen=True)
class LayerRequest:
    layer_id: str
    predecessor_layer: str | None
    directed_pairs: tuple[tuple[str, str], ...]
    intended_cz_pairs: tuple[tuple[str, str], ...]
    hadamard_targets: tuple[str, ...]
    claim: str = 'requires placement and actual-pair validation; pulse count unknown'


def layer_requests(layers, bindings: Mapping[str, str]):
    """Bind directed pairs without losing CNOT target basis-change semantics."""
    layers = tuple(layers)
    if len({layer.id for layer in layers}) != len(layers):
        raise ValueError('Layer IDs must be unique')
    roles = {q for layer in layers for p in layer.cnot_pairs for q in p}
    values = tuple(bindings.values())
    if (not roles <= bindings.keys() or len(set(values)) != len(values)
            or any(not isinstance(q, str) or not q for q in values)):
        raise ValueError('Bindings must cover roles with distinct physical IDs')
    requests = []
    for i, layer in enumerate(layers):
        pairs = tuple((bindings[c], bindings[t]) for c, t in layer.cnot_pairs)
        requests.append(LayerRequest(layer.id, layers[i-1].id if i else None,
            pairs, tuple(tuple(sorted(p)) for p in pairs), tuple(t for _, t in pairs)))
    return tuple(requests)


def canonical_layer_requests(canonical_memory, bindings: Mapping[str, str]):
    """Read canonical coupling records structurally, without a module dependency.

    Requests refer to coupling semantics only; use the canonical frontend's
    own native CZ IDs when connecting requests to its complete physical DAG.
    """
    grouped = {}
    for coupling in canonical_memory.couplings:
        key = (coupling.round_index, coupling.layer_index)
        grouped.setdefault(key, []).append((coupling.control_role, coupling.target_role))
    layers = tuple(CouplingLayer(f'round.{r}.layer.{layer}', tuple(pairs))
                   for (r, layer), pairs in sorted(grouped.items()))
    return layer_requests(layers, bindings)


def lower_coupling_layers(layers, bindings: Mapping[str, str]):
    """Emit H(target)-CZ-H(target) DAG with whole-layer barriers.

This is only the coupling segment, not a complete syndrome instrument. Each CZ
is a separate gate request; the backend may split or group it after validation.
"""
    requests = layer_requests(layers, bindings)
    gates, frontier = [], ()
    for i, request in enumerate(requests):
        phases = [('pre', 'H'), ('cz', 'CZ'), ('post', 'H')]
        for phase, kind in phases:
            ids = []
            for j, pair in enumerate(request.directed_pairs):
                gid = f'coupling.{i}.{phase}.{j}'
                gates.append(PhysicalGate(gid, kind,
                    pair if kind == 'CZ' else (pair[1],), depends_on=frontier))
                ids.append(gid)
            frontier = tuple(ids)
    return PhysicalCircuit(tuple(gates))


def validate_global_cz_pairs(eligible_positions, intended_pairs, radius_um):
    """Check ALL eligible live EZ atoms, including spectators.

Caller must obtain eligibility/positions from a real backend snapshot. This
static audit does not check support, motion, resources or pulse duration.
"""
    if not isfinite(radius_um) or radius_um <= 0:
        raise ValueError('Interaction radius must be positive and finite')
    for q, position in eligible_positions.items():
        if not q or len(position) != 2 or not all(isfinite(v) for v in position):
            raise ValueError('Invalid eligible position')
    intended_list = tuple(tuple(p) for p in intended_pairs)
    if any(len(p) != 2 or p[0] == p[1] for p in intended_list):
        raise ValueError('Intended CZ pairs require distinct atoms')
    intended = {tuple(sorted(p)) for p in intended_list}
    if len(intended) != len(intended_list):
        raise ValueError('Duplicate intended pair')
    if any(q not in eligible_positions for p in intended for q in p):
        raise ValueError('Intended atom is not eligible')
    actual = {tuple(sorted((a, b))) for a, b in combinations(eligible_positions, 2)
        if hypot(eligible_positions[a][0]-eligible_positions[b][0],
                 eligible_positions[a][1]-eligible_positions[b][1]) <= radius_um}
    if actual != intended:
        raise ValueError(f'Global CZ mismatch: extra={sorted(actual-intended)}, '
                         f'missing={sorted(intended-actual)}')
    return tuple(sorted(actual))


def validate_aod_rectangle(active_rows, active_columns, captured_by_intersection,
                           requested_atoms, *, rigid_offsets_before=None,
                           rigid_offsets_after=None):
    """Audit captured set over the full active row × column rectangle.

Empty intersections are allowed but still need ordinary sweep validation.
Rigid-offset comparisons forbid hidden row/column deformation.
"""
    rows, columns = tuple(active_rows), tuple(active_columns)
    if (not rows or not columns or len(set(rows)) != len(rows)
            or len(set(columns)) != len(columns)):
        raise ValueError('Active axes must be nonempty and unique')
    rectangle = {(r, c) for r in rows for c in columns}
    if not set(captured_by_intersection) <= rectangle:
        raise ValueError('Captured atom outside active rectangle')
    captured = tuple(captured_by_intersection.values())
    requested = tuple(requested_atoms)
    if (len(set(captured)) != len(captured) or len(set(requested)) != len(requested)
            or set(captured) != set(requested)):
        raise ValueError('Rectangle captures differ from requested atom set')
    if ((rigid_offsets_before is None) != (rigid_offsets_after is None)
            or rigid_offsets_before != rigid_offsets_after):
        raise ValueError('Rigid AOD offsets must remain unchanged')
    return tuple(sorted(captured))
