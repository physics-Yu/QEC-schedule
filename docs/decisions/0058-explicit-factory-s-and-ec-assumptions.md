# Explicit factory S and EC assumptions

Status: implemented; center-distance cost model explicitly selected by the user.

## Context

Single-level MSD scaling needs an independently configurable transversal-S
assumption and a visible error-correction policy. Existing surface S is a
measured fold operation. Replacing it must not silently retain its result
cardinality, embedded SE, timing, noise, or physical calibration identity.

## Decision

The code-owned `TransversalSAssumption` declares a positive duration and an
independent Pauli channel per data atom. Its full hash is carried in every
`assumed_transversal_s` call. The operation has zero classical results and no
AOD demand. It is a cost hypothesis, not a verified surface-code realization.

`AssumedSProfile` overlays that operation on an existing profile. All other
lookups and exact joint-coverage failures remain those of the base provider.
The overlay cannot create calibration data or relabel an old measured-S trace.

`ECPolicy` supports preparation-only operation and explicit rounds after each
completed parity rotation. A round count can be a positive integer or the code
distance. Code builds `RotationRecipe.post_rotation_rounds`; the generic runtime
exposes each round's independent calls through `ParallelFlows`, joins result
availability, and retains the existing cohort barrier. The compiler does not
choose cadence or change the code's gates. Empty declarations preserve existing
execution. The reserved injection carrier is excluded from these rounds.

The candidate experiment uses d rounds on W1 through W5 after uncompute for
each of the eleven rotations. Both injection outcomes receive the same EC
policy; conditional S still completes before uncompute. Existing preparation
and accepted-growth SE remain counted. Added syndromes are unobserved cost
receipts. No noisy decoder, waiting-period maintenance, or logical correction
is inferred by these declarations.

`no_atom_execution()` observes known Python execution entrypoints during a fast
run and rejects compilation, component expansion, native execution/replay and
offline calibration. It covers the current thread; each worker must install
its own guard. It is verification instrumentation, not a security sandbox or
a physical-legality proof.

## Consequences

- S timing/noise and EC cadence have distinct, inspectable identities.
- The existing scheduler, seeded events and resource ledger are reused.
- Supplementary SE result readiness can delay a successor even after atom
  action time would have ended.
- Exact-cache execution needs coverage for new SE and final-MX frontiers.
  Missing records are not replaced by serial execution or old singleton costs.
- The user explicitly selected center-to-target travel estimates for readout
  and CNOT, retaining all intrinsic reference costs. `CenterSurfaceFactoryProfile`
  supplies homogeneous estimation-only batch identities; no physical joint trace
  is fabricated. Readout destinations preserve source row order through a common
  translation into disjoint reserved rows. Raw rejection probabilities remain
  separately labeled archived references, not a new detector simulation.
- The output-quality reference remains separate from cost and syndrome data.

## Alternatives

Embedding EC into the S surrogate would make EC depend on the random correction
branch. Replacing old S durations in place would lose source identity and retain
incorrect measurement dependencies. Both alternatives are rejected.
