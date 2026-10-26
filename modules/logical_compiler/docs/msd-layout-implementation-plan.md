# MSD Whole-Factory Layout Implementation Plan

Date: 2026-10-25.
Task: MSD-LAYOUT-01.
Status: layout interface and d3 N4 local comparison implemented; d5/d7 and N8 deferred.
Implementation baseline: `codex/msd-object-scheduler` at `cb3a089`.

Prerequisite correction: use synchronous/v2 production rounds from ADR 0053.
The original baseline's accepted-output epoch barrier is superseded. The corrected
production data was accepted before the user authorized this d3 N4 layout comparison.

## Goal and contract

Compare vertical, horizontal and 2D whole-factory layouts using asynchronous
and synchronous object scheduling, one shared AOD, and unchanged precomputed
probability fake backends. Implement
[ADR 0054](../../../docs/decisions/0054-msd-layout-cost-comparison.md) through
the existing catalog, placement, scheduler and report interfaces.

The user subsequently authorized d3 N4, vertical/horizontal/2x2 and both policies.
The [local report](../../../docs/experiments/msd-object-layout-d3-n4-20261025.md)
records the completed twelve cases (seeds 0/1), checks and full schedules.
Further distances and factory counts are not part of this implementation run.

## File ownership

Paths are repository-relative. Edit them only when their step begins; avoid
unrelated refactors and new orchestration frameworks.

| Path | Planned responsibility |
| --- | --- |
| `modules/logical_compiler/examples/factory_objects.py` | Placement configuration, paired metadata, accounting and reuse/runtime output |
| `modules/codes/rotated_surface/object_factory.py` | Forward layout selection; preserve recorded numeric cost binding and caches |
| `modules/codes/rotated_surface/object_readout.py` | Build the selected whole-factory placement through existing placement contracts |
| `modules/logical_compiler/src/placement/strategies.py` | Reuse existing grid/vertical strategies; no new placement algorithm planned |
| `modules/logical_compiler/examples/factory_schedule.py` | Layout plot, full schedule and unambiguous geometry/wait labels |
| `experiments/msd/` | Later reproducible paired local configurations and usage documentation |
| `modules/logical_compiler/tests/`, `modules/codes/rotated_surface/tests/` | Existing relevant test owners; confirm exact test selection/mapping before edits |
| `docs/experiments/` | Later measured results, provenance, limitations and links to complete schedules |

Keep strategy/barrier semantics and probability ports unchanged. Do not change
the physical compiler or regenerate component source records for this task.
Any newly discovered scheduler/model gap must be described before expanding scope.

## 1. Placement selection and backward compatibility

Status: implemented and verified with existing grid placement.

- Thread an optional placement selection through the estimator/catalog chain;
  omitted selection remains vertical. Define the serialized option and explicit
  grid column count in the implementation step, using existing placement types.
- Preserve IDs, role order, geometry versions and default coordinates. Reject
  invalid options with context; never silently use another layout or code distance.
- Test N=1 degeneracy, N=2 grid aliases, N=4 rectangular coordinates, spacing,
  bounds and fingerprints. Geometry/placement tests use block metadata only.

Acceptance: existing default results remain unchanged; every selected layout
has validated nonoverlapping home footprints and stable factory/block identities.

## 2. Numeric cost binding and common-resource controls

Status: implemented and verified; no scheduler or cost-record changes required.

- Verify vertical movement changes with depth while horizontal translation
  preserves intrinsic costs and signed internal CNOT displacement.
- Exercise compatible same-component sharing and incompatible resource groups
  on the single AOD, including both CNOT endpoints and sufficient readout lift.
- Check raw retry offsets and conditional S+SE joins under both policies.
  No successful raw state is resampled; no different-component overlap is added.
- Reuse one fixed catalog across N, seed, retries and layouts. Distinguish cheap
  numeric binding misses from component construction; retain forbidden-call guards.

Acceptance: homogeneous waves, legal modeled resource intervals, unchanged
component templates/probability inputs, zero physical compiler/atom calls, and
separately accounted resource, barrier and wave-tail waits. Small fixtures may
test scheduler contracts but cannot replace complete factory acceptance results.

## 3. Reports and bounded local paired acceptance

Status: d3 N4 six-condition comparisons implemented for seeds 0/1. N1/N2 layout
degeneracy and paired real-factory controls use seed 1 and one round in fast tests;
the previous full vertical controls remain recorded separately. D and N8 are deferred.

| Order | Cases | Purpose |
| --- | --- | --- |
| A | d3, N1, both policies, seeds 0/1 | Layout aliases and policy equivalence control |
| B | d3, N2, vertical/horizontal, both policies, seeds 0/1 | Genuine geometry change; identify duplicate grid aliases |
| C | d3, N4, vertical/horizontal/2x2, both policies, seeds 0/1 | First full six-condition comparison per seed |
| D | d5/d7 equivalents, only after A-C pass within budget | Recorded-distance coverage |
| Later | N8, including 4x2 and 2x4 | Deferred extension, not initial acceptance |

Each run completes two attempted production rounds per factory under both
policies, with `production_basis="production_rounds"`, input Z error 0.01, raw
attempt limit 32, batch attempt limit 16, case limit 20 seconds, wave limit
5 seconds and worker wall limit 60 seconds. Do not increase limits silently.
Successful outputs are delivered immediately; final rejection is a normal
no-output round. Both factories proceed to the next round, with no per-factory
success quota. Batch retry limits apply only to the legacy accepted-output mode;
raw retry limits remain active. Stop at the first runtime failure/timeout, preserve diagnostic evidence and report
configuration, last stage, elapsed time and cause; do not start the next case.

Acceptance: paired semantic events/outcomes and invocation/operation counts
match; all ADR 0054 metrics, model hashes, configuration and software runtimes
are saved. Provide layout views and complete HTML schedules with a linked
comparison index. Report unavailable full-device area/steady-state/decoded-error
metrics explicitly. Retain prior artifacts and use new output directories.

## Verification policy and completion evidence

Follow [agent.md](../../../agent.md) for small verifiable steps and commits.
Pure documentation uses document checks under
[docs/testing.md](../../../docs/testing.md). Later implementation runs a relevant
fast baseline, meaningful regression tests first, related fast consumers and
the bounded local cases above. The user's task-specific restriction in ADR 0052
overrides blanket full-suite/all-fast-plus-slow checks: no bench, full slow suite,
physical compilation or server run. Report this exception when implementation starts.

Close each step only with the actual changed files, executed checks and outcomes,
commit, runtime/reuse evidence and remaining limitations. Complete task closure
requires the real-factory local acceptance artifacts; documentation alone does
not establish implementation, performance improvement or physical correctness.
