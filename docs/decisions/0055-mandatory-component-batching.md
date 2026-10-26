# ADR 0055: Mandatory component batching

Status: Implemented, 2026-10-24.

## Context

Logical factory compilation and fast logical experiments already share component
declarations, but still expose serial scheduling and artificial batch-width
controls. The single-factory executor also retains a separate sequential control
path. These choices can suppress legal batching, duplicate protocol behavior and
require maintaining serial comparison work files as part of normal compilation.

The user requires the compiler to batch operations whenever the current logical
frontier and actual device constraints permit them. This is a compiler contract,
not a selectable experiment policy.

## Decision

### One scheduling policy

`ComponentScheduler()` has no `mode` or `max_parallel` argument. Its snapshot
records `{"batching": "maximal_compatible_frontier"}`. Physical and fast entries
do not expose replacement switches that artificially limit component count.

The first ready node anchors a deterministic greedy batch. Every subsequent
ready node joins when the complete group's declarations remain compatible.
The result is inclusion-maximal relative to that anchored ready frontier; it is
not a maximum-cardinality batch or a globally optimal schedule.

Code declarations, participant ownership, patch dependencies, classical-result
availability, resource readiness, spaces, waveform compatibility and aggregate
device capacities continue to constrain admission. The physical execution path
still validates combined atom actions. The fast path uses calibrated claims and
does not acquire a physical-validation claim by sharing the scheduler.

Capacity studies change actual AOD row/column or readout budgets. Necessary
dependencies and finite capacities may produce single-member waves. This does
not reintroduce a serial execution mode.

### One protocol runtime

`FactoryExecutor` adapts a single `FactoryProcess` to
`CooperativeFactoryRuntime`, retaining its single-factory result envelope and
semantic identity namespace. Factory arrays pass several processes to the same
runtime. Fast execution uses a profile execution kernel with the same processes,
frontier scheduler, event journal and resource ledger.

The separate initial-supply coordinator and sequential factory control loop are
removed. Initial preparations and their local feedback chains remain independent.
Successful resources stay valid while a peer resets and retries a rejected raw
input. Existing cohort barriers expose matching work across lines after their
required resources and results are ready.

`ParallelFlows` exposes independent protocol branches to the coordinator. In
particular, all final MX calls are submitted as independent branches, and the
final joint event waits for every required measurement and physical exit. The
runtime does not manufacture call-order edges between disjoint final checks.
Parity CNOTs, consumption, conditional S and uncomputation retain their actual
protocol dependencies.

### Whole-wave budgets and terminal cleanup

The component-call budget is checked against the complete admitted wave before
execution. If that wave exceeds the remaining budget, the runtime stops without
committing a partial wave or shrinking it solely to satisfy the budget. Resource
consumption and physical mutations retain transactional wave semantics.

Single and multiple factories use the existing cooperative terminal cleanup.
A terminated line discards unconsumed resources and releases its work ownership
after safe exits; consumed-token history and the compiled prefix remain in the
audit. This cleanup does not apply merely because a peer is retrying. No restart,
new resource or second consumption is inferred from cleanup.

### Calibration and work-file cleanup

Offline fast calibration accepts completed, stable, physically validated cases
with complete required component/event coverage. Batched artifacts use verified
member source/action projections to retain each component's actions, results,
phase boundaries and costs. A separate serialized factory experiment is not a
calibration prerequisite. Invalid or ambiguous projection evidence, source drift
and missing required coverage remain errors.

The serial/parallel comparison entry, dedicated configuration, comparison report
and their dedicated tests are removed. Current entry documentation describes
mandatory batching and real device capacity studies. Tests for event identity,
retry isolation, constraint-driven batching, resource ownership and full/fast
behavior remain required; comparison against an artificially serialized run is
not an acceptance condition.

Earlier ADRs retain their original experiment records and measurements, with
supersession notes pointing here. Old artifacts are historical evidence and do
not establish timing or throughput for this scheduler revision. This ADR records
the decision and verification obligations; it contains no new experiment result.

## Alternatives and consequences

Keeping serial controls as diagnostic options was rejected because they remain
production paths capable of bypassing required batching. A hidden width cap
would have the same problem. Global schedule optimization is separate work:
the selected deterministic frontier rule has a precise, bounded guarantee.

Duplicating single-factory protocol execution was rejected because retry,
measurement-group and cleanup behavior could diverge from arrays and the fast
kernel. The envelope adapter keeps the external single-factory representation
without retaining a second execution engine.

The change intentionally removes old scheduling options and comparison modules.
It does not change the 15-to-1 recipe, acceptance model, input-error meaning,
code-specific component implementations or physical compiler algorithms.
Inventory, prefetch, arbitrary asynchronous scheduling and decoded noisy logical
success remain outside this decision.

## Verification obligations

Verify that every ready compatible member joins the selected wave, and that real
capacity, conflicting participants and unresolved results still prevent illegal
batching. Cover independent retries, successful-peer retention, final-MX groups,
whole-wave budget exhaustion, terminal cleanup and unique resource consumption.
Check rejected obsolete CLI/API options and calibration projection integrity.
Run related fast tests during iteration and all fast plus slow before a code
commit, following [the repository workflow](../testing.md). Bench requires
explicit authorization.
