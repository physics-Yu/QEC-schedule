# Initial two-level MSD object acceptance

Date: 2026-10-25. Branch: `codex/msd-level2-factory`.
Design baseline: `ef14296`, ADR 0055 / task MSD-L2-01.
Scope: local d3, one L1 and one L2, producer-held B=1, one attempted L2 round.
No physical compilation, atom construction/expansion, server submission or bench.

## Implementation and boundaries

The existing `FactoryProcess`, cooperative scheduler, resource ledger, phase
kernel and 59-CNOT recipe are reused. External supply replaces only L2 resource
preparations: W1 initializes locally, four inputs are adopted into W2-W5, and
eleven subsequent inputs are reserved on R and consumed at the existing injection
boundary. No raw injection, postselection or growth is repeated by L2.

`ObjectFactorySupply` counts published/reserved/in-transit entries against B
until committed delivery. It preserves original token/carrier IDs and epochs.
The output retains all fifteen input IDs in its provenance. Queue release,
carrier release and consumption are separate transitions. Roles change owners;
quantum states are never copied. An accepted state is not destroyed by transport.

Delivery is three moves: receiver to parking, output to receiver, parked carrier
to producer. Each is Load 10 us, Euclidean source/destination displacement times
the recorded `move_us_per_um`, and Store 10 us. There is no added SE or reset.
Each completed leg updates current position/version from its receipt. All legs
use the same AOD scheduler as computation. Partial failure stops with committed
positions, ownership and parking reservation intact. Endpoints are checked;
available transit clearance is a cost-model assumption, not atomic collision
validation. Delivery profiles cache numeric displacement costs, not atoms.

L1/L2 have independent cohorts and stable level/factory/round event identities.
Supply uses current demands, FIFO outputs, fair service and homogeneous waves.
For this one-producer witness, production starts on outstanding demand; no
speculative prefetch. Final L1 rejection advances its attempt normally. L2
closes demand after its requested attempted-round count. Surplus can be retained
without claiming consumption or carrier release. Errors and timeouts stop,
preserving diagnostics; no budget increase or next-case submission follows.

## Reproduction

Configuration: [`level2-d3-n1-b1.json`](../../experiments/msd/level2-d3-n1-b1.json).
Seed 0; async policy; one L2 attempted round; producer maximum 32 attempted
rounds, local raw-attempt limit 32, batch limit 16, component-call limit 10000
per factory. Case/wave/worker deadlines remain 20/5/60 seconds. Producers stop
on demand closure rather than completing all 32 budgeted rounds.

From the repository root, using the existing environment:

```powershell
$env:PYTHONPATH = '.;modules/physical_compiler;modules/physical_compiler/src'
$testPython = 'C:/Users/yuyqp/Documents/ChatGPT/NADiT/modules/physical_compiler/.venv/Scripts/python.exe'
& $testPython -m modules.logical_compiler.examples.factory_level2 --config experiments/msd/level2-d3-n1-b1.json --output artifacts/msd-object-local/level2-d3-n1-b1-reproduction
```

Use a fresh output directory. The existing bounded worker records stdout,
stderr, actual wall time, failure cause and partial-prefix diagnostics. A
successful run writes `case.json`, `summary.json`, `configuration.json`,
`render-audit.json` and `complete-schedule.html`. Source hashes and the component
catalog fingerprint are embedded in the case; generated artifacts are untracked.

Final local artifact root:
`artifacts/msd-object-local/20261025-level2-d3-n1-b1-release/`.
The earlier `...-seed0/`, `...-final/` and `...-verified/` runs are preserved as development evidence. Their events
and makespan exactly match the final run.

## Results

| Quantity | Recorded value |
| --- | ---: |
| L1 attempted rounds / accepted outputs supplied | 15 / 15 |
| L2 attempted rounds / accepted final outputs | 1 / 1 |
| Initial adoptions / later consumptions | 4 / 11 |
| Raw attempts / raw rejections (L1 only) | 287 / 62 |
| Final batch rejections in this seed | 0 |
| First final output and total drain completion | 1314.028055 ms |
| Delivery legs | 45 |
| Delivery movement | 18.720170 ms |
| Delivery Load/Store | 0.900000 ms |
| Total inter-level delivery | 19.620170 ms |
| Single-AOD busy time | 1285.298555 ms |
| L1 supply/demand wait | 66.982127 ms |
| L2 supply wait | 1246.049110 ms |
| Allocated atoms / carriers | 204 / 12 |
| Storage plus parking bounding box | 660 x 160 um; 105600 um2 |
| Sum of resident block footprints | 43200 um2 |
| Empty parking footprint | 3600 um2; zero extra atoms |
| Atom-time per accepted final output | 268061723.178663 atom-us |
| Area-time per accepted final output | 138761362586.60187 um2-us |
| Finite-batch accepted output rate | 0.761019 / s |

