# Generic fast factory acceptance experiment

**Withdrawn as parallel-factory acceptance.** The adapter in `976ef72` incorrectly
assigned whole-component exclusive AOD leases to independent factory modules.
Calling that behavior a conservative estimate did not satisfy the requested
shared-device parallel interface. Its tables remain historical evidence only.
Use the corrected [joint factory experiment](JOINT_FAST_FACTORY.md); independent
AOD controls cannot substitute for that experiment.

The factory adapter accepts any odd distance `d >= 3` and any positive integer
module count `N`. It reuses the fast logical compiler introduced by `852fd73`:
`ProfileExecutionKernel`, `FactoryProcess`, `CooperativeFactoryRuntime`,
`ComponentScheduler`, and the existing resource ledger. There is no second
factory scheduler. The fixed experimental grid is d3/5/7 and N1/2/4; synthetic
control tests additionally exercise N3/N7 and the d9 recipe. Larger calibrated
grids are supported but were not measured here.

## Frozen standard

Factories run top to bottom; their W1..W5,R patches run left to right. Storage
and gates occupy the lower half-plane, readout the upper half-plane, with a
50 um transport gap. The existing finite enclosing execution window implements
these unbounded operating domains; its area is not a hardware footprint.

| Operation | Duration |
| --- | --- |
| SLM to AOD LOAD | 10 us |
| AOD to SLM STORE | 10 us |
| Measurement | 100 us |
| Classical processing | 0 us |
| CZ | 0.5 us |
| Rotation | 1 us |
| Reset | 5 us |
| Movement | 1 us/um |

Use the unchanged `noise_illustrative.json`. Injection takes three total SE
rounds at d3. Only accepted injections grow to target d, using d ordinary SE
rounds including deformation, without postselecting growth outcomes. Target d3
does not grow. The real code-owned S implementation is included. Each accepted
preparation also pays a calibrated one-Pauli-layer correction envelope; an
identity decoder correction can be cheaper. This is a resource envelope, not a
sampled noisy frame.

The complete existing 4+11 recipe retains 15 accepted inputs, 59 logical CNOTs,
11 consumption MZs, conditional S, four final MX checks and accepted-output X.
No SE rounds are silently added after every CNOT. The original recipe does not
establish a complete fault-tolerant EC policy for a noisy production factory.

## Calibration and concurrency

Each profile covers 33 operation/role variants per module, explicitly compiled
and bound in the complete spectator world. Coverage includes absolute position,
ordered participants, distance and preparation parameters. Missing coverage
fails rather than compiling during a fast run. Binary injection acceptance uses
65,536 shots per position, seed 20261024, and retained Wilson intervals. It does
not supply an accepted-state logical error rate.

Two resource policies are exposed:

- `shared_aod`: the original one-AOD budget. Every transport-bearing component
  reserves the AOD until return-home. This intentionally conservative model
  cannot represent joint atom batching across components. Its growth with N is
  not evidence that the hardware must serialize complete factories.
- `independent_aod_control`: one AOD per module plus independently addressable
  gate/readout control. Disjoint components with different durations can overlap.
  This changes the hardware budget and retains the existing coordinator's wave
  barriers; it is not a same-budget speedup or an optimum schedule.

The new `profile_parallel` contract is estimation-only and is rejected by the
physical execution kernel. Full noisy joint factory execution remains open.

## Sampling and result interpretation

The committed plan fixes 16 seeds (0..15), one batch per factory, at most eight
attempts per raw input, and accepted-input iid Z error p=0.01. Final acceptance
uses the existing ideal-Clifford 15-to-1 reference model. The same assumed p
across d is a controlled comparison, not a measured or matched physical LER.
Aborted input supply and rejected final batches remain in time/output totals.

Mean makespan is the mean duration of the entire finite N-factory trajectory.
Output rate is total accepted outputs divided by total modeled elapsed time.
It is not steady-state throughput or mean latency conditional on success.
Allocated spacetime is all allocated atoms times elapsed time, including idle
spectators. Operation work categories may overlap and must not be summed as
elapsed time. Software execution time excludes profile loading and file export.

