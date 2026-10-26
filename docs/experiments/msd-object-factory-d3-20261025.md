# Complete d3 factory recipe: object resource estimates

This local continuation executes the actual first-level recipe as an object
resource simulation. Preparation uses the previously calculated probability in
a fake backend. No quantum state is prepared, no circuit is compiled, and no
physical probability is recalculated. Scheduling changes timing and resource
use; it does not change the selected raw acceptance parameter.

## Reproduction and outputs

Configuration: [factory-objects-d3.json](../../experiments/msd/factory-objects-d3.json).
Run from this checkout, using a fresh output directory:

```powershell
$msdPython = 'C:\Users\yuyqp\Documents\ChatGPT\NADiT\modules\physical_compiler\.venv\Scripts\python.exe'
$env:PYTHONPATH = "$PWD;$PWD\modules\physical_compiler\src"
& $msdPython -m modules.logical_compiler.examples.factory_objects `
  --config experiments/msd/factory-objects-d3.json `
  --output artifacts/msd-object-local/factory-d3-reproduction
```

The outer worker limit is 60 seconds, each production case 20 seconds, and each
component wave 5 seconds. A timeout stops execution and records its reason,
last progress and stdout/stderr in `error.json`; an outer timeout returns 124.
No later cases, automatic retries, fallback compilation or server work follow.

Verified local outputs (excluded from Git):

- [Summary and model provenance](../../artifacts/msd-object-local/20261025-full-d3-v2/summary.json).
- [Representative vertical layout and time schedules](../../artifacts/msd-object-local/20261025-full-d3-v2/schedule.html).
- [Complete N=2, seed=0 event/phase trace](../../artifacts/msd-object-local/20261025-full-d3-v2/d3-n2-seed0.json).
- [Worker runtime](../../artifacts/msd-object-local/20261025-full-d3-v2/worker.json).
- [Runtime source hashes](../../artifacts/msd-object-local/20261025-full-d3-v2/source-hashes.json).

## Existing inputs and boundaries

The portable [numeric input](../../modules/codes/rotated_surface/configs/object_d3_reference.json)
contains the saved component stage durations, primitive counts and raw port.
It was extracted by reading numeric fields of the existing
`generic-factory-20261024/profiles/d3-n1/profile.json`, without running its
producer. The original profile SHA256 is
`c8c31d3f367fc43fde2165affcae3e04fd7f1132eab4f4cc2fb3d106939a5b18`;
its recorded source tree hash is
`123c9752baa95eb0eba411b990834a6e6ffd34025d96a9a7871205622568d57c`.
The portable catalog fingerprint for this run is
`959321fe6566d9434bb2e514ec27b1131843b4cfa4fec62f4e856514f2ce6599`.
No old campaign orchestration or uncommitted main-worktree changes are imported.

| Input | Value and source |
| --- | --- |
| Load / Store | 10 us each, saved stages; enforced by catalog validation |
| Measurement / classical processing | 100 / 0 us, saved stages and ports |
| Local gate / CZ / reset | 1 / 0.5 / 5 us, saved numeric stages |
| Movement | 1 us/um; readout height and signed CNOT displacement parameterize saved stages |
| Layout | Existing vertical surface layout, six blocks/factory, 10 um grid, 40 um inter-block gap |
| Zones | Storage/gates below y=0; readout above y=50 um; capacities unbounded in this model |
| Raw acceptance | 51235/65536 = 0.7817840576171875, saved port |
| Raw provenance | Existing estimator: 65536 shots, seed 20261024, 20 detectors; Wilson 95% interval [0.7786053515, 0.7849297316] |
| Raw protocol | d3 injection, **three total SE rounds**, followed by postselection; d3 growth rounds = 0 |
| Accepted-input error | Existing theoretical model parameter p=0.01, separate from raw rejection |
| Canonicalization | Existing one-Pauli-layer cost bound; no sampled decoder correction frame |

The standalone raw-T interface and factory postselection interface are distinct:
the low-level d3 raw-T primitive contains **one** complete SE round. The older
d3 postselection wrapper defaults to two total rounds (primitive plus one);
this factory explicitly requests the migrated three-round staged postselection
protocol (primitive plus two). No extra round is appended here. This distinction
is visible in `rotated_surface_d3/components/injection.py`, its `protocols/raw_t.md`
and `rotated_surface/staged_raw_t.py`. At d3 there is no expansion to a larger block. Migrated d5/d7
protocols retain accepted-only expansion with ordinary SE and decoding, but their
complete object inputs are not supplied by this d3 acceptance run. Requests for
those distances fail explicitly, rather than using zero growth cost.

Noise inputs are retained verbatim in the numeric input and raw-port provenance:
single-qubit Pauli probabilities (1e-4 each, Z override zero), each of 15 CZ
Pauli channels 1e-4, readout/reset flips 0.001, Load/Store loss 1e-4,
move loss 2e-5 plus 1e-6/um, AOD loss 1e-8/us, movement Pauli channels 1e-5 each,
SLM/AOD T2 1.5e6 us, and the saved zero loss/spectator terms. These parameters
document the selected reference probability; this run does not evaluate a new
schedule-dependent noise model or infer decoded logical error rates.

