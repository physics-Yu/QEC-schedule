# Two-level factories with progressive object supply

Date: 2026-10-25.
Status: accepted design; initial d3, N1=N2=B=1 object witness implemented.
Evidence: [bounded local report](../experiments/msd-object-level2-d3-20261025.md).

Implementation extension (2026-10-25): the
[two-producer comparison](../experiments/msd-object-level2-n2-20261025.md) uses d3,
N1=2, N2=B=1 and matched seed/consumer-round limits. The entry reuses existing
recorded distances and L1 layout/count interfaces. L2 remains one same-distance
consumer, placed below the L1 array; parking is derived at the right edge.
Only L1 policy changes between paired runs. This does not extend mixed-distance
delivery or claim complete production validation for every configurable layout.

## Context

The current baseline `9b18380` estimates complete first-level factories from
recorded component objects at d=3/5/7/9/11. It has one shared AOD, homogeneous
component waves, asynchronous readiness and synchronous/v2 production rounds.
Its ideal external sink consumes outputs and releases carriers. That sink cannot
connect L1 to L2: an L1 state needed by L2 must remain on its actual carrier.

The user selected same-target-distance two-level production, progressive supply,
finite buffering and explicit delivery cost. This ADR extends
[ADR 0052](0052-msd-object-waves.md), [ADR 0053](0053-factory-strategy-boundaries.md)
and [ADR 0054](0054-msd-layout-cost-comparison.md). The
[implementation plan](../../modules/logical_compiler/docs/msd-level2-implementation-plan.md)
defines file ownership, milestones and bounded acceptance. This document records
the intended behavior. The first bounded entry now implements that subset;
multi-factory scaling and the remaining acceptance extensions stay pending.

## Decision

### Reuse the factory recipe and change the input supplier

Both levels use the existing six roles W1-W5,R and 15-to-1 recipe at the same
target distance. L2 initializes W1 locally. It adopts four accepted L1 outputs
into W2-W5, then consumes eleven further L1 outputs through R at the existing
rotation stages. These are distinct use modes: four work-state adoptions and
eleven T-consumption operations, not fifteen identical injection operations.
Retain the existing CNOT, actual S+SE, measurement and final-decision components.

L2 does not repeat raw injection, injection postselection or target growth on
an already accepted same-distance L1 output. L1 retains d3 injection with three
total SE rounds, followed only on acceptance by 0/5/7/9/11 ordinary growth SE
rounds. Growth is not another postselection process. All timing/noise inputs
remain recorded, including measurement 100 us, processing 0 and Load/Store 10 us.

L2's four initial inputs may arrive one at a time. Once all four are usable,
the dependent core proceeds. Later R inputs are requested progressively; the
factory preserves work states while waiting. Neither four simultaneously queued
outputs nor a stockpile of fifteen is required. With one producer, early adoption
must release supply capacity so that the producer can make the next input.
Receiving an input counts as adoption/consumption only at the existing declared
semantic boundary, not merely because a transport reservation was created.

### Token, carrier and role ownership

Preserve token ID, carrier ID/epoch, code/distance, resource kind, canonicalization,
quality provenance, ready/safe-exit time and location across delivery. Roles are
assignments to carriers; changing role ownership does not copy a quantum state.
An accepted L1 output is offered once, reserved for at most one demand and used
once. Initial adoption transfers it into an L2 work state; a later R resource
is consumed at the recipe's declared irreversible use. Transport alone does not
consume it. Rejected L1 batches publish nothing.

Reuse `ResourceToken`, `ResourceLedger`, `FactoryProcess`, `ComponentCall`,
`ProfileExecutionKernel` and the cooperative scheduler. Add external input
supply at the existing preparation boundary. Extend output disposition to
distinguish consumed external delivery, retained output and handoff. Do not
weaken `OutputDelivery.validate` to pretend a retained token was consumed/freed.
Old `FactorySupply`/`TokenBuffer` and handoff contracts are reference material
for selective reuse, not authorization to import their physical compiler,
calibration, campaign or server execution paths.

### Finite producer-held inventory

The first baseline retains accepted outputs on producer carriers and uses one
explicit empty parking location for delivery. Define queue capacity B as the
maximum published outstanding supply entries, including reserved/in-transit
entries until committed delivery into an L2 input position. B is a logical admission limit, not an
allocation of B extra quantum memory blocks.

