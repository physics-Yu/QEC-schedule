"""Exact unitary Clifford+T normalization, independent of QEC and hardware.

Chronological input gates become chronological signed Pauli rotations followed
by a residual Clifford. This is not stabilizer-register elimination (BSS PBC).
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from .pauli import PauliProduct

_ARITY = {**dict.fromkeys(('H', 'S', 'Sdg', 'X', 'Y', 'Z', 'T', 'Tdg'), 1), 'CX': 2, 'CZ': 2}


@dataclass(frozen=True, slots=True)
class LogicalGate:
    name: str
    wires: tuple[str, ...]

    def __post_init__(self):
        if self.name not in _ARITY:
            raise ValueError(f'Unsupported unitary gate {self.name!r}; measurement/reset/conditions require an instrument compiler')
        object.__setattr__(self, 'wires', tuple(self.wires))
        if len(self.wires) != _ARITY[self.name] or len(set(self.wires)) != len(self.wires):
            raise ValueError('Gate arity or duplicate wires')
        if any(not isinstance(w, str) or not w.strip() for w in self.wires):
            raise ValueError('Logical wires must be nonempty names')


@dataclass(frozen=True, slots=True)
class PauliRotation:
    observable: PauliProduct
    quarter_turns: int
    source_index: int

    def __post_init__(self):
        if not isinstance(self.observable, PauliProduct):
            raise TypeError('Rotation requires a PauliProduct')
        if type(self.quarter_turns) is not int or type(self.source_index) is not int or self.source_index < 0:
            raise ValueError('Rotation angle and source index must be integers')


@dataclass(frozen=True, slots=True)
class LogicalPauliProgram:
    wires: tuple[str, ...]
    rotations: tuple[PauliRotation, ...]
    residual_clifford: tuple[LogicalGate, ...]
    global_phase_eighth_turns: int

    def to_dict(self):
        return {'schema': 'logical-pauli-unitary-v1', 'wires': list(self.wires),
                'semantic_scope': 'exact unitary Pauli rotations; not a PBC measurement circuit',
                'implementation_status': {'unitary_normalization': True,
                    'adaptive_pbc_measurements': False, 'magic_injection_lowering': False,
                    'surface_code_physical_lowering': False},
                'rotation_convention': 'exp(-i*pi*quarter_turns*P/8)',
                'global_phase_convention': 'exp(i*pi*global_phase_eighth_turns/8)',
                'global_phase_eighth_turns': self.global_phase_eighth_turns,
                'rotations': [{'observable': r.observable.to_dict(), 'quarter_turns': r.quarter_turns,
                               'source_index': r.source_index} for r in self.rotations],
                'residual_clifford': [{'name': g.name, 'wires': list(g.wires)} for g in self.residual_clifford]}


def conjugate_pauli(observable: PauliProduct, gate: LogicalGate, *, inverse: bool = False) -> PauliProduct:
    """Return G P G† (or G† P G), including exact Hermitian signs."""
    if gate.name in ('T', 'Tdg'):
        raise ValueError('Non-Clifford conjugation cannot remain a Pauli product')
    name = {'S': 'Sdg', 'Sdg': 'S'}.get(gate.name, gate.name) if inverse else gate.name
    image = PauliProduct(())
    phase = complex(observable.sign)
    for wire, basis in observable.factors:
        factors = [(wire, basis)]
        sign = 1
        if wire in gate.wires:
            if name == 'H':
                basis, sign = {'X': ('Z', 1), 'Y': ('Y', -1), 'Z': ('X', 1)}[basis]
                factors = [(wire, basis)]
            elif name in ('S', 'Sdg'):
                basis, sign = ({'X': ('Y', 1), 'Y': ('X', -1), 'Z': ('Z', 1)} if name == 'S'
                               else {'X': ('Y', -1), 'Y': ('X', 1), 'Z': ('Z', 1)})[basis]
                factors = [(wire, basis)]
            elif name in ('X', 'Y', 'Z'):
                sign = 1 if name == basis else -1
            elif name == 'CX':
                control, target = gate.wires
                if wire == control and basis in ('X', 'Y'):
                    factors.append((target, 'X'))
                elif wire == target and basis in ('Z', 'Y'):
                    factors.append((control, 'Z'))
            elif name == 'CZ' and basis in ('X', 'Y'):
                factors.append((gate.wires[1] if wire == gate.wires[0] else gate.wires[0], 'Z'))
        local_phase, image = image.multiply(PauliProduct(tuple(factors), sign))
        phase *= local_phase
    if phase not in (1, -1):
        raise AssertionError('Clifford conjugation produced a non-Hermitian product')
    return PauliProduct(image.factors, int(phase.real))


def compile_logical_pauli(gates: Iterable[LogicalGate], *, wires: Iterable[str] | None = None) -> LogicalPauliProgram:
    """Normalize an arbitrary-input unitary; preserve gate order and global phase.

    U = exp(i*pi*phase/8) C R_last ... R_first. The residual C is
    represented in chronological gate order and is applied after rotations.
    """
    gates = tuple(gates)
    if any(not isinstance(g, LogicalGate) for g in gates):
        raise TypeError('Input must contain LogicalGate values; instrument boundaries are not supported')
    inferred = tuple(dict.fromkeys(w for g in gates for w in g.wires))
    wires = inferred if wires is None else tuple(wires)
    if any(not isinstance(w, str) or not w.strip() for w in wires) or len(set(wires)) != len(wires):
        raise ValueError('Wire order must contain unique nonempty names')
    if not set(inferred).issubset(wires):
        raise ValueError('Gate refers to an undeclared wire')
    clifford = []
    rotations = []
    phase = 0
    # Images of 2n generators under C† P C. Updating G C only changes images
    # on G's wires, avoiding a traversal of the accumulated Clifford history.
    images = {(w, b): PauliProduct(((w, b),)) for w in wires for b in ('X', 'Z')}

    def substitute(observable, snapshot):
        result = PauliProduct(())
        scalar = complex(observable.sign)
        for wire, basis in observable.factors:
            if basis == 'Y':
                local_phase, local = snapshot[wire, 'X'].multiply(snapshot[wire, 'Z'])
                scalar *= 1j * local_phase  # Y = i X Z
            else:
                local = snapshot[wire, basis]
            local_phase, result = result.multiply(local)
            scalar *= local_phase
        if scalar not in (1, -1):
            raise AssertionError('Inverse Clifford frame produced a non-Hermitian image')
        return PauliProduct(result.factors, int(scalar.real))

    for index, gate in enumerate(gates):
        if gate.name not in ('T', 'Tdg'):
            updates = {}
            for wire in gate.wires:
                for basis in ('X', 'Z'):
                    local = conjugate_pauli(PauliProduct(((wire, basis),)), gate, inverse=True)
                    updates[wire, basis] = substitute(local, images)
            images.update(updates)
            clifford.append(gate)
            continue
        observable = images[gate.wires[0], 'Z']
        turns = 1 if gate.name == 'T' else -1
        rotations.append(PauliRotation(observable, turns, index))
        phase += turns
    return LogicalPauliProgram(wires, tuple(rotations), tuple(clifford), phase % 16)
