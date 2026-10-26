# Shared AOD component waves

Status: Accepted for implementation, 2026-10-24. Extends ADR 0046.

## Context

ADR 0046 admitted transport only when different component members used distinct
AODs. The factory example consequently allocated four AODs for four identical raw
preparations. This encoded a composer limitation as a resource requirement.
Aligned copies of SE, S, raw preparation and initialization can instead share one
row trajectory and contribute disjoint column bands to the same AOD.

## Decision

Code declares `SharedAODClaim` alongside the exact component and waveform identity.
It names the AOD, row trajectory, absolute column band, peak row/column/readout
demands, and actual Device capacity limits. The logical scheduler checks the whole
candidate group before binding or atom expansion. Shared row demand is not summed;
column demand is summed per AOD, and readout demand per readout channel, including
members using different AODs. Conflicting capability declarations fail closed.
Exclusive claims still conflict with shared claims on the same resource.

The physical composer admits only inactive shared grids at a wave entrance.
It maps each member's local column IDs to stable distinct IDs, verifies identical
rows at each synchronized phase, and combines same-AOD Load/Move/Store actions.
No action is padded or stretched. Each member's atoms, measurements, time and
source operations remain separately attributable, including when several member
actions contribute to one physical action. Full-world physical validation remains
mandatory before committing any state or result allocation.

Code-owned probability adapters independently verify fused-action membership,
grid mappings and participant trajectories before reusing the supported local
independent-noise estimator. Shared controls do not justify an independence claim
for correlated noise. Actual logical quality remains unsupported as before.

The default acceptance configuration has one AOD. Both serial and parallel runs
use that same Device, code entry, noise parameters, seed and event identities.
The complete case must contain four concurrent initial raw preparations, seeded
local rejection/retry, retained successful carriers and unique algorithm T use.
The experiment is compiled and sampled through the normal entry; postprocessing
an old four-AOD program is not acceptance evidence.

## Limits

This implements synchronous same-component waves, not arbitrary asynchronous grid
sharing. Different component types, nonmatching trajectories and multi-patch gates
do not inherit this rule. Inventory, prefetch and multi-factory policies remain
separate work. Device geometry, optical capacity and noise assumptions still bound
the usable wave width; the illustrative Device has no explicit row/column count
limit. The QASM frontend's general binding pipeline remains separate from this
explicit factory protocol entry.
