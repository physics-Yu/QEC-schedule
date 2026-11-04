# Surface SE trade-off platform, v1 specification

Date: 2026-10-27. Status: draft for review; nothing here is implemented.

## Purpose

Show an experimental group, for one rotated-surface-code syndrome-extraction
(SE) round, how architecture, compiler, AOD capability and timing parameters
trade speed against accumulated error and footprint. Timing and error
parameters are adjustable in the browser without recompiling.

v1 answers three questions:

1. How many SE rounds per second each configuration sustains, and at what
   per-round error proxy.
2. How much a flexible AOD improves on the rigid AOD the group operates now.
3. Where the ranking of configurations changes as transport, transfer and
   readout parameters change.

## Two layers

| Layer | Varies | Cost | Output |
| --- | --- | --- | --- |
| Compile grid | circuit, architecture, AOD motion, compiler, anchor timing | offline, once per cell | validated `nadit.result/2` + evidence |
| Evaluation | timing parameters, error parameters | in browser, per slider event | period, error proxy, breakdown |

The evaluation layer re-times a **fixed schedule**. It does not re-optimize.
Compilers may choose different schedules under different timing (the SMT
objective uses Device durations directly; whether Search Smarter scoring does
is to be checked in the pilot). To show this, every cell is also compiled at
each anchor timing (below); the chart draws the anchor recompilation as a ghost
marker next to the re-timed point. A visible gap means the slider result is a
lower-quality schedule, not the best achievable one.

## Compile grid

### Axes

| Axis | v1 values | Source |
| --- | --- | --- |
| Code distance d | 3, 5, 7 | `methods/surface_memory.prepare_memory`, basis z, pitch 8 um |
| Rounds R | 1, 2, 3 | same generator, `rounds=R` |
| Architecture | `shared` (shared/v1), `zoned-1row` (zoned/v1, one gate row), `zoned-multirow` (zoned/v1, d gate rows, current generator default) | generator `_architecture`, extended for row count |
| AOD motion x readout | flexible+batch, flexible+single, rigid+single | Device `aod.motion`, `measurement.readout.max_atoms` (null or 1) |
| Compiler | see below | registry `strategy.kind` |

Batch readout requires a flexible AOD, so rigid cells use single-atom
readout. Flexible single-atom readout separates the transport benefit of a
flexible AOD from the batching benefit.
| Anchor timing | A0, A1, A2 | see Parameters |

Compilers:

| ID | Configuration | Notes |
| --- | --- | --- |
| `ss-qec` | Search Smarter, `mode=qec`, ready/catalog, IDS (trials 4), strict, whole_layer, reuse none | generator default |
| `ss-qec-reuse` | `ss-qec` + `cross_layer_reuse=true`, `reuse.kind=matching` | ADR 0035 fixed-home reuse |
| `nonzoned` | `strategy.kind=nonzoned` | requires flexible AOD and shared arrays |

`smt` is excluded from this grid. It needs a hand-chosen coordinate alphabet
and horizon; its single-round d3 reference stays with the ADR 0058 harness.

Cell count before admission: 3 R x 3 arch x 3 AOD/readout x 3 compilers = 81
per distance and anchor.

### Admission

Admission comes from `experiment plan` / registry admission, never from a
hand-curated list. Generate inputs and label the plan with:

```text
python -m experiments.se_tradeoff.prepare --distance 3 --output experiments/se_tradeoff/inputs/d3
nadit experiment plan experiments/se_tradeoff/inputs/d3/experiment.json > plan.json
python -m experiments.se_tradeoff.admission experiments/se_tradeoff/inputs/d3/experiment.json plan.json -o experiments/se_tradeoff/inputs/d3/admission.json
```

d3 result (2026-10-27, all three rounds agree): 42 of 81 runs admitted
(14 of 27 configurations). Rejections:

- Search Smarter on `shared`: IDS placement needs a storage zone.
- `nonzoned` on zoned architectures: needs shared arrays with
  `cz.allow_spectators=true`.
- `nonzoned` with rigid AOD: requires flexible motion.

Admitted: `nonzoned` on shared with flexible AOD (batch and single readout);
`ss-qec` and `ss-qec-reuse` on both zoned row counts with all three
AOD/readout settings. Admission does not guarantee that compilation succeeds.

Unsupported and failed cells are listed in the chart legend with their reason;
they are never silently dropped.

### Budgets and determinism

- Per run `timeout_s` 600 for heuristics; `smt` uses its own `wall_timeout_s`
  and reports evidence status (`optimal_in_domain`, `feasible_unknown`,
  `unsat_in_domain`, `unknown`).
- Memory circuits have no feedback, so `case.seed` does not affect the schedule;
  it stays fixed at 17. Placement trials use the strategy's own seeds.
- Every result must pass `nadit validate`. Invalid results are failures.

## Parameters

### Timing (sliders)

