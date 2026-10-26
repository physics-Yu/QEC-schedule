# Whole-factory layout comparison for MSD object estimates

Date: 2026-10-25.
Status: implemented for the d3 N4 local comparison; wider experiments deferred.

Correction, 2026-10-25: synchronous/v2 aligns attempted production rounds, not
successful-output counts. Both policies must use the same explicit round workload
for future layout comparisons. The earlier success-quota boundary is superseded.

## Context

The complete d3/d5/d7 factory object catalogs and asynchronous/synchronous
policies are implemented at `d9a60c1`. Their current estimator entry places
factories vertically. The user selected a comparison of vertical, horizontal
and two-dimensional arrangements under both policies, with one shared AOD and
the original precomputed probability fake backend. This decision records the
next task; it does not report new runs or authorize physical compilation.

This extends [ADR 0052](0052-msd-object-waves.md) and
[ADR 0053](0053-factory-strategy-boundaries.md). It uses the existing component,
placement and cooperative scheduling interfaces, not a second execution engine.
The [implementation plan](../../modules/logical_compiler/docs/msd-layout-implementation-plan.md)
defines staged tasks and acceptance criteria. The subsequent
[d3 N4 local report](../experiments/msd-object-layout-d3-n4-20261025.md) records
implementation and bounded acceptance; it does not extend these model claims.

## Decision

### Placement and fixed resource assumptions

Translate whole factories while preserving their six horizontal roles
`W1,W2,W3,W4,W5,R`, orientation, carrier/token identities and internal spacing.
Reuse `PlacementRequest`, `PlacementPlan`, `GridFactoryPlacement`, `place` and
`validate_plan`. Preserve `ExplicitPlacement` as the existing extension seam;
custom layout search is outside this task.

| Layout | Factory columns | Placement order |
| --- | ---: | --- |
| Vertical | 1 | Top to bottom; existing default coordinates exactly |
| Horizontal | N | Left to right |
| Grid | Explicit positive column count | Left to right, then top to bottom |

Factory IDs retain request order. They are not reassigned to improve a result.
N=1 has one unique placement. N=2 has no distinct nondegenerate 2D arrangement.
N=4 provides the first three-way comparison: 4 rows by 1 column, 1 by 4, and
2 by 2. Later N=8 may compare both 4 by 2 and 2 by 4. A square grid of factory
indices is not necessarily a square physical footprint.

The current same-distance geometry has block extent `b = 20d` micrometers,
patch gap `g = 40` micrometers and factory width `W = 6b + 5g`.
For row r, column c and internal role index j, its origin is
`(c(W+g) + j(b+g), -b-r(b+g))`. Implementation must obtain footprints from
code-owned geometry; this formula explains the current convention, not a new
hardcoded substitute for `PlacementPlan`.

Retain site pitch 10 micrometers, factory x/y gaps 40 micrometers, storage/gate
home footprints below y=0 and readout above y=50 micrometers. The 50 micrometer
gap remains fixed. Storage/readout capacities and AOD row/column counts remain
unbounded in this estimate, while actual allocated atoms and finite storage
dimensions are reported. One AOD remains shared by every factory.

### Model inputs and provenance

| Input | Existing owner; treatment |
| --- | --- |
| Block geometry and pitch | `modules/codes/rotated_surface/geometry.py`; reuse code-owned bounds |
| Placement and gaps | `modules/logical_compiler/src/placement/strategies.py`; reuse whole-factory grid |
| Staged component times, transport coefficients and source hashes | `modules/codes/rotated_surface/configs/object_d{3,5,7,9,11}_reference.json`; retain numeric records |
| Readout budget and geometry binding | `modules/codes/rotated_surface/object_readout.py` and `object_factory.py`; expose placement selection |
| Raw and other event probabilities | Existing catalog probability ports and event backend; retain selected documents, hashes and semantic IDs |
| Production settings and limits | `experiments/msd/factory-objects-rounds-d{3,5,7,9,11}.json` and `factory-objects-sync-d{3,5,7,9,11}.json`; equal attempted-round workload and retained budgets |

Measurement is 100 microseconds, classical processing 0, Load and Store each
10. Other timing/noise inputs remain those of the loaded records, with no
retuning. Supported numeric distances are d=3/5/7/9/11; missing coverage is an error.
Preserve d3 injection with three total SE rounds and postselection, followed
only after success by target growth with 0/5/7/9/11 ordinary SE rounds at d=3/5/7/9/11.
The d9/d11 extension has separate vertical N1/N2 acceptance; it does not extend
the completed d3 N4 layout experiment to those distances automatically.
Preserve the implemented logical S+SE and full rejection/reset/retry/next-cycle
recipe. Do not add transversal S, target-wide postselection or waiting SE.
Code-specific costs remain code-owned, preserving the future color-code seam.

### Cost binding and shared scheduling

