"""Synthetic reference Monte Carlo; not an executed neutral-atom benchmark."""
import argparse
import json
from pathlib import Path
from neutral_atom_experiments.qec_pbc.noise import PauliNoise
from neutral_atom_experiments.qec_pbc.stim_bridge import sample_matching


def main():
    import stim
    parser = argparse.ArgumentParser()
    parser.add_argument('--shots', type=int, default=20000)
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    profile = PauliNoise('synthetic demonstration, not measured hardware calibration',
                         one_qubit=0.005, two_qubit=0.005, readout=0.005)
    results = {}
    for basis in ('x', 'z'):
        circuit = stim.Circuit.generated(f'surface_code:rotated_memory_{basis}', distance=3, rounds=3,
                                         after_clifford_depolarization=profile.one_qubit,
                                         before_measure_flip_probability=profile.readout)
        results[basis] = sample_matching(circuit, shots=args.shots, seed=args.seed)
    report = {'parameters': profile.to_dict(), 'distance': 3, 'rounds': 3,
              'source': 'Stim official generated memory, no neutral-atom timing', 'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
