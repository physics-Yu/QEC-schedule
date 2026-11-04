# ADR 0042: Code-owned event probabilities and compiler-owned case expansion

Status: Accepted for the first coarse-event backend, 2026-10-23.

## Context

Protocol outcomes can require another raw-T preparation or an S correction after
T consumption. The current task needs these events to drive compilation without
implementing syndrome sampling, a decoder or global frame propagation.

## Decision

Use the shared [event probability v1 contract](../../modules/codes/contracts/event_probability_v1.md).
Codes calculate finite joint outcome distributions and declare local branch
steps, with explicit assumptions and complete model fingerprints. The logical
compiler binds occurrences, samples once per identity, waits for result and
exit dependencies, and expands the selected continuation or bounded retry.
Compilation progresses dynamically; a completed result is one static case.

Surface d3 supplies raw-T repeated-SE acceptance and the specified logical
T-consumption measurement branches. The latter does not include factory
distillation acceptance or establish a physical T-consumption component.
The detailed syndrome/decoder backend remains an explicit unsupported capability.

## Alternatives and consequences

Putting surface probability calculations in the logical compiler would duplicate
code-specific protocol knowledge. Putting sampling and retries in components
would mix reusable definitions with invocation state. Both are avoided by the
portable immutable probability document and separate occurrence records.

The first consumer emits abstract static cases. Physical binding, scheduling and
validation remain required before any such case can be called an AtomProgram.
Coarse raw-T acceptance leaves random bulk signs and frame relations unresolved.
Nonideal probabilities require explicit noise inputs; the initial Pauli/readout
estimate reports loss separately and does not certify logical-state fidelity.
