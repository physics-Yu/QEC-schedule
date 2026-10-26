# Shared-AOD joint factory experiment

Status: nine single-AOD witness cases completed and independently audited at
`c7b484c`, before mandatory final-MX batching was integrated.
Previous whole-component-exclusive results are withdrawn as parallel acceptance.

The integrated runtime from `7293379` submits all four independent final MX
calls per factory together. The tables below remain frozen historical evidence,
not timings for that updated runtime. Profiles must cover the complete final
frontier (up to 4N members); old per-role coverage raises
`MISSING_JOINT_CALIBRATION` rather than splitting the frontier or summing old
costs. Synthetic interface regressions verify this rule and shared timing,
but do not replace renewed physical calibration for updated performance claims.

This experiment uses the original single shared AOD, vertical factory placement,
lower storage/gate half-plane, upper readout half-plane and 50 um gap. LOAD and
STORE take 10 us, measurement 100 us and classical processing 0 us. Other timing
and `noise_illustrative.json` parameters remain unchanged. Injection postselects
three d3 SE rounds; accepted states then grow with ordinary d-round target SE.

`JointSurfaceFactoryProfile` extends the existing shared-AOD admission interface
and fast logical kernel. Actual mixed frontiers are jointly compiled offline,
with the complete spectator world, and then replayed as frozen cost profiles.
Only missing calibration stops execution; it does not silently force serial
calls or introduce independent AOD hardware. Actual within-wave conflicts are
resolved by the physical scheduler and retained in the trace.

The single-AOD cohort stage barriers are retained as the user-selected grouping
strategy. Multi-AOD independent progression is paused. The abandoned independent-
frontier diagnostic directory is explicitly invalidated and is not acceptance
evidence. The acceptance grid uses seed 0 for d3/5/7 and N1/2/4, as recorded in
`joint_factory_plan.json`; these are complete representative schedules, not
finite-sample average throughput estimates.

The experiment CLI is `python -m experiments.msd.joint_factory --base-profile
<single-component-profile.json> --output <new-directory>`. Existing singleton
profiles provide carrier identities and component result contracts, not joint
timing or joint raw acceptance. The CLI calibrates uncovered frontiers explicitly,
freezes the resulting profile, then runs the selected seeds again through the
fast kernel without invoking physical compilation. The default seed set is
0..15, and acceptance calibration uses 65,536 shots at seed 20261024. Seed/shots
overrides are diagnostic controls and must be labeled accordingly.

See [ADR 0057](../../docs/decisions/0057-joint-factory-profile-admission.md).

## Results

Complete finite batch duration, including raw retries, growth, recipe gates,
measurements, conditional S and final acceptance (seed 0, milliseconds):

| Target d | N=1 | N=2 | N=4 |
| --- | --- | --- | --- |
| 3 | 80.217 | 112.008 | 155.062 |
| 5 | 184.905 | 307.331 | 524.120 |
| 7 | 236.660 | 408.916 | 725.685 |

Each distance produced 1, 2 and 3 accepted outputs for N1/2/4 in this witness.
The N4 final rejection remains in elapsed time. These are single seeded complete
cycles, not expected times, precision yield estimates or steady-state rates.
Final checks use the unchanged ideal-Clifford reference with assumed accepted
input Z error p=0.01; physical output-error quality is not established.

This is the complete existing factory recipe. Its preparation, growth and
measured-S SE are retained; no additional SE is inserted after each logical CNOT.
General noisy frame propagation, a separately qualified fault-tolerant EC policy,
two-level factory routing and steady-state production are not supplied by this
acceptance batch. The preparation correction-layer resource envelope is explicit.

The first all-factory R raw-A wave contains three d3 injection SE rounds and 24
check outcomes per factory. Its actual joint duration is:

| Target d | N=1 ms | N=2 ms | N=4 ms | Cross-factory shared transport batches (N>1) |
| --- | --- | --- | --- | --- |
| 3 | 2.374 | 2.974 | 4.174 | 39 |
| 5 | 4.602 | 7.122 | 12.162 | 57 |
| 7 | 4.602 | 7.842 | 14.322 | 57 |

All selected N2/N4 raw waves have peak active factory count N, with concurrent
native activity throughout the wave. A single shared AOD transports atoms from
multiple factories in the same batches. This is checked from atom actions,
not inferred from overlapping component spans.

At fixed d, all measured raw-wave time partitions except readout movement are
unchanged across N. For d7,N4, 11.460 ms of 14.322 ms is readout movement;
readout exposure is 0.900 ms, gate-related transport is 1.693 ms, and the other
0.269 ms contains resets, rotations, CZ pulses and readout transfers. The
increase with N in these waves comes from the longer vertical readout trip,
not multiplying gates or readout exposures by N. This attribution applies to
the displayed raw wave, not automatically to the entire factory trajectory.

