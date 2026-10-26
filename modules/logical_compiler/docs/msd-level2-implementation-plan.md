# Two-Level MSD Object Implementation Plan

Date: 2026-10-25.
Task: MSD-L2-01.
Status: initial d3, N1=N2=B=1 implementation and one-round local acceptance complete;
wider task coverage remains pending.

2026-10-25 extension: the user authorized d3 N1=2, N2=B=1, matched L1 async/sync
comparison and a reusable distance/count/layout entry. This is implemented using
the existing placement catalog, supplier and scheduler; see the
[N1=2 report](../../../docs/experiments/msd-object-level2-n2-20261025.md).
Supported configuration distances are 3/5/7/9/11 with matching L2 distance, any
positive L1 count and vertical/horizontal/grid placement. Full production evidence
remains d3 N1=1/2, one L2 consumer and B=1; other combinations are not claimed tested.
Baseline: `9b18380`; task branch `codex/msd-level2-factory`.

The next scan is separately frozen in the
[synchronous single-consumer preparation](../../../docs/experiments/msd-level2-sync-scan-preparation.md)
and [ADR 0056](../../../docs/decisions/0056-single-consumer-synchronous-msd-scan.md).
The latest user instruction excludes further L1 asynchronous runs and additional
L2 consumers from that campaign, selects 89 single-thread workers, and sets
30 s/shot and 3060 s/100-shot cell. Preparation is authorized; implementation and
experiment execution remain pending approval. Earlier local results and limits
below describe historical acceptance, not this new campaign's executed status.

## Goal and contract

Implement [ADR 0055](../../../docs/decisions/0055-two-level-object-factory-supply.md)
using accepted L1 tokens to supply the existing L2 fifteen-input recipe, with
progressive supply, finite producer-held inventory, costed same-distance block
exchange, separate synchronization cohorts and one shared object scheduler.
The user authorized the initial implementation and bounded local case on
2026-10-25. See the [acceptance report](../../../docs/experiments/msd-object-level2-d3-20261025.md).

Initial scope: d3, one L1 plus one L2, B=1 published outstanding supply entry,
one explicitly placed vacant parking slot, finite L2 attempted rounds and an
ideal external sink only after L2. Later supported distances remain 3/5/7/9/11;
multi-factory ratios/layouts and dedicated storage are subsequent milestones.
Mixed target distances, multi-AOD, physical compilation and server scans are out.

## Existing seams and file ownership

Paths are repository-relative. Reuse existing owners before adding files; a
planned owner below is not a claim that its L2 capability exists today.

| Owner | Planned responsibility |
| --- | --- |
| `modules/codes/contracts/factory_recipe.py`, `modules/codes/rotated_surface/fast_factory.py` | Preserve four initial adoptions, eleven consumptions and existing code-owned gate recipe |
| `modules/logical_compiler/src/protocols/factory_process.py` | External supply at preparation boundaries; progressive demand and terminal disposition |
| `modules/logical_compiler/src/protocols/production.py` | Distinguish external consumption, retained output and handoff; finite demand closure |
| `modules/logical_compiler/src/protocols/resources.py` | Stable carrier/token identity, reservation, adoption/consumption and occupancy |
| `modules/logical_compiler/src/protocols/protocol_intents.py`, `cooperative.py` in the same directory | Resource waits and delivery receipts, level-specific cohorts, progress diagnostics |
| `modules/logical_compiler/src/protocols/` supply seam | Selectively reuse old `FactorySupply`/`TokenBuffer` semantics; no physical/campaign dependencies |
| `modules/codes/rotated_surface/object_factory.py`, `object_readout.py` in the same directory | Current geometry/cost bindings and code-owned applicability for delivery objects |
| `modules/logical_compiler/src/estimation/kernel.py`, `src/placement/` | Admit delivery stages on the common resources; commit current positions and parking claims |
| `modules/logical_compiler/examples/factory_objects.py`, `factory_schedule.py` in the same directory | Explicit two-level configuration, metrics and full timelines with token lineage |
| `modules/logical_compiler/tests/`, `modules/codes/rotated_surface/tests/` | Focused regression and small integration controls |
| `experiments/msd/`, `docs/experiments/` | Reproducible bounded configurations and subsequent measured reports |

Old main-worktree supply implementations may inform contract reuse. Audit the
exact dependencies before selective migration. Do not merge the old campaign
or import atom-template execution into the new supply path. The existing static
object binding map and consumed-only `OutputDelivery` validation are concrete
gaps: resolve them without fabricating consumed/released state or rebuilding
component internals. Keep code-family transport/quality semantics out of the
generic scheduler, preserving the future color-code boundary.

## 1. Freeze supply and lifecycle contracts

Status: initial contracts implemented and locally checked. Two producers with
B=1 now have real-recipe acceptance; wider production ratios remain unverified.

- Specify external demand identity, expected code/distance/kind/quality, input
  role and adoption versus consumption. Register L1/L2 IDs in distinct namespaces.
- Specify queue entries, pending producer outputs, reservations, in-transit
  tokens and L2 work states separately. Document exactly which states count
  against B and which continue occupying a producer carrier outside the queue.
- Add meaningful rejection tests for token duplication, wrong distance/quality,
  busy receiver, missing safe exit and a stale carrier/binding version.
- Establish demand-driven L1 stopping with explicit finite budgets and surplus
  disposition; do not assume equal L1/L2 production counts.

Acceptance: a state cannot be copied, overwritten, consumed twice or released
while still needed. Four initial inputs can be adopted sequentially with B=1.
Committed delivery frees a queue entry, not the destination carrier; a delivered
R token remains reserved until its declared irreversible consumption.
Legacy one-level output behavior remains compatible.

