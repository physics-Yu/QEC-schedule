# Parallel SE scaling under the unchanged MSD standard

This experiment corrects the earlier bottom-row-only calibration. Each factory
submits one complete `se_round` on W1; N factories mean N simultaneous SE
instances, not 6N. All six patches per factory remain in the physical world.
No layout, physical timing, code circuit or AOD capacity is changed.

The existing source is composed into disjoint quantum/classical registers, with
each source barrier scoped to its own block. One imported PhysicalDAG feeds one
`compile_physical` invocation with `NonZonedStrategy` and `ReadyScheduler`. That
existing controller jointly chooses ready gates and readout and lowers them in
one world using one AOD and one global clock. Independently compiled action
tables are never overlaid. The separate logical factory scheduler is not used:
its current component-level lockstep declarations are restricted to horizontal
tiles. This fixed, branch-free kernel uses the existing physical global frontier
directly; it is not a complete production factory runtime.

## Controls and interpretation

For every d,N configuration compile the following actual schedules:

1. **Joint**: every W1 SE is ready at time zero, with no cross-factory DAG edges.
2. **Serial**: identical sources, with explicit cross-instance barriers.
3. **Solo i**: each selected W1 individually at its actual coordinate in the
   identical complete world, with all other atoms retained as spectators.

Let `i*` be the index of the longest total solo schedule. Report:

`Tjoint = Tsolo_top + (Tsolo_i* - Tsolo_top) + (Tjoint - Tsolo_i*)`.

The first difference measures the isolated position effect. The signed second
difference measures the net effect of joint execution. It can contain shared
resource serialization, batching gains, changes in joint readout destinations,
and heuristic scheduling choices. It is not automatically pure AOD contention.
Likewise max(solo) is an independent-execution reference, not a proven feasible
overlapped schedule or optimal lower bound. Do not clamp negative differences.

All differences are also decomposed using the same `i*` into mutually exclusive
step-time categories: CZ LOAD/MOVE/STORE, CZ pulse, readout LOAD/MOVE/STORE,
readout exposure, local rotations and reset. Compare real transport batches,
their active owners, row/column demands and distances to explain differences.
The batch's readout destinations preserve source row ordering; they need not
coincide with the solo destinations. An N-AOD comparison would be another
hardware model and is not synthesized by overlapping solo traces.

Whole-round completion includes all returned atoms at their homes and result
availability. Native gate/measurement interval ends alone do not establish
carrier return. `rounds_per_second` is aggregate individual W1 SE rounds per
second (`N/Tjoint`), not whole-array cycles per second or accepted magic states.

## Reproduction and evidence

With the existing Python 3.12 environment and this checkout first on PYTHONPATH:

```powershell
$env:PYTHONPATH="$PWD\modules\physical_compiler\src;$PWD"
python -m experiments.msd.parallel_se_survey --output output/parallel-se
python -m experiments.msd.parallel_se_plot output/parallel-se
python -m pytest experiments/msd/tests -q
```

The [plan](parallel_se_plan.json) freezes the 39 schedules spanning d=3/5/7 and
N=1/2/4. The runner enforces the same 120-second cell, 1800-second campaign and
20000-atom limits. It fingerprints runtime sources and reference configuration,
stops on source drift, and retains failures rather than silently dropping cells.
Every successful case retains the complete result and scheduler evidence.

`RecordedStrategy` observes the existing selector/lowerer without changing its
choices; equality against the unwrapped strategy is tested. Actual source IDs
establish CZ participant ownership. Ambient spectator illumination does not
count as active factory concurrency. The complete global trace is revalidated
against its native DAG, device, occupancy, pulse and measurement requirements.
Physical measurement values remain compilation fixtures, not quantum samples.

The previous [component survey](README.md) remains reproducible as a separate
position-dependent calibration. It must not be used as the concurrent-SE result.
