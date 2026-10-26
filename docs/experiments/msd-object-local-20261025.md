# MSD object scheduler: first local acceptance, 2026-10-25

Scope: necessary source migration and three local scheduling/control cases.
This is not a complete first-level MSD factory performance experiment.

Configuration: [object-cases.json](../../experiments/msd/object-cases.json).
Reproduction and limitations: [OBJECT_CASES.md](../../experiments/msd/OBJECT_CASES.md).
Migration provenance: [manifest](msd-object-migration.json).

Local generated results, deliberately excluded from Git:

- [Summary](../../artifacts/msd-object-local/20261025-acceptance/summary.json)
- [Representative time tables](../../artifacts/msd-object-local/20261025-acceptance/schedule.html)
- [Worker timing](../../artifacts/msd-object-local/20261025-acceptance/worker.json)
- [Exact runtime source hashes](../../artifacts/msd-object-local/20261025-acceptance/source-hashes.json)

## Observed results

All three cases completed within the 45-second wall budget. Worker wall time,
including process startup/imports, was **1.46649 seconds**. In-worker work took
**0.118227 seconds**, including **0.010727 seconds** of export. Component metadata
preparation took **0.000654 seconds**. These are software runtimes, not modeled
hardware times.

| Case | Result |
| --- | --- |
| Synchronous d3 MZ | 520 us; measurement results at 310 us; AOD held until Store at 520 us |
| Incompatible transport bands | 840 us; second member waits 320 us for the same AOD |
| Scripted retry/production fixture | Both processes complete two cycles; four output tokens consumed once; failed W2 retries locally; ten preparation/reset executions |

The retry fixture's 2888 us total is synthetic control-flow timing. It is not a
surface-code factory latency, acceptance estimate, or steady-state throughput.

Three surface-MZ templates and three separately labeled fixture templates were
prepared once. There were **165 surface lookups** and **296 fixture lookups**.
Template object identities were preserved across N, seed, retry and combination
changes. Instrumented forbidden-call counts were all **zero**:

- Physical compilation attempts: 0.
- Atom binding/expansion attempts: 0.
- Atom/program construction attempts: 0.

Process startup/imports dominate this small run's total wall time. Among timed
calculation stages, the reuse probe loop was largest at 0.050060 seconds; the
representative retry case took 0.013097 seconds. This does not establish the
bottleneck of the still-pending complete factory/probability model.

## Readout-only scaling

These rows schedule one logical MZ per factory. The allocated-atom column counts
six resident target-distance blocks per factory. No accepted-output rate is
derived from these numbers.

| d | N | Modeled single-wave time (us) | Allocated atoms |
| ---: | ---: | ---: | ---: |
| 3 | 1 | 320 | 102 |
| 3 | 2 | 520 | 204 |
| 3 | 4 | 920 | 408 |
| 3 | 8 | 1720 | 816 |
| 5 | 1 | 400 | 294 |
| 5 | 2 | 680 | 588 |
| 5 | 4 | 1240 | 1176 |
| 5 | 8 | 2360 | 2352 |
| 7 | 1 | 480 | 582 |
| 7 | 2 | 840 | 1164 |
| 7 | 4 | 1560 | 2328 |
| 7 | 8 | 3000 | 4656 |

The modeled layout is vertical, with existing 40 um gaps, 10 um grid pitch,
single AOD and readout above y=50 um. Compatible readouts share one rigid
translation; the farthest data row determines that common command. The model
does not claim a validated physical route or the best possible batching policy.

## Verification

- Initial bounded baseline: 79 passed, one import failure from the absent
  `methods.clifford` dependency in the starting commit. After tier migration,
  the 79 fast cases passed and that physical integration case was left unrun.
- Main mapped related-fast regression: **694 passed**, **0 failed/skipped**;
  **526 slow** and **22 bench** cases were collected but not selected. Pytest
  time 17.66 seconds; bounded process time 18.551 seconds.
- Final focused object suite after timeout hardening: **25 fast passed**,
  **0 failed/skipped**. This includes six additional timeout regression cases
  beyond the main related run, and rechecks the affected object paths.
- Transfer-noise migration controls: **3 fast + 2 explicitly selected small
  slow controls passed**. The rest of that slow file was not run.
- Ruff: formatting/checks passed for 54 changed/new Python files using the
  repository physical-compiler configuration.
- Strict mypy: passed for 49 changed/new non-test Python files, with explicit
  package bases and silent imported-module following. The reference's optional
  Stim/PyMatching missing-stub overrides are retained.
- `uv lock --check --offline`: passed. No installation or environment upgrade.
- Independent artifact readback checked exact source hashes, nonoverlapping
  shared-resource intervals, sequential wave boundaries, completion status and
  the absence of an error artifact.

The starting commit also lacked Load/Store Pauli configuration support already
expected by its fast comparison test. Two small reference updates repaired it;
their defaults remain zero. Empty preparation parameters preserve legacy recipe
serialization, so the four pre-existing execution golden hashes still pass
without changing assertions.

Timeout tests intentionally terminate sleeping workers, including after an early
summary exists. They verify error code/reason, last progress, no later command,
and invalidation of stale success markers. The actual acceptance run did not time
out. No bench suite, server task or animation was started. The acceptance entry
point did not perform atom-level physical validation.

Environment: Python 3.12.15, Qiskit 2.6.0, Stim 1.16.0, PyMatching 2.3.1,
NumPy 2.5.4 and pytest 9.1.1 from the existing environment.

## Remaining first-level work

The real object catalog currently covers `logical_mz`. The migrated generic
surface recipe and staged preparation implementations are available, but the
remaining component phase costs and schedule-dependent raw acceptance adapter
are not yet connected. Missing coverage fails explicitly. Complete factory
startup/steady-state throughput, full noise exposure and accepted-output cost
results remain pending; their summary fields are not fabricated from fixtures.