## 2. Add object-level block delivery

Status: implemented for the initial single exchange/parking witness; each leg
uses Euclidean displacement times recorded speed plus Load/Store (10 us each).
No additional SE/reset or physical routing is charged.

- Validate explicit producer/receiver/parking footprints and choose the initial
  exchange path under the existing distance-to-time model. Record model version,
  waypoint/path rule and applicability before any timing comparison.
- Implement three costed carrier movements with phase resources and safe exits;
  maintain reservations and position/binding versions across receipts.
- Commit role ownership after the required exchange receipts. Reuse numeric
  binding caches under current coordinates; never cache live carrier ownership
  or measurement outcomes inside component templates.
- Test common-AOD conflicts with computation, partial failure diagnostics,
  parking contention and token identity across delivery.

Acceptance: delivery is neither zero-cost nor a logical copy. The receiver gets
the original output carrier, the producer receives a reusable carrier, atom
count is conserved, and no compiler/expander/atom constructor is called.

## 3. Connect progressive L2 and synchronization boundaries

Status: initial real recipe connected; independent L1/L2 cohorts verified with
matched async/sync one-member and two-producer runs. Wider cohorts remain pending.

- Replace only L2 resource preparations: W1 remains local initialization,
  W2-W5 adopt four L1 outputs, and R takes eleven later resources. No repeated
  injection/postselection/growth charge is allowed for accepted L1 inputs.
- Use FIFO ready tokens and oldest eligible demands with stable tie-breaks.
  Keep existing fair ready-frontier/correction scheduling and homogeneous waves.
- Keep L1 and L2 cohorts separate. Permit supply to progress while producers
  wait for output capacity; neither layer may wait for a matching success ordinal.
- Connect L1 output-quality metadata to the compatible declared L2 theoretical
  port. Verify provenance and independence assumptions; unsupported quality
  fails explicitly rather than reverting to raw p=0.01.
- Add explicit supply-exhaustion and no-progress detection with wait-for context.

Acceptance: the real factory recipe uses fifteen unique inputs per completed
L2 attempt, preserves its 59-CNOT structure, and can progress with one producer
and B=1. Consumed inputs are never resurrected after final rejection. A bounded
multi-member control must show that cross-level global barriers are absent.

## 4. Bounded local acceptance and reports

Status: one real L2 round at seed 0 completed, with full HTML and resource records.
Two-round paired-seed production and rare full-L2 rejection trajectories remain
pending; lifecycle tests cover fresh inputs after abandonment, retained surplus,
partial delivery and two reserved R inputs with B=1.

Start with one L2 attempted round at d3, N1=N2=1, B=1 and an explicit seed. Only
after it completes within budget, extend to two L2 attempted rounds and paired
seeds 0/1. Configure sufficient but finite L1 round/call budgets in advance;
do not infer them from lucky outcomes or silently increase them on failure.
Retain current 20 s/case, 5 s/wave and 60 s/worker limits for initial acceptance;
any changed budget needs an explicit subsequent decision. Stop on the first
unexpected error/timeout. No server run is part of this milestone.

Required controls:

1. Sequential supply: one producer supplies four initial adoptions and eleven
   later inputs without a simultaneous four/fifteen-token inventory requirement.
2. Raw retry and conditional S offset: correct internal joins remain; one layer
   can make progress while the other waits for supply or finishes its branch.
3. Backpressure/resource conflict: B=1 and occupied parking/AOD produce explained
   waits without holding AOD during pure input/capacity waits or deadlocking.
   A multi-L2 input-ready control must permit sequential deliveries into each
   free R with B=1; waiting for actual consumption to free the queue is forbidden.
4. L2 final rejection and continuation: previously used inputs remain used;
   the next attempt obtains fresh inputs. Controlled outcomes may test this rare
   branch but must be labeled tests, never substituted for factory run results.
5. Demand closure: in-flight work is drained/accounted for, surplus tokens have
   explicit owners and locations, and no early success marker hides unfinished work.
6. Failure: raw exhaustion, insufficient remaining supply, invalid ownership,
   no-progress cycles and timeout return distinct diagnostic causes.

Deliver exact configs/seeds, source/model hashes, event and token-lineage records,
component reuse counters, measured software runtime and a complete HTML schedule.
Show both levels, deliveries and parking usage on one timeline. Report first L2
output, total/drain completion, accepted L2 output count, finite-batch rate,
L1 attempts/accepted inputs used, all allocated atoms, finite occupied/parking
geometry, per-L2-output time-space cost and explicitly unavailable device area.
Separate producer backpressure, consumer starvation, protocol barrier, scheduling
and transport waits/exposures; do not add member-time sums to global makespan.

## Verification policy and completion evidence

Follow [agent.md](../../../agent.md) for stepwise tests and commits. This document
change uses only documentation checks under [docs/testing.md](../../../docs/testing.md).
Later code work runs relevant fast baselines, regressions first, mapped fast
consumers and the bounded local controls above. The user's task-specific scope
overrides blanket all-fast-plus-slow checks: no bench, full slow suite, physical
compilation or automatic server submission. State that exception in run reports.

Closure requires actual real-factory evidence, zero forbidden atom/compiler work,
preserved component identities under changed seeds/retries/combinations, validated
ownership transitions and no unresolved stalled supply. Report changed files,
commands/counts, commit, runtime and limitations at each milestone. Documentation
approval alone does not mark any implementation step or throughput claim complete.