An L1 output that cannot enter a full queue stays on its producer's W1 carrier;
the producer cannot overwrite it or start another round using that role. Count
such outputs separately as pending publication, with their atoms, location and
waiting exposure. They are not an unbounded overflow queue: each producer has
at most one retained output. Report queue occupancy and total physical inventory
separately, including pending, reserved and in-transit tokens. Setting B larger
than the producer count creates no additional producer-held storage.

After delivery into W2-W5 or R, release the supply-queue entry while continuing
to account for the occupied L2 input carrier. Initial W2-W5 adoption transfers
the state into work. An R token remains reserved and unconsumed until actual
use, and stays unavailable to other demands even though it no longer occupies
a supply-queue entry. Queue release is not token consumption. Keeping delivered
inputs charged against B can deadlock progressive initial preparation or a
multi-L2 input-ready barrier at B=1. Delivery into an occupied R is forbidden;
this boundary permits no hidden extra storage beyond the declared L2 roles.

Waiting for capacity releases no live state and holds no AOD lease. The default
has no output-drop/expiry policy. Dedicated buffer blocks and multi-slot prefetch
are later alternatives requiring explicit atoms, geometry, transport and policy.

### Same-distance delivery and cost

The first delivery construction is a whole-block exchange with a vacant parking
location, a free/reusable L2 receiving carrier and a retained L1 output:

1. Move the reusable receiver carrier to parking.
2. Move the output carrier to the L2 input position.
3. Move the parked carrier to the L1 output position for future production.

Each movement is a staged object with Load, movement and Store as applicable,
explicit dependencies and AOD occupancy. Record actual source/destination
coordinates and the selected path segments. Charge existing transfer times and
the existing distance-to-time model per segment; no free teleportation or
unjustified extra SE/reset is added. A shortcut or different placement requires
an explicit applicability rule, not silently deleting one of these costs.

Reserve the involved carriers, destination and parking location before starting
an exchange. Finish the admitted exchange before reusing those resources; do
not claim the output delivered or the producer reusable before its required
receipt/safe exit. Commit each completed leg's position, then commit role handoff
only once the required exchange receipts exist. A partial failure retains its
actual receipts/occupancy and terminates the estimate; it is not rolled back as
if the state had never moved. Never move an occupied L2 work state into an input
slot just to satisfy a demand.

Parking reserves finite geometric space but adds no atoms if it is initially
vacant. Count all carriers once as roles change. The object profile must use
committed current positions/binding versions rather than its initial static
lookup alone. Reuse component definitions; refresh only numeric bindings and
geometry-dependent admission. Missing delivery geometry/cost coverage is an
explicit error, never a physical-build fallback.

These rules specify an object cost/applicability model, not verified atomic
paths, crossing constraints or a physical collision certificate.

### Shared resources and separate synchronization groups

All L1 processes, L2 processes and deliveries use one clock, ledger and AOD
scheduler. Never sum or maximize independently estimated factory schedules.
Same-component calls across either level may share commands only when all
existing dependency, carrier, geometry and resource constraints permit it;
different component types remain serial. Delivery commands obey the same rule.

Define distinct L1 and L2 synchronization cohorts. Within each synchronous
cohort, retain raw/input-ready joins, deterministic steps, conditional S+SE joins
and attempted-round completion. There is no cross-level stage/round barrier:
levels communicate through tokens and resources. Equal round counts across
levels are neither required nor meaningful for a fifteen-input consumer.

L1 final success makes its output available to supply immediately. L1 rejection
completes a no-output attempt. L2 success makes its output available to the
selected final sink; L2 rejection completes its attempt and needs fresh inputs
next time. Never wait for peers to replace the same ordinal successful output.
Capacity-induced waiting for an occupied carrier is legitimate backpressure,
and must be labeled separately from stage synchronization. Supply processing
must remain active while a producer is blocked at a round boundary so that it
can drain the very inventory needed to release that boundary.

### First dynamic scheduling policy

Keep policies deterministic and use only observable/current state. Future fake
outcomes must not be sampled or inspected to improve scheduling decisions.

