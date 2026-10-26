# Distance-aware raw-T detector acceptance

Status: Accepted for the user's requested distance-dependent raw-T acceptance fix.

## Context

Odd-distance components already generated raw preparation and repeated-SE
detectors, but only the d3 package produced noisy acceptance probabilities.
The new distances could not supply a source-grounded acceptance port. Reusing a
d3 probability or assuming acceptance one under noise would invalidate rejection
and retry resource estimates. The agreed MSD geometry and timing must stay fixed.

## Decision

Produce binary accepted/rejected probabilities from the actual compiled raw-T
plus repeated-SE sequence. Admit its distance-specific source, roles, measurement
identities, acceptance predicates and semantic physical trace. Keep every world
atom and the real inter-round idle intervals and result-ready tail. Resolve the
explicit `noise/v1` profile once and map its mutually exclusive Pauli/readout
alternatives to complete detector-flip signatures.

Share the detector-observable backpropagation engine with the legacy d3 adapter.
The actual seed T gate remains in the admitted circuit. Every detector must
propagate to identity on that seed at its T checkpoint; otherwise reject the
model. This proves acceptance statistics within the selected independent Pauli
model without approximating an arbitrary quantum output by a Clifford state.

Use exact XOR convolution through 20 detectors, otherwise
sample independent channels while preserving exclusive alternatives and fault
cancellation. Sampling uses an explicit seed, batch size and shot budget, supports
signatures wider than 64 bits, and reports a Wilson 95% interval. Ideal acceptance
one at every distance is verified for an explicitly zero-noise calculation. An
empty set of effective detector-flip channels is evaluated as exact probability
one without allocating an exponential table, even at large distance; this says
nothing about faults invisible to the acceptance detectors.

Preserve source, device, world, duration, distance, rounds, noise and estimator
fingerprints. A portable `nadit.event_probability/1` port carries the two detector
outcomes. Consumers may use it for an acceptance/retry decision only within its
recorded scope; they must not reuse an entry after layout, timing or noise changes.

## Alternatives

- Copying the d3 scalar or fitting a multiplier in d ignores actual check counts,
  circuit fault propagation and physical exposure.
- Dense convolution over every detector needs exponential memory (32 and 68
  detectors at d5 and d7 with one extra SE), beyond a practical general API.
- Full noisy state simulation is unnecessary for these detector events and would
  not scale to the requested distances. It remains a distinct possible quality
  backend rather than a claim made by this producer.

## Consequences and boundaries

The first deterministic check count comes from the actual product seed and check
intersection, not a guessed polynomial. Independent readout-only controls verify
the probability using those counts. Tests also compare d3 with its legacy exact
implementation and preserve strict source/noise admission.

Physical loss, leakage and coherent non-Pauli errors are outside this acceptance
model and are stated explicitly; physical loss metrics remain separately visible.
No logical error probability, accepted-state fidelity, factory throughput or
hardware execution is inferred. The external fast factory currently consumes a
d3-only joint acceptance/preparation-class table. This generic binary port does
not implement the missing class distribution, correction execution or larger-d
factory adapter. Those must be supplied before generic factory yield is claimed.