## Measured results (2026-10-24)

The 288 seeded trajectories completed. All 18 seed-0 schedules passed an
independent audit of 4,940 execution calls, exclusive resources, patch occupancy,
event dependencies, accepted-only growth, single-use input tokens, exported CSV
times, paired control outcomes, and aggregate output/time arithmetic.

| d | N | Shared AOD mean ms (conservative) | Independent hardware mean ms | Shared outputs/s | Independent outputs/s |
| --- | --- | --- | --- | --- | --- |
| 3 | 1 | 91.522 | 91.522 | 10.243 | 10.243 |
| 3 | 2 | 198.872 | 118.792 | 8.485 | 14.206 |
| 3 | 4 | 463.595 | 169.892 | 6.876 | 18.762 |
| 5 | 1 | 220.326 | 220.326 | 4.255 | 4.255 |
| 5 | 2 | 513.879 | 314.363 | 3.284 | 5.368 |
| 5 | 4 | 1340.213 | 515.046 | 2.378 | 6.189 |
| 7 | 1 | 278.178 | 278.178 | 3.370 | 3.370 |
| 7 | 2 | 677.947 | 426.117 | 2.489 | 3.960 |
| 7 | 4 | 1804.238 | 726.797 | 1.767 | 4.386 |

These are diagnostic finite-sample means, not precision yield estimates. Both
hardware policies use identical seeds and produce identical sampled branch
outcomes: 15/16, 27/32 and 51/64 accepted outputs for N1/2/4 respectively at each
distance. The final acceptance probability is fixed by the reference model, not
estimated from physical faults. Single-factory atom counts are 102, 294 and 582.
Mean software runtime per trajectory ranges from 0.095 to 0.804 seconds; the
average across the grid is 0.336 seconds. One-time physical calibration ranges
from 4.8 seconds (d3,N1) to 2411.6 seconds (d7,N4), and is excluded from fast-run
timing. This calibration cost is the present large-grid bottleneck.

Single-factory mean movement work is 61.594, 141.210 and 186.743 ms for d3/5/7,
about 64-67% of elapsed time; LOAD/STORE work adds 19.860, 47.766 and 56.955 ms.
Movement and transfer dominate the current calibrated implementation. The raw
injection protocol is fixed, but the complete spectator geometry can change its
transport batching and exposure. For N4, R-port acceptance at the first/last
factory is 78.18%/77.86% (d3), 77.75%/76.66% (d5), and 77.75%/76.25% (d7), with
roughly +/-0.32 percentage point Wilson half-widths. These modest differences
come from calibrated injection trajectories, not postselection of d growth rounds.

### Actual shared-world joint SE control

To distinguish genuine parallel capability from the fast model's conservative
lease, the existing physical compiler compiled one W1 SE per factory in a
single DAG, all ready at t=0, under the same one-AOD device and full spectator
world. A serial barrier control uses the same sources and geometry. Full physical
replay validates both controls and return-home completion; measurements remain
compiler fixtures, not quantum samples.

| d | N | Joint round ms | Serial control ms | Joint readout movement ms |
| --- | --- | --- | --- | --- |
| 3 | 2 | 0.989 | 1.778 | 0.420 |
| 3 | 4 | 1.389 | 4.355 | 0.820 |
| 5 | 2 | 1.149 | 2.018 | 0.580 |
| 5 | 4 | 1.709 | 5.155 | 1.140 |
| 7 | 2 | 1.309 | 2.258 | 0.740 |
| 7 | 4 | 2.029 | 5.955 | 1.460 |

All six joint cases have 13 shared transport batches and overlap all selected
factories. The elapsed partition outside readout movement is identical:
568.817 us, including 100 us readout exposure. Thus the d/N dependence of these
joint SE cases comes entirely from the readout trip, not repeated gate or
measurement duration per factory. This demonstrates that whole-component AOD
serialization substantially overstates SE cost. It does not provide a universal
correction factor for the complete factory, whose operations and rejection
branches differ between modules.

