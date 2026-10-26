# MSD experiment standard

For actual simultaneous N-factory SE execution, use the
[parallel SE experiment](PARALLEL_SE.md). The single-component survey below
remains a position-dependent calibration, not a concurrency measurement.

The current raw-T protocol uses fixed d3 injection followed by ordinary growth.
See [the 10 us transfer animation](TRANSFER_10US_ANIMATION.md). The
[all-d experiment](RAW_T_DISTANCE_ROUNDS.md) and
[two-round results](RAW_T_ACCEPTANCE.md) are historical controls.

The accepted experiment uses real code-owned logical S components. Measurement
takes **100 us**, classical result processing **0 us**, and each SLM/AOD transfer
**10 us** under `nadit.msd.standard/2`. Standard/1 used 100 us transfers; its saved
results are unchanged and must be reproduced from their recorded source revision.
All other capability/timing values come from the existing d3 CNOT
reference: CZ 0.5 us, rotation 1 us, reset 5 us, movement 1 us/um. This is a
comparison standard, not a calibrated hardware specification.

`standard.py` builds an explicit six-patch world for odd distance d and N=1,2,4,...
factories. Roles W1..W5,R run left to right; factory rows run top to bottom. The
code owns its actual components; this experiment does not implement another
logical scheduler or alter the separately developed logical compiler.

## Geometry and resource interpretation

Cartesian y increases upward. Storage and gates occupy y<=0; readout occupies
y>=50 um. The intervening 50 um strip is transport-only. Both operating domains
are mathematically unbounded. The existing physical `Region` API remains finite:
each run derives an enclosing execution window from its actual source geometry
and worst-case readout row demand. The window is not a hardware footprint budget.
Compare an enlarged window to check it does not determine the measured result.
An empty enlargement can change a symbolic CZ coverage rectangle; acceptance
compares the replay-time illuminated atom identities as well as all actual
targets, trajectories and times. Spectator illumination remains part of exposure.

Area metrics use actual occupied/visited coordinates. They do not use the area of
the ideal half-plane or finite execution window. The baseline has one flexible
AOD with the reference's unbounded row/column counts; finite capacities can later
define separate matched-budget experiments. Order, line spacing, capture closure,
occupancy and pulse semantics still constrain concurrent operations.

## Deliverables and status

- `level1_plan.json`: independent d/N axes, frozen timing and geometry, metric
  definitions, proposed production observation windows and explicit run limits.
- `standard.build_world(ExperimentSpec(...))`: complete Device, AtomLayout and
  code-owned ComponentBinding records, exportable via `.document()`.
- `calibrate.py`: compact statistics from an actual component source lowered by
  `compile_physical` and `NonZonedStrategy` in the complete spectator world.
- `../../docs/experiments/msd-interface-audit.md`: actual integration APIs and the
  remaining external fast-runner/vertical-parallel admission dependencies.

Component calibration reports no accepted-output throughput or output error.
All other factories are idle spectators in each calibration cell. A pipeline
count axis therefore measures the physical world and location dependence, not
parallel production speedup. The compiled physical measurements are case
fixtures; this is not a noisy quantum-state simulation or hardware execution.

Production benchmarks require the separately developed logical compiler to
provide sustained batch execution, final acceptance, carrier release, rejection
and retry accounting, and explicit EC policy. A whole-factory cycle must include
all operations in the recipe, not a sum of a few calibration components. The
existing horizontal-only admission declarations need an explicit vertical/common
readout profile. Two-level sizing waits for measured first-level accepted arrival
traces; unknown output quality remains unknown.

## Reproduction

Use the existing Python 3.12 physical-compiler environment, with this checkout's
`modules/physical_compiler/src` and repository root on `PYTHONPATH`. No dependency
changes are needed. From the repository root:

```powershell
$env:PYTHONPATH="$PWD\modules\physical_compiler\src;$PWD"
python -m experiments.msd.calibrate --distance 3 --pipelines 1 --operation logical_s --output output/d3-n1-s.json --witness
python -m experiments.msd.survey --output output/component-survey
python -m experiments.msd.plot output/component-survey
python -m pytest experiments/msd/tests -q
```

`--factory-index` selects the actual row; default 0 is closest to readout. Use
the final index N-1 to assess the bottom row. `--padding 1000` repeats the cell
with an enlarged execution window. Output files are exclusive-create and retain
source/device identities. `compile_wall_s` measures host calculation time;
`execution_duration_us` measures planned device time. These are different axes.

`transport_elapsed_us` is the union of transport time intervals, while
`transport_action_sum_us` sums Load/Move/Store action durations including any
concurrency. Atom idle/busy costs include every retained spectator and conserve
`atom_count * execution_duration_us`. Exposure is broken down by actual action
type; an error probability must be computed with a separately named noise model.

The survey enforces subprocess timeouts, a campaign time limit and an atom-count
admission limit. It fingerprints physical, code and experiment sources, stops if
they change, records failed/censored cells, limits numerical library threads,
and saves compact rows plus one full d3 S witness. Its default 72 cells cover
d=3/5/7, N=1/2/4 and eight components, always at the bottom factory row. `raw_t`
is the primitive; required repeated-SE postselection is separately implemented
in the code library and verified by component contract tests. These calibration
cells do not constitute the complete factory production cycle.