The embedded d3 seed in d5/d7 target worlds uses nine physical readout batches
over three SE rounds, versus three batches in the d3 world. The duration per
measurement batch is still 100 us. The viewer distinguishes readout batches
from syndrome rounds. Investigating whether those extra batches can be reduced
with a validated single-AOD route is a concrete next improvement; no such
optimization is claimed here.

Raw acceptance was recalculated on each joint trace. In the displayed N4 R
wave, each factory has estimated acceptance 0.778610 (d3), 0.766586 (d5), or
0.762512 (d7), from 65,536 samples per port. Full Wilson intervals and channel
proofs are retained. Earlier singleton probabilities are not reused for the
joint exposure. Growth outcomes are never postselected.

## Evidence and inspection

The campaign contains 301 distinct validated joint-frontier calibrations and
2,464 logical component calls across nine witnesses. The independent auditor
reconstructs each member's activity, primitive counts, measurement phases,
aggregate resource peaks and factory overlap directly from serialized atom
actions. It also checks exact trace hashes, return-home world equality, timing,
group membership, event availability and accepted-only growth.

The interactive viewer offers the joint raw-A wave, accepted target growth/SE,
and the complete factory cycle. Raw-A/growth views show actual native activity;
the complete-cycle view shows component spans, including waiting inside a wave.
Time axes are relative to the selected
window, while clicked details show absolute microseconds. Component and native
activity CSVs retain the source group key. Full atom traces remain available in
each cell's `groups/` directory.

- [Interactive local schedules](../../modules/physical_compiler/artifacts/joint-factory-cohort-20261024/report/index.html)
- [Compact results](results/joint-single-aod-20261024/summary.json)
- [Independent audit](results/joint-single-aod-20261024/audit.json)
- [Scaling plot](results/joint-single-aod-20261024/scaling.png)
- [Source manifest](results/joint-single-aod-20261024/source-manifest.json)

All calibration sources were frozen throughout the nine cases. Afterwards, the
existing scan entry was updated to select joint profiles and only the shared-AOD
policy. Legacy band consumers gained explicit concrete-demand guards, and the
preparation-port hook gained a type-only return annotation. None changes joint
source gates, noise, layout, cohort scheduling or calibration calculations.
The public scan reproduced every duration and output count. After the consumer
checks, all nine complete case documents were replayed and matched exactly.
Calibration, scan and final verification source snapshots are retained.

The two abandoned independent-frontier diagnostic processes were stopped and
their directory marked invalid. No independent progression option remains in
the factory coordinator; its source is unchanged by this correction. Multi-AOD
work remains paused.

## Reproduction

Run from the repository root with the existing Python environment. Existing
single-component profiles can be reused for bindings and result contracts. For
a fresh clone, first create them with `experiments.msd.generic_factory calibrate`
as described in the historical report; their singleton timings/probabilities
are not used as joint costs/probabilities.

```powershell
$env:PYTHONPATH="$PWD/modules/physical_compiler/src;$PWD"
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$py='C:/Users/yuyqp/Documents/ChatGPT/NADiT/modules/physical_compiler/.venv/Scripts/python.exe'
$base='modules/physical_compiler/artifacts/generic-factory-20261024/profiles'
$out='modules/physical_compiler/artifacts/joint-factory-reproduction'
foreach ($d in @(3,5,7)) {
  foreach ($n in @(1,2,4)) {
    & $py -m experiments.msd.joint_factory --base-profile "$base/d$d-n$n/profile.json" --output "$out/d$d-n$n" --seeds 0 --shots 65536
    if ($LASTEXITCODE -ne 0) { throw 'Joint calibration failed' }
  }
}
& $py -m experiments.msd.generic_factory scan --profiles $out --output "$out/fast-scan" --plan experiments/msd/joint_factory_plan.json
& $py -m experiments.analysis.joint_factory_report $out
```

Subsequent resource queries can load a frozen joint profile through
`modules.logical_compiler.examples.surface_factory_fast`; no atom compilation
runs in that path. Uncovered frontiers raise `MISSING_JOINT_CALIBRATION`. This
is finite calibrated coverage for arbitrary module counts, not an assertion
that every possible stochastic branch has already been calibrated.

## Verification

The final unscoped fast + slow check passed 853 fast and 2521 slow tests, with
zero failures/skips; 14 bench tests were not run (649.02 seconds). The subsequent
type-only annotation passed 262 related fast tests including consumers, and all
nine exact case replays remained identical. Strict mypy passed on 16 affected
runtime/consumer files; scoped Ruff checks passed. No dependency was added.

New regressions cover vertical same-column sharing, mixed component frontiers,
missing group coverage without serial/physical fallback, measured group capacity,
single-AOD cohort retention during peer retries, actual joint raw/SE compilation,
actual-trajectory probability provenance, and the existing public scan dispatch.
Legacy band merging explicitly rejects a deferred joint-trace claim instead of
mistaking it for a horizontal band with concrete peak counts.

UI checks cover all three schedule views, case selection, zoom/reset, component
and native activity details, and d3's no-growth correction displayed in microseconds.
Software validation is complete; human acceptance and noisy factory logical
quality are not claimed.
