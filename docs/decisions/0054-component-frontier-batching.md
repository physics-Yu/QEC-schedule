# ADR 0054: Component frontier batching

Status: Accepted for the current implementation stage, 2026-10-24.

Current policy update, 2026-10-24:
[ADR 0055](0055-mandatory-component-batching.md) requires compatible frontier
batching, removes serial-policy comparisons and shares the cooperative runtime
across single factories, arrays and fast execution. The original stage described
below remains historical context.

The independent-AOD restriction and four-AOD default below are superseded by
[ADR 0047](0047-shared-aod-component-waves.md). Other scope boundaries remain.

## Context

Factory preparation used a global previous-call dependency and completed each
patch's retries before starting the next patch. This serialized independent
initial resources and obscured the actual feedback dependencies.

## Decision

Different patches executing the same declared single-patch logical component,
with matching parameters/implementation identity, may form a parallel candidate
group. SE, S, X and Z follow this generic rule. It does not follow from a surface
code algebraic simplification and never exempts a call from constraint checking.

Code publishes participant, space, transport and implementation claims before
binding or atom expansion. The logical compiler owns a component DAG, ready
frontier, stable selection policy and patch/resource admission. Multi-patch
operations do not inherit the single-patch batching rule; the current CNOT path
has explicit participant/space/AOD claims and remains exclusive.

The first physical composer supports synchronous component waves. It consumes
the immutable admission, checks the unchanged world snapshot, allocates separate
result identities and combines matching existing action phases. It does not
pad or split gates to manufacture agreement. The actual complete world, pulses,
transport, timing and DAG undergo physical validation before atomic commitment.

Initial preparations are independent local feedback chains. Rejection appends
only that patch's next attempt. Accepted states remain held. Event and resource
dependencies refer to their declared participants rather than a global last
event. Corrections receive scheduling priority when ready; asynchronous component
starts inside an active wave are not implemented.

Device inventory and role-to-AOD allocation are configuration. Transport claims
must be disjoint in this implementation; local X/Z need no AOD claim. The four-raw
acceptance example uses four AODs in both its serial and parallel runs.

The existing noise experiment remains a proxy. A code-owned adapter checks each
raw's actual actions, times and participant trajectory in the combined program
before using an independent Pauli/readout marginal. Unsupported correlated or
spectator-Pauli models are rejected. Factory cost exclusions use the union of raw
horizons, retaining every original attempt's provenance.

## Alternatives and consequences

Atomic expansion as an admission search was rejected: it puts the scheduling
decision below the requested abstraction and can silently turn an incompatible
declaration into a different schedule. Distinct patch identity alone was also
rejected because shared AOD grids, illumination and spaces can conflict.

Strict waves are a bounded first implementation. Arbitrary asynchronous overlap,
same-AOD grid fusion for SE/S, multi-patch batching, inventory, prefetch and
multi-factory policies remain separate work. Frozen same-device comparisons keep
the case ID, seed and semantic event identity constant; changed costs may change
outcomes, and no logical-success claim is inferred from a proxy sample.
