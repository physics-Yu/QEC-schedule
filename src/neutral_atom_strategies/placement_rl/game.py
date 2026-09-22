"""Bounded adversarial game, exact scenario enumeration, and fair baselines."""
from math import exp, hypot
from random import Random
from time import perf_counter

import torch

from .model import Scenario, CompilerConfig
from .compiler import compile_layout, audit_result


def default_scenarios():
    # Same geometry/constraints/gates. Only illustrative duration parameters and
    # deterministic legal grouping order change, never physical legality.
    return (Scenario('nominal'),
            Scenario('move_heavy', 1.2, .8),
            Scenario('transfer_heavy', .8, 1.2),
            Scenario('move_heavy_reverse', 1.2, .8, 'reverse'),
            Scenario('transfer_heavy_reverse', .8, 1.2, 'reverse'))


def interaction_layout(circuit, hardware):
    """Deterministic temporal-interaction baseline, not a ZAC reproduction."""
    weights = [[0.] * circuit.n_qubits for _ in range(circuit.n_qubits)]
    for t, layer in enumerate(circuit.layers):
        for a, b in layer:
            weights[a][b] += 1 / (1 + t)
            weights[b][a] = weights[a][b]
    order = sorted(range(circuit.n_qubits), key=lambda q: (-sum(weights[q]), q))
    mapping, free = {}, set(range(len(hardware.storage)))
    targets = [p for pair in hardware.entangling for p in pair]
    for q in order:
        def score(index):
            x, y = hardware.storage[index]
            distance = sum(weights[q][b] * hypot(x-hardware.storage[s][0],
                                                 y-hardware.storage[s][1]) for b, s in mapping.items())
            access = min(hypot(x-a, y-b) for a, b in targets)
            return distance, access, index
        chosen = min(free, key=score)
        mapping[q] = chosen
        free.remove(chosen)
    return tuple(mapping[q] for q in range(circuit.n_qubits))


class Evaluator:
    """Cache only within a fixed circuit/hardware/scenario/compiler contract."""
    def __init__(self, circuit, hardware, scenarios=None, config=None):
        self.circuit, self.hardware = circuit, hardware
        self.scenarios = tuple(scenarios or default_scenarios())
        self.config = config or CompilerConfig()
        self.cache, self.calls, self.cache_hits, self.seconds = {}, 0, 0, 0.

    def result(self, mapping, scenario_index):
        key = tuple(mapping), scenario_index
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key]
        start = perf_counter()
        scenario = self.scenarios[scenario_index]
        result = compile_layout(self.circuit, self.hardware, tuple(mapping), scenario, self.config)
        if result.status == 'completed':
            audit = audit_result(self.circuit, self.hardware, tuple(mapping), result, scenario, self.config)
            if audit.get('status') != 'passed':
                raise AssertionError(f'Fast compiler failed independent replay: {audit}')
        self.seconds += perf_counter()-start
        self.calls += 1
        self.cache[key] = result
        return result

    def costs(self, mapping):
        results = [self.result(mapping, i) for i in range(len(self.scenarios))]
        return tuple(r.duration_us if r.status == 'completed' else float('inf') for r in results)

    def losses(self, mapping, reference):
        """Bounded monotone regret: all legal completions <1, failure =2.

        (C-Cref)/(C+Cref) preserves scenario-wise cost order without permitting
        failed short prefixes to beat a slow but legal completed program.
        """
        values = []
        for i in range(len(self.scenarios)):
            base = self.result(reference, i)
            if base.status != 'completed':
                raise ValueError('Reference failed; cannot normalize this scenario')
            candidate = self.result(mapping, i)
            if candidate.status != 'completed':
                values.append(2.)
            else:
                c, b = candidate.duration_us, base.duration_us
                values.append((c-b) / max(c+b, 1e-9))
        return torch.tensor(values, dtype=torch.float32)


def game_value(losses, probabilities, nominal_share=.25):
    if not 0 <= nominal_share <= 1:
        raise ValueError('nominal_share must lie in [0,1]')
    return nominal_share * losses[0] + (1-nominal_share) * (probabilities * losses).sum()


