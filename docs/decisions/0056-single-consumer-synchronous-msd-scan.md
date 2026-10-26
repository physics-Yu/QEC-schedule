# Single-consumer MSD scan with synchronous L1 supply

Date: 2026-10-25.
Status: parameters confirmed for preparation; implementation and experiment
execution await explicit user approval. No new experiment has been run.

## Context

[ADR 0055](0055-two-level-object-factory-supply.md) and the current baseline
`6db07b9` provide progressive, costed object supply and local d3 N1=1/2, N2=B=1
acceptance. The single-level branch adds a completed 180-cell scan and reusable
statistics/report tools, but its runner is restricted to single-level one-round
shots. Neither branch alone implements the requested full two-level scan.

The user fixed N2=1, removed the L1 asynchronous arm, selected the previous
89 single-thread workers, increased each shot budget to 30 seconds, and requested
preparation files before approving any implementation or experiment.

## Decision

Freeze the [preparation document](../experiments/msd-level2-sync-scan-preparation.md)
and [parameter record](../../experiments/msd/level2-sync-scan-preparation.json):

- d=3/5/7/9/11 with matching target distance at both levels; N1=1/2/4/6/8/10.
- Exactly one L2, B=1, no additional storage blocks, one vacant parking slot.
- Only L1 synchronous/v2; the single L2 progresses independently. All computation
  and delivery share one AOD. Same-component compatible commands may share;
  different components remain serial.
- Preserve all complete rectangular L1 arrays, including both orientations;
  place L2 below-center, right-center or above-center. Preserve internal factory
  orientation and six-role geometry. The matrix has 270 cells and 27000 shots.
- Each shot ends after one L2 attempted round plus drainage. Final rejection is
  a valid no-output round; no accepted-output quota or kth-success barrier.
- Keep all existing timing/noise/protocol/probability conventions. No physical
  compilation, atom construction/expansion or per-combination calibration.
- Use at most 89 single-thread workers. Wave/shot/cell limits are 5/30/3060 s;
  the cell limit is 100 x 30 + 60 s startup allowance. The previous design's
  24-hour batch cap remains unchanged; it is not the old scan's one-hour cap.
- Stop on the first error or timeout; preserve cause and partial evidence,
  terminate only this run's children and do not retry, resume or enlarge budgets.

The new JSON is a preparation schema, not an executable configuration for either
existing runner. Its approval fields document current authorization; editing a
flag does not substitute for explicit user approval. The execution source SHA
stays unset until the adapted implementation is validated and frozen.

## Alternatives

- Continue L1 async/sync scanning: excluded from this campaign by the user;
  preserve the implementation and historical results for reference.
- Increase N2 or scan ratios: excluded; the variable is upstream supply N1,
  while receiver/pipeline count remains one.
- Add dedicated storage or scan B: deferred; B=1 retains its producer-held
  queue semantics and does not allocate extra quantum memory.
- Pass the record directly to the old single-level runner: rejected; it would
  use the wrong production endpoint and lacks costed two-level delivery metrics.
- Label the pooled finite-shot rate as continuous steady state: rejected.

## Consequences

The accepted object runtime, supplier, carrier ledger, probability backend and
existing placement interfaces remain the implementation base. Subsequent work
must expose the three L2 positions, adapt the bounded runner and translate the
single-level accounting to real carrier identities and delivery stages. These
are readiness gaps, not completed work in this document commit.

At fixed d/N1, layout comparisons use the same atoms and AOD. Across d/N1, show
actual allocation, occupancy and Pareto tradeoffs; extra supply is not free.
Storage bounding area is not full device/readout/swept area. Current unbounded
zone capacities are not silently replaced with invented physical limits.

This preparation changes no runtime defaults, historical configs or results.
Execution approval remains pending. Follow the repository's documentation-only
checks for this change; later code requires related fast tests and bounded local
acceptance before a server scan, within the approved scope.
