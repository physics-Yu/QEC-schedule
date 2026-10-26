# ADR 0040: Protocol-aware case compilation and configurable resources

Status: accepted as a design direction on 2026-10-23. Interfaces and runtime
implementation remain open.

## Context

The logical compiler needs to continue individual compilation cases using
simulated measurement outcomes before a real device backend is available.
Factory production adds protocol acceptance, rejected attempts and retries.
Resource contention can make multiple production lines behave differently from
independent copies of one factory.

## Decision

Use seeded, protocol-aware case sampling and retain one shared timeline,
device state, result table and resource state across component invocations.

Components/protocols define result meaning, known distribution/correlation
constraints and acceptance predicates. General data measurements may also depend
on the quantum state; fake probabilities must be declared as scenario assumptions.
Fair-coin sampling is appropriate for specified
teleportation correction bits, not every measurement or acceptance check.
Separate ideal-protocol cases from explicitly configured rejection stress models.

T consumes a factory-produced resource state through teleportation and the
required feedback. Its correction outcomes are distinct from factory acceptance.

Assign unique measurement occurrences to each invocation and attempt. Record
results once and allow feedback only at their availability time. Retries use new
identities and include protocol-defined cleanup and initialization costs.

Treat one AOD as the first experiment configuration. Keep AOD inventory,
capabilities, binding and availability behind the Device/resource interface.
Do not hardcode one AOD into codes or components. Multiple AODs require explicit
joint legality and shared-resource handling; no multi-AOD support is delivered
by this decision.

Evaluate lines jointly under the selected device model. Rejection need not
restart other lines, and shared AOD use does not imply factory-round lockstep.
Measure accepted/delivered throughput, timing distributions, resource contention
and retry costs under explicitly stated study assumptions.

The [design note](../../modules/logical_compiler/docs/case-driven-compilation.md)
records the detailed boundaries and open questions.

## Alternatives

- Uniform independent bits for every measurement would violate ideal checks and
  correlations and can create artificial rejection rates.
- Reusing template-local IDs across retries would repeat identical seeded outcomes.
- Overlaying separately compiled line schedules would omit shared-device conflicts.
- Hardcoding one AOD would turn a study assumption into an architecture constraint.
- Treating fake acceptance as verified state fidelity would overstate the evidence.

## Consequences

The direction supports reproducible scheduling studies before state-aware or
device-backed measurement is connected. Sampling fidelity and scheduling fidelity
remain separately assessable.

Backend contracts, component execution, shared case state, resource interfaces,
factory protocols, multi-AOD algorithms and study parameters require subsequent
implementation decisions. This change contains documentation only.