| Slider | Device field | Notes |
| --- | --- | --- |
| AOD speed | `timing.move_us_per_um` (linear profile) | shown as um/us |
| AOD-SLM transfer | `timing.load_us`, `timing.store_us` | one slider, equal values, unless the group requires separate ones |
| Readout exposure | `readout.duration_us` | |
| Readout latency | `readout.latency_us` | affects only the final result tail (see Metrics) |

Gate durations (`cz.duration_us`, `local.rotation_us`, `local.reset_us`) stay
fixed at anchor values in v1.

The `paper` move profile has no free parameter. v1 uses the linear profile for
all sliders; `paper` appears only as an alternative anchor if requested.

Anchors: A0 = generator defaults (1 us/um, 10 us transfer, 10 us exposure,
500 us latency). A1 and A2 are group-supplied values for today's hardware
and a projected upgrade. **Ranges and A1/A2 are open decisions.**

### Error (sliders, additive model v1)

All fields of `cost/additive.py` `DEFAULTS`: `cz_infidelity`,
`single_infidelity`, `readout_infidelity`, `reset_infidelity`,
`transfer_loss`, `slm_t2_us`, `aod_t2_us`, `heating_per_um`,
`heating_us_per_um2`.

`heating_us_per_um2` adds `d^2 / t_move` per moved atom, so faster moves cost
error. Without a nonzero value the speed slider has no trade-off, so v1
requires a group-agreed nominal value. Calibrating it is an open decision.

## Metrics

Let `T(R)` be the program duration (sum of step durations) for R rounds,
**excluding** the final readout-latency tail, and `L(R)` the additive
`log_fidelity` (natural log, <= 0).

- Period: `P = T(3) - T(2)`. Report `P' = T(2) - T(1)` too. If
  `|P - P'| / P > 0.05`, mark the point "not steady" (hollow marker).
  Differencing cancels data initialization and final data readout.
- Rate: `rounds_per_s = 1e6 / P` (P in us).
- Per-round error proxy: `e = 1 - exp(L(3) - L(2))`. Hover shows the per-round
  breakdown by additive term (cz, single, readout, reset, transfer, idle,
  heating). Transfer is labelled as loss; the others as Pauli-like. This is a
  physical-event proxy, not a logical error rate.
- Footprint: area of the bounding box of every position any atom occupies in
  the R=3 schedule, in um^2. Also report the count of distinct SLM sites used
  and the declared Device area (SLM sites and zone bounds). Footprint does not
  depend on sliders.
- Anchor-only: logical error per round from the Stim memory method
  (`stim/v1`) at each anchor, shown in hover. It is not recomputed by sliders.

The ADR 0058 single-round `smt` reference does not enter the steady-state
chart; it can appear in a separate table with its evidence status.

## Re-timing data format: `nadit.retiming/1`

One JSON document per validated result, generated offline from the result
and its Device. It holds exactly what the evaluation needs to recompute `T` and
`L` as functions of slider parameters.

### Exactness basis

- A step lasts as long as its longest action (`AtomStep.duration_us`).
- Fixed actions take Device durations exactly; validation enforces this.
- Move duration is `move_duration(d)`, with d the largest atom endpoint
  displacement in the action; the validator only enforces a lower bound,
  so a recorded Move may be longer. Both move profiles are nondecreasing
  in d. Only the selected AOD moves, so a step holds at most one Move action;
  the exporter rejects a step with more. A step is then fully described by its
  Move distance plus the set of fixed action kinds present.
- Each atom's busy interval starts at the step start and ends with its own
  action; it is idle in its post-action holder until the step ends
  (`activity.py`).

### Schema

Implemented by `experiments/se_tradeoff/retiming.py`
(`python -m experiments.se_tradeoff.retiming RESULT.json --error-params P.json`).

```json
{
  "schema": "nadit.retiming/1",
  "result_hash": "cost.base.result_hash of the result",
  "compiler": {"kind": "search_smarter", "version": "1"},
  "reference": {
    "timing": {"move_profile": "linear", "move_us_per_um": 1,
               "load_us": 10, "store_us": 10, "cz_us": 0.5,
               "rotation_us": 1, "reset_us": 5, "global_ry_us": null,
               "measure_us": 10, "latency_us": 500},
    "duration_us": 3806.47,
    "available_us": 4306.47
  },
  "footprint": {"bbox_um2": 6700.0, "slm_sites_used": 49, "device_um2": 8800.0},
  "counts": {"cz": 24, "single": 0, "readout": 8, "reset": 0, "transfer": 0},
  "final_holders": {"slm": 17, "aod": 0},
  "signatures": [
    {
      "n": 12,
      "kinds": ["load"],
      "move_um": null,
      "idle": {"slm": 9, "aod": 0},
      "tail": [[["load"], "aod", 8]],
      "moves": null
    },
    {
      "n": 6,
      "kinds": ["move"],
      "move_um": 24.0,
      "idle": {"slm": 9, "aod": 0},
      "tail": [[["move"], "aod", 8]],
      "moves": {"sum_d_um": 144.0, "sum_d2_um2": 2688.0}
    }
  ],
  "last_measure": {"signature": 1, "after": [[0, 3]]},
  "acceptance": {"retiming_exact": true, "duration_us": {}, "term_mismatches": {}}
}
```

