# Logical placement implementation and verification

Date: 2026-10-24. Base: `5ee05a9`, branch `feat/test-tiers`.

## Delivered

`modules/logical_compiler/src/placement/` now exposes
`place(request, strategy) -> PlacementPlan`, with `ExplicitPlacement` and
`VerticalFactoryPlacement`. Code-owned geometry supplies bounds, orientations,
spacing and version identity. Placement performs no physical compilation or
probability sampling. External plans are revalidated before binding.

The MSD world builder retains Device construction and consumes the plan. Storage
and gates remain below y=0; readout remains above y=50 micrometers. Every positive
integer factory count is accepted. The full and fast historical horizontal
factory entries now share an explicit placement source.

The fast entry accepts the existing factory recipe, a plan and cost records
directly. Raw T preparation, postselection, local correction, retry, consumption
and final checks retain their existing protocol. Cache lookup does not invoke
physical compilation. Missing records produce explicit applicability failures.

Applicability checks include code/distance, component source/version, relative
geometry, Device/readout/workspace and declared spectator influence. N and the
complete plan hash alone do not invalidate local records. Saved records retain
the original calibration provenance. Test models cannot supply production
calibration evidence, and a bound Device budget cannot change during execution.

## Completed evidence

| Check | Result |
| --- | --- |
| d=3/5/7, N=1/2/3/4 layout matrix | Exact expected coordinates; N=3 accepted |
| Nine pre-extraction MSD worlds, d=3/5/7 and N=1/2/4 | Device, entry-state, site, atom-ID and patch data hashes unchanged; new placement metadata is separate |
| Three historical horizontal full worlds, N=1/2/3 | Device, entry-state and patch hashes unchanged; full/fast plans identical |
| Explicit placement validation | Missing/extra blocks, overlap, touching, spacing, orientation, region and forged-plan errors covered |
| Sparse N=128 layouts | Sweep validation avoids the old all-pairs exact checks; no timing threshold asserted |
| Custom explicit layout, two real SE instances | Existing physical compiler validates shared-1-AOD execution and multi-owner CZ actions |
| Real shared-AOD SE calibration | Per-member costs and applicability metadata captured from the validated physical world |
| Fast factory entry | Explicit N=3 plan used without physical compilation; fixed-seed replay and batching retained |
| Cache | Far added factories reuse local keys; relevant geometry, Device, source and spectator changes invalidate them; JSON round-trip verified |
| Related fast tests and mapped consumers | **1344 passed, 0 failed, 0 skipped**, 23.54 seconds |
| Code quality | Ruff formatting/lint passed; strict mypy passed for 18 affected production files |

The all-fast-and-slow `check` command was started and **interrupted at the user's
request**. It did not finish, and is not reported as a passing full-suite check.
The separately executed small physical checks above passed. No bench was run;
22 bench tests were deselected in the completed fast run.

Local, ignored evidence is retained under
`modules/logical_compiler/artifacts/`: `placement-fast-report.json`,
`placement-fast.log`, `placement-check.log`, and `placement-legacy-worlds.json`.
The interrupted log is partial evidence only.

## Scope of the result

d5/d7 layout generation does not imply new numerical fast calibration at those
distances. Existing d3 horizontal records cannot silently cover vertical factories
with a different common readout region. Production profiles without saved
applicability context require updated metadata. Automatic optimization, inventory
policy and arbitrary QASM-to-component execution are outside this phase.

See [the placement API](../../modules/logical_compiler/docs/placement.md) and
[ADR 0056](../decisions/0056-logical-placement-and-calibration-context.md).
