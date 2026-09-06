"""Immutable gate records. Graph execution / ready-set API belongs to step 3."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType


class GateType(str, Enum):
    PREPARE = "PREPARE"
    RESET = "RESET"
    H = "H"
    X = "X"
    Y = "Y"
    Z = "Z"
    CZ = "CZ"
    CNOT = "CNOT"
    MEASURE_X = "MEASURE_X"
    MEASURE_Z = "MEASURE_Z"


@dataclass(frozen=True)
class PhysicalGate:
    id: str
    gate_type: GateType
    qubits: tuple[str, ...]
    predecessors: tuple[str, ...] = ()
    metadata: Mapping[str, str | int] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "gate_type", GateType(self.gate_type))
        object.__setattr__(self, "qubits", tuple(self.qubits))
        object.__setattr__(self, "predecessors", tuple(self.predecessors))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        arity = 2 if self.gate_type in (GateType.CZ, GateType.CNOT) else 1
        if not self.id or len(self.qubits) != arity or len(set(self.qubits)) != arity or any(not q for q in self.qubits):
            raise ValueError("Gate requires ID and distinct qubits of the correct arity")
        if self.id in self.predecessors or len(set(self.predecessors)) != len(self.predecessors):
            raise ValueError("Invalid gate predecessors")
        if any(type(v) not in (str, int) for v in self.metadata.values()):
            raise ValueError("Metadata values must be strings or integers")

    def to_dict(self):
        return {"id": self.id, "gate_type": self.gate_type.value, "qubits": list(self.qubits),
                "predecessors": list(self.predecessors), "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class PhysicalCircuit:
    qubits: tuple[str, ...]
    gates: tuple[PhysicalGate, ...]

    def __post_init__(self):
        object.__setattr__(self, "qubits", tuple(self.qubits))
        object.__setattr__(self, "gates", tuple(self.gates))
        if len(set(self.qubits)) != len(self.qubits) or any(not q for q in self.qubits):
            raise ValueError("Circuit qubits must be unique and nonempty")
        seen = set()
        for gate in self.gates:
            if gate.id in seen or not set(gate.qubits) <= set(self.qubits):
                raise ValueError("Duplicate gate ID or unknown qubit")
            if not set(gate.predecessors) <= seen:
                raise ValueError("Gate predecessors must refer to earlier records")
            seen.add(gate.id)

    def to_dict(self):
        return {"schema_version": 1, "qubits": list(self.qubits),
                "gates": [g.to_dict() for g in self.gates]}
