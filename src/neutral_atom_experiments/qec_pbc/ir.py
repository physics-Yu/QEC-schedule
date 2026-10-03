"""Role-based QEC/PBC measurement IR; independent of placement and timing.

This is a protocol IR, not the ideal Clifford-elimination algorithm of standard
PBC. Classical XORs stay explicit and are never disguised as native conditions.
"""
from dataclasses import dataclass
from typing import Mapping

from .pauli import PauliProduct


@dataclass(frozen=True)
class Role:
    id: str
    kind: str
    patch: str | None = None
    local: int | None = None

    def __post_init__(self):
        if (not isinstance(self.id, str) or not self.id.strip() or
                self.kind not in {'data', 'syndrome_ancilla', 'parity_ancilla'} or
                self.patch is not None and (not isinstance(self.patch, str) or not self.patch) or
                self.local is not None and (type(self.local) is not int or self.local < 0)):
            raise ValueError('Invalid qubit role')


@dataclass(frozen=True)
class BitExpr:
    """XOR of semantic measurement bits; bit 0 denotes eigenvalue +1."""
    terms: tuple[str, ...]
    constant: int = 0

    def __post_init__(self):
        object.__setattr__(self, 'terms', tuple(self.terms))
        if type(self.constant) is not int or self.constant not in (0, 1):
            raise ValueError('XOR constant must be a bit')
        if (any(not isinstance(t, str) or not t for t in self.terms) or
                len(set(self.terms)) != len(self.terms)):
            raise ValueError('XOR terms must be distinct measurement IDs')

    def evaluate(self, measurements: Mapping[str, int]):
        value = self.constant
        for key in self.terms:
            bit = measurements[key]
            if type(bit) is not int or bit not in (0, 1):
                raise ValueError('Measurement results must be integer bits')
            value ^= bit
        return value

    def to_dict(self):
        return {'terms': list(self.terms), 'constant': self.constant}


@dataclass(frozen=True)
class GateTask:
    id: str
    gate_type: str
    targets: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    condition: tuple[tuple[str, int], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'targets', tuple(self.targets))
        object.__setattr__(self, 'depends_on', tuple(self.depends_on))
        object.__setattr__(self, 'condition', tuple(tuple(c) for c in self.condition))
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('Operation ID must be a nonempty string')
        if self.gate_type not in {'H', 'X', 'Z', 'CZ', 'RESET', 'MEASURE'}:
            raise ValueError('Unsupported protocol primitive')
        if len(self.targets) != (2 if self.gate_type == 'CZ' else 1):
            raise ValueError('Invalid primitive arity')
        if self.condition and (self.gate_type not in {'X', 'Z'} or
                any(len(c) != 2 or not isinstance(c[0], str) or not c[0] or
                    type(c[1]) is not int or c[1] not in (0, 1) for c in self.condition) or
                len({c[0] for c in self.condition}) != len(self.condition)):
            raise ValueError('Only X/Z support AND-of-measurement-bit conditions')


@dataclass(frozen=True)
class PauliMeasurement:
    id: str
    product: PauliProduct
    ancilla: str
    coupling_order: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    purpose: str = 'syndrome'
    patch: str | None = None
    round_index: int | None = None
    protocol: str = 'bare_ancilla_ideal'

    def __post_init__(self):
        object.__setattr__(self, 'coupling_order', tuple(self.coupling_order))
        object.__setattr__(self, 'depends_on', tuple(self.depends_on))
        if not isinstance(self.id, str) or not self.id or not isinstance(self.product, PauliProduct):
            raise ValueError('Measurement requires an ID and PauliProduct')
        if not self.product.support or self.ancilla in self.product.support:
            raise ValueError('Measurement needs nonempty data support and a separate ancilla')
        if (len(self.coupling_order) != len(self.product.support) or
                set(self.coupling_order) != set(self.product.support)):
            raise ValueError('Coupling order must cover each factor exactly once')
        if self.purpose not in {'syndrome', 'logical_ppm', 'factory_check'}:
            raise ValueError('Unknown Pauli measurement purpose')
        if self.protocol != 'bare_ancilla_ideal':
            raise ValueError('Measurement protocol is not implemented')


@dataclass(frozen=True)
class Detector:
    id: str
    expression: BitExpr
    boundary: str


@dataclass(frozen=True)
class Observable:
    id: str
    expression: BitExpr
    interpretation: str


@dataclass(frozen=True)
class MemoryContract:
    patch: str
    basis: str
    closing_round: int
    observable_id: str
    decoder: str = 'perfect_readout_single_data_pauli'

    def __post_init__(self):
        if (not isinstance(self.patch, str) or not self.patch or self.basis not in ('X', 'Z') or
                type(self.closing_round) is not int or self.closing_round < 1 or
                not isinstance(self.observable_id, str) or not self.observable_id or
                self.decoder not in {'perfect_readout_single_data_pauli', 'canonical_detector_memory'}):
            raise ValueError('Invalid ideal memory decoding contract')


@dataclass(frozen=True)
class PBCProgram:
    roles: tuple[Role, ...]
    operations: tuple[GateTask | PauliMeasurement, ...]
    detectors: tuple[Detector, ...] = ()
    observables: tuple[Observable, ...] = ()
    name: str = 'qec-pbc'
    memory_contract: MemoryContract | None = None

    def __post_init__(self):
        for field in ('roles', 'operations', 'detectors', 'observables'):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        role_map = {role.id: role for role in self.roles}
        if len(role_map) != len(self.roles):
            raise ValueError('Duplicate role ID')
        seen, measured = set(), set()
        for op in self.operations:
            if not isinstance(op, (GateTask, PauliMeasurement)):
                raise ValueError('Unknown protocol operation')
            if not op.id or op.id in seen or not set(op.depends_on) <= seen:
                raise ValueError('Duplicate operation ID or non-earlier dependency')
            if len(set(op.depends_on)) != len(op.depends_on):
                raise ValueError('Duplicate operation dependency')
            targets = op.targets if isinstance(op, GateTask) else (*op.product.support, op.ancilla)
            if not set(targets) <= role_map.keys() or len(set(targets)) != len(targets):
                raise ValueError('Unknown or duplicate target role')
            if isinstance(op, GateTask):
                if not {c[0] for c in op.condition} <= measured:
                    raise ValueError('Condition must refer to earlier semantic measurements')
                if op.gate_type == 'MEASURE':
                    measured.add(op.id)
            else:
                if role_map[op.ancilla].kind == 'data':
                    raise ValueError('Parity ancilla cannot be a data role')
                measured.add(op.id)
            seen.add(op.id)
        for specs in (self.detectors, self.observables):
            if len({s.id for s in specs}) != len(specs):
                raise ValueError('Duplicate classical output ID')
            if any(not set(s.expression.terms) <= measured for s in specs):
                raise ValueError('Classical expression refers to an unknown measurement')
        if self.memory_contract is not None and self.memory_contract.observable_id not in {
                o.id for o in self.observables}:
            raise ValueError('Memory contract must refer to a declared observable')

    def to_dict(self):
        from dataclasses import asdict
        return {'schema': 'qec-pbc-protocol/1', 'name': self.name,
                'roles': [asdict(r) for r in self.roles],
                'operations': [dict(asdict(op), kind='pauli_measurement' if
                    isinstance(op, PauliMeasurement) else 'gate_task') for op in self.operations],
                'detectors': [asdict(d) for d in self.detectors],
                'observables': [asdict(o) for o in self.observables],
                'memory_contract': None if self.memory_contract is None else asdict(self.memory_contract)}
