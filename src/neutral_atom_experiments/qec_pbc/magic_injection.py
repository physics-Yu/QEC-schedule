"""Logical T/Tdg injection instrument contracts; no physical/QEC lowering."""
from __future__ import annotations

from dataclasses import dataclass
from .logical_pauli import LogicalGate


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    wire: str
    state: str
    provenance: str
    quality: str = 'unknown'
    consumed: bool = True

    def __post_init__(self):
        if self.state not in ('T', 'Tdg') or not isinstance(self.wire, str) or not self.wire.strip():
            raise ValueError('Resource requires a named wire and T/Tdg state')
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError('Resource provenance must be explicit')
        if self.quality not in ('unknown', 'ideal_reference') or self.consumed is not True:
            raise ValueError('Injection consumes its resource; quality is unknown or ideal_reference')


@dataclass(frozen=True, slots=True)
class InjectionBranch:
    outcome: int
    correction: tuple[LogicalGate, ...]


@dataclass(frozen=True, slots=True)
class MagicInjection:
    gate: str
    data_wire: str
    resource: ResourceRequest
    entangling_gates: tuple[LogicalGate, ...]
    measurement_id: str
    branches: tuple[InjectionBranch, ...]

    def to_dict(self):
        return {
            'schema': 'logical-magic-injection-v1',
            'implementation_status': {'logical_contract': True,
                'encoded_resource_preparation': False, 'surface_code_protocol': False,
                'physical_circuit': False, 'executor_run': False},
            'gate': self.gate, 'data_wire': self.data_wire,
            'resource': {'wire': self.resource.wire, 'state': self.resource.state,
                         'provenance': self.resource.provenance, 'quality': self.resource.quality,
                         'consumed': self.resource.consumed},
            'entangling_gates': [{'name': g.name, 'wires': list(g.wires)} for g in self.entangling_gates],
            'measurement': {'id': self.measurement_id, 'wire': self.resource.wire, 'basis': 'Z',
                            'destructive': True},
            'branches': [{'outcome': b.outcome,
                          'correction': [{'name': g.name, 'wires': list(g.wires)} for g in b.correction],
                          'depends_on_measurement': self.measurement_id if b.correction else None}
                         for b in self.branches],
            'semantic_scope': 'logical instrument; exact identity assumes ideal reference resource',
            'fault_tolerant': False,
        }


def make_magic_injection(gate: str, data_wire: str, resource_wire: str, *,
                         measurement_id: str, provenance: str,
                         quality: str = 'unknown') -> MagicInjection:
    """Construct a logical injection with explicit branch-dependent correction.

    Ideal |T_s> = (|0> + exp(s*i*pi/4)|1>)/sqrt(2), s=+1/-1.
    Data controls a CX onto the resource, followed by resource Z readout.
    Outcome one requires S/Sdg respectively. The measured resource is consumed.
    """
    if gate not in ('T', 'Tdg'):
        raise ValueError('Injection supports T or Tdg')
    if not isinstance(measurement_id, str) or not measurement_id.strip():
        raise ValueError('Injection requires a nonempty measurement ID')
    resource = ResourceRequest(resource_wire, gate, provenance, quality)
    entangler = LogicalGate('CX', (data_wire, resource_wire))
    correction = LogicalGate('S' if gate == 'T' else 'Sdg', (data_wire,))
    return MagicInjection(gate, data_wire, resource, (entangler,), measurement_id,
                          (InjectionBranch(0, ()), InjectionBranch(1, (correction,))))
