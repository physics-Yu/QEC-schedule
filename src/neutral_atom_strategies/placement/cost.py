"""Cached static-map proxy, deliberately separate from physical legality/time.

All gates participate in dependency layering. Only CZ geometry is scored;
measurement/1Q/feedback transport is not estimated in this first implementation.
"""
from functools import lru_cache
from math import sqrt
from copy import deepcopy

from neutral_atom_env.circuit import DynamicGateDAG
from neutral_atom_strategies.motion.parking_groups import analyze
from .models import CostEstimate


def circuit_layers(circuit):
    dag = DynamicGateDAG(circuit)
    predecessors = {g.id: set() for g in circuit.gates}
    for key, node in dag.nodes.items():
        for child in node.successors:
            predecessors[child].add(key)
    levels = {}
    for gate in circuit.gates:
        levels[gate.id] = 1 + max((levels[p] for p in predecessors[gate.id]), default=-1)
    return tuple(tuple(g for g in circuit.gates if levels[g.id] == i)
                 for i in range(max(levels.values(), default=-1) + 1))


def segment_time(distance, hardware):
    """Same cubic rest-to-rest bounds as ordered AOD; no obstacle claim."""
    return max(1.5 * distance / hardware.speed_um_per_us,
               sqrt(6 * distance / hardware.max_acceleration_um_per_us2),
               (12 * distance / hardware.max_jerk_um_per_us3) ** (1 / 3))


@lru_cache(maxsize=4096)
def _groups(mask):
    return analyze([list(r) for r in mask])


class PlacementCostModel:
    def __init__(self, problem, config):
        if problem.hardware.backend != 'row_column_orthogonal':
            raise ValueError('Initial cost model currently requires row_column_orthogonal hardware')
        self.problem, self.config = problem, config
        self.sites = {s.id: s for s in problem.storage}
        self.xs = sorted({s.x_um for s in problem.storage})
        self.ys = sorted({s.y_um for s in problem.storage})
        self.indices = {s.id: (self.ys.index(s.y_um), self.xs.index(s.x_um)) for s in problem.storage}
        self.regular = all(len(v) < 3 or all(abs((v[i+1]-v[i])-(v[1]-v[0])) < 1e-8
                           for i in range(1, len(v)-1)) for v in (self.xs, self.ys))
        self.layers = tuple(layer for layer in circuit_layers(problem.circuit) if any(g.is_two_qubit for g in layer))[:config.lookahead_layers]
        self.evaluations = 0
        # Per-search cache does not retain unrelated problems or contaminate
        # per-run hit counts. Pattern masks can safely be shared globally.
        self._pair = lru_cache(maxsize=32768)(self._pair)

    def _pair(self, left, right):
        a, b = self.sites[left], self.sites[right]
        # Nearest shared reference site. Assignment contention and final paired
        # offsets are left to physical compilation, not silently called solved.
        costs = []
        for target in self.problem.interaction_sites:
            ta = segment_time(abs(a.x_um-target.x_um), self.problem.hardware) + segment_time(abs(a.y_um-target.y_um), self.problem.hardware)
            tb = segment_time(abs(b.x_um-target.x_um), self.problem.hardware) + segment_time(abs(b.y_um-target.y_um), self.problem.hardware)
            costs.append(max(ta, tb) if a.y_um == b.y_um else ta + tb)
        return 2 * min(costs)  # outward + return proxy, NOT a routed path

    def estimate(self, mapping):
        mapping = dict(self.problem.validate_mapping(mapping))
        transport = capture = 0.0
        details = []
        self.evaluations += 1
        for index, layer in enumerate(self.layers):
            gates = tuple(g for g in layer if g.is_two_qubit)
            targets = {q for g in gates for q in g.qubit_ids}
            positions = {q: self.indices[mapping[q]] for q in targets}
            rs = {r for r, c in positions.values()}; cs = {c for r, c in positions.values()}
            applicable = (self.regular and max(len(self.xs), len(self.ys)) <= 16
                          and len(rs) <= self.problem.aod_rows and len(cs) <= self.problem.aod_columns)
            if applicable:
                mask = [[0] * len(self.xs) for _ in self.ys]
                for q, site in mapping.items():
                    r, c = self.indices[site]; mask[r][c] = 2 if q in targets else 1
                # Report dictionaries are caller-owned; do not let edits poison
                # the shared pure-pattern cache used by later searches.
                groups = deepcopy(_groups(tuple(map(tuple, mask))))
                axis = groups['selected_axis']
                batches = groups[axis]['batches']
            else:
                # Do not claim the parking template fits oversized/irregular
                # geometry. This conservative singleton *proxy* is not a route.
                groups = None; axis = 'singleton_proxy'; batches = len(targets)
            t = sum(self._pair(*(mapping[q] for q in g.qubit_ids)) for g in gates)
            c = batches * (self.problem.hardware.load_duration_us + self.problem.hardware.offload_duration_us)
            weight = self.config.decay ** index
            transport += weight * t; capture += weight * c
            details.append(dict(gate_ids=[g.id for g in gates], weight=weight,
                axis=axis, capture_batches=batches, compatibility=groups,
                transport_proxy_us=t, capture_proxy_us=c, parking_pattern_applicable=applicable))
        total = transport + (capture if self.config.objective == 'parking_aware' else 0)
        return CostEstimate(total, transport, capture, tuple(details))

    def statistics(self):
        return dict(cost_evaluations=self.evaluations, pair_cache=self._pair.cache_info()._asdict(),
                    pattern_cache=_groups.cache_info()._asdict())
