"""Optional Stim bridge for native Clifford circuits and explicit sidecars."""
from dataclasses import dataclass
from math import sqrt
from .noise import PauliNoise, exposure_report


def _dependency(name):
    import importlib
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise RuntimeError(f'Optional dependency {name} is required; install in an isolated environment') from exc


@dataclass(frozen=True)
class StimExport:
    circuit: object
    atom_indices: tuple
    measurement_indices: tuple
    detector_ids: tuple
    observable_ids: tuple
    exposure_metadata: dict


def export_stim(compiled, noise=None, exposures=()):
    """Export supplied native gates, never abstract MPP or free measurements.

    Conditions support one reported measurement bit. General AND feedback is
    non-Clifford classical control and fails closed. Circuit order must already
    be topological. Exposures must be explicitly anchored after native gates.
    """
    stim = _dependency('stim')
    noise = noise or PauliNoise('ideal reference, explicitly zero noise')
    exposures = tuple(exposures)
    report = exposure_report(exposures, noise)
    atoms = tuple(dict.fromkeys(q for g in compiled.circuit.gates for q in g.qubit_ids))
    index = {q: i for i, q in enumerate(atoms)}
    circuit = stim.Circuit()
    measurements, seen = {}, set()
    anchors = {}
    for e in exposures:
        if e.atom_id not in index:
            raise ValueError('Exposure atom is absent from circuit')
        anchors.setdefault(e.after_gate_id, []).append(e)
    for gate in compiled.circuit.gates:
        if not set(gate.depends_on) <= seen:
            raise ValueError('Native gate order is not topological')
        targets = [index[q] for q in gate.qubit_ids]
        if gate.condition:
            if noise.one_qubit:
                raise ValueError('Branch-conditioned gate noise is unsupported; skipped gates have no pulse')
            if len(gate.condition) != 1 or gate.gate_type not in {'X', 'Z'}:
                raise ValueError('Stim bridge supports only single-bit X/Z feedback')
            key, expected = gate.condition[0]
            if key not in measurements:
                raise ValueError('Feedback measurement is not earlier')
            if expected == 0:
                circuit.append(gate.gate_type, targets)
            circuit.append('CX' if gate.gate_type == 'X' else 'CZ',
                           [stim.target_rec(measurements[key] - circuit.num_measurements), *targets])
        elif gate.gate_type == 'MEASURE':
            measurements[gate.id] = circuit.num_measurements
            circuit.append('M', targets, noise.readout)
        elif gate.gate_type == 'RESET':
            circuit.append('R', targets)
            if noise.reset:
                circuit.append('X_ERROR', targets, noise.reset)
        elif gate.gate_type in {'H', 'X', 'Y', 'Z', 'S', 'S_DAG', 'CZ', 'CX'}:
            circuit.append(gate.gate_type, targets)
        else:
            raise ValueError(f'Unsupported native operation {gate.gate_type}; no T/non-Pauli approximation')
        if gate.gate_type not in {'MEASURE', 'RESET'}:
            p = noise.two_qubit if len(targets) == 2 else noise.one_qubit
            if p:
                circuit.append('DEPOLARIZE2' if len(targets) == 2 else 'DEPOLARIZE1', targets, p)
        for e in anchors.pop(gate.id, ()):
            channel = noise.timed_channel(e)
            for name, p in [('Z_ERROR', channel['z_error']), ('DEPOLARIZE1', channel['depolarize1'])]:
                if p:
                    circuit.append(name, [index[e.atom_id]], p)
        seen.add(gate.id)
    if anchors:
        raise ValueError('Exposure anchor is absent from circuit')
    semantic = {m.result_id: (measurements[m.raw_gate_id], m.bit_flip) for m in compiled.measurements}
    def expression_targets(expr):
        terms = [semantic[key] for key in expr.terms]
        flip = expr.constant
        for _, bit in terms:
            flip ^= bit
        if flip:
            circuit.append('MPAD', [1])
            terms.append((circuit.num_measurements - 1, 0))
        return [stim.target_rec(i - circuit.num_measurements) for i, _ in terms]
    for detector in compiled.program.detectors:
        circuit.append('DETECTOR', expression_targets(detector.expression))
    for i, observable in enumerate(compiled.program.observables):
        circuit.append('OBSERVABLE_INCLUDE', expression_targets(observable.expression), i)
    return StimExport(circuit, tuple(index.items()), tuple(measurements.items()),
                      tuple(d.id for d in compiled.program.detectors),
                      tuple(o.id for o in compiled.program.observables), report)


def sample_matching(circuit, *, shots, seed):
    """Graphlike DEM/MWPM baseline; errors fail instead of dropping mechanisms.

    Counts any observable mismatch. This is a decoder-specific memory failure
    probability, not overall quantum-state fidelity or Shor success probability.
    """
    if type(shots) is not int or shots <= 0 or type(seed) is not int or seed < 0:
        raise ValueError('Positive shot count and nonnegative integer seed required')
    matching_module = _dependency('pymatching')
    dem = circuit.detector_error_model(decompose_errors=True)
    matching = matching_module.Matching.from_detector_error_model(dem)
    detections, actual = circuit.compile_detector_sampler(seed=seed).sample(shots, separate_observables=True)
    predicted = matching.decode_batch(detections)
    failures = int((predicted != actual).any(axis=1).sum())
    p = failures / shots
    z = 1.959963984540054
    denominator = 1 + z*z/shots
    center = (p + z*z/(2*shots))/denominator
    radius = z*sqrt(p*(1-p)/shots + z*z/(4*shots*shots))/denominator
    return {'schema': 'qec-memory-monte-carlo/1', 'shots': shots, 'seed': seed,
            'failures': failures, 'logical_failure_probability': p,
            'wilson_95': [0.0 if failures == 0 else max(0, center-radius),
                          1.0 if failures == shots else min(1, center+radius)],
            'decoder': 'PyMatching graphlike decomposed DEM baseline',
            'stim_version': _dependency('stim').__version__,
            'pymatching_version': matching_module.__version__,
            'claim': 'observable mismatch under declared Pauli model; not total fidelity'}
