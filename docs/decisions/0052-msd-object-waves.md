# Homogeneous component-object waves for MSD estimates

Status: approved design; first local acceptance milestone implemented.

## Batching correction and authorized server rerun, 2026-10-25

The user authorized correcting final-MX submission and conservative geometry
grouping, then rerunning the unchanged d3, N=1/2, seeds=0/1 configuration on the
server after bounded local checks. This authorization applies to this new run;
it does not resume or modify earlier server jobs.

Independent, homogeneous final measurements declared as `object_wave` use the
existing finite child-flow join. Their original invocation IDs and joint event
identities remain unchanged, and feedback waits for all four receipts. Other
execution paths and dependent final calls retain the existing sequence.

Shared commands require identical signed relative participant geometry,
nonoverlapping whole-call storage/gate claims, and aligned or separated home
bands on each axis for every participant. The existing d3 60 um home extent
with 2 um margins gives a 64 um band. This admits rectangular and staggered
compatible arrays without the former all-same-x or all-same-y restriction.
Readout uses a common sufficient translation. Different signed CNOT
displacements, partially overlapping bands and conflicting claims do not gain
automatic shared execution. This is an object-cost applicability contract,
not a physical trajectory or collision certificate.

The raw probability input, recipe, timing/noise parameters and seed scheme
remain unchanged. Source/model hashes, full per-case event outcomes, forbidden
compiler/atom counters and server software runtime accompany the rerun.

## Approved clarification: precomputed fake backend, 2026-10-25

The user's latest clarification supersedes the earlier proposal below to adapt
detector signatures to each schedule. Preparation is a costed protocol operation
with its **existing calculated probability**, sampled by the fake backend.
There is no new physical compilation, offline calibration, atom expansion or
probability estimation in this continuation. A changed schedule changes resource
cost and output timing, not the selected raw acceptance parameter.

The full d3 recipe now uses portable numeric stage records from the already
existing d3-n1 profile, normalized into ten semantic objects. It reuses the
existing factory process, probability ports, event journal and object-wave kernel.
The original one-Pauli-layer correction cost envelope is explicit; no decoder
frame distribution is invented. Congruent horizontal or vertical groups share
commands; readout movement uses a common translation sufficient for all members.
Different groups compete for one AOD and different component waves remain serial.

Missing d5/d7 full component inputs remain errors. At d3, accepted-only expansion
has zero rounds, as declared by the existing protocol. The new acceptance report
is [here](../experiments/msd-object-factory-d3-20261025.md). Earlier paragraphs
describe the initial milestone and are retained as design history.

## Context

The task starts at `852fd731196673ed07fcac46c4ae172dab31ebb5`, using committed
`85f5479da14c842228a1274e9eff7ee11535adcd` only as a source for necessary later
components and conventions. The starting commit lacks the generic surface
components, continuous production and test-tier workflow. Its existing raw-T
probability import also references an absent Clifford helper, and its noise
normalization test expects missing Load/Store Pauli fields.

The user clarified that different components must execute serially; only
instances of the same component may run together. An asynchronous heterogeneous
execution runtime is therefore unnecessary. Exact-frontier physical compilation
and the previous campaign/server machinery are not part of this design.

## Decision

Reuse `ComponentCall`, `ComponentCostProfile`, `ComponentScheduler`,
`ProfileExecutionKernel`, `FactoryProcess`, `EventJournal` and `ResourceLedger`.
Add a declared `object_wave` mode and typed `ComponentPhase` records. A profile
instantiates a finite list of stage costs for the requested logical carriers.
The existing execution kernel schedules those stages and emits its existing
component receipts. Whole waves remain sequential and retain fixed membership.

Inside one homogeneous wave, stages may overlap only on disjoint resources.
Identical stage records with a nonempty code-owned batch certificate can describe
one shared command. A shared lease requires identical subsequent stage records;
matching Load operations alone cannot merge incompatible continuations.
Persistent AOD leases run from Load through Store, including the entire readout
hold. An object declaration is explicitly rejected by the physical execution
kernel and does not establish an atom-level schedule.

The first real object catalog is intentionally limited to logical MZ readout.
It uses the committed surface geometry and an explicit rigid vertical movement
model: compatible bands share a translation sufficient to put every measured row
above y=50 um, then return home. Same columns with disjoint rows, or same rows
with disjoint columns, are the admitted cases. Other requests serialize on the
same AOD. This conservative model is not a physical route/collision proof.

The generic surface recipe and staged preparation sources are migrated without
position-calibrated profiles. They retain actual S-SE, three d3 injection rounds,
and accepted-only target growth with 0/5/7 rounds at target d=3/5/7. Growth uses
ordinary decoding and has no rejection port. The first milestone does not yet
supply object costs for the complete factory or a schedule-dependent raw
acceptance model. Missing component coverage is an error, never a compile or
ideal-probability fallback.

Factory processes may use separate cohorts so an unrelated preparation retry
does not introduce an all-factory barrier. A common scheduler still arbitrates
all their work. Continuous production uses the migrated explicit ideal external
sink and keeps next-cycle preparations and resets. Preparation parameters are
forwarded on every attempt. Empty optional preparation parameters retain the
old serialized recipe shape, preserving existing deterministic golden tests.

## Scope and evidence

The local acceptance suite includes a synchronous readout, an incompatible
readout-resource case, and scripted postselection/retry/production control.
The latter is visibly a test fixture, not an MSD fidelity or timing model.
Readout-only d/N scaling is also not factory throughput or steady-state evidence.
No theoretical output error is reported as a decoded logical error rate.

The run prepares finite catalogs once, changes N, seeds, retries and combinations,
and checks object identity preservation. Instrumented guards abort on physical
compilation, atom binding/expansion or atom construction. A worker wall deadline
terminates the process and writes `error.json` with the last stage and reason;
no subsequent case is attempted. Per-wave and runtime deadlines also raise
errors without returning successful partial schedules.

## Validation policy for this task

The user's task-specific instruction supersedes this base's full-suite rule and
the reference branch's pre-commit all-fast-plus-slow requirement. Run related
fast tests and necessary bounded small controls only, with no bench, server
tasks or blanket repository checks. This exception does not redefine other
tasks' test policy. The imported test map retains only present tests and valid
overrides; two old report/configuration unit-test files are preserved as fast.

The simulation optional extra is copied from the committed reference; the
existing Python 3.12 environment already provides its pinned packages. No
package installation, dependency upgrade or server action is required here.

## Remaining first-level work

Prepare the remaining code-owned component phase profiles, including actual
S-SE and accepted-only growth/correction costs, then adapt detector signatures to
the newly scheduled exposures. Only after those contracts and small reference
checks pass should complete factory d/N production, noise exposure and throughput
experiments run. Two-level supply, mixed target distances, server orchestration
and physical animation remain separate later work.