The implemented call chain is `run_factory_objects -> FactoryObjectCatalog.layout
-> SurfaceReadoutCatalog.layout -> place -> FastLayout`, followed by the
existing `FactoryObjectProfile`, `ProfileExecutionKernel`, cooperative runtime
and component scheduler. Only placement selection is newly passed through it.
Python entry points accept `placement="vertical"|"horizontal"|"grid"` and
optional `columns` for grid. JSON uses `placement: {kind, columns?}`. Non-grid
choices reject explicit columns; grid requires a positive integer. Existing
grid behavior clamps columns to N, reporting requested and effective columns.

1. Reuse the recorded stage objects. For each readout-tagged movement stage,
   preserve the existing rule `t(y) = t_ref + (y_ref-y) * move_us_per_um`.
   Preserve the existing CNOT movement rule
   `abs(signed_dx + pair_separation_um) * move_us_per_um`.
   Translating a whole factory preserves its internal signed CNOT displacement.
   Gate, measurement, reset, SE and growth stage structures are unchanged.
2. Only same-component calls with matching relative geometry and compatible
   whole-call claims/home bands can share commands. Include both CNOT endpoints.
   Re-evaluate group applicability against current positions. A shared readout
   movement uses the existing common sufficient translation, charging the
   maximum required movement within that compatible group. This maximum applies
   to a shared stage, never to independently estimated whole-factory schedules.
3. Different component waves remain serial. Preserve phase resources and
   persistent AOD leases from Load through Store, including retained readout.
   Resource conflicts produce explicit waits in the single common scheduler.
4. Asynchronous readiness remains independent. Synchronous readiness retains
   raw-success waiting, the conditional S+SE join, deterministic-stage barriers
   and production-round membership from ADR 0053. Accepted outputs are delivered
   immediately; final rejection also completes the round, so both factories
   begin fresh production without waiting for replacement successes. Waiting does not change event
   probabilities or reprepare successful states.

Load each distance/protocol/model catalog once. N, layout, seed, retry count
and policy must not rebuild its internal components. Numeric bound-cost cache
keys remain `(component, signed_dx, origin_y)` within a catalog whose identity
includes the recorded model inputs. X translation is omitted only because the
present cost model is x-invariant; full coordinates still govern batching.
A new y can cause a cheap numeric cache miss, never compilation or atom
expansion. Record layout fingerprints in results, not in random-event IDs.

### Paired comparison and reporting contract

Hold d, N, seed, per-factory attempted-round count, limits, component/probability
documents and ideal external sink fixed across layouts and policies. Keep two
production rounds per factory for the first local comparison. Accepted outputs
are sampled results, not per-factory quotas. Internal reset and
next-cycle preparation remain charged. Check semantic event IDs, draws/outcomes,
invocation IDs and operation counts across all paired conditions; ordering of
their timestamps may differ. Policy/layout names must not affect sampling.
Do not compare these times directly against old runs that retried until each
factory reached a fixed number of successes. Zero accepted outputs yield zero
finite-batch rate and unavailable startup/per-output cost, not an error or retry.

Deliver reproducible configurations, a layout plot and complete HTML schedule
for each case, plus a comparison index. Report startup latency, completion time,
finite-batch accepted-output rate, allocated atoms, storage width/depth/area,
atom-time and storage-area-time per accepted output. Distinguish allocated
block area from the storage bounding envelope if both are presented.
Separate readout/other transport, AOD busy time, resource waiting, protocol
barrier waiting and wave-tail waiting, and report shared-command counts by
component. Member-time sums are not additive global makespan terms.
Retain operation/transport/idle exposure accounting without inventing a
schedule-dependent acceptance or decoded logical-error model.

Readout swept area and full-device footprint are not supplied by the reduced
records: keep them explicitly unavailable. Storage area must not be labeled
whole-device area. Finite batches must not be labeled steady-state throughput.
Include software wall time, template reuse, numeric cache hits/misses and
forbidden physical compilation/atom expansion/construction counters.

## Alternatives

- Recompile or calibrate every layout: rejected; violates the object-estimation
  boundary and is unnecessary for the admitted translation model.
- Sum independent factory runs, or take their maximum: rejected; loses shared
  AOD arbitration and command batching.
- Rotate/repack internal blocks or optimize placement: deferred; changes more
  than whole-factory geometry and may invalidate component applicability.
- Add camera field-of-view, width/capacity limits or congestion penalties:
  deferred pending explicit device inputs and a separate agreed comparison.

## Consequences and limits

Horizontal arrangements can reduce readout depth without any modeled width
penalty. The comparison therefore studies a width-versus-depth/time tradeoff
under the existing unbounded-capacity model; it cannot establish an optimal
physical layout or an equal-area/equal-width device comparison. Fixed N and d
hold atom count and AOD count constant, not the storage bounding area.

Object schedules are cost estimates, not verified atom trajectories or collision
certificates. Physical reference validation, multi-AOD, level-two factories,
mixed target distances, new probability models and server orchestration are
outside this task. Any timeout stops execution with its cause and last stage;
there is no automatic continuation, retry or successful partial comparison.
