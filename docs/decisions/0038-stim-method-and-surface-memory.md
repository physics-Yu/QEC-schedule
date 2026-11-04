# ADR 0038: Atom-action Stim method and surface memory

Status: Accepted (2026-10-23, scope confirmed by the user).

## Contract

`stim/v1` is a post-compilation NADiT method, not a physical compiler or cost
model. It reads a validated `nadit.result/2`, explicitly invokes `noise/v1`
with supplied parameters, and returns a Stim circuit and an audit report.
It never recompiles the input or samples the FakeBackend. The method is
discoverable through `nadit describe` and callable from Python and the CLI.

Atom identities map to fixed Stim wires regardless of trap ownership or motion.
Native Clifford rotations/U, illuminated CZ pairs, reset and measurement become
ideal Stim operations. Non-Clifford operations are rejected. LOAD/MOVE/STORE and
WAIT have no ideal quantum operation; their configured Pauli channels and exposure
are retained. TICK represents an AtomStep boundary, not elapsed physical time.
Physical durations remain in the report and determine noise through AtomActivity.
The existing transport model gains zero-default `load_pauli` and `store_pauli`
alongside `move_pauli`; transfer loss remains a separate effect.

Gate channels retain their explicit before/after placement. Readout error becomes
the measurement argument. Idle/transport dephasing is inserted at its interval
end, before the next action on that atom. Actions in a step use their own durations.
Measurement identity is mapped to its actual Stim record index, never the compiler's
fake value. Detector and observable parities are supplied by the workload and
translated through that identity map after all measurements are emitted.

A compiled conditional branch is not a dynamic circuit. Default export rejects
conditional DAGs; an explicit fixed-case export records this limitation and cannot
be used by the memory sampler. No missing branch is reconstructed or silently
controlled by new noisy measurements.

Physical loss, computational leakage and upstream diagnostics remain in the report.
They are not converted to unheralded Pauli noise or HERALDED_ERASE. Memory estimates
cover the Pauli/readout model only, not a loss-aware logical error rate.

## Memory workload and execution

Provide a reusable benchmark workload for one rotated surface-code block at
d=3,5,7,9 with rounds=d by default and X/Z memory bases. Use Stim's noiseless
standard construction for circuit structure, hook ordering, coordinates,
detectors and final logical readout. Export QASM and a measurement-identity
annotation document bound to its source hash. This benchmark does not implement
the separate code-library/component contracts or logical compiler.

Generate explicit standard-coordinate homes and jobs for existing `nonzoned`
(ENOLA-inspired transport) and `search_smarter` QEC return modes. Architecture
and strategy remain ordinary editable job configuration. No ENOLA SA or new
placement optimizer is introduced. Device parameters are benchmark defaults,
not calibrated hardware claims.

Sampling uses Stim detector samples and PyMatching MWPM predictions. Record shots,
seed, failures, a binomial interval, circuit/noise identities and package versions.
DEM conversion explicitly records any disjoint-channel approximation. Do not
discard undecomposable faults. A memory run consumes the exported circuit without
calling the compiler or cost model again.

## Delivery and verification

1. Add an optional pinned simulation extra and method discovery/CLI.
2. Implement event ordering, Clifford conversion and measurement annotations.
3. Implement workload preparation and decoded memory sampling.
4. Test exact channels, differing action durations, loss separation, measurement
   reordering, source/result binding, conditional/non-Clifford rejection and
   noiseless detectors. Check small compiled cases with both physical backends,
   final-state replay and semantic validation. Generate d=3,5,7,9 workloads.
5. Leave the full distance/shots experiment campaign for subsequent work.

Baseline on the current checkout: 1,759 physical-compiler tests passed.

Final verification: 1,807 tests passed (1,759 core, 31 simulation, 17 optional
hsim); Ruff and strict mypy passed on source/tests/examples. Both physical
backends pass compiled d3 X/Z noiseless parity and memory tests, with d3 Z
minimum graphlike fault length verified as three. Generated d3/d5/d7/d9 inputs
load successfully. An installed wheel completed the two d3 Z-memory CLI chains
outside the checkout, including 512-shot decoded sampling. No formal scan ran.

References: [Stim gates](https://github.com/quantumlib/Stim/blob/main/doc/gates.md),
[PyMatching Stim decoding](https://pymatching.readthedocs.io/en/stable/#decoding-stim-circuits).
