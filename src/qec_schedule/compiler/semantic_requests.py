"""Semantic hardware requests emitted from the physical-gate DAG.

This layer deliberately contains no hardware coordinates, trap sites, AOD
actions, or runtime state. Placement and transport are execution-time
decisions made by the hardware planner.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .dag import PhysicalCircuitDAG
from .physical_gate_ir import GateType, PhysicalCircuit


Metadata = Mapping[str, str | int]


def _common(id_, gate_id, dependencies, metadata):
    if not isinstance(id_, str) or not id_ or not isinstance(gate_id, str) or not gate_id:
        raise ValueError("Semantic request requires nonempty IDs")
    dependencies = tuple(dependencies)
    if len(set(dependencies)) != len(dependencies) or id_ in dependencies:
        raise ValueError("Invalid semantic request dependencies")
    if not isinstance(metadata, Mapping) or any(not isinstance(k, str) or type(v) not in (str, int)
                                                for k, v in metadata.items()):
        raise ValueError("Semantic request metadata needs string keys and string/integer values")
    return dependencies, MappingProxyType(dict(metadata))


def _one_atom(atoms):
    atoms = tuple(atoms)
    if len(atoms) != 1 or not isinstance(atoms[0], str) or not atoms[0].strip():
        raise ValueError("Semantic request requires one nonempty atom ID")
    return atoms


def _two_atoms(atoms):
    atoms = tuple(atoms)
    if len(atoms) != 2 or len(set(atoms)) != 2 or any(not isinstance(a, str) or not a.strip() for a in atoms):
        raise ValueError("Entangle request requires two distinct nonempty atom IDs")
    return atoms


@dataclass(frozen=True)
class EntangleRequest:
    id: str
    gate_id: str
    atoms: tuple[str, str]
    dependencies: tuple[str, ...]
    interaction_type: str = "CZ"
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "atoms", _two_atoms(self.atoms))
        deps, metadata = _common(self.id, self.gate_id, self.dependencies, self.metadata)
        object.__setattr__(self, "dependencies", deps)
        object.__setattr__(self, "metadata", metadata)
        if self.interaction_type not in ("CZ", "CNOT"):
            raise ValueError("Unsupported entangling interaction type")

    def to_dict(self):
        return {"id": self.id, "gate_id": self.gate_id, "type": "ENTANGLE",
                "atoms": list(self.atoms), "dependencies": list(self.dependencies),
                "interaction_type": self.interaction_type, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class MeasureRequest:
    id: str
    gate_id: str
    atom: str
    basis: str
    dependencies: tuple[str, ...]
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self):
        _one_atom((self.atom,))
        deps, metadata = _common(self.id, self.gate_id, self.dependencies, self.metadata)
        object.__setattr__(self, "dependencies", deps)
        object.__setattr__(self, "metadata", metadata)
        if self.basis not in ("X", "Y", "Z"):
            raise ValueError("Measurement basis must be X, Y, or Z")

    def to_dict(self):
        return {"id": self.id, "gate_id": self.gate_id, "type": "MEASURE",
                "atom": self.atom, "basis": self.basis,
                "dependencies": list(self.dependencies), "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class SingleQubitRequest:
    id: str
    gate_id: str
    atom: str
    operation: str
    dependencies: tuple[str, ...]
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self):
        _one_atom((self.atom,))
        deps, metadata = _common(self.id, self.gate_id, self.dependencies, self.metadata)
        object.__setattr__(self, "dependencies", deps)
        object.__setattr__(self, "metadata", metadata)
        if self.operation not in ("H", "X", "Y", "Z"):
            raise ValueError("Unsupported single-qubit operation")

    def to_dict(self):
        return {"id": self.id, "gate_id": self.gate_id, "type": "SINGLE_QUBIT",
                "atom": self.atom, "operation": self.operation,
                "dependencies": list(self.dependencies), "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class PrepareRequest:
    id: str
    gate_id: str
    atom: str
    dependencies: tuple[str, ...]
    state: str = "0"
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self):
        _one_atom((self.atom,))
        deps, metadata = _common(self.id, self.gate_id, self.dependencies, self.metadata)
        object.__setattr__(self, "dependencies", deps)
        object.__setattr__(self, "metadata", metadata)
        if self.state != "0":
            raise ValueError("Only |0> preparation is supported")

    def to_dict(self):
        return {"id": self.id, "gate_id": self.gate_id, "type": "PREPARE",
                "atom": self.atom, "state": self.state,
                "dependencies": list(self.dependencies), "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class ResetRequest:
    id: str
    gate_id: str
    atom: str
    dependencies: tuple[str, ...]
    state: str = "0"
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self):
        _one_atom((self.atom,))
        deps, metadata = _common(self.id, self.gate_id, self.dependencies, self.metadata)
        object.__setattr__(self, "dependencies", deps)
        object.__setattr__(self, "metadata", metadata)
        if self.state != "0":
            raise ValueError("Only |0> reset is supported")

    def to_dict(self):
        return {"id": self.id, "gate_id": self.gate_id, "type": "RESET",
                "atom": self.atom, "state": self.state,
                "dependencies": list(self.dependencies), "metadata": dict(self.metadata)}


SemanticRequest = (EntangleRequest | MeasureRequest | SingleQubitRequest |
                   PrepareRequest | ResetRequest)


@dataclass(frozen=True)
class SemanticRequestPlan:
    """Immutable request program preserving the physical DAG dependencies."""

    requests: tuple[SemanticRequest, ...]
    gate_completion: Mapping[str, tuple[str, ...]]

    def __post_init__(self):
        object.__setattr__(self, "requests", tuple(self.requests))
        object.__setattr__(self, "gate_completion",
                           MappingProxyType({k: tuple(v) for k, v in self.gate_completion.items()}))
        seen = set()
        for request in self.requests:
            if request.id in seen or not set(request.dependencies) <= seen:
                raise ValueError("Request IDs must be unique and dependencies must refer to earlier requests")
            seen.add(request.id)
        if set(self.gate_completion) != {r.gate_id for r in self.requests}:
            raise ValueError("Gate completion must cover every semantic request gate")
        for gate_id, terminals in self.gate_completion.items():
            if tuple(terminals) != (gate_id,) or gate_id not in seen:
                raise ValueError("Each semantic gate must map to its request ID")

    @property
    def requests_by_id(self):
        return MappingProxyType({request.id: request for request in self.requests})

    def ready_requests(self, completed: set[str] | frozenset[str] = frozenset()):
        completed = set(completed)
        if not completed <= self.requests_by_id.keys():
            raise ValueError("Unknown completed semantic request")
        return tuple(request for request in self.requests
                     if request.id not in completed and set(request.dependencies) <= completed)

    def to_dict(self):
        return {"schema_version": 1, "kind": "semantic_hardware_requests", "scheduled": False,
                "requests": [request.to_dict() for request in self.requests],
                "gate_completion": {k: list(v) for k, v in self.gate_completion.items()}}


class SemanticGateLowerer:
    """Pure physical-gate to semantic-request lowering.

    ``state`` is accepted only to translate qubit IDs to atom IDs. It is read
    and validated, never mutated, and no location or destination is selected.
    """

    def lower(self, circuit: PhysicalCircuit, state=None) -> SemanticRequestPlan:
        dag = PhysicalCircuitDAG(circuit)
        qubit_to_atom = {}
        if state is not None:
            state.validate()
            qubit_to_atom = {qubit: state.atom_for_qubit(qubit).atom_id for qubit in circuit.qubits}
        requests = []
        completion = {}
        for gate in dag.circuit.gates:
            atoms = tuple(qubit_to_atom.get(qubit, qubit) for qubit in gate.qubits)
            metadata = {**gate.metadata, "physical_gate": gate.gate_type.value}
            kind = gate.gate_type
            if kind in (GateType.CZ, GateType.CNOT):
                request = EntangleRequest(gate.id, gate.id, atoms, gate.predecessors,
                                          kind.value, metadata)
            elif kind in (GateType.MEASURE_X, GateType.MEASURE_Z):
                request = MeasureRequest(gate.id, gate.id, atoms[0], kind.value.removeprefix("MEASURE_"),
                                         gate.predecessors, metadata)
            elif kind in (GateType.H, GateType.X, GateType.Y, GateType.Z):
                request = SingleQubitRequest(gate.id, gate.id, atoms[0], kind.value,
                                             gate.predecessors, metadata)
            elif kind == GateType.PREPARE:
                request = PrepareRequest(gate.id, gate.id, atoms[0], gate.predecessors,
                                         str(gate.metadata.get("state", "0")), metadata)
            elif kind == GateType.RESET:
                request = ResetRequest(gate.id, gate.id, atoms[0], gate.predecessors,
                                       str(gate.metadata.get("state", "0")), metadata)
            else:
                raise ValueError(f"Unsupported physical gate: {kind.value}")
            requests.append(request)
            completion[gate.id] = (request.id,)
        return SemanticRequestPlan(tuple(requests), completion)
