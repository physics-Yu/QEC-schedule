# MSD object batching correction and server rerun

Source commit: `5d49f4fd989b12cdc978446678e2ede33d5a0385`.
Configuration: [factory-objects-d3.json](../../experiments/msd/factory-objects-d3.json),
unchanged: d=3, N=1/2, seeds=0/1, two accepted cycles per factory, one AOD,
raw probability `51235/65536`, theoretical accepted-input p=0.01.

## Results

The final run executed on `10.133.24.178` (`ubuntu-Server-R5300-G6`) in the
new directory
`/home/yyq/nadit-experiments/msd-object-scheduler-20261025-5d49f4f`.
Previous server jobs and results were not resumed or modified. The existing
Python environment was reused without installation or dependency changes.

The comparison baseline is the saved `20261025-full-d3-v2` result. The same
configuration, component input and semantic seeds were retained. All **443
event occurrences** produced the same outcomes as before; all 1,544 invocation
IDs were preserved. Raw attempts, raw rejection, final rejection and accepted
output counts are unchanged. This isolates the schedule changes from different
random outcomes.

| N | Seed | Accepted outputs | Before ms | After ms | Reduction |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 2 | 182.950904 | 181.018904 | 1.056% |
| 1 | 1 | 2 | 164.964706 | 163.032706 | 1.171% |
| 2 | 0 | 4 | 334.840768 | 312.989714 | 6.526% |
| 2 | 1 | 4 | 457.437288 | 445.059592 | 2.706% |

| N | Seed | Raw attempts / rejects | Final rejects | First accepted output, after (ms) |
| ---: | ---: | --- | ---: | ---: |
| 1 | 0 | 47 / 17 | 0 | 89.886371 |
| 1 | 1 | 36 / 6 | 0 | 79.024531 |
| 2 | 0 | 84 / 24 | 0 | 148.940192 |
| 2 | 1 | 107 / 32 | 1 | 131.047537 |

These are finite production makespans, not steady-state throughput. The N=2
cases produce four outputs; the N=1 cases produce two. The remaining large
transport cost has not been removed or relabeled as free parallel execution.

## What changed

1. Final independent MX calls now enter the existing cooperative child-flow
   join together. Joint feedback still waits for all four original receipts.
   Only homogeneous, disjoint-role `object_wave` calls use this path; dependent
   calls and physical/legacy profile execution retain their existing ordering.
2. Congruent commands may share one AOD across compatible two-dimensional home
   bands. The earlier common-x/common-y restriction is removed. All participants
   must fit aligned or separated 64 um home bands, whole-call claims must not
   overlap, and signed relative CNOT geometry must match. Different signed
   displacements or partially overlapping bands still queue.
3. A reusable standalone HTML renderer reads saved traces. It displays the whole
   production interval, unique AOD use, waits, outputs and all phase records;
   an optional matching baseline adds before/after timing. It runs no backend.

The grouping contract is an object-level cost applicability rule, not proof of
atomic routes or collisions. The raw fake-backend probability is not recalculated
as a function of the changed schedule.

The small controls changed as follows:

| Control | Before us | After us |
| --- | ---: | ---: |
| Initial 2-by-4 raw group | 5205.904943 | 2974.452471 |
| Translated equal-displacement CNOT pair | 476.000 | 240.500 |
| Partially offset MZ columns | 840.000 | 840.000 |

Different signed CNOT displacements still compete for one AOD; overlapping
home claims still prevent joint admission. The first two controls were observed
failing before their implementation changes, then passed.

For N=2, seed=0, final MX goes from **16 single-member waves to four four-member
waves**, reducing its wave charges from 6.752 to 1.688 ms. The complete run goes
from 324 to 310 waves. CNOT cross-factory shared-command waves increase from 21
to 32. Raw and CNOT wave totals are still 146.820 and 120.477 ms. AOD occupancy
is 306.840 ms, 98.04% of elapsed time under this model. Different-displacement
transport, dependencies and rejection offsets still limit common commands;
the result is not a claim of optimal scheduling.

## Runtime, reuse and validation

- Starting focused baseline: **31 fast passed**, 2.51 s.
- Final mapped related regression: **531 fast passed**, 12.85 s pytest time,
  13.492 s bounded subprocess time; 138 slow and 9 bench deselected.
- Ruff format/check passed for all six changed/new Python files; strict mypy
  passed for the three changed/new production Python modules.