def learn_step(actor, adversary, actor_optimizer, adversary_optimizer, evaluators,
               *, nominal_share=.25, actor_entropy=.002, adversary_entropy=.01):
    """Simultaneous detached updates; exact finite adversary expectation.

    Actor's greedy-rollout baseline is evaluated independently of its sampled
    layout, avoiding an action-dependent scenario baseline in REINFORCE.
    Adversary receives no gradients through actor choices or compiler costs.
    """
    actor_losses, adversary_losses, records = [], [], []
    for evaluator in evaluators:
        circuit, hardware = evaluator.circuit, evaluator.hardware
        reference = interaction_layout(circuit, hardware)
        mapping, logp, entropy = actor.sample(circuit, hardware)
        values = evaluator.losses(mapping, reference)
        distribution = adversary.distribution(circuit, hardware, mapping)
        value = game_value(values, distribution.probs.detach(), nominal_share)
        with torch.no_grad():
            greedy, _, _ = actor.sample(circuit, hardware, greedy=True)
            baseline_values = evaluator.losses(greedy, reference)
            baseline_distribution = adversary.distribution(circuit, hardware, greedy)
            baseline = game_value(baseline_values, baseline_distribution.probs, nominal_share)
        actor_losses.append((value-baseline).detach() * logp - actor_entropy * entropy)
        adversary_losses.append(-(distribution.probs * values.detach()).sum()
                                - adversary_entropy * distribution.entropy())
        records.append(dict(mapping=list(mapping), greedy_mapping=list(greedy),
                            scenario_losses=values.tolist(), probabilities=distribution.probs.detach().tolist(),
                            value=float(value), baseline=float(baseline),
                            worst_loss=float(values.max()), entropy=float(distribution.entropy().detach())))
    actor_optimizer.zero_grad()
    actor_loss = torch.stack(actor_losses).mean()
    actor_loss.backward()
    torch.nn.utils.clip_grad_norm_(actor.parameters(), 1.)
    actor_optimizer.step()
    adversary_optimizer.zero_grad()
    adversary_loss = torch.stack(adversary_losses).mean()
    adversary_loss.backward()
    torch.nn.utils.clip_grad_norm_(adversary.parameters(), 1.)
    adversary_optimizer.step()
    return dict(actor_loss=float(actor_loss.detach()), adversary_loss=float(adversary_loss.detach()),
                records=records)


def search_baseline(evaluator, *, method='random', budget=8, seed=0):
    """Equal distinct-layout evaluation cap, using the full finite robust objective.

    SA here is compiler-feedback local search, not the author's original ZAC SA.
    All methods start from the same temporal-interaction layout.
    """
    if method not in ('random', 'anneal') or budget < 1:
        raise ValueError('Invalid search method/budget')
    rng = Random(seed)
    reference = interaction_layout(evaluator.circuit, evaluator.hardware)
    current = best = reference
    def score(m):
        return float(evaluator.losses(m, reference).max())
    current_cost = best_cost = score(current)
    seen, attempts = {current}, 0
    while len(seen) < budget and attempts < budget * 30:
        attempts += 1
        if method == 'random':
            candidate = tuple(rng.sample(range(len(evaluator.hardware.storage)), len(current)))
        else:
            candidate = list(current)
            q = rng.randrange(len(candidate))
            site = rng.randrange(len(evaluator.hardware.storage))
            if site in candidate:
                other = candidate.index(site)
                candidate[q], candidate[other] = candidate[other], candidate[q]
            else:
                candidate[q] = site
            candidate = tuple(candidate)
        if candidate in seen:
            continue
        seen.add(candidate)
        cost = score(candidate)
        if cost < best_cost:
            best, best_cost = candidate, cost
        temperature = .2 * (.05 ** (len(seen) / budget))
        if cost < current_cost or rng.random() < exp(min(0., (current_cost-cost)/temperature)):
            current, current_cost = candidate, cost
    return best, dict(unique_layouts=len(seen), worst_bounded_regret=best_cost)
