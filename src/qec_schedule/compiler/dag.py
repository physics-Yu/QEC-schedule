"""Physical dependency graph and completion bookkeeping; no hardware scheduling."""
from collections.abc import Iterable
from enum import Enum
import heapq
from types import MappingProxyType

from .physical_gate_ir import PhysicalCircuit, PhysicalGate


class OperationState(str, Enum):
    WAITING = "WAITING"
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"


def _topological_order(qubits: tuple[str, ...], gates: tuple[PhysicalGate, ...]):
    """Validate explicit edges and sort stably, allowing unordered input records."""
    if len(set(qubits)) != len(qubits) or any(not q for q in qubits):
        raise ValueError("Circuit qubits must be unique and nonempty")
    declared = set(qubits)
    by_id = {}
    for gate in gates:
        if gate.id in by_id:
            raise ValueError(f"Duplicate gate ID: {gate.id}")
        if not set(gate.qubits) <= declared:
            raise ValueError(f"Unknown qubit in gate: {gate.id}")
        by_id[gate.id] = gate
    indices = {gate.id: i for i, gate in enumerate(gates)}
    remaining = {gate.id: len(gate.predecessors) for gate in gates}
    successors = {gate.id: [] for gate in gates}
    for gate in gates:
        for parent in gate.predecessors:
            if parent not in by_id:
                raise ValueError(f"Unknown predecessor {parent!r} in gate {gate.id!r}")
            successors[parent].append(gate.id)
    ready = [indices[gate_id] for gate_id, count in remaining.items() if count == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        gate = gates[heapq.heappop(ready)]
        ordered.append(gate)
        for child in successors[gate.id]:
            remaining[child] -= 1
            if remaining[child] == 0:
                heapq.heappush(ready, indices[child])
    if len(ordered) != len(gates):
        unresolved = ", ".join(gate_id for gate_id, count in remaining.items() if count)
        raise ValueError(f"Dependency cycle; unresolved gates: {unresolved}")
    return tuple(ordered)


class PhysicalCircuitDAG:
    """Immutable graph indices plus state for one execution.

    A ready gate has all predecessors DONE. Starting a gate does not unlock its
    successors; only completing it does. Multiple gates can remain RUNNING.
    To replay, construct a fresh DAG from ``dag.circuit``.
    """

    def __init__(self, circuit: PhysicalCircuit):
        self._circuit = circuit
        self._gates = MappingProxyType({gate.id: gate for gate in circuit.gates})
        self._order = tuple(self._gates)
        self._index = {gate_id: i for i, gate_id in enumerate(self._order)}
        self._predecessors = MappingProxyType({
            gate.id: tuple(sorted(gate.predecessors, key=self._index.__getitem__))
            for gate in circuit.gates
        })
        successors = {gate_id: [] for gate_id in self._order}
        for gate_id, parents in self._predecessors.items():
            for parent in parents:
                successors[parent].append(gate_id)
        self._successors = MappingProxyType({k: tuple(v) for k, v in successors.items()})
        self._validate_qubit_order()
        self._remaining = {k: len(v) for k, v in self._predecessors.items()}
        self._states = {k: OperationState.WAITING if count else OperationState.READY
                        for k, count in self._remaining.items()}
        self._ready = {k for k, count in self._remaining.items() if count == 0}
        self._running: set[str] = set()
        self._completed: set[str] = set()

    @classmethod
    def from_gates(cls, qubits: Iterable[str], gates: Iterable[PhysicalGate]):
        """Import unordered gate records, rejecting cycles and dangling edges."""
        qubits, gates = tuple(qubits), tuple(gates)
        return cls(PhysicalCircuit(qubits, _topological_order(qubits, gates)))

    @property
    def circuit(self) -> PhysicalCircuit:
        return self._circuit

    @property
    def gates(self):
        """Read-only ID -> PhysicalGate mapping in stable topological order."""
        return self._gates

    @property
    def edge_count(self) -> int:
        return sum(len(parents) for parents in self._predecessors.values())

    @property
    def is_complete(self) -> bool:
        return len(self._completed) == len(self._gates)

    def predecessors(self, gate_id: str) -> tuple[str, ...]:
        return self._predecessors[gate_id]

    def successors(self, gate_id: str) -> tuple[str, ...]:
        return self._successors[gate_id]

    def topological_order(self) -> tuple[str, ...]:
        return self._order

    def state(self, gate_id: str) -> OperationState:
        return self._states[gate_id]

    def _operations(self, ids: set[str]) -> tuple[PhysicalGate, ...]:
        return tuple(self._gates[k] for k in sorted(ids, key=self._index.__getitem__))

    def ready_operations(self) -> tuple[PhysicalGate, ...]:
        """Circuit-eligible gates only; no resource or duration assumptions."""
        return self._operations(self._ready)

    def running_operations(self) -> tuple[PhysicalGate, ...]:
        return self._operations(self._running)

    def completed_operations(self) -> tuple[PhysicalGate, ...]:
        return self._operations(self._completed)

    def start(self, gate_id: str) -> None:
        self.start_operations((gate_id,))

    def start_operations(self, gate_ids: Iterable[str]) -> None:
        """Atomically claim a subset of ready gates, or leave all states intact."""
        ids = tuple(gate_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate gate IDs in start request")
        for gate_id in ids:
            if self.state(gate_id) != OperationState.READY:
                raise ValueError(f"Gate {gate_id!r} is not READY")
        for gate_id in ids:
            self._states[gate_id] = OperationState.RUNNING
            self._ready.remove(gate_id)
            self._running.add(gate_id)

    def complete(self, gate_id: str) -> None:
        """Complete one running gate and immediately unlock eligible successors."""
        if self.state(gate_id) != OperationState.RUNNING:
            raise ValueError(f"Gate {gate_id!r} is not RUNNING")
        self._states[gate_id] = OperationState.DONE
        self._running.remove(gate_id)
        self._completed.add(gate_id)
        for child in self._successors[gate_id]:
            self._remaining[child] -= 1
            if self._remaining[child] == 0:
                self._states[child] = OperationState.READY
                self._ready.add(child)

    def _validate_qubit_order(self) -> None:
        """Reject ambiguous same-qubit ordering; never invent dependency edges."""
        def is_ancestor(earlier, later):
            pending = list(self._predecessors[later])
            visited = set()
            while pending:
                parent = pending.pop()
                if parent == earlier:
                    return True
                if parent not in visited and self._index[parent] > self._index[earlier]:
                    visited.add(parent)
                    pending.extend(self._predecessors[parent])
            return False

        last = {}
        for gate in self._circuit.gates:
            for qubit in gate.qubits:
                if qubit in last and not is_ancestor(last[qubit], gate.id):
                    raise ValueError(f"Missing dependency order on qubit {qubit!r}: {last[qubit]!r}, {gate.id!r}")
                last[qubit] = gate.id

    def to_dict(self):
        """Export static topology. This is not a timed hardware execution trace."""
        return {"schema_version": 1, "kind": "physical_circuit_dag",
                "qubits": list(self._circuit.qubits),
                "topological_order": list(self._order),
                "gates": [{**gate.to_dict(), "predecessors": list(self.predecessors(gate.id)),
                           "successors": list(self.successors(gate.id))}
                          for gate in self._circuit.gates]}
