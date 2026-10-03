"""Reproducible JSON experiments for the component viewer, without UI or hardware mutation."""
from math import exp
from .canonical import canonical_memory_program
from .lowering import lower_to_physical
from .noise import Exposure, PauliNoise
from .stim_bridge import export_stim, sample_matching, _dependency


def _shot_examples(compiled, exported, seed, count=4096):
    """Raw measurements and decoder input come from exactly the same shots."""
    matching_module = _dependency('pymatching')
    circuit = exported.circuit
    raw = circuit.compile_sampler(seed=seed).sample(count)
    detections, actual = circuit.compile_m2d_converter().convert(
        measurements=raw, separate_observables=True)
    matcher = matching_module.Matching.from_detector_error_model(
        circuit.detector_error_model(decompose_errors=True))
    predicted = matcher.decode_batch(detections)
    correct = (predicted == actual).all(axis=1)
    active = detections.any(axis=1)
    examples = {}
    for name, selector in [('detected_and_decoded', active & correct),
                           ('logical_failure', ~correct)]:
        rows = selector.nonzero()[0]
        if not len(rows):
            examples[name] = {'found': False, 'searched_shots': count}
            continue
        row = int(rows[0])
        native = {gid: int(raw[row, offset]) for gid, offset in exported.measurement_indices}
        semantic = compiled.semantic_results(native)
        examples[name] = {
            'found': True, 'shot_index': row, 'sample_seed': seed,
            'raw_measurements': native, 'semantic_measurements': semantic,
            'semantic_outputs': compiled.classical_outputs(native),
            'detector_flips': {key: int(detections[row, i]) for i, key in enumerate(exported.detector_ids)},
            'active_detector_ids': [key for i, key in enumerate(exported.detector_ids) if detections[row, i]],
            'actual_observable_flips': actual[row].astype(int).tolist(),
            'predicted_observable_flips': predicted[row].astype(int).tolist(),
            'logical_failure': not bool(correct[row]),
            'meaning': 'Decoder estimates logical observable flip; detection alone does not imply failure',
            'shot_provenance': 'One raw sampler row converted by compile_m2d_converter; no independent sampler mixing',
        }
    return {'searched_shots': count, 'seed': seed, 'examples': examples,
            'detector_ids': list(exported.detector_ids), 'observable_ids': list(exported.observable_ids),
            'detector_convention': 'Flips relative to noiseless Stim reference; semantic_outputs are absolute XORs'}


def noise_experiment_data(*, shots=20000, seed=17):
    """Synthetic per-native-gate sweep; not a fit or neutral-atom fidelity claim.

    shots is per curve point, not a total budget. All 30 points use declared
    independent Pauli event probabilities; the hardware schedule is not used.
    """
    if type(shots) is not int or shots <= 0 or type(seed) is not int or seed < 0:
        raise ValueError('Positive shots and nonnegative integer seed required')
    probabilities = [0, 0.001, 0.003, 0.005, 0.01]
    curves, examples, native_counts = [], {}, {}
    for basis_index, basis in enumerate(('X', 'Z')):
        compiled = lower_to_physical(canonical_memory_program(basis=basis, rounds=3).program)
        counts = {}
        for gate in compiled.circuit.gates:
            counts[gate.gate_type] = counts.get(gate.gate_type, 0) + 1
        native_counts[basis] = counts
        for scenario_index, scenario in enumerate(('gate_only', 'readout_only', 'both')):
            points = []
            for point_index, p in enumerate(probabilities):
                profile = PauliNoise('synthetic viewer experiment; no experimental calibration',
                                     one_qubit=p if scenario != 'readout_only' else 0,
                                     two_qubit=p if scenario != 'readout_only' else 0,
                                     readout=p if scenario != 'gate_only' else 0)
                exported = export_stim(compiled, profile)
                point_seed = seed + basis_index*1000 + scenario_index*100 + point_index
                stats = sample_matching(exported.circuit, shots=shots, seed=point_seed)
                points.append({'event_probability': p, 'parameters': profile.to_dict(), **stats})
                if scenario == 'both' and p == 0.01:
                    examples[basis] = _shot_examples(compiled, exported, seed + 2000 + basis_index)
            curves.append({'basis': basis, 'scenario': scenario, 'points': points})
    tphi = 1e6
    move_rate = 1e-7
    times = [0, 1e3, 1e4, 1e5, 5e5, 1e6]
    profile = PauliNoise('synthetic dephasing/transport illustration, not measured T1/T2',
                         tphi_us=tphi, move_depolarizing_rate_per_us=move_rate)
    time_points = []
    for t in times:
        idle = profile.timed_channel(Exposure('illustration', 0, t, 'idle', 'illustration'))
        move = profile.timed_channel(Exposure('illustration', 0, t, 'move', 'illustration'))
        time_points.append({'duration_us': t, 'p_z': idle['z_error'],
                            'ramsey_contrast': exp(-t/tphi),
                            'move_depolarizing_probability': move['depolarize1']})
    return {'schema': 'qec-visual-noise-experiments/1', 'distance': 3, 'rounds': 3,
            'shots_per_point': shots, 'seed': seed, 'curves': curves, 'shot_examples': examples,
            'native_gate_counts': native_counts,
            'dephasing': {'parameters': profile.to_dict(), 'points': time_points,
                          'meaning': 'Unencoded single-qubit pure dephasing illustration; not encoded lifetime'},
            'claim': 'Seeded native H/CZ Clifford memory Monte Carlo with MWPM observable mismatch; not total fidelity',
            'limits': ['No executed hardware timing or automatic exposure extraction',
                       'Synthetic independent Pauli event probabilities, not calibrated gate infidelities',
                       'No loss, leakage, amplitude damping, coherent drift or magic-state factory simulation',
                       'MWPM decomposed DEM baseline does not establish correlated decoding optimality'],
            'versions': {'stim': _dependency('stim').__version__,
                         'pymatching': _dependency('pymatching').__version__}}
