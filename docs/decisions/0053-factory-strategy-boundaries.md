# Named asynchronous and round-synchronous factory strategies

Status: asynchronous/v1 retained; synchronous/v2 corrects the superseded
synchronous/v1 accepted-output quota barrier. See the current semantics below.

## Existing asynchronous policy

`asynchronous/v1` names the existing behavior without changing it:

- Every factory has its own cohort and retries locally.
- Ready corrections have priority; ordinary calls retain fair-service ordering.
- Select the first ready request, then greedily admit compatible requests of
  the same component. Do not deliberately wait for future batching opportunities.
- Complete the whole admitted wave before choosing the next wave.
- All factories share one AOD. Geometry-compatible same-component commands can
  share resources; different component types remain serial.

`AsynchronousStrategy` describes these semantics and supplies the existing
cohort identity and `ComponentScheduler`. It does not create a second scheduler,
cost model, backend or compiler. The existing cooperative runtime owns the
priority implementation. Invocation IDs, case IDs, probability ports and semantic
seeds are unchanged. Explicit `strategy="asynchronous"` is equivalent to the
backward-compatible default. `async` and `asynchronous/v1` are accepted names.

The policy itself has no distance or factory-count restriction. The estimator
accepts explicit distance and arbitrary positive integer N; cost coverage is
validated separately. In particular, accepting a distance argument does not
constitute proof that the loaded component catalog covers that distance.
The standalone report supports arbitrary positive N, including factory IDs
above 9 and waves with more than 32 members.

## Distance coverage: a separate model boundary

The code definition, logical placement and factory recipe already support odd
surface-code distances d >= 3. Following the user's scope clarification, the
loaded complete numeric catalogs now cover d=3,5,7,9,11. Missing costs are an explicit error, never a physical
compile, atomic expansion, silent d3 reuse or zero-cost growth fallback.

The saved d5/d7 profiles have been selectively migrated as numeric input records.
They are not the same model as a scaled d3 catalog:

| Target d | Saved raw-body us | Accepted-only growth/correction us | Growth rounds | Saved raw acceptance |
| ---: | ---: | ---: | ---: | ---: |
| 3 | 2374.452471 | 1 | 0 | 0.7817840576171875 |
| 5 | 4601.898464 | 4352.087452 | 5 | 0.7775421142578125 |
| 7 | 4601.898464 | 6649.722433 | 7 | 0.7775421142578125 |

Those records reside in the older checkout's
`modules/physical_compiler/artifacts/generic-factory-20261024/profiles/d{d}-n1/profile.json`.
For d5/d7, `/canonicalize` includes accepted-only expansion, ordinary SE and
correction; it cannot be charged on rejected injection attempts or replaced
with the d3 one-layer correction cost. The d5/d7 saved injection readout uses
three batches, explaining why its recorded injection costs/probabilities differ
despite the same d3 injection and three SE rounds.

The selected first scope is recorded d3/d5/d7 catalogs with an extensible
interface. A parameterized cost family for all valid d remains future work.
The later user-authorized [d9/d11 migration](../experiments/msd-object-d911-20261025.md)
adds saved component-stage records and their original exact-XOR acceptance cache.
It does not extrapolate costs or regenerate probabilities. The three earlier
catalogs and their sampled probability evidence remain unchanged.
Counts alone do not determine that family. For example, 2d^2-1 atoms,
4d(d-1) ordinary-SE interactions and (d-1)^2
additional fold-S CZ operations are derivable, but they do not fix the number
of transport groups or stage durations. No such timing extrapolation has been
silently introduced by the strategy refactor.

The intended cost-provider boundary is the existing catalog/profile seam:
coverage is identified by code family, d, protocol version and timing/geometry
model version. Cache reuse depends on those inputs, not N, seed, retry count or
policy. Strategies select readiness/barrier behavior only. This also preserves
a future color-code boundary without teaching the strategy surface-code costs.

## Synchronous/v2: production rounds, not accepted-output quotas

The user corrected the final-output boundary on 2026-10-25. Synchronization
aligns operations inside a production round, not the ordinal of successful T
outputs. The old v1 policy parked successful factories while a rejected peer
retried until success; that is not the requested continuous production policy.
The old [v1 report](../experiments/msd-object-synchronous-20261025.md) is retained
as historical evidence only. Explicit `synchronous/v1` now raises an error;
`synchronous`, `sync` and `synchronous/v2` select the corrected policy.