## Call chain and caching

`factory_objects.run_acceptance` loads `FactoryObjectCatalog` once, then runs
`FactoryProcess(factory_recipe(3))` through `CooperativeFactoryRuntime` and the
existing `ComponentScheduler`. `FactoryObjectProfile.describe/instantiate_wave`
provide existing `ComponentCostProfile`/`ComponentPhase` objects to
`ProfileExecutionKernel` and `schedule_phases`. `FactoryObjectBackend` returns
the saved probability ports; the existing event journal samples them.

The ten semantic objects cover plus preparation/correction, raw
postselection/correction, logical X/S/MX/MZ, CNOT and standalone SE. SE inside
plus preparation, raw preparation and S is already included, not added twice.
The standalone SE object is extracted from the identical second/third ordinary
SE rounds of the saved raw record. The actual factory recipe uses embedded SE.
There are 59 CNOTs per batch, four initial raw inputs and eleven reused R inputs.
Raw rejection retries only its carrier; final rejection restarts the batch.
The next production cycle includes its preparations/resets. The ideal external
sink excludes external consumption cost and preserves explicit delivery events.

Object templates remain fixed across N, seeds, retries and combinations. Cheap
numeric binding caches component/displacement/height; new heights add bindings,
not compiled components. Per-wave aligned batching and AOD waits are calculated
from those records. Aligned congruent instances share a command; a vertical
readout group uses the largest required translation for every member. This is
a stage transport model, not a maximum of independently computed factories.
Different component types never overlap.

For two vertical MZ components the shared schedule is:

| Stage | Start us | End us | Shared resource |
| --- | ---: | ---: | --- |
| Load | 0 | 10 | AOD |
| Translate to readout | 10 | 210 | AOD |
| Measure | 210 | 310 | AOD + camera |
| Return | 310 | 510 | AOD |
| Store | 510 | 520 | AOD |

## Local finite production results

Each factory delivers two accepted outputs. Seeds are reproducible event-journal
seeds, not new physical-noise sampling jobs.

| N | Seed | Outputs | Raw attempts / rejects | Final rejects | Startup us | Total us | Outputs/s, finite batch |
| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 0 | 2 | 47 / 17 | 0 | 90852.371 | 182950.904 | 10.9319 |
| 1 | 1 | 2 | 36 / 6 | 0 | 79990.531 | 164964.706 | 12.1238 |
| 2 | 0 | 4 | 84 / 24 | 0 | 161327.002 | 334840.768 | 11.9460 |
| 2 | 1 | 4 | 107 / 32 | 1 | 140239.733 | 457437.288 | 8.7444 |

Allocated atoms are 102/204 for N=1/2; resident storage rectangles are
33600/89600 um2. Atom-us per accepted output, in table order, are
9330496.101, 8413200.000, 17076879.148 and 23329301.681.
These include all resident atoms across the complete finite run. Storage area
time is also exported. The readout rectangle is **not specified** by the source
records; storage footprint must not be presented as total device footprint.

For N=2, seed=0, readout transport is 114400 member-us, other gate transport
183548.271 member-us, shared AOD waiting 103378.648 member-us, and wave-tail
synchronization 29313.532 member-us. The summary also separates local-control
waiting and per-factory frontier waiting. These categories are not all additive;
member work is not global elapsed time or atom exposure. Primitive operation
counts and resource busy intervals are exported, but exact transport/idle
atom-noise exposures remain unavailable from these reduced records.

## Runtime, reuse and verification

Total subprocess runtime was **4.167015 s**, including startup/imports; in-worker
work was **3.087862 s**. Individual production calculations took 0.378, 0.351,
0.874 and 1.189 s. Their 2.792 s total dominates this small run's in-worker work;
imports/startup add about 1.079 s. No separate function profiler was run, so no
more specific algorithmic bottleneck is claimed.

Ten templates were loaded once: **4840 lookups, 4810 binding-cache hits, 30
numeric binding misses**. Template identities stayed unchanged. Instrumented
physical compilation, atom expansion/binding and atom construction counts were
all **zero**. The existing source-hash guard also confirmed unchanged code
throughout the acceptance run.

- Focused initial object baseline: 25 fast tests passed.
- Six new complete-catalog/factory tests passed, including the vertical sharing
  regression and rejection of unsupported distance or altered probability inputs.
- Final mapped related-fast selection: **516 passed, 147 deselected**, 9.19 s
  pytest time, 9.778 s bounded subprocess time. The deselections are 138 slow
  and 9 bench; no bench or full-library suite ran. Existing timeout/control cases
  are included in this selection.
- Independent result readback checked homogeneous waves, sequential wave
  boundaries, AOD/control/camera resource conflicts, real probability ports,
  15 accepted raw inputs per attempted batch and 59 CNOTs per batch.
- Ruff formatting/lint and strict mypy checked the changed Python sources.

The user-authorized related-test scope supersedes the repository's blanket
all-suite rule for this task. No server tasks were started or modified.

This is a complete **d3 recipe flow** with an approximate object cost model,
not an atomically validated execution schedule. Steady-state throughput,
decoded logical error rate, complete readout footprint, exact atom-noise
exposures, d5/d7 production and second-level factories remain unreported.
