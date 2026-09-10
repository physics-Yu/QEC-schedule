from dataclasses import dataclass, replace
from types import MappingProxyType
from collections.abc import Mapping
from .physical_circuit import PhysicalCircuit
from neutral_atom_env.domain.models import GateStatus, PhysicalGate


@dataclass(frozen=True)
class GateNodeRuntime:
    gate: PhysicalGate
    status: GateStatus
    remaining_predecessors: int
    successors: frozenset[str]


@dataclass(frozen=True, init=False)
class DynamicGateDAG:
    """Logical dependencies only. Runtime transitions are executor-internal."""

    _nodes: Mapping[str, GateNodeRuntime]
    circuit: PhysicalCircuit

    def __init__(self, circuit):
        previous, predecessors, successors = {}, {}, {g.id: set() for g in circuit.gates}
        for gate in circuit.gates:
            deps = {previous[q] for q in gate.qubit_ids if q in previous}
            predecessors[gate.id] = deps
            for parent in deps:
                successors[parent].add(gate.id)
            for q in gate.qubit_ids:
                previous[q] = gate.id
        object.__setattr__(self, 'circuit', circuit)
        object.__setattr__(self, '_nodes', MappingProxyType({g.id: GateNodeRuntime(g, GateStatus.BLOCKED if predecessors[g.id]
            else GateStatus.READY, len(predecessors[g.id]), frozenset(successors[g.id])) for g in circuit.gates}))

    @property
    def nodes(self):
        return self._nodes

    def ready_gates(self):
        return tuple(n.gate for _, n in sorted(self._nodes.items()) if n.status == GateStatus.READY)

    @property
    def completed(self):
        return all(n.status == GateStatus.COMPLETED for n in self._nodes.values())

    def transitioned(self, gate_id, target) -> 'DynamicGateDAG':
        """Pure logical reducer; only executor installs results into live state."""
        node = self._nodes[gate_id]
        allowed = {GateStatus.READY: {GateStatus.RESERVED},
                   GateStatus.RESERVED: {GateStatus.RUNNING, GateStatus.FAILED},
                   GateStatus.RUNNING: {GateStatus.COMPLETED, GateStatus.FAILED}}
        if target not in allowed.get(node.status, set()):
            raise ValueError(f"Illegal transition: {node.status} -> {target}")
        nodes = dict(self._nodes)
        nodes[gate_id] = replace(node, status=target)
        if target == GateStatus.COMPLETED:
            for successor in sorted(node.successors):
                child = self._nodes[successor]
                remaining = child.remaining_predecessors - 1
                nodes[successor] = replace(child, remaining_predecessors=remaining,
                    status=GateStatus.READY if remaining == 0 else child.status)
        result = DynamicGateDAG(self.circuit)
        object.__setattr__(result, '_nodes', MappingProxyType(nodes))
        return result

    @classmethod
    def restored(cls, circuit, runtime):
        result = cls(circuit)
        if set(runtime) != set(result.nodes):
            raise ValueError('Snapshot DAG IDs do not match circuit')
        statuses = {key: GateStatus(n['status']) for key, n in runtime.items()}
        nodes = {}
        for key, node in result.nodes.items():
            data = runtime[key]
            parents = [p for p, n in result.nodes.items() if key in n.successors]
            remaining = sum(statuses[p] != GateStatus.COMPLETED for p in parents)
            status = statuses[key]
            if (set(data['successors']) != node.successors or data['remaining_predecessors'] != remaining or
                    (remaining > 0) != (status == GateStatus.BLOCKED)):
                raise ValueError('Inconsistent restored DAG dependency state')
            nodes[key] = replace(node, status=status, remaining_predecessors=remaining)
        object.__setattr__(result, '_nodes', MappingProxyType(nodes))
        return result
