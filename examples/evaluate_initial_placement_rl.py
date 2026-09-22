"""Infer a layout for a CZ-layer JSON and audit all authorized scenarios.

Input: {"n_qubits":4,"layers":[[[0,1],[2,3]],[[0,2],[1,3]]]}
Optional hardware has storage coordinates, paired entangling coordinates, and
AOD rows/cols. Layout preparation and continuous physical validation are outside
this command; it never submits a layout to the production environment.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import torch
from neutral_atom_strategies.placement_rl.model import Circuit, Hardware, CompilerConfig, standard_hardware
from neutral_atom_strategies.placement_rl.policy import PlacementPolicy, ScenarioAdversary
from neutral_atom_strategies.placement_rl.game import Evaluator, default_scenarios, interaction_layout
from neutral_atom_strategies.placement_rl.compiler import audit_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output exists; use a fresh file')
    torch.set_num_threads(1)
    checkpoint = torch.load(args.checkpoint, map_location='cpu', weights_only=True)
    if checkpoint.get('schema') != 'placement-rl/1':
        raise ValueError('Unsupported checkpoint schema')
    raw = json.loads(args.input.read_text(encoding='utf-8'))
    unknown = set(raw) - {'n_qubits', 'layers', 'hardware'}
    if unknown:
        raise ValueError(f'Unknown input fields {unknown}; unsupported gates are never silently dropped')
    circuit = Circuit(raw['n_qubits'], raw['layers'])
    hardware = Hardware(**raw['hardware']) if 'hardware' in raw else standard_hardware(
        circuit.n_qubits, checkpoint['config']['vacancies'])
    evaluator = Evaluator(circuit, hardware, config=CompilerConfig(**checkpoint['config']['compiler']))
    actor = PlacementPolicy(checkpoint['hidden'])
    actor.load_state_dict(checkpoint['actor'])
    adversary = ScenarioAdversary(len(default_scenarios()), checkpoint['hidden'])
    adversary.load_state_dict(checkpoint['adversary'])
    start = perf_counter()
    with torch.no_grad():
        mapping, _, _ = actor.sample(circuit, hardware, greedy=True)
        probabilities = adversary.distribution(circuit, hardware, mapping).probs.tolist()
    inference = perf_counter()-start
    reference = interaction_layout(circuit, hardware)
    losses = evaluator.losses(mapping, reference).tolist()
    results = []
    for i, scenario in enumerate(evaluator.scenarios):
        result = evaluator.result(mapping, i)
        results.append(dict(scenario=asdict(scenario), result=asdict(result),
                           audit=audit_result(circuit, hardware, mapping, result, scenario, evaluator.config)))
    output = dict(schema='placement-rl-inference/1', scope='discrete_model_only',
        circuit=asdict(circuit), hardware=asdict(hardware), compiler=asdict(evaluator.config),
        selected_training_step=checkpoint['selected_step'], mapping=list(mapping),
        coordinates=[hardware.storage[i] for i in mapping], inference_seconds=inference,
        reference_mapping=list(reference), scenario_losses=losses, worst_bounded_regret=max(losses),
        adversary_probabilities=probabilities, scenarios=results, physical_validation='not_run')
    output['adversary_step'] = checkpoint.get('adversary_step', checkpoint['config']['updates'])
    output['adversary_role'] = 'final opponent diagnostic; actor selected independently on validation'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(mapping=mapping, statuses=[r['result']['status'] for r in results],
                         model_only=True, output=str(args.output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
