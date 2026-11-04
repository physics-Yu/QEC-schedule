# Surface SE trade-off platform

Design: [v1 specification](../../docs/experiments/se-tradeoff-v1-spec.md).

Run from the repository root with the physical compiler environment
(`modules/physical_compiler/.venv`, extras `simulation`; `stim` is required).

| Module | Purpose |
| --- | --- |
| `prepare.py` | Freeze surface-memory circuits for R=1..3, a pinned suite and the `nadit.experiment/1` grid |
| `admission.py` | Label `nadit experiment plan` output by architecture, AOD/readout and compiler |
| `retiming.py` | Export a validated result as `nadit.retiming/1`, re-evaluate it, and check it against `cost.evaluate` |

```text
python -m experiments.se_tradeoff.prepare --distance 3 --output experiments/se_tradeoff/inputs/d3
nadit experiment plan experiments/se_tradeoff/inputs/d3/experiment.json > plan.json
python -m experiments.se_tradeoff.admission experiments/se_tradeoff/inputs/d3/experiment.json plan.json -o experiments/se_tradeoff/inputs/d3/admission.json
nadit method retiming/v1 RESULT.json --params PARAMS.json -o RESULT.retiming.json
python -m experiments.se_tradeoff.retiming RESULT.json --error-params PARAMS.json -o RESULT.retiming.json
```

The last two commands write the same `nadit.retiming/1` document. The optional
parameter file contains additive error parameters for the reference check.
The `acceptance.retiming_exact` field records agreement with the original
durations and additive cost. Python callers can use
`nadit_physical_compiler.methods.retiming.evaluate(exported, timing, error)`
to evaluate alternative timings on this fixed schedule. The method accepts
retained-atom, feedback-free schedules with supported action kinds and at most
one MOVE per step. Native CPhase and WAIT are outside this model.

`inputs/d3/` holds the generated d3 inputs and the recorded admission table.
The parameter scan is pending.
At `6bbe046`, the tests compared re-timing with independent d3 one-round
recompilations. The current [regressions](tests/test_retiming.py) reproduce
input overwrite in the legacy CLI and three cases the exporter mishandled.