| Event/state | Baseline decision |
| --- | --- |
| Raw retry or conditional branch resolves | Expose the actual continuation; preserve successful raw states during peer retries |
| Accepted L1 output is safely available | Publish if capacity exists; otherwise retain it on the producer |
| L2 reaches an input request | Match the oldest eligible demand to the earliest ready compatible token |
| Several eligible tokens/demands tie | Use stable semantic IDs and a deterministic registration sequence |
| Input slot or parking is unavailable | Keep the request pending without holding the AOD or blocking unrelated eligible requests |
| Exchange becomes feasible | Reserve endpoints/parking and submit its staged commands to the shared scheduler |
| Components contend for AOD | Retain existing correction priority and fair-service ordering; greedily batch compatible same-component ready calls |
| L2 rejects its attempt | Invalidate used work through the recipe lifecycle; request new tokens for the next attempt, never resurrect consumed inputs |
| Producer budget is exhausted | Use remaining valid inventory if sufficient; otherwise report supply exhaustion with unmet demands |

Distance affects delivery cost and feasibility but is not a new nearest-token
selection heuristic in the baseline. Likewise, do not silently prioritize L2,
prefer nearly finished attempts, wait for a larger batch, expire old states or
add speculative prefetch. Those are explicit later policy comparisons. Record
why each allocation/admission/wait occurred so such alternatives can be compared.

A stable event identity includes level, factory, attempt/round and semantic
operation. Layout, queue arbitration and scheduling-policy names do not enter
the fake-backend sampling identity. Separate barrier keys from successful-output
ordinals and from local raw retry indices.

### Probability, liveness and stopping

L1 raw acceptance uses the original recorded ports. L2 input quality comes
from the accepted L1 output's declared quality model, not automatically from
the raw input's p=0.01. Reuse existing theoretical input/output-quality and
final-check interfaces under their explicit independent-input assumptions.
Require compatible input quality/provenance for the selected L2 model; do not
average heterogeneous qualities or derive quality from acceptance alone.
Prepare/cache supported theoretical ports once per declared model inputs,
without new physical/noise estimation. Unsupported quality is an explicit gap.

Waiting/transport contributes exposure and occupancy but does not change raw
acceptance or quality without an agreed model. Retain lineage of all fifteen
inputs. Neither theoretical output error nor a valid object schedule establishes
decoded logical error rate, physical independence or fault tolerance.

The first bounded run ends after an explicit number of L2 attempted rounds,
with an ideal external sink only at the final output. L1 produces on demand
subject to separate explicit safety budgets; it is not stopped after the same
round count as L2. On demand closure, stop initiating production at a safe
policy boundary, finish already admitted exchanges, and drain any already
started rounds to a recorded disposition. Surplus accepted outputs remain
explicitly retained and costed, not silently destroyed or omitted. Include
drain time in total completion time and report terminal-output time separately.
At demand closure, a safely retained surplus is a valid terminal disposition
for the producer's round join. It must not wait for queue admission or consumer
use that will never be requested, and it must not falsely release its carrier.

Distinguish normal input waiting (a producer/event can still advance), finite
supply exhaustion, a wait-for cycle with no possible progress, and wall timeout.
Errors include level/factory, phase, unmet demand, token reservations, resource
owners and last progress. A timeout stops subsequent cases with no automatic
retry or budget increase. A partial schedule is not a successful result.

## Alternatives

- Reserve fifteen simultaneous inputs before L2 starts: deferred; unnecessary
  for the progressive recipe and can deadlock small producer-held inventories.
- Replace delivered states with newly prepared local raw states: rejected;
  changes both the physical resource identity and the intended distillation level.
- Globally synchronize L1 and L2: rejected; creates avoidable supply cycles.
- Give L2 permanent scheduling priority or select nearest/oldest-risk tokens:
  deferred policy comparisons, requiring declared objectives and matched inputs.
- Dedicated storage banks, mixed target distances, multiple AODs and full
  physical delivery compilation: separate capabilities, not prerequisites here.

## Consequences

The first witness is one L1 and one L2 at d3, producer-held B=1 supply and one
explicit vacant parking position. It tests the smallest useful ownership and
liveness boundary, not the optimal factory ratio or steady-state capacity.
Reuse existing code/ports/interfaces selectively; add no campaign/recovery
framework. All normal combinations and scans remain free of atom expansion
and physical compilation. Report L2 output metrics, L1 work consumed per L2
output, inventory histories and transport/wait breakdowns under a common budget.
