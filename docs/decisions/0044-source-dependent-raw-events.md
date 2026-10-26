# ADR 0044: Source-dependent raw preparation events

Status: Accepted for actual raw Pauli/readout events; full noisy factory and
algorithm quality remains unresolved.

## Context

The logical compiler needs sampled raw rejection to trigger actual reset and
repreparation in a shared factory world. The previous detector estimator had a
seventeen-atom universe and returned acceptance only. The controller also needs
the class selecting the approved local preparation relation.

## Decision

Validate and cost the actual source sequence with every occupied atom retained.
Distinguish seventeen participant roles from the complete Pauli-observable
universe. Under the frozen independent Pauli/readout model, branch isometry and
Pauli covariance prove joint accepted-class mass Pacc/16. Keep source/model hashes,
loss exclusions and the exact segment horizon. The logical compiler continues to
own seeds, retries, resource lifetimes and the static selected case.

Expose source-dependent preparation event and quality hooks. The noisy quality
hook returns unsupported, not an assumed logical-Z error rate. Paired bulk
readout flips can pass acceptance and request a correction into a nonzero
stabilizer sector. Actual correction noise and subsequent storage also remain
outside this estimator. A recovery convention and conditional channel model are
required before using noisy raw quality in a complete factory success model.

Use ordered global AtomStep additions for public component times. Separately
reconstruct private cost-document times when rebasing to zero; never rewrite
public measurement events or relax physical validation tolerances.

## Consequences

Real noisy raw rejection and retry control are supported. Arbitrary coherent or
correlated noise, global frame/decoding, and full noisy algorithm success are not
implied. Unconditional no-fault products remain diagnostics unless a separate
event scope and conditioning rule is defined.

See [the protocol and proof scope](../../modules/codes/rotated_surface_d3/protocols/noisy_raw_preparation.md).
