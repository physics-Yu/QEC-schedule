# Two L1 producers: asynchronous versus synchronous supply

Date: 2026-10-25. Branch: `codex/msd-level2-factory`.
Baseline: `026cb12`. Design: ADR 0055 / MSD-L2-01 extension.
Scope: d3, N1=2, N2=1, B=1, seed 0, one attempted L2 round, local only.

## Result

For this matched finite trajectory, synchronizing the two L1 factories reduces
L2 supply waiting by **264.005011 ms (23.624709%)**, and total completion including
drain by **442.646608 ms (32.330193%)**. This is not a steady-state result or a
general optimum. Both runs use the same geometry, 306 allocated atoms and
171600 um2 storage/parking bounding box, the original precomputed fake backend,
one AOD and homogeneous component waves. No atoms or physical compilation occur.

| Metric | L1 asynchronous | L1 synchronous |
| --- | ---: | ---: |
| L2 supply waiting | 1117.495289 ms | 853.490278 ms |
| L2 scheduler/resource waiting | 79.581663 ms | 0 ms |
| First L2 output / L2 completion | 1295.073651 ms | 926.496477 ms |
| Total completion, including drain | 1369.143085 ms | 926.496477 ms |
| Drain after L2 completion | 74.069434 ms | 0 ms |
| Three-leg inter-level delivery | 21.047424 ms | 21.047424 ms |
| L1 attempted rounds, each producer | 8, 8 | 8, 8 |
| L1 accepted outputs | 16 | 16 |
| L1 outputs delivered / retained | 15 / 1 | 15 / 1 |
| L2 attempted rounds / accepted outputs | 1 / 1 | 1 / 1 |
| Raw attempts / raw rejections | 307 / 67 | 307 / 67 |
| Final factory rejections in this seed | 0 | 0 |
| Atom-time per accepted final output | 418.957784 atom-s | 283.507922 atom-s |
| Area-time per accepted final output | 234944.953345 um2-s | 158986.795394 um2-s |
| Finite-batch output rate, including drain | 0.730384 / s | 1.079335 / s |

The retained output remains offered on its actual producer carrier; no discard,
free external consumption or cost credit is invented for it. B=1 limits published
outstanding queue entries, not the number of producer-held states. Pending
publication stays on one of the already allocated producer carriers.

## Why the schedules differ

All **528 semantic event outcomes** match, with no extra events in either run.
Both execute exactly 2001 component calls, including 1003 CNOTs, 100 S+SE calls,
307 raw attempts, 68 MX calls and 45 delivery legs. Thus the reduction is not
caused by fewer retries, a different probability model, or omitted operations.

