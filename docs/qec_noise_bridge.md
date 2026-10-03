# Pauli noise and Stim bridge

This opt-in upstream module changes no hardware defaults or live environment state.
`noise.PauliNoise` requires a parameter source. Gate depolarizing probabilities
are event probabilities, not measured average gate infidelity. Gate parameters
cover the whole gate interval. `Exposure` covers disjoint idle/move intervals in
microseconds; `exposure_report` rejects overlap. Pure dephasing has
`pZ=(1-exp(-dt/Tphi))/2`. Tphi is not interchangeable with T2 when relaxation exists.
Move depolarization uses an explicit inverse-microsecond rate. No hardware values
are supplied by default. The caller must extract/partition the actual timeline
and anchor each exposure after its native circuit location; automatic ingestion
of transport traces is not yet implemented.

`stim_bridge.export_stim(compiled, noise, exposures)` expands only supplied native
Clifford gates and preserves raw measurement indexing, semantic sign flips,
detector IDs and observable IDs. Single-bit reported-measurement X/Z feedback is
supported only with zero gate noise; noisy conditional pulses require a
branch-conditioned sampler and fail closed. Multi-bit AND control, T/non-Pauli
gates and loss fail closed. Stim
DETECTOR and OBSERVABLE_INCLUDE annotations are bookkeeping, not extra physical
measurements. MPAD handles classical parity constants.

`sample_matching(circuit, shots=..., seed=...)` samples detections and observable
flips using seeded Stim, decodes a decomposed graphlike DEM with PyMatching, and
reports logical observable mismatch with Wilson 95% confidence intervals and
dependency versions. DEM generation/decomposition errors are not suppressed.
Stim detector sampling reports flips relative to its noiseless reference sample;
it is not the raw semantic measurement/output dictionary. Use the measurement
sidecar with a raw sampler to inspect absolute reported bits and signed parities.
The decoder baseline can lose correlations; cross-patch correlated decoding is
not implemented. X/Z memory results are not a full quantum-channel fidelity.

Optional dependencies live in `.venv-qec-noise-modern` (Python 3.12), not project
dependencies: Stim 1.15.0, Sinter 1.15.0, PyMatching 2.3.1. Example:

```powershell
$env:PYTHONPATH='src'
& .\.venv-qec-noise-modern\Scripts\python.exe examples/run_qec_noise_reference.py --shots 20000 --seed 17 --output artifacts/qec-noise-reference-2026-10-02/report.json
```

This reference uses the official Stim d=3, three-round memory generator and
synthetic 0.005 gate/readout probabilities. It has no transport timeline and is
not a neutral-atom fidelity benchmark. Official API references:
[Stim](https://github.com/quantumlib/Stim/blob/v1.15.0/doc/python_api_reference.md),
[PyMatching](https://pymatching.readthedocs.io/en/stable/).
Loss requires lifecycle-conditioned circuit rewriting and only observable loss
information for the decoder; `require_loss_decoder` explicitly rejects requests.
Amplitude damping, coherent drift, leakage, magic-state factories, Shor success
and Sinter batch orchestration remain future extensions.

Validation on 2026-10-02: five tests passed using the isolated modern environment.
With 20,000 shots per basis, seed 17, the official reference produced X 184/20000
and Z 165/20000 failures. A read-only integration with task A's canonical native
H/CZ memory produced X 869/20000 and Z 605/20000 using 0.005 per native gate and
readout. These are different noise locations/circuit decompositions, not a
hardware performance comparison. Integration report:
`artifacts/qec-noise-reference-2026-10-02/native-canonical-report.json`.