The next improvement is calibrated joint-component admission (including mixed
frontiers) in the fast profile, with phase-level resource claims checked against
real joint traces. The second is safe reuse of equivalent complete-world
calibrations. Simply dropping AOD exclusion would produce unvalidated schedules.
Two-level routing, sustained production and physical output-error matching are
outside this acceptance batch.

## Reproduction and inspection

Run from this checkout with its physical compiler source first on `PYTHONPATH`.
Use the existing Python 3.12 environment and single-thread numerical libraries.
Output directories must be new, preserving prior evidence.

```powershell
$env:PYTHONPATH="$PWD/modules/physical_compiler/src;$PWD"
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$py='C:/Users/yuyqp/Documents/ChatGPT/NADiT/modules/physical_compiler/.venv/Scripts/python.exe'
$out='modules/physical_compiler/artifacts/generic-factory-reproduction'
foreach ($d in @(3,5,7)) {
  foreach ($n in @(1,2,4)) {
    & $py -m experiments.msd.generic_factory calibrate --distance $d --factories $n --output "$out/profiles/d$d-n$n"
    if ($LASTEXITCODE -ne 0) { throw 'Calibration failed' }
  }
}
& $py -m experiments.msd.generic_factory scan --profiles "$out/profiles" --output "$out/results"
& $py -m experiments.analysis.audit_generic_factory "$out/results"
& $py -m experiments.analysis.generic_factory_report "$out/results"
```

`time-schedules.html` contains all 18 seed-0 witnesses. Select distance, N and
hardware; inspect AOD and patch lanes, zoom, and click a component for exact
start/end/result-ready times. Adjacent CSVs and case JSON retain every call and
event. These are component schedules, not atom animations. Source/profile hashes,
raw probability evidence and full spectator worlds are retained in local artifacts.

The first campaign uses `modules/physical_compiler/artifacts/generic-factory-20261024`.
Compact tracked evidence is in [results/generic-fast-20261024](results/generic-fast-20261024/summary.json):
[scaling plot](results/generic-fast-20261024/scaling.png),
[schedule audit](results/generic-fast-20261024/audit.json),
[calibration evidence](results/generic-fast-20261024/calibration-summary.json), and
[actual joint/serial SE controls](results/generic-fast-20261024/joint-se-summary.json).
The interactive [local time schedules](../../modules/physical_compiler/artifacts/generic-factory-20261024/results/time-schedules.html)
and full cases remain generated artifacts; the commands above recreate them.
Calibration sources were frozen throughout. The only calibration-to-scan source
change fixes the CSV export to read kernel execution calls, rather than protocol
records; calibration and scheduling code are unchanged. `campaign-manifest.json`
records both identities. Reproduction may therefore have a different aggregate
source hash while preserving this documented physical implementation.

See [ADR 0056](../../docs/decisions/0056-generic-fast-factory-resources.md) for
interface ownership and [testing.md](../../docs/testing.md) for test tiers.

## Verification

The final unscoped `python -m tools.testing.run check` completed with 840 fast
and 2520 slow tests passed, zero failures/skips, and 14 bench tests not run
(459.66 seconds). The export regression first failed on protocol-call fields,
then passed after switching to kernel execution records. Its related fast
selection passed 6 tests. Earlier affected-component/runtime checks also passed;
the final full check includes their consumers.

Scoped Ruff checks and strict mypy checks on eight runtime files passed. New
documentation links and diff whitespace passed inspection. Two pre-existing
links in the legacy fast-experiments document refer to generated artifacts not
copied into this isolated checkout; their source text is unchanged. The time
schedule UI was checked for case selection, zoom/reset, and exact call details.
This is software/UI verification, not user sign-off or hardware execution.

The test workflow from `83ed2a8` is integrated on this branch, with current code
and experiment tests mapped to tiers and consumers. The baseline includes fast
compiler commit `852fd73`. Existing worktrees and their uncommitted edits are
preserved.