| Boundary | Condition for release |
| --- | --- |
| Initial preparation | Every factory has usable W1-W5 states, including accepted-only growth/correction |
| Rotation raw supply | Every required raw state is accepted; successful states wait while only failed raw preparations retry |
| Deterministic compute/uncompute and CX/MZ | Corresponding deterministic substep is complete for all members |
| Conditional S+SE join | Required S+SE branches finish; skipped branches wait without extra operations |
| Final measurements/decision | Every factory has its own final result, whether accepted or rejected |
| Production round complete | Every member finishes its final branch: accepted output delivered, or rejected work released; acceptance is not a join requirement |

A final rejection produces no output for that round. It does not trigger an
extra factory attempt inside the round. After the end-of-round join, successful
and rejected factories both start new production. Existing next-round preparation
contains reset costs. No output state is fabricated on failure. Outputs are
consumed immediately by the existing ideal external sink before the round join;
external injection and transport remain excluded, not physically modeled.
Waiting until a peer finishes its current final correction/delivery is legitimate
stage coordination. Waiting for that peer's next accepted output is forbidden.

Reuse `BarrierIntent`, `FactoryProcess`, the shared cooperative runtime, resource
ledger and homogeneous component scheduler. `production/round_complete` uses
batch index -1 and the production-round index. All original cohort members
remain required, including rejected members; there is no parked-success subset.
Raw retry counts never enter barrier identities. One AOD and serial different-
component waves remain unchanged. Successful raw states retain token identity;
barrier waits do not hold AOD leases or resample any probability.

`ProductionPolicy.completion_basis` distinguishes `accepted_outputs` (legacy
asynchronous default) from `production_rounds`. Synchronous/v2 requires matching
finite production-round policies. The object entry defaults synchronous calls
to rounds, and paired configurations explicitly select rounds for both policies.
`cycles_per_factory` counts the declared basis; `production_rounds` records every
attempted round, while `production_cycles` retains successful delivery records.
Raw exhaustion/member failure aborts the whole estimate; ordinary final rejection
is a completed round. Timeouts stop immediately without continuation or retries.
`batch_attempt_limit` applies to accepted-output mode; round mode has one factory
attempt per round, bounded by the round count. Raw attempt limits still apply.

## Acceptance and interpretation

1. Raw retry offsets preserve successful states and block the next deterministic
   step until all required raw states are usable.
2. Conditional S+SE branches join and geometrically compatible CNOTs align.
3. With one final rejection, N factories over R rounds execute exactly N*R full
   factory attempts. Success is delivered once, rejection has no output, and
   both members advance together without a replacement attempt inside the round.
4. Zero-output runs complete with rate zero and null startup/per-output costs.
5. Actual member failure and timeout still return diagnostic errors.
6. Paired async/sync round runs retain the same d, N, seed, component/probability
   documents and invocation identity scheme. Verify event outcomes and operation
   counts match. Report attempted rounds and accepted output counts separately.

Two rounds are finite-batch evidence, not steady state. Old equal-success-quota
runs do different work and cannot provide a direct speedup baseline for the new
round workload. The same semantic event IDs retain the same probability draws;
additional old replacement attempts have no counterpart in the corrected trace.

The [v2 local acceptance report](../experiments/msd-object-round-sync-v2-20261025.md)
records the corrected real-factory traces, paired data, reuse and runtime checks.

## Implemented asynchronous maintenance verification

- Focused baseline: 46 fast passed. Final mapped related selection: 73 fast
  passed in 7.69 s; no slow/bench suite or server campaign was started.
- The explicit strategy/distance entry and a configuration containing only N=3
  first failed against the previous implementation, then passed. The N=3 case
  executes the real d3 recipe and probability backend for one output per factory.
- HTML-only synthetic tests cover N=3, factory IDs above 9, more than 32 members
  and exact 50 ms boundaries. They are renderer controls, not factory results.
- Bounded local replay of d3 N=1/2, seeds=0/1 completed in 4.610 s worker time.
  Every complete case object and layout is identical to the preceding saved
  local result. The four makespans remain 181018.903936, 163032.705883,
  312989.713860 and 445059.591516 us.
- Ten templates, 4892 lookups, 4862 cache hits and 30 numeric bindings remain
  unchanged; forbidden physical compile/atom expansion/atom construction counts
  are all zero.
- Ruff formatting/lint and strict mypy passed for the changed Python modules.

Replay evidence is saved in
[behavior-preservation.json](../../artifacts/msd-object-local/20261025-asynchronous-v1/behavior-preservation.json).
This verification does not close the arbitrary-distance numeric-model gap above.

The subsequent [d3/d5/d7 migration and local acceptance report](../experiments/msd-object-d357-20261025.md)
records completion of the user's selected distance scope. The later synchronous
implementation changes readiness coordination, not those recorded cost inputs.
