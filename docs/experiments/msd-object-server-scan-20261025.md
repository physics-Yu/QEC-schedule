# Single-round object-factory server scan

Status: completed; all 180 cells / 18,000 shots passed independent readback audit.
Date: 2026-10-25. Base component/scheduler commit: `9b18380`.
Executed source snapshot: `12816435bfa0599a4c44c937a02b969b3a1e4438`.

## Authorized workload and server

The user requested d=3/5/7/9/11, N=1/2/4/6/8/10, one production round per shot,
at least 100 seeds and approximately 80 percent CPU use. The frozen
[configuration](../../experiments/msd/server-scan-d3-d11-n1-n10-100seeds.json)
uses seeds 0 through 99, both asynchronous/v1 and synchronous/v2, and every full
rectangular grid. Distances, factory count and strategy remain separate axes.

Only layouts with identical coordinates, identities and resource assumptions
are aliases: N1 has one geometry, N2 retains vertical and horizontal. N4 has
three; N6, N8 and N10 each have four, including both nonsquare orientations.
There are 18 distinct N/layout combinations, 180 parameter cells and 18,000
shots. Each shot makes exactly N complete factory attempts; final rejection
counts as a no-output result, while raw injection retries remain inside the shot.

Server: `yyq@10.133.24.178`, `ubuntu-Server-R5300-G6`, reachable over the already
active ZeroTier network `166359304ed7c7a5`. Preflight found 112 physical cores /
224 threads, about 470 GiB available memory and 413 GiB free disk. At most 89
single-thread workers use one hardware thread per selected physical core, balanced
across sockets. BLAS/OpenMP thread counts are one. Existing jobs are not resumed,
modified or terminated; only owned process groups from this scan can be stopped.

The unchanged source pilot at d11 N10, vertical, seed0, one round completed both
policies: async runtime 8.997 s / peak RSS 660220 KiB, sync 8.626 s / 634040 KiB.
Worker times were 9.833/9.405 s, with zero compiler/atom calls. Pilot source is
isolated at `/home/yyq/nadit-experiments/msd-object-scan-20261025-9b18380-pilot`.

## Statistics and interpretation

Let each seed supply duration T_i and accepted count O_i. Report all-shot means
and unbiased sample variances (denominator m-1), plus the primary production rate
`sum(O_i) / sum(T_i)` with seconds as the time unit. Also retain the distribution
of individual shot rates, which is a different statistic. Rate-estimator variance
and a 95 percent interval use the delta method on residuals O_i - r*T_i.

This is a renewal-reward estimate under independent shot restart. Synchronous
rounds can be interpreted as regenerative cycles if the modeled initial-state
conditions recur. The asynchronous shot drains every factory before restarting;
equivalence to an uninterrupted asynchronous pipeline is not established. Reports
must state this distinction rather than label short-shot averages unqualified
continuous-pipeline steady-state throughput.

For shots with no accepted output, measured startup is null, never zero. Report
conditional startup statistics and no-output frequency. Under the same renewal
assumption, first-delivery mean is `(sum(successful first-delivery times) +
sum(empty-shot durations)) / successful-shot count`; second moments follow the
geometric restart recurrence. These derived moments are separate from directly
observed conditional startup variance.

Per-output costs use `sum(resource*time) / sum(outputs)`, including resource-time
of zero-output shots. Do not average only successful-shot ratios and discard
failure costs. If all shots reject, rate is zero and per-output/startup estimates
remain unavailable. All failed or timed-out execution records invalidate the
scan; ordinary protocol rejection is a valid sample.

## Metric coverage

| Metric | Reported quantity and boundary |
| --- | --- |
| Startup | Direct conditional first delivery, no-output frequency, and renewal first-delivery estimate |
| Production rate | Pooled accepted-output/time ratio under the explicit shot-restart interpretation; shot variance and estimator uncertainty separated |
| Atoms | All six configured blocks per factory, including idle carriers: 6N(2d^2-1) |
| Area | Storage bounding width/depth/area; whole-device/readout/transport area is null because reduced objects do not carry complete swept geometry |
| Space-time | Pooled atom-us and storage-area-us per accepted output, including failed shots |
| Atom movement | Saved reference atom-distance totals plus object-model common readout lift; CNOT uses d-squared moved data and its signed displacement model |
| Command movement | Sum of each shared Move phase's limiting displacement, duration divided by the retained linear move coefficient; common commands counted once |
| Transport time | Move, Load and Store separately, plus readout versus gate movement and AOD occupied time |
| Idle/wait | Factory dispatch/barrier waits, member wave-tail/phase waits, and unassigned block-us from call occupancy intervals |
| Operation exposure | Native single-qubit/CZ/measure/reset counts, transfer/move command counts and category member-us; no new logical-error or atom-level T2 estimate |

