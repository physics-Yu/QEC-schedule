# Saved Shor15 prefix → parallel physical compilation

A reviewed 1.14 MB [source packet](../references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04/README.md) makes this stage reproducible without regenerating the multi-GB complete stream. Its packet manifest binds exact raw files and preserves the mother run manifest; the omitted suffix is never called a complete delivered stream. Git attributes preserve packet bytes across Windows checkouts. The adapter authenticates the complete first resource function as source evidence, then selects only the 17 RESET / H prefix before T. `examples/export_shor15_prefix_packet.py` rebuilds the packet from the complete saved run.

This experiment compiles a bounded, authenticated part of the saved complete
encoded Shor15 source. It retains the twelve algorithm patches' 2,988 native
RESET/CSS-encoder/first-canonical-round gates. The optional right-side resource
patch uses the **same saved seventeen carrier identities** and the producer's
first seventeen RESETs followed by H, stopping immediately before its first T.
The two-device input therefore has 3,006 native gates, 413 actual projections,
221 atoms and two separately identified AODs. The resource state at the stop
is an unencoded physical `|+>` with sixteen zero carriers; it is not a prepared
magic state, factory output or available inventory resource.

The native writer's `previous gate` dependency was an export ordering. This
adapter checks every selected gate against the actual CSS and canonical
templates, preserves all native IDs and measurement/reset reports, retains
the CSS CNOT network sequence and canonical syndrome phase barriers, and
removes only the artificial serialization between independent patches.
`DynamicGateDAG` still enforces every physical qubit's order. This bounded
rewrite is not applied to adaptive injection/frame-feedback dependencies.

The declared research platform has one COMPUTE permission zone and MZ.
SLM candidate sites remain a fixed 5 µm World lattice. The occupied subset
uses 10 µm spacing and each patch has its own persistent holders. Only the
221 actual home supports are instantiated, since this bounded compiler never
enables or offloads into any other SLM point; omitted supports would stay
disabled throughout. This reduces snapshots without changing grid, positions,
trajectory, collision, support or spectator checks. The algorithm AOD uses a
3-column × 4-row rectangle with 80/60 µm offsets. The resource AOD is a separate
4 × 6 capacity rectangle in a disjoint right-side envelope; its selected
Cartesian mask has twenty active intersections for seventeen actual carriers.

Authored CZ pairs need not be nearest neighbors in the code-block layout.
The compiler transports corresponding carriers to `(-3,-3) µm` from their
actual partners. CZ still has a finite **6 µm** interaction distance and the
complete COMPUTE `actual_pairs` must equal the intended batch. All active
empty AOD intersections and all atoms, including the right-side carriers,
remain subject to ordinary validation. Explicit 5 µm corridor segments and
actual LOAD/OFFLOAD operations restore each carrier to its original block.

The first two-device service transports twelve algorithm d0 carriers and all
seventeen right-side resource carriers into MZ concurrently. Once both arrays
are stationary there, one actual 29-gate RESET batch executes. The two arrays
then return concurrently. Separate RESET pulses are not overlapped because
the current readout contract reserves all AODs. The resource H subsequently
executes on its original carrier; it then remains idle while the algorithm
prefix runs. Every MEASURE and RESET in the accepted circuit physically visits
MZ, and only Executor commits gate effects, reports and placement.

Reproduce from the small checked-in source packet without building the
multi-GB native suffix:

```powershell
python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-parallel-prefix `
  --patches 12 --wall-budget 1800 --routing-policy legacy_5um
```

This historical time table uses the fixed 5 μm route. The explicit
`legacy_5um` flag reproduces it; the current default is the validated direct /
2.5 μm half-grid [standard route](qec_routing_standard.md).

`--patches 1`, `2` and `4` select smaller algorithm inputs; `--algorithm-only`
preserves the one-device comparison. The output directory must be fresh.
Failures retain source, initial state, accepted plans, trace, final checkpoint,
decisions and recording whenever initialization succeeded. A skipped replay is
explicitly null and never counted as a verified independent replay.

The output includes `source-prefix.json`, `prefix-circuit.json`, the recovered
protocol phases, platform and initial placement, original initial snapshot,
accepted physical plans, committed trace, final snapshot, decisions, the common
VisualRecorder recording and `animation.html`. Source and executed counts are
distinct from the complete Shor run. The shared viewer uses actual operation
intervals and both device identities; it does not infer time from circuit depth.

Independent acceptance should check whole native IDs/effects exactly once,
source raw reports, final code/logical/auxiliary stabilizers, actual finite CZ
pair sets at every pulse, dependency timing, actual MZ positions and full plan
replay from the original initial snapshot. This is ideal Clifford physical
prefix execution. It does not execute a complete physical Shor algorithm,
non-Clifford resource production, noise, decoding or fault-tolerant supply.

Current implementation:
`neutral_atom_experiments.qec_pbc.parallel_prefix` owns source/template binding
and platform declaration. `neutral_atom_strategies.scheduling.parallel_patch`
owns placement-specific grouping, explicit routes and scheduling. Environment
owns the global safety checks and Executor; the common observer owns playback.

## Accepted twelve-patch run and function visualization

The [portable acceptance summary](../references/qec_pbc_validation/native_parallel_physical_2026_10_04.json)
binds the actual completed twelve-patch run: 3,006 gates, 413 projections,
221 atoms, two AODs and 196 accepted plans. The full original-state replay
matches every canonical snapshot byte. There are 68 actual CZ pulses for
816 native CZ gates, at most twelve pairs in one pulse; the largest H batch
has 72 carriers. Terminal time including return is 69,927.725855 µs under
the declared model. This is a pulse-count observation, not a measured
full-Shor or equal-platform serial-baseline speedup.

After generating a fresh run, independently audit it and show the spatial report:

```powershell
python tools/audit_native_parallel_physical.py artifacts/my-parallel-prefix `
  --output artifacts/my-parallel-prefix/independent-audit.json
python examples/serve_native_parallel.py --run-dir artifacts/my-parallel-prefix --port 8773
```

The page provides actual-operation bookmarks for initial patch placement,
MZ RESET, common H, simultaneous finite CZ pairs, MZ syndrome readout,
two loaded AODs moving together, and the committed terminal state. Use the
shared viewer's event controls, atom inspector and device axes/resources to
inspect each operation. The evidence table distinguishes native gate counts
from physical pulse counts. Accepted report rendering requires every producer
check including original-initial replay, and the current recording byte hash
must match the independent audit; a replaced file cannot reuse old acceptance.

The independent arithmetic tool preserves the exact source ID multiset,
checks operation-kind and authoritative trace times, implicit wire/explicit
dependencies, full finite carrier geometry, initial-world zone identity,
all global CZ pairs, MZ and Raman separation, and independent signed Stim
state/projections. Continuous trajectory validation belongs to Executor
and original-state replay, rather than sampled observer frames.

Current acceptance includes 54 new and 180 existing distinct pytest passes,
263 modules with zero architecture violations, and actual browser checks.
Three absent historical artifact inputs are skipped, separately reported.
The prior ideal complete native generator, historical 913 tests and peer
overlapping regressions are not added to this current test total.
