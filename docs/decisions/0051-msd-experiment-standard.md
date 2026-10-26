# ADR 0051: MSD experiment standard and distance-selected component calibration

Status: User-directed implementation, 2026-10-24.

## Context

MSD comparisons require one explicit physical timing/layout standard. The user
has a separately developed fast logical compiler for production scheduling and
resource summaries. Its working source must not be overwritten or replaced by
an independent experiment scheduler. The d3 code already implements real logical
S, so a transversal-S assumption is neither needed nor used.

## Decision

Use measurement=100 us, result processing=0 us, LOAD=STORE=100 us. Preserve all
other d3 CNOT reference capabilities and timing. Use the nonzoned physical
compiler with caller-supplied homes. Place each six-block factory horizontally
and stack factory rows downward. Storage/gates occupy y<=0 and readout y>=50 um.
Both ideal operating domains are unbounded; no literal JSON infinity is added
to the established finite Region contract. Materialize an enclosing execution
window per configuration and compare actual semantic actions under enlargement.

Generate odd-distance surface-code definitions and concrete components through
an additive shared helper with explicit distance-selected code identities. Keep
the old d3 implementation intact and provide a d5 facade. Preserve the d3 check,
logical-string and phase conventions. Validate Clifford action, measurement
relations, raw-seed encoding and returned correction relations independently;
check actual compiled and bound atom programs in the full occupied world.

Fix readout destination candidate generation using actual source/obstacle
coordinates. Preserve AOD order, spacing, capture closure, occupancy and replay
checks. This is not a complete continuous-placement solver or optimality claim.

The experiment adapter consumes existing PhysicalDAG, Device, AtomLayout,
NonZonedStrategy, validation and activity interfaces. Component calibration
records actual per-call time/exposure, all spectator costs, and source/device
hashes. It does not infer factory throughput from isolated calls. Production
metrics stay unavailable until the external logical runner supports the chosen
distance and vertical/common-readout profile, event models and sustained output
carrier lifecycle. Two-level design waits for first-level arrival data.

## Alternatives

An enormous constant rectangle would hide an arbitrary capacity limit and could
make old destination search scale with area. Infinite Region values would change
geometry/serialization/viewer contracts across the project. A finite materialized
window plus semantic enlargement checks preserves current interfaces and makes
the approximation boundary inspectable. Raw equality of coverage rectangles is
not required when both illuminate exactly the same atoms during replay.

Multiplying one isolated factory cost by N would omit shared AOD constraints,
common readout distance and spectator illumination. It cannot replace actual
logical scheduling. Likewise, raw detector acceptance and physical exposure do
not establish a decoded logical error probability.

## Consequences

The versioned [experiment plan](../../experiments/msd/level1_plan.json) records
independent d/N axes, timing, resource and observation conventions, execution
limits, and second-level inputs. The [interface audit](../experiments/msd-interface-audit.md)
documents the concrete external seams and unsupported integration paths.
Models remain explicitly scoped: real compiled components, ideal algebraic
checks, pending quantum outcomes, and separately specified noise estimates.
Human acceptance and full factory production validation remain distinct gates.