Unassigned-block atom-us multiplies unassigned block time by configured atoms per
block; it is an occupancy proxy, not a measured atom-resolved idle/coherence history.
Global AOD busy time, per-factory waits and per-member work are different bases
and must not be summed into makespan.

The [motion reference](../../experiments/msd/object-motion-reference.json) reads
existing numeric d3/d5/d7 profiles and d9/d11 component resource records. It
retains their file hashes and exact catalog fingerprints. No atom objects are
constructed. Source path patterns are preserved, with additional common vertical
translation for readout; each such translation is weighted by its measured-atom
count. This is a documented object-model estimate, not an atomic route proof.
In the d3 two-factory shared-MZ control, command distance is 400 um while estimated
atom-summed distance is 6660 atom-um; these are intentionally different measures.

## Execution limits and retained evidence

Keep single AOD, existing timing/noise, fixed probability ports and input Z error
0.01. No physical compilation, atom construction/expansion or probability
re-estimation is allowed. Each worker loads ten objects once and reuses them
across its 100 seeds, retaining identity/cache/forbidden-call counts.

The per-shot wall limit is 20 seconds, including metric extraction and selected
trace serialization; wave planning retains 5 seconds. A 100-shot cell has an
explicit 2060-second wall limit (100 shot budgets plus startup allowance); the
whole scan has a 3600-second wall cap. The former 60-second small-local-worker
cap is replaced only for these explicitly larger 100-shot workers, not used to
silently increase individual shot or wave limits.

On the first worker failure or timeout, stop dispatch, terminate only currently
owned scan children and write the precise cell/seed/stage reason. Do not continue,
retry, resume or turn partial output into success. A fresh run directory is mandatory.
Per-seed compact JSONL includes metrics and event/invocation signatures. Save a
compressed complete seed0 trace per cell; full traces for the other 99 seeds
are reproducible from the frozen inputs rather than all retained in memory/disk.

The [scan coordinator](../../experiments/msd/scan_objects.py) is a bounded matrix
runner over the existing factory entry, not an old campaign/recovery framework.
[Metric code](../../experiments/msd/scan_metrics.py) is independent of scheduling.
Related fast tests and bounded controls apply; no bench or full slow suite.

## Results

The isolated run at
`/home/yyq/nadit-experiments/msd-object-scan-20261025-1281643`
completed in **1379.604 seconds (22.99 minutes)** with 89 workers, no failed
shots and no timeouts. Every cell contains seeds 0-99. All 3,000 matched
(d, N, seed) groups retain identical probability-event and invocation signatures
across layout/policy comparisons; all five catalog fingerprints remain unchanged.
All physical compilation and atom expansion guards remain zero.

Across 180 workers, 1,800 template objects were loaded once (ten per process),
with 41,787,058 lookups, 8,400 numeric bindings and 41,778,658 cache hits.
This is numeric catalog reuse, not repeated physical compilation. Recorded
shot execution/accounting time averages 3.833 seconds, p95 7.956 seconds and
maximum 10.107 seconds. Selected-trace serialization is additionally covered
by the worker's 20-second deadline. Summed shot and worker elapsed times are
68,988.537 and 71,490.851 seconds; these are not measured CPU seconds.
No per-function profile was collected, so the results do not identify a precise
function-level bottleneck.

For N=10 with horizontal placement, accepted outputs per second are:

| d | Asynchronous | Synchronous | Sync 95% interval | Sync / async |
| --- | ---: | ---: | --- | ---: |
| 3 | 30.846 | 69.303 | [67.536, 71.069] | 2.247 |
| 5 | 12.843 | 24.670 | [23.970, 25.369] | 1.921 |
| 7 | 9.640 | 18.698 | [18.203, 19.193] | 1.940 |
| 9 | 7.522 | 14.620 | [14.226, 15.014] | 1.944 |
| 11 | 5.672 | 11.252 | [10.962, 11.542] | 1.984 |

Horizontal placement has the highest N=10 rate in this model. Its unlimited
horizontal extent trades width for shorter readout movement; this is not a
hardware-optimality claim. More factories do not guarantee higher rate:
d11 vertical asynchronous falls from 2.017/s at N1 to 1.777/s at N10 (11.9%).
No decoded output-error comparison or output-quality matching is implied.

## Report and reproducibility

