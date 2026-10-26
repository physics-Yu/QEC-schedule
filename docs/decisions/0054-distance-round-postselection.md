# Distance-round raw-T postselection and cache migration

Status: Accepted. The user selected total SE rounds equal to code distance.

## Context

The raw-T primitive already contains injection and the first full SE. The earlier
postselection wrapper appended one ordinary SE at every distance, so its d3/5/7
acceptance experiment used two total rounds throughout. The logical factory calls
that wrapper, and its fast d3 profile cached the two-round costs and joint
acceptance/preparation-class distribution. Updating a default alone would leave
explicit callers and old caches on a different temporal protocol.

## Decision

Keep the raw-T primitive, single-SE primitive, layout, timing and noise unchanged.
Normal postselection now uses R=d total rounds: one raw preparation followed by
d-1 complete ordinary SE rounds. d3/5/7 therefore use 3/5/7 rounds. First-round
deterministic checks and all adjacent-round syndrome differences remain the
acceptance rule; only the observation horizon changes.

Share an explicit round-policy resolver. Normal calls reject a contradictory
extra-round count. Historical short-round calculations require
`round_policy="explicit_control"` and an explicit count; their provenance marks
them as controls. Logical factory execution admits the normal policy.

Protocol/template/probability identities carry version 2 and explicit distance,
round policy, extra rounds and total rounds. The code-owned factory recipe
declares preparation parameters, and the logical consumers pass them through
without inferring code-specific rules. Physical result reservation, execution
claims and caches use the resolved count. For d3, the normal preparation has
24 measured results and 20 detectors.

Fast profiles migrate to `nadit.fast_surface_factory_profile/2`. Admission checks
their protocol identity, preparation call parameters, actual calibration result
counts and joint probability-port identity. Version-1 or two-round profiles are
rejected; new labels alone cannot make an old calibration valid. Recalibration
must use an actual three-round source. The generic binary acceptance port is not
substituted for a joint canonical-preparation table.

## Verification and consequences

The temporal detector counts are B+(d-1)(d^2-1), where the actual initial seed
determines B: 20, 104 and 308 at d=3,5,7. Recompute the three distances using the
same physical world, noise parameters, sample budget and seed as the historical
two-round experiment. Keep old results intact and distinguish the new protocol.
Check zero-noise acceptance, the independent multi-round readout formula,
unchanged raw primitive templates and device geometry, complete physical replay,
and rejection of old caches at the actual logical consumer boundary.

Report per-attempt resources and independent-repeat expectations separately.
Those expectations exclude canonicalization and downstream factory work, and
do not count atom loss as detector rejection. Accepted logical quality remains
unknown. Choosing R=d is an explicit experiment standard, not a proof of
circuit-level fault distance for this injection construction. The fast factory
backend remains d3-specific; larger-distance postselection components and binary
acceptance ports do not establish a generic full-factory backend.