- Local full small acceptance: 4.492 s worker time, no timeout.
- Server final acceptance: **5.555 s worker time**, **6.429 s total invocation**;
  in-worker work 4.636 s. These nested timings must not be added together.
- Ten component templates retained their identities. There were 4,892 lookups,
  4,862 geometry-cache hits and 30 numeric binding misses. The extra 52 lookups
  are the four capability checks in each of 13 attempted batches.
- Instrumented physical compilation, atom binding/expansion and atom construction:
  **0 / 0 / 0** on the server.
- Independent trace audit checked homogeneous waves, conflict-free resource
  intervals, final four-MX joins, unchanged event outcomes and invocation IDs.
- All 776 transferred source files were hash-verified before execution. Local
  and server runtime source hashes match. The config SHA256 is
  `1f3a8ffdbbd0e0743934eabe561e03587d3481ebaab98ba607ea350bca00b414`;
  source archive SHA256 is
  `9d85d0d5e46b9db6dcaab0165b8aefd5cdb6d41d467f4af3cc57036009875190`.

Local and server schedules, event times, sampled outcomes and layouts match
exactly. Full case JSON is **not byte-identical**: the existing theoretical
T-consumption port's `magic_density.imag` off-diagonal values differ by one ULP
(`5.551115123125783e-17`) between Windows and Linux complex exponentiation.
This changes the port document hash. Its branch probabilities remain exactly
0.5/0.5; raw probabilities and all other port content are unchanged. The sampler
uses seed and occurrence, not that document hash. The comparison records both
original hashes/values and verifies complete trace equality after this precise
metadata normalization; it does not silently drop probability differences.
No source or probability input was altered to hide the difference.

Budgets remained 20 s per production case, 5 s per component wave and 60 s per
worker. A 70 s server process-group guard also bounds entry startup/shutdown.
All commands completed normally. Existing timeout regressions verify termination,
error reason/last-stage recording and invalidation of partial success. No automatic
retry or continued scan after timeout is introduced.

## Artifacts and reproduction

Local copies of verified server results (ignored by Git):

- [Complete N=2 seed=0 schedule with before/after](../../artifacts/msd-object-local/20261025-parallel-fix-server/complete-schedule.html).
- [N=1 seed=0 schedule](../../artifacts/msd-object-local/20261025-parallel-fix-server/d3-n1-seed0-schedule.html).
- [N=1 seed=1 schedule](../../artifacts/msd-object-local/20261025-parallel-fix-server/d3-n1-seed1-schedule.html).
- [N=2 seed=1 schedule, including final rejection](../../artifacts/msd-object-local/20261025-parallel-fix-server/d3-n2-seed1-schedule.html).
- [Before/after audit and explicit cross-host metadata differences](../../artifacts/msd-object-local/20261025-parallel-fix-server/before-after.json).
- [Server summary](../../artifacts/msd-object-local/20261025-parallel-fix-server/summary.json).
- [Server runtime/environment](../../artifacts/msd-object-local/20261025-parallel-fix-server/server-environment.json).
- [Source manifest](../../artifacts/msd-object-local/20261025-parallel-fix-server/source-manifest.json).

The server reused Python 3.12.3 with NumPy 2.5.4, Qiskit 2.6.0,
qiskit-qasm3-import 0.6.0, Stim 1.16.0 and PyMatching 2.3.1. Those packages were
already installed; no physical compile or simulation was invoked.

To reproduce in the frozen server source directory, choose a fresh output path:

```bash
cd /home/yyq/nadit-experiments/msd-object-scheduler-20261025-5d49f4f/source
export PYTHONPATH="$PWD:$PWD/modules/physical_compiler/src"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
/usr/bin/timeout --signal=TERM --kill-after=2s 70s \
  /home/yyq/nadit-experiments/msd-single-aod-20261025/package-l2-scan-3600-85f5479/source/modules/physical_compiler/.venv/bin/python \
  -m modules.logical_compiler.examples.factory_objects \
  --config experiments/msd/factory-objects-d3.json --output ../reproduction-new
```

The same module/config can run locally using the existing Python 3.12 environment.
Generate the standalone HTML from saved files, without rerunning production:

```text
python -m modules.logical_compiler.examples.factory_schedule
  --case NEW/d3-n2-seed0.json
  --baseline-case artifacts/msd-object-local/20261025-full-d3-v2/d3-n2-seed0.json
  --output NEW/complete-schedule.html
```

The task-specific test scope remains related fast and bounded local controls;
no full slow suite, bench, old campaign recovery or unrelated server scan ran.