Numbers above are illustrative. Fields:

- `reference.duration_us`: program duration (sum of steps).
  `reference.available_us`: duration including the final readout-latency tail,
  as used by the additive idle term.
- `footprint.device_um2`: bounding box of declared SLM sites and zone bounds.
- `counts`: event counts for the θ-independent additive terms.
- `final_holders`: atoms per holder after the last step; they are idle for
  the latency tail.
- `signatures[*].n`: number of steps with identical content (order is
  irrelevant for `T` and `L`).
- `kinds`: action kinds present: `load`, `store`, `move`, `cz`, `rotation`
  (Rotation and LocalU), `global_ry`, `reset`, `measure`.
- `move_um`: the Move action's maximal atom displacement, or null.
- `idle`: per holder, atoms with no action in the step (idle all step).
- `tail`: `[own_kinds, holder_after, count]` for busy atoms; each is idle in
  `holder_after` for `D - max f(own_kinds)`. All atoms of a Move action finish
  together, so moving atoms use `f(move, move_um)`.
- `moves`: per-atom displacement sums for heating, with `f(move, move_um)` as
  `t_move`.
- `last_measure`: signature index of the last step containing a Measure, and
  `[signature, count]` for the steps after it; null without measurements.
- `acceptance`: written by the CLI; see below.

### Evaluation

For parameters θ, with `f(kind, d; θ)` the Device duration:

```
D_s(θ)    = max over kinds in s of f(kind, move_um; θ)
T(θ)      = Σ_s n_s · D_s(θ)
A(θ)      = max(T, T − Σ_after n·D − D_last + f(measure) + latency)
idle_h    = Σ_s n_s · [ idle_s[h] · D_s + Σ_tail(h) count · (D_s − max f(own_kinds)) ]
            + final_holders[h] · (A − T)
heating   = Σ_s n_s · [ heating_per_um · sum_d + heating_us_per_um2 · sum_d2 / f(move, move_um) ]
L(θ)      = Σ_k counts_k · log1p(−p_k) − Σ_h idle_h / T2_h − heating
```

### Exporter acceptance

The exporter is accepted per result only if, at the reference parameters:

1. `T` and `A` equal the recorded program and available durations within
   1e-6 us, and
2. every additive contribution equals the independent `cost.evaluate`
   output within 1e-9 relative.

A result failing (1) has a Move recorded longer than its lower bound.
It is still exported, flagged `retiming_exact=false`, and drawn with a warning
marker; v1 re-times such Moves with `move_duration(d)` and reports the
reference discrepancy. The exporter rejects (`UnsupportedSchedule`) steps with
`Wait` (feedback latency), several Move actions, or removed atoms.

At `6bbe046`, the tests compiled d3 one-round memory for zoned Search Smarter
and shared nonzoned and checked (1) and (2) with nonzero error parameters.
They independently recompiled with altered transport, transfer, exposure and
latency, then compared step structure, recorded duration and `cost.evaluate`
terms with re-timing. The [current regressions](../../experiments/se_tradeoff/tests/test_retiming.py)
cover input overwrite, CPhase, feedback and rotation durations inconsistent
with the device.

## Chart

Main panel: x = per-round error proxy `e` (log scale), y = rounds per second
(log scale), marker area proportional to footprint `bbox_um2`, colour =
architecture, shape = compiler, fill = flexible / outline = rigid. Faceted or
filtered by d. Pareto front (higher rate, lower error) drawn per d. Ghost
markers: anchor recompilations at the nearest anchor.

Linked panel: x = footprint `bbox_um2`, y = rounds per second, same encodings.
Hovering or selecting a point highlights it in both panels.

Hover: configuration, P and P', error breakdown, footprint triple, evidence
status, anchor logical error, `retiming_exact`.

Controls: timing sliders, error sliders, anchor reset buttons, d selector.
Legend table: unsupported or failed cells with reasons.

Deferred to v1.1: per-slider ranking-flip markers.

## Pilot and acceptance

1. Done: generate inputs for d=3, R=1..3, all architectures and AOD motions.
2. Done: `experiment plan`; admitted and unsupported cells recorded above.
3. Run A0 for all admitted d=3 cells; validate; export re-timing documents.
4. Check exporter acceptance on every result, and steady-state agreement
   `P ≈ P'`.
5. Recompile at A1; compare ghost against re-timed points; decide whether the
   gap needs more anchors.
6. Extend to d=5, 7 only after the pilot passes.

## Open decisions

- Slider ranges and anchor values A1, A2 (group).
- Nominal error parameters, especially `heating_us_per_um2` and T2 by holder
  (group or literature).
- Separate load/store sliders or one transfer slider.
- Whether `zoned-1row` needs generator support beyond the row count.

## Out of scope for v1

HGP/LP and other codes, algorithm circuits, measurement feedback, slider-driven
logical error rates, gate-duration sliders, and re-optimization under sliders.