The L1 synchronous cohort aligns the recipe stages, including raw retry joins
and conditional S+SE joins. Matching ordered geometry can then share AOD
commands. CNOT wave count falls from 620 to 531; the fraction of CNOT stage
commands with multiple members rises from **7.043757% to 88.888889%** (including
L2's unpaired calls). Merely sharing a component name does not guarantee common
commands when relative geometry differs. The existing compatibility rules remain.

| Shared resource busy time | L1 asynchronous | L1 synchronous |
| --- | ---: | ---: |
| AOD | 1344.150585 ms | 908.198477 ms |
| Camera | 92.200000 ms | 64.000000 ms |
| Local control | 24.567000 ms | 16.933000 ms |
| Rydberg operations | 2.010500 ms | 1.365000 ms |

These resource times overlap and must not be added to obtain elapsed time.
Likewise, summing the four initial input-request waits double counts overlap;
the headline waiting metric is the L2 process's `waiting_supply` time partition.
The report separates input starvation, shared-resource waits and L1 barriers.

The two L1 factories share a cohort only for the synchronous policy. L2 keeps
its own independent asynchronous cohort in both cases. Supply remains active
while a producer is waiting at a barrier. At demand closure, already-started
production drains, and a safely retained surplus allows its round join to finish.
The old kth-success synchronization model is not reintroduced.

## Comparison with the previous single-producer witness

The earlier N1=1 case at the same seed and one L2 round had 1246.049110 ms L2
supply waiting, 1314.028055 ms total completion and 204 atoms. Relative to that
reference, the new asynchronous and synchronous runs reduce L2 supply waiting
by **10.316915%** and **31.504283%**, respectively.

This is not a common-budget N comparison: adding a producer increases atoms
by 50%, changes the storage/parking box from 105600 to 171600 um2, and moves
L2 from y=-160 to y=-260 um. The asynchronous pair actually takes 4.194357%
longer to finish draining than the single producer. The synchronous pair is
29.491880% faster overall but costs 5.762180% more atom-time per final output.
The matched N1=2 policy comparison above uses an identical resource budget.

## Reusable configuration entry

The existing `examples.factory_level2` entry now accepts:

| Field | Supported contract |
| --- | --- |
| `distance` | Recorded catalogs 3, 5, 7, 9, 11; shared target distance for both levels |
| `level1_factories` | Positive integer; no new fixed count cap |
| `placement` | `vertical`, `horizontal`, `grid`; default `vertical` |
| `columns` | Required positive integer for grid, rejected for other layouts |
| `strategy` | L1 `asynchronous` or `synchronous`; L2 stays independent |
| `level2_factories`, `buffer_capacity` | Currently exactly 1 and 1 |
| `level2_distance` | Optional; must equal `distance`, otherwise explicit error |
| `level2_rounds`, `seed` | Explicit finite attempted-round count and production seed |
| `producer_round_budget` | Finite per-producer safety bound, fixed before sampling |

The Python API reuses a caller-owned `FactoryObjectCatalog.load(distance=d)`:
`run_level2(catalog, seed=0, level1_factories=2, placement="vertical",
strategy="synchronous")`. New N, layout and strategy combinations use the same
component objects and numeric geometry bindings; no calibration or build fallback.

`factory_supply_layout` reuses the existing L1 catalog layout without changing
its internal six-role arrangement. It places one same-distance L2 at the lower
left beneath the L1 array, retaining the existing factory gap. One empty parking
block is placed to the right and contributes area but no additional atoms.
In the present case, L1 origins are y=-60/-160 um, L2 y=-260 um and parking
(600,-60) um, giving a 660 x 260 um storage/parking box. Readout area remains
unassigned in the existing model, not zero or an independently validated area.

All three layouts and five distances have geometry/interface checks. Complete
L2 production acceptance currently covers d3, N1=1/2, N2=B=1. Other positive N
and recorded distances are configurable, not yet complete-production results.
Large combinations remain subject to explicit wall and call budgets. Mixed
distances, multiple L2 factories and B other than one remain separate work.

## Reproduction and artifacts

Configs:
[`level2-d3-n2-b1-asynchronous.json`](../../experiments/msd/level2-d3-n2-b1-asynchronous.json)
and [`level2-d3-n2-b1-synchronous.json`](../../experiments/msd/level2-d3-n2-b1-synchronous.json).
The only changed policy input is `strategy`. Both use vertical placement, seed 0,
one L2 attempted round and at most 32 rounds per L1 producer. Raw attempts and
component-call budgets remain 32 and 10000 per relevant owner. Case/wave/worker
deadlines remain 20/5/60 s. A timeout/error stops before any next case.

```powershell
$env:PYTHONPATH = '.;modules/physical_compiler;modules/physical_compiler/src'
$testPython = 'C:/Users/yuyqp/Documents/ChatGPT/NADiT/modules/physical_compiler/.venv/Scripts/python.exe'
foreach ($strategy in @('asynchronous', 'synchronous')) {
  & $testPython -m modules.logical_compiler.examples.factory_level2 --config "experiments/msd/level2-d3-n2-b1-$strategy.json" --output "artifacts/msd-object-local/reproduce-n2-$strategy"
  if ($LASTEXITCODE -ne 0) { throw "Stopped after failed $strategy run; inspect error.json" }
}
& $testPython -m modules.logical_compiler.examples.factory_level2_compare --asynchronous artifacts/msd-object-local/reproduce-n2-asynchronous/case.json --synchronous artifacts/msd-object-local/reproduce-n2-synchronous/case.json --output artifacts/msd-object-local/reproduce-n2-comparison
```

Use fresh output directories. The comparator reads saved data only, checks
matched configuration/model/budget and common seeded outcomes, and writes an
index linking both complete self-contained schedules. An optional `--baseline`
supplies the previous single-producer case as a separately labeled reference.

Delivered local artifact roots under `artifacts/msd-object-local/`:

- `20261025-level2-d3-n2-b1-asynchronous/`: case, configuration, summary,
  complete schedule, worker logs/timing and independent audit.
- `20261025-level2-d3-n2-b1-synchronous/`: same records for the matched policy.
- `20261025-level2-d3-n2-b1-comparison/`: `index.html`, `comparison.json` and
  combined saved-data audit. Links point to both complete schedules.

Asynchronous HTML contains all 1376 waves and 63679 phases; synchronous HTML
contains all 1070 waves and 43850 phases. Both retain all 2001 calls, input
lineage, carrier movements, parking reservations, round decisions and surplus
disposition. Saved-data checks pass; browser visual review was not performed.

## Runtime, reuse and verification

Actual estimator wall times: 5.580197 s async and 5.031658 s sync. Bounded worker
times including imports, JSON and HTML are 9.010456 s and 8.162674 s. No timeout
occurred. Phase traversal/serialization quantities are reported; no profiler or
bench was run to assign exact software bottleneck percentages.

Each run loads ten factory objects once and preserves their identities. Both
record 6193 factory cost lookups, 6150 hits and 43 numeric binding misses, plus
nine cached delivery-distance variants and 180 delivery lookups. Physical
compile, atom expansion and atom-construction attempts are all zero. Catalog
SHA256 remains `959321fe6566d9434bb2e514ec27b1131843b4cfa4fec62f4e856514f2ce6599`.
Probability ports and noise inputs are unchanged; recorded theoretical output
quality is not decoded logical error. All runtime source hashes match the files
used for the saved runs, and no old result or server task was changed.

Baseline: 35 focused fast tests passed in 14.16 s. After changes, the mapped
object consumers pass **154 fast tests in 39.34 s**, including both real N1=2
strategies, independent cohorts, B=1 accounting, retained surplus, all five
distances/three layout interfaces, earlier ownership/retry controls and saved-data
comparison validation. Ruff format/lint passes for six changed Python files;
scoped mypy passes for four runtime files. No slow, bench or full-repository
suite was run, following the user's explicit test scope.

The independent audit confirms 18 conserved and uniquely assigned carriers,
four adoptions plus eleven consumptions, 45 distance-derived moves, queue maximum
one, no unfinished demand, one intact retained output, homogeneous waves and
no overlapping single-AOD command intervals. The existing cooperative scheduler,
supplier and probability models needed no parallel framework or server machinery.