The local result root is `artifacts/msd-object-server/20261025-scan-1281643/`.
Generated artifacts are intentionally excluded from Git:

- [Complete HTML report](../../artifacts/msd-object-server/20261025-scan-1281643/report/index.html): all 180 cells, metric filters, means/variances, uncertainty and nine scaling figures.
- [Full schedules](../../artifacts/msd-object-server/20261025-scan-1281643/report/schedules/index.html): twelve actual seed0 traces, including both policies at every d and the d11 vertical congestion case.
- [Metric table](../../artifacts/msd-object-server/20261025-scan-1281643/report/cell-summary.csv) and [all shot records](../../artifacts/msd-object-server/20261025-scan-1281643/report/all-shots.jsonl.gz).
- [Independent audit](../../artifacts/msd-object-server/20261025-scan-1281643/report/audit.json): coverage, signatures, fingerprints and frozen configuration.

All 180 seed0 full traces remain on the server. Twelve selected traces were
downloaded; their render audits verify counts, homogeneous waves, single-AOD
exclusion and per-factory time accounting. Compact results and representative
archives were SHA256 checked after download:

- Source archive: `dd5835d0ac98fe73f31679da02c370924e8ea80c879ecd21fe0e123c8eedb824`.
- Compact results: `26f069e59b5df4fcf0f0bbdcc73662fcd811de930b1df2635299a3958663af03`.
- Selected traces: `5bab8547ce59e62ba5279992abe5f2bcf7736902ec5f0e77353acb6896c5ca8b`.

Rebuild analysis into a fresh directory without running any factory:

```sh
python -m experiments.msd.report_object_scan --input artifacts/msd-object-server/20261025-scan-1281643/download/run --output artifacts/msd-object-server/rebuilt-report
```

The analysis builder writes figures, statistics and HTML; schedules are rendered
separately from decompressed selected `representative.json.gz` records:

```sh
python -m modules.logical_compiler.examples.factory_schedule --case saved-case.json --output new-schedule.html
```

The supplied report includes the populated `schedules/index.html`; copying or
rendering those schedules is necessary when assembling a new report directory.
Neither report command executes factories or compilers.

Verification: 485 mapped related fast tests passed; the direct case-runner tests
passed 15 before the runtime commit and 16 after adding report-statistics checks.
Ruff formatting/lint and targeted mypy passed. No bench or full slow suite was run,
following the task's explicit test scope over the generic full-suite rule.

### Figure revision: common scales and transposed axes

The revised report provides 18 figures: nine metrics in each of the N-axis /
d-legend and d-axis / N-legend projections. Every metric uses the same y limits
and ticks across all layouts, both policies and both projections. The upper limit
includes the largest 95 percent interval endpoint; the lower limit is zero.
Two-column/two-row grids only show existing N>=4 configurations.

Readback confirmed that all 180 atom-count and storage-area estimates have zero
seed variance. Each of the other seven plotted metrics has 180 nonzero intervals
and no missing uncertainty. Atom-summed movement interval halfwidths are only
0.036759-0.709879 percent of the mean; these can be visually smaller than a marker.
The bars represent estimate +/- 1.96 standard errors, not shot standard deviations.
Hollow markers and bars drawn above them improve visibility without inflating
uncertainty. Unknown uncertainty is represented separately, never as a zero bar.

`plot-audit.json` records zero/nonzero/missing intervals, relative halfwidth ranges,
panel limits and ticks. Related fast tests increased from 16 to 17, including
projection selection, zero versus missing uncertainty and common-limit checks.
No experiment or probability computation was repeated for this revision.

Deliverables: [revised report](../../artifacts/msd-object-server/20261025-scan-1281643/report-v2/index.html)
and [single-file offline report v2](../../artifacts/msd-object-server/20261025-scan-1281643/NADiT-MSD-report-single-file-v2.html)
(55,494,801 bytes), including all twelve complete schedules. Packaging checks
verified all 71 embedded files against their originals and all 68 local links.
Aggregate JSON and metric CSV are byte-identical to the initial report.

### Figure revision v3: independent panel scales

The user superseded the common-scale preference because it obscured smaller
curves. Each layout/policy panel now fits its own data and 95 percent interval
endpoints, retaining a zero lower bound and eight percent upper headroom.
Both axis projections, interval semantics and the underlying statistics remain
unchanged. Cross-panel comparisons must use tick values rather than visual height.
All 17 related fast tests pass, including independently fitted panel limits.
The revised standalone deliverable is
[single-file report v3](../../artifacts/msd-object-server/20261025-scan-1281643/NADiT-MSD-report-single-file-v3.html).
