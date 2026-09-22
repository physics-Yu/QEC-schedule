"""Headless training/evaluation for initial placement against a learned opponent.

Run with the isolated torch runtime, not the production workbench. Outputs are
research-model evidence only; successful discrete replay is not physical replay.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from random import Random
import shutil
from statistics import mean
from time import perf_counter

import torch

from neutral_atom_strategies.placement_rl.model import Circuit, CompilerConfig, standard_hardware
from neutral_atom_strategies.placement_rl.compiler import audit_result
from neutral_atom_strategies.placement_rl.policy import PlacementPolicy, ScenarioAdversary
from neutral_atom_strategies.placement_rl.game import (Evaluator, default_scenarios,
    interaction_layout, learn_step, search_baseline)

ROOT = Path(__file__).resolve().parents[2]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def circuit_digest(circuit):
    return sha256(json.dumps(asdict(circuit), sort_keys=True).encode()).hexdigest()


def make_case(n, depth, seed, family='random'):
    rng, layers = Random(seed), []
    labels = list(range(n))
    rng.shuffle(labels)
    for t in range(depth):
        if family == 'bipartite':
            left, right = labels[:n//2], labels[n//2:]
            rng.shuffle(right)
            pairs = list(zip(left, right))
        elif family == 'alternating':
            shifted = labels[t % n:] + labels[:t % n]
            pairs = list(zip(shifted[::2], shifted[1::2]))
        else:
            order = labels[:]
            rng.shuffle(order)
            pairs = list(zip(order[::2], order[1::2]))
        layers.append(tuple(sorted(tuple(sorted(p)) for p in pairs)))
    return Circuit(n, tuple(layers))


def dataset(config):
    """Generate all splits before training; no performance-based filtering."""
    seen, splits = set(), {}
    for split, offset, count, n in (
        ('train', 1000, config['train_cases'], config['qubits']),
        ('validation', 2000, config['validation_cases'], config['qubits']),
        ('test', 3000, config['test_cases'], config['qubits']),
        ('size_holdout', 4000, config['holdout_cases'], config['qubits']+2)):
        rows, attempt = [], 0
        while len(rows) < count:
            if attempt > 10000:
                raise ValueError('Cannot construct disjoint requested dataset')
            seed = config['dataset_seed'] + offset + attempt
            family = ('random', 'bipartite')[attempt % 2] if split != 'size_holdout' else 'alternating'
            circuit = make_case(n, config['depth'], seed, family)
            attempt += 1
            digest = circuit_digest(circuit)
            if digest in seen:
                continue
            seen.add(digest)
            rows.append(dict(id=f'{split}-{len(rows):03d}', seed=seed, family=family,
                             digest=digest, circuit=asdict(circuit)))
        splits[split] = rows
    return splits


def evaluator_for(row, config):
    raw = row['circuit']
    circuit = Circuit(raw['n_qubits'], tuple(tuple(tuple(p) for p in layer) for layer in raw['layers']))
    return Evaluator(circuit, standard_hardware(circuit.n_qubits, vacancies=config['vacancies']),
                     config=CompilerConfig(**config['compiler']))


def uniform_adversary(adversary):
    # Zero final logits yields a fixed uniform distribution for the RL ablation.
    with torch.no_grad():
        adversary.readout[-1].weight.zero_()
        adversary.readout[-1].bias.zero_()


def validation_score(actor, evaluators):
    scores = []
    with torch.no_grad():
        for evaluator in evaluators:
            mapping, _, _ = actor.sample(evaluator.circuit, evaluator.hardware, greedy=True)
            reference = interaction_layout(evaluator.circuit, evaluator.hardware)
            scores.append(float(evaluator.losses(mapping, reference).max()))
    return mean(scores)


def model_digest(model):
    digest = sha256()
    for name, tensor in model.state_dict().items():
        digest.update(name.encode())
        # Hash the same contiguous tensor bytes without requiring Torch's
        # optional NumPy ABI bridge (training itself does not need it).
        values = tensor.detach().cpu().reshape(-1).contiguous()
        digest.update(bytes(values.view(torch.uint8).tolist()))
    return digest.hexdigest()


def train_variant(config, splits, output, seed, mode):
    torch.manual_seed(seed)
    actor = PlacementPolicy(config['hidden'])
    adversary = ScenarioAdversary(len(default_scenarios()), config['hidden'])
    if mode == 'uniform':
        uniform_adversary(adversary)
    actor_start, adversary_start = model_digest(actor), model_digest(adversary)
    initial = deepcopy(actor.state_dict())
    actor_optimizer = torch.optim.Adam(actor.parameters(), lr=config['learning_rate'])
    adversary_optimizer = torch.optim.Adam(adversary.parameters(),
                                          lr=config['adversary_learning_rate'] if mode == 'adversarial' else 0.)
    train = [evaluator_for(row, config) for row in splits['train']]
    validation = [evaluator_for(row, config) for row in splits['validation']]
    selected = deepcopy(initial)
    best_score = validation_score(actor, validation)
    best_step, history, validations = 0, [], [dict(step=0, score=best_score)]
    rng = Random(seed)
    start = perf_counter()
    for step in range(1, config['updates']+1):
        batch = rng.sample(train, min(config['batch_size'], len(train)))
        result = learn_step(actor, adversary, actor_optimizer, adversary_optimizer, batch,
                            nominal_share=config['nominal_share'])
        history.append(dict(step=step, **result))
        if step % config['validation_interval'] == 0 or step == config['updates']:
            score = validation_score(actor, validation)
            validations.append(dict(step=step, score=score))
            if score < best_score - 1e-9:
                best_score, best_step, selected = score, step, deepcopy(actor.state_dict())
            print(f'{mode} seed={seed} step={step}: validation worst regret={score:.5f}, selected={best_step}', flush=True)
    seconds = perf_counter()-start
    output.mkdir(parents=True, exist_ok=True)
    torch.save(dict(schema='placement-rl/1', hidden=config['hidden'], actor=selected,
                    last_actor=actor.state_dict(), initial_actor=initial, adversary=adversary.state_dict(),
                    selected_step=best_step, adversary_step=config['updates'],
                    adversary_role='final opponent diagnostic; actor selected independently on validation',
                    config=config), output/'checkpoint.pt')
    summary = dict(mode=mode, seed=seed, selected_step=best_step,
                   validation_score=best_score, training_seconds=seconds,
                   actor_changed=model_digest(actor) != actor_start,
                   adversary_changed=model_digest(adversary) != adversary_start,
                   compiler_calls=sum(e.calls for e in train+validation),
                   compiler_seconds=sum(e.seconds for e in train+validation),
                   cache_hits=sum(e.cache_hits for e in train+validation), validations=validations)
    write_json(output/'training.json', dict(summary=summary, history=history))
    actor.load_state_dict(selected)
    untrained = PlacementPolicy(config['hidden'])
    untrained.load_state_dict(initial)
    return actor, untrained, adversary, summary


def measure_mapping(evaluator, mapping, reference):
    values = evaluator.losses(mapping, reference)
    results = [evaluator.result(mapping, i) for i in range(len(evaluator.scenarios))]
    base = [evaluator.result(reference, i) for i in range(len(evaluator.scenarios))]
    return dict(mapping=list(mapping),
                statuses=[r.status for r in results],
                modeled_duration_us=[r.duration_us if r.status == 'completed' else None for r in results],
                relative_change=[r.duration_us / b.duration_us - 1 if r.status == 'completed' and b.duration_us else None
                                 for r, b in zip(results, base)],
                worst_bounded_regret=float(values.max()),
                all_scenarios_completed=all(r.status == 'completed' for r in results),
                errors=[r.error for r in results])


def evaluate_variant(actor, initial, adversary, config, splits, output, seed):
    rows, start = [], perf_counter()
    torch.manual_seed(seed + 70000)
    for split in ('test', 'size_holdout'):
        for row in splits[split]:
            evaluator = evaluator_for(row, config)
            circuit, hardware = evaluator.circuit, evaluator.hardware
            reference = interaction_layout(circuit, hardware)
            t = perf_counter()
            with torch.no_grad():
                learned, _, _ = actor.sample(circuit, hardware, greedy=True)
                untrained, _, _ = initial.sample(circuit, hardware, greedy=True)
            greedy_seconds = perf_counter()-t
            mappings = dict(identity=tuple(range(circuit.n_qubits)), interaction=reference,
                            untrained_greedy=untrained, trained_greedy=learned)
            budgets = {name: dict(unique_layouts=1) for name in mappings}
            for method in ('random', 'anneal'):
                mappings[method], budgets[method] = search_baseline(evaluator, method=method,
                    budget=config['search_budget'], seed=row['seed'])
            # Equal shortlist cap includes heuristic safety fallback and greedy.
            pool, attempts = {reference, learned}, 0
            with torch.no_grad():
                while len(pool) < config['search_budget'] and attempts < config['search_budget'] * 30:
                    candidate, _, _ = actor.sample(circuit, hardware)
                    pool.add(candidate)
                    attempts += 1
            mappings['trained_search'] = min(pool, key=lambda m:(float(evaluator.losses(m, reference).max()), m))
            budgets['trained_search'] = dict(unique_layouts=len(pool), draws=attempts)
            measurements = {name: dict(**measure_mapping(evaluator, mapping, reference), search=budgets[name])
                            for name, mapping in mappings.items()}
            with torch.no_grad():
                probabilities = adversary.distribution(circuit, hardware, learned).probs.tolist()
            # Retain the selected and reference witnesses for independent review.
            for name in ('interaction', 'trained_greedy', 'trained_search'):
                for i, scenario in enumerate(evaluator.scenarios):
                    result = evaluator.result(mappings[name], i)
                    audit = audit_result(circuit, hardware, mappings[name], result, scenario, evaluator.config)
                    write_json(output/'witnesses'/row['id']/f'{name}-{i}.json',
                        dict(circuit=asdict(circuit), hardware=asdict(hardware), mapping=mappings[name],
                             scenario=asdict(scenario), compiler=asdict(evaluator.config),
                             result=asdict(result), audit=audit))
            rows.append(dict(id=row['id'], split=split, family=row['family'],
                             digest=row['digest'], measurements=measurements,
                             adversary_probabilities=probabilities, greedy_pair_inference_seconds=greedy_seconds,
                             adversary_step=config['updates'], adversary_role='final opponent diagnostic',
                             compiler_calls=evaluator.calls, compiler_seconds=evaluator.seconds))
            print(f'evaluated {row["id"]}: greedy={measurements["trained_greedy"]["worst_bounded_regret"]:.5f}', flush=True)
    aggregate = {}
    for split in ('test', 'size_holdout'):
        selected_rows = [r for r in rows if r['split'] == split]
        aggregate[split] = {}
        for name in rows[0]['measurements']:
            values = [r['measurements'][name] for r in selected_rows]
            nominal = [v['relative_change'][0] for v in values if v['relative_change'][0] is not None]
            aggregate[split][name] = dict(cases=len(values), completed=sum(v['all_scenarios_completed'] for v in values),
                mean_worst_bounded_regret=mean(v['worst_bounded_regret'] for v in values),
                nominal_mean_change=mean(nominal) if nominal else None)
    summary = dict(aggregate=aggregate, evaluation_seconds=perf_counter()-start,
                   compiler_calls=sum(r['compiler_calls'] for r in rows),
                   compiler_seconds=sum(r['compiler_seconds'] for r in rows))
    write_json(output/'evaluation.json', dict(summary=summary, cases=rows))
    return summary


def run(config, output):
    if output.exists():
        raise ValueError('Use a fresh output directory; existing experiments are never overwritten')
    if config['search_budget'] < 2 or config['updates'] < 1:
        raise ValueError('search_budget >=2 and updates >=1 required')
    if not config['modes'] or any(m not in ('adversarial', 'uniform') for m in config['modes']):
        raise ValueError('modes must contain adversarial and/or uniform')
    if len(set(config['modes'])) != len(config['modes']) or len(set(config['seeds'])) != len(config['seeds']):
        raise ValueError('Duplicate mode/seed would overwrite a variant')
    torch.set_num_threads(1)
    splits = dataset(config)
    sources = sorted((ROOT/'src/neutral_atom_strategies/placement_rl').glob('*.py')) + [Path(__file__)]
    provenance = {str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in sources}
    write_json(output/'manifest.json', dict(schema='placement-rl-experiment/1', config=config,
        splits=splits, scenarios=[asdict(s) for s in default_scenarios()], source_sha256=provenance,
        torch_version=str(torch.__version__),
        scope='Illustrative strict discrete compiler; no continuous path or physical Executor acceptance'))
    for path in sources:
        destination = output/'source-snapshot'/path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    results = []
    try:
        for seed in config['seeds']:
            for mode in config['modes']:
                directory = output/f'{mode}-seed-{seed}'
                actor, initial, adversary, training = train_variant(config, splits, directory, seed, mode)
                evaluation = evaluate_variant(actor, initial, adversary, config, splits, directory, seed)
                results.append(dict(training=training, evaluation=evaluation))
                write_json(output/'summary.json', dict(status='running', results=results))
    except Exception as exc:
        write_json(output/'summary.json', dict(status='failed', results=results,
                   error=dict(type=type(exc).__name__, message=str(exc))))
        raise
    write_json(output/'summary.json', dict(status='completed', results=results,
        physical_validation='not_run', native_author_compiler_parity='not_run',
        general_performance_advantage='not_established_by_small_pilot'))
    lines = ['# Initial placement RL pilot', '',
             'Research-model durations only. No physical Executor or continuous collision validation.', '',
             '| Mode | Seed | Selected update | Actor updated | Opponent updated | Test worst regret | Nominal change |',
             '| --- | ---: | ---: | --- | --- | ---: | ---: |']
    for r in results:
        t = r['training']; m = r['evaluation']['aggregate']['test']['trained_greedy']
        lines.append(f'| {t["mode"]} | {t["seed"]} | {t["selected_step"]} | {t["actor_changed"]} | '
                     f'{t["adversary_changed"]} | {m["mean_worst_bounded_regret"]:.5f} | {m["nominal_mean_change"]:.2%} |')
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'configs/rl/initial_placement.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--updates', type=int)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if args.updates is not None:
        config['updates'] = args.updates
    run(config, args.output)


if __name__ == '__main__':
    main()
