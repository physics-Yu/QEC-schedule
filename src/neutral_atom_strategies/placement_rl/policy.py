"""Masked initial-layout policy and conditional finite-scenario adversary.

Optional torch dependency. Neither model imports the physical executor or UI.
Layouts are constructed before execution; these actions are not physical SWAPs.
"""
from math import hypot

import torch
from torch import nn
from torch.distributions import Categorical


def circuit_tensors(circuit):
    """Three time bins retain more information than a static interaction count."""
    n, depth = circuit.n_qubits, max(1, len(circuit.layers))
    edges = torch.zeros(3, n, n)
    first, last, degree = [depth] * n, [0] * n, [0] * n
    for t, layer in enumerate(circuit.layers):
        for a, b in layer:
            edges[min(2, 3 * t // depth), a, b] += 1
            edges[min(2, 3 * t // depth), b, a] += 1
            for q in (a, b):
                first[q], last[q] = min(first[q], t), max(last[q], t)
                degree[q] += 1
    features = torch.tensor([[degree[q] / depth, first[q] / depth,
                              last[q] / depth, float(degree[q] == 0)] for q in range(n)])
    return features, edges


def site_tensors(hardware):
    points = hardware.storage
    targets = [p for pair in hardware.entangling for p in pair]
    scale = max(1., *(abs(v) for p in (*points, *targets) for v in p))
    return torch.tensor([[x / scale, y / scale,
                          min(hypot(x-a, y-b) for a, b in targets) / scale]
                         for x, y in points]), scale


class CircuitEncoder(nn.Module):
    def __init__(self, hidden):
        super().__init__()
        self.input = nn.Linear(4, hidden)
        self.update = nn.Sequential(nn.Linear(4 * hidden, hidden), nn.Tanh(),
                                    nn.Linear(hidden, hidden), nn.Tanh())

    def forward(self, circuit):
        features, edges = circuit_tensors(circuit)
        h = torch.tanh(self.input(features))
        degree = edges.sum(-1, keepdim=True).clamp_min(1.)
        messages = (edges / degree) @ h
        return self.update(torch.cat([h, *messages.unbind(0)], -1)), edges


class PlacementPolicy(nn.Module):
    """Autoregressive pointer over all eligible storage sites, including vacancies."""
    def __init__(self, hidden=32):
        super().__init__()
        self.hidden = hidden
        self.encoder = CircuitEncoder(hidden)
        self.site = nn.Sequential(nn.Linear(3, hidden), nn.Tanh())
        self.score = nn.Sequential(nn.Linear(2 * hidden + 5, hidden), nn.Tanh(),
                                   nn.Linear(hidden, 1))

    def sample(self, circuit, hardware, *, greedy=False):
        if len(hardware.storage) < circuit.n_qubits:
            raise ValueError('Insufficient storage sites')
        qubits, edges = self.encoder(circuit)
        site_features, scale = site_tensors(hardware)
        sites = self.site(site_features)
        count = len(hardware.storage)
        available = torch.ones(count, dtype=torch.bool)
        mapping, logps, entropies = [], [], []
        weights = edges[0] + .7 * edges[1] + .4 * edges[2]
        for q in range(circuit.n_qubits):
            dynamic = []
            denom = max(1., float(weights[q].sum()))
            for x, y in hardware.storage:
                weighted_distance = same_row = same_col = 0.
                for prior, index in enumerate(mapping):
                    px, py = hardware.storage[index]
                    w = float(weights[q, prior]) / denom
                    weighted_distance += w * hypot(x-px, y-py) / scale
                    same_row += w * (y == py)
                    same_col += w * (x == px)
                dynamic.append([weighted_distance, same_row, same_col,
                                q / max(1, circuit.n_qubits),
                                hardware.aod_rows / max(1, hardware.aod_rows + hardware.aod_cols)])
            logits = self.score(torch.cat([sites, qubits[q].expand(count, -1),
                                            torch.tensor(dynamic)], -1)).squeeze(-1)
            distribution = Categorical(logits=logits.masked_fill(~available, -torch.inf))
            action = logits.masked_fill(~available, -torch.inf).argmax() if greedy else distribution.sample()
            mapping.append(int(action))
            logps.append(distribution.log_prob(action))
            entropies.append(distribution.entropy())
            # Don't mutate a mask retained by autograd.
            available = available.clone()
            available[int(action)] = False
        return tuple(mapping), torch.stack(logps).sum(), torch.stack(entropies).mean()


class ScenarioAdversary(nn.Module):
    """Learn which authorized scenario exposes a completed layout's weakness."""
    def __init__(self, n_scenarios, hidden=32):
        super().__init__()
        if n_scenarios < 2:
            raise ValueError('The adversary needs at least two scenarios')
        self.encoder = CircuitEncoder(hidden)
        self.mapped_node = nn.Sequential(nn.Linear(hidden + 3, hidden), nn.Tanh())
        self.readout = nn.Sequential(nn.Linear(2 * hidden + 6, hidden), nn.Tanh(),
                                     nn.Linear(hidden, n_scenarios))

    def distribution(self, circuit, hardware, mapping):
        if len(mapping) != circuit.n_qubits or len(set(mapping)) != len(mapping):
            raise ValueError('Adversary requires a complete injective mapping')
        if any(type(i) is not int or not 0 <= i < len(hardware.storage) for i in mapping):
            raise ValueError('Mapping outside storage')
        h, edges = self.encoder(circuit)
        sites, scale = site_tensors(hardware)
        mapped = self.mapped_node(torch.cat([h, sites[list(mapping)]], -1))
        features = []
        for t in range(3):
            distance = same_row = total = 0.
            for a in range(circuit.n_qubits):
                for b in range(a):
                    w = float(edges[t, a, b])
                    ax, ay = hardware.storage[mapping[a]]
                    bx, by = hardware.storage[mapping[b]]
                    distance += w * hypot(ax-bx, ay-by) / scale
                    same_row += w * (ay == by)
                    total += w
            features.extend([distance / max(1., total), same_row / max(1., total)])
        return Categorical(logits=self.readout(torch.cat([mapped.mean(0), mapped.max(0).values,
                                                          torch.tensor(features)])))
