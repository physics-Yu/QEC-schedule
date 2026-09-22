"""Dependency-aware frontier; measurements/conditions are never stripped."""


class LayerScheduler:
    def __init__(self, dag):
        # Immutable successors include explicit and measurement dependencies.
        self.order = {g.id: i for i, g in enumerate(dag.circuit.gates)}
        self.depth = {}
        for gate in reversed(dag.circuit.gates):
            self.depth[gate.id] = 1 + max((self.depth[s] for s in dag.nodes[gate.id].successors), default=0)

    def frontier(self, state):
        ready = sorted(state.dag.ready_gates(), key=lambda g: (-self.depth[g.id], self.order[g.id]))
        rotations = [g for g in ready if g.u_parameters is not None]
        if rotations:
            return tuple(g for g in rotations if g.gate_type == rotations[0].gate_type)
        cz = tuple(g for g in ready if g.gate_type == 'CZ')
        if cz:
            return cz
        return tuple(g for g in ready if g.gate_type == ready[0].gate_type) if ready else ()