These are one finite trajectory, not steady-state throughput or a statistical
acceptance-rate estimate. Dedicated readout area is not assigned by the existing
model and remains unavailable. Both factories are stacked vertically; parking
origin is (600, -60) um. The upper readout half-plane remains separated by 50 um.

Global category busy times: movement 918.438555 ms, Load/Store 265.860000 ms,
measurement 101.000000 ms, gates 23.374500 ms and reset 5.355000 ms. Member work,
resource times and per-demand waits must not be added to obtain global makespan.
The four initial demands overlap; the per-demand starvation sum differs from
the de-duplicated factory wait reported above. JSON retains both.

The report includes component-envelope idle-carrier exposure, recorded noise
parameters and primitive operation counts. Idle allocated-atom exposure is
234076954.441085 atom-us. This coarse allocation statistic is not a site-resolved
quantum-state noise integral; it does not change the fake probabilities.

## Probability and reuse evidence

Raw acceptance is unchanged at 0.7817840576171875. L1 uses the original iid
accepted-input Z-error assumption p=0.01. Its theoretical conditional output
error, 3.60876839653233e-5, becomes the declared homogeneous L2 input parameter.
The existing model gives L2 acceptance 0.9994588214644804 and conditional output
error 1.6450992273590814e-12. These assume independent inputs and ideal Clifford,
storage and readout; neither is decoded logical error or validated physical quality.
Theoretical ports are prepared/cached independently of production events.

The final run preserves all ten loaded factory component identities: 5804
cost lookups, 5776 bound-cost hits, 28 misses. Delivery creates six numeric
displacement variants with 180 lookups. Instrumented physical compile, atom
expansion and atom-construction attempts are all zero. A separate matched
async/sync test reuses the same catalog: event records and makespan match, and
the second run has zero additional factory binding misses. With one member per
layer this equality is expected; it checks the absence of a cross-level barrier.

Measured final software time: 5.647893 s for the estimator/report-data assembly;
5.655910 s through guard/catalog work; 8.866443 s for the bounded worker including
startup, serialization and HTML. No timeout occurred. There are 1878 component
calls, 1744 waves and 68497 modeled phases. No profiler/bench was run, so the
relative cost of phase traversal, ledger copying and serialization has not been
quantitatively attributed; none of this workload is physical compilation.

## Verification and remaining work

- Baseline: 23 related fast passed, one slow deselected (5.77 s).
- Mapped protocol/object consumers: 617 fast passed, 138 slow and nine bench
  deselected (24.05 s), before adding the matched two-level integration control.
- Final focused supply/report checks including matched real async/sync control,
  blocked-demand arbitration and a twelve-factory report-ordering regression:
  35 fast passed (15.02 s). These overlap the mapped run; counts are not additive.
- Tests cover progressive four-plus-one supply, two R slots with B=1 before
  consumption, duplicate publication, incompatible quality, finite exhaustion,
  retained surplus, partial exchange, stale position replay, transport epoch
  preservation and fresh input lineage after work abandonment. The real recipe
  run verifies all fifteen inputs and 59 L2 CNOTs.
- Independent saved-data audit checks 12 conserved carriers, 15 unique inputs,
  45 distance-derived moves, queue maximum one, same-component waves, nonoverlap
  of single-AOD intervals and unchanged seeded replay. HTML contains all 1744
  waves and 68497 phases; no external requests or unresolved placeholders.
  Browser visual review was not performed.
- Changed-file Ruff format/lint passed for thirteen Python files; scoped mypy
  passed for eleven runtime sources. Thirty-one documentation links passed.
  The release audit confirms current source hashes and identical events,
  calls, resources and movements relative to the verified prior run. The user's
  related-fast-only scope overrides the repository's blanket all-fast-plus-slow
  pre-commit rule; no full/slow/bench run is claimed.

Only d3, N1=N2=B=1 is exposed by this initial L2 command. Wider distances,
ratios/layouts and dedicated buffers are not accepted L2 results. Two-round
paired-seed production and a complete forced-L2-rejection trajectory are not
part of this one-round result; the inherited round-rejection semantics and
fresh-token lifecycle have focused controls. No optimization or superiority
claim follows from this seed.
