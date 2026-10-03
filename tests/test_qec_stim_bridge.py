import pytest
stim = pytest.importorskip('stim')
from neutral_atom_experiments.qec_pbc.ir import Role, GateTask, BitExpr, Detector, Observable, PBCProgram
from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical
from neutral_atom_experiments.qec_pbc.noise import PauliNoise, Exposure
from neutral_atom_experiments.qec_pbc.stim_bridge import export_stim, sample_matching


def test_signed_result_constant_and_conditional_correction():
    program = PBCProgram((Role('q', 'data'),), (
        GateTask('r', 'RESET', ('q',)), GateTask('x', 'X', ('q',)),
        GateTask('m', 'MEASURE', ('q',)),
        GateTask('fix', 'X', ('q',), condition=(('m', 1),)),
        GateTask('out', 'MEASURE', ('q',))),
        (Detector('known', BitExpr(('m',), 1), 'test'),),
        (Observable('zero', BitExpr(('out',)), 'corrected bit'),))
    exported = export_stim(lower_to_physical(program))
    det, obs = exported.circuit.compile_detector_sampler(seed=4).sample(100, separate_observables=True)
    assert not det.any() and not obs.any()
    assert exported.detector_ids == ('known',)
    assert 'CX rec[' in str(exported.circuit)
    assert len(exported.measurement_indices) == 2
    assert exported.circuit.num_measurements == 3  # one classical MPAD, not hardware M
    raw = exported.circuit.compile_sampler(seed=4).sample(20)
    assert raw[:, 0].all() and not raw[:, 1].any() and raw[:, 2].all()
    with pytest.raises(ValueError, match='Branch-conditioned'):
        export_stim(lower_to_physical(program), PauliNoise('synthetic', one_qubit=0.01))


def test_native_readout_noise_and_timed_exposure():
    program = PBCProgram((Role('q', 'data'),), (GateTask('r', 'RESET', ('q',)), GateTask('m', 'MEASURE', ('q',))),
                         observables=(Observable('out', BitExpr(('m',)), 'bit'),))
    exported = export_stim(lower_to_physical(program), PauliNoise('synthetic', readout=1),
                          [Exposure('Q000', 0, 100, 'idle', 'r__g000')])
    _, obs = exported.circuit.compile_detector_sampler(seed=0).sample(20, separate_observables=True)
    assert obs.all()
    assert exported.exposure_metadata['exposures'][0]['end_us'] == 100


def test_matching_official_memory_reference_reproducible():
    pytest.importorskip('pymatching')
    circuit = stim.Circuit.generated('surface_code:rotated_memory_z', distance=3, rounds=3,
                                     after_clifford_depolarization=0.005,
                                     before_measure_flip_probability=0.005)
    a = sample_matching(circuit, shots=2000, seed=17)
    b = sample_matching(circuit, shots=2000, seed=17)
    assert a == b
    assert 0 < a['failures'] < 2000
    assert a['wilson_95'][0] <= a['logical_failure_probability'] <= a['wilson_95'][1]
