"""Exact arithmetic-to-logical adapter; no QFT, noise or hardware scheduling.

The published N=21 prefix is imported from a caller-provided pinned source.
The generic increment-ladder remains a correctness fixture, not a cost baseline.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from .logical_pauli import LogicalGate, compile_logical_pauli

GIDNEY_SOURCE = 'https://algassert.com/assets/2025-08-30-why-no-factor-21/factor21.qasm'
GIDNEY_SHA256 = '1349167dc4e60e4df6f4687b1e4e09550dfc2ba140076400e05a847f69739068'
_ARITIES = {'X': 1, 'H': 1, 'CX': 2, 'CCX': 3}


@dataclass(frozen=True)
class ArithmeticProgram:
    wires: tuple[str, ...]
    gates: tuple[tuple[str, tuple[int, ...]], ...]
    source: str
    source_sha256: str | None = None

    def __post_init__(self):
        object.__setattr__(self, 'wires', tuple(self.wires))
        object.__setattr__(self, 'gates', tuple((kind, tuple(qs)) for kind, qs in self.gates))
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError('Arithmetic source provenance is required')
        if not self.wires or len(set(self.wires)) != len(self.wires):
            raise ValueError('Unique logical wire names are required')
        if any(not isinstance(w, str) or not w.strip() for w in self.wires):
            raise ValueError('Logical wires must be nonempty strings')
        for kind, qs in self.gates:
            if kind not in _ARITIES or len(qs) != _ARITIES[kind]:
                raise ValueError('Unsupported arithmetic operation or arity')
            if len(set(qs)) != len(qs) or any(type(q) is not int or not 0 <= q < len(self.wires) for q in qs):
                raise ValueError('Aliased or out-of-range arithmetic operand')


def expand_clifford_t(program: ArithmeticProgram) -> tuple[LogicalGate, ...]:
    """Exact 7-T Toffoli (four T and three Tdg); preserves CCX provenance separately."""
    result = []
    for kind, qs in program.gates:
        if kind != 'CCX':
            result.append(LogicalGate(kind, tuple(program.wires[q] for q in qs)))
            continue
        a, b, t = (program.wires[q] for q in qs)
        recipe = (('H', (t,)), ('CX', (b, t)), ('Tdg', (t,)),
                  ('CX', (a, t)), ('T', (t,)), ('CX', (b, t)),
                  ('Tdg', (t,)), ('CX', (a, t)), ('T', (b,)),
                  ('T', (t,)), ('H', (t,)), ('CX', (a, b)),
                  ('T', (a,)), ('Tdg', (b,)), ('CX', (a, b)))
        result.extend(LogicalGate(name, wires) for name, wires in recipe)
    return tuple(result)


def compile_arithmetic(program: ArithmeticProgram):
    return compile_logical_pauli(expand_clifford_t(program), wires=program.wires)


def resource_report(program: ArithmeticProgram) -> dict:
    gates = expand_clifford_t(program)
    counts = Counter(g.name for g in gates)
    return dict(source=program.source, source_sha256=program.source_sha256,
                logical_qubits=len(program.wires), arithmetic_counts=dict(Counter(k for k, _ in program.gates)),
                clifford_t_counts=dict(counts), t_resource_consumptions=counts['T'] + counts['Tdg'],
                magic_buffer_peak=None, physical_atom_peak=None, qft_included=False,
                measurements_included=False, complete_shor=False,
                note='T consumption is not simultaneous patch allocation; no factory or physical cost assigned.')


def import_gidney_modexp(path: str | Path) -> ArithmeticProgram:
    """Import the previously audited preparation/modexp prefix, excluding Fourier readout."""
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != GIDNEY_SHA256:
        raise ValueError('Source fingerprint mismatch; audit changed QASM before import')
    text = raw.decode('utf-8')
    registers = re.findall(r'^qreg (\w+)\[1\];', text, re.M)
    expected = [f'val{i}' for i in range(5)] + [f'exp{i}' for i in range(10)]
    if registers != expected:
        raise ValueError('Unexpected pinned register layout')
    indices = {name: i for i, name in enumerate(registers)}
    gates = []
    for line in text.splitlines():
        if line.startswith('measure '):
            break
        match = re.fullmatch(r'(x|h|cx|ccx) ([^;]+);', line)
        if match:
            gates.append((match[1].upper(), tuple(indices[q.strip()] for q in match[2].split(','))))
    if not gates or gates[-1] != ('H', (14,)) or sum(k == 'H' for k, _ in gates) != 11:
        raise ValueError('Preparation/Fourier-readout boundary changed')
    gates.pop()
    return ArithmeticProgram(tuple(registers), tuple(gates), GIDNEY_SOURCE, GIDNEY_SHA256)
