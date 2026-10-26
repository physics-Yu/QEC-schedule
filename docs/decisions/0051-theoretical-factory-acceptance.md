# Theoretical factory acceptance with separate physical cost diagnostics

Status: Accepted, implemented and verified, 2026-10-24. Supersedes the default
acceptance-model selection in
[ADR 0050](0050-fast-logical-experiments.md), while retaining its execution-kernel,
scheduling, calibration and accounting design.

Scheduling update, 2026-10-24:
[ADR 0055](0055-mandatory-component-batching.md) supersedes optional serial
controls and the serial calibration prerequisite. The probability contract and
all frozen experimental results below remain unchanged; they do not establish
performance for later scheduling revisions.

## Context

Both the full factory-array entry and the first fast experiment selected
`factory_proxy_recipe()`. That recipe replaced the existing joint final-MX event
with `factory_cost_proxy`: all modeled physical operations having no fault became
the criterion for issuing an output token. Fast compilation reproduced this
earlier full-entry choice. Agreement between the two entries therefore did not
establish that they sampled theoretical 15-to-1 acceptance.

The user confirmed that the fake backend should sample the theoretical 15-to-1
model, without first implementing a full noisy Stim factory simulation. The
accepted-input reference parameter for the corrected study is explicitly
**p = 0.01**. This is the Z-error probability of each raw A state after its
preparation was accepted and its local correction completed. Neither raw
rejection probability nor a physical gate error rate determines this parameter.

The physical diagnostic also had a coverage gap: excluding one line's raw-time
union from all six patches excluded successful patches' storage during those
attempts. The raw acceptance model does not include physical loss, so excluding
that whole interval left raw loss outside both assessments. This is a diagnostic
coverage issue, not a reason to add another factor to the theoretical acceptance.

## Decision

### Three distinct model quantities

| Quantity | Source and meaning | Effect on control |
| --- | --- | --- |
| Raw acceptance and local correction class | Existing code-owned noisy raw preparation model; one joint event, profiled for the fast path | Reject resets and retries only that patch; accepted canonical resources become available |
| Final joint MX checks and conditional output quality | Existing `factory_mx_port(input_z_error=p)` under an explicit iid input-Z-error model | One joint draw controls acceptance, rejection and output creation; quality is metadata |
| Physical no-fault diagnostic | `noise/v1` on the selected line's complete evaluation window, or its calibrated fast estimate | Recorded separately; does not affect theoretical acceptance or create a second final draw |

The supply and accepted-state quality parameters are independently declared model
inputs. This separation is not a claim that a physical raw implementation has
independent preparation failures and output errors. The reference input quality
is assumed; it is not derived from the current raw circuit or cost model.

### Final checks use the existing theoretical joint distribution

The common recipe remains `factory_recipe()`. Its `factory_mx` event obtains the
16 joint four-bit outcomes from the code-owned finite convolution over 15
independent input Z errors. All four check bits being zero is the only accepting
outcome. The controller must not draw a separate Bernoulli acceptance bit or four
independent MX bits. Accepted output X and resource delivery follow that same
event. The accepted output-error mass is not controller-visible feedback.

For x = 1 - 2p, this reference model gives

\[
a(p)=\frac{1+15x^8}{16},\qquad
p_{\mathrm{out}}=\frac{1-15x^7+15x^8-x^{15}}{2(1+15x^8)}.
\]

At the user-confirmed **p = 0.01**, the implemented finite convolution returns
**a = 0.860090333670424** and
**p_out = 3.60876839653233e-05**, conditional on acceptance and output
canonicalization. Factory Clifford gates, storage and readout are ideal in this
reference calculation. The result is not a noisy d3 logical failure rate or a
fault-tolerance certification. Conditional quality can be passed as reference
metadata to a later consumer; it is not a measured error bit.

The raw supply model still rejects and retries according to its own distribution.
Changing the declared p changes the accepted-resource quality and theoretical
final checks, not the raw supply probability. The final reference probability
does not vary with scheduling time under its ideal-storage assumption. Physical
diagnostics do vary with that time. This distinction must remain visible in
serial/parallel and scaling comparisons.

### Explicit model selection at both entries

`examples.factory_array` and `examples.factory_fast run/sweep` default to
`--acceptance-model theory`, and require an explicit `--input-z-error` value.
There is no silent p=0 or inferred-p fallback. The corrected study passes
`--input-z-error 0.01`; this study choice does not become an implicit library
default. Code, profile/configuration, model ID and p are retained in exports.

Historical proxy experiments remain available only through the explicit
`--acceptance-model physical_no_fault_proxy` selection, which rejects an
`--input-z-error` argument. Their final proxy decision and output quality retain
legacy semantics and clear labels. Full and fast theory paths share the same
factory probability port and quality contract; the compiler continues to own
dependencies, frontier admission, barriers, retries and resource lifecycle.

### Complete line-window physical diagnostic

The theory path uses `full_line_diagnostic` from that line's first component in
the batch to its own final-check evaluation. All six patches and all 102 carrier
roles are included throughout that window. Raw attempts, rejected attempts,
resets, transport loss, holder residence and other patches' waits during raw
production remain in the cost assessment. Raw horizons are retained as provenance,
not excluded. Physical evaluation selects actual owned atoms in the shared
timeline; fast evaluation rebuilds the calibrated role intervals and channel
contributions on the current component schedule.

The fast report records per-patch role-time coverage, overlap with raw windows,
SLM/AOD residence and channel log contributions. Its `controls_factory_acceptance`
is false. A full-line diagnostic cannot be converted into a factory proxy event.
No physical loss event is sampled and no atom is removed or replaced by this
diagnostic. `no_fault_probability` already includes modeled loss; a separate
all-survive factor must not be multiplied into it.

This no-fault value diagnoses the physical channels assigned to the selected
actions and timeline. It is not conditioned on the raw postselection outcomes
already selected by the fake backend, and is not multiplied by either raw or
factory acceptance probability.

This window excludes later final-cohort waiting, accepted output X and subsequent
output holding. Those downstream costs need a separately declared assessment.
Neither path infers shared-control correlations or actual accepted-state quality
from its no-fault number. Fast estimates still do not run physical validation.

`legacy_raw_excluded_proxy` retains the previous raw-union exclusion, its coverage
limitations and old numerical behavior for reproducibility. Old saved artifacts
are preserved rather than relabeled as theory runs.

## Verification and experiment records

The pre-change combined baseline is **1159 passed in 310.96 seconds**. The
corrected acceptance artifacts are saved under
`modules/logical_compiler/artifacts/theoretical-factory-verified/`:

- `fast/` and `replay/`: the same declared p and seed, with deterministic case,
  event and resource readback.
- `full/`: a matching physically expanded case, including physical validation
  and an independent complete-window diagnostic.
- `scaling/`: normal seeds 0 through 15 at 1, 2, 4, 8 and 16 lines, with one AOD,
  four rows, 48 columns and 96 simultaneous readout atoms held fixed.

The [formal validation](../../modules/logical_compiler/artifacts/theoretical-factory-verified/validation.md)
and [independent readback](../../modules/logical_compiler/artifacts/theoretical-factory-verified/independent-audit.json)
verify joint-check/acceptance consistency, raw local retry, successful-resource
retention, unique output delivery, repeated-seed reproducibility and full/fast
event semantics. The independent audit completes **7821 checks with zero failures**
without invoking compiler APIs.

The detailed seed-0 case uses two lines and the fixed resource budget above. It
records **35 raw attempts, five raw rejections, six conditional S calls and two
offered outputs**. All eight initial raw calls share one wave. In that initial
cohort, only `factory0/W5` rejects and independently retries; the other seven
accepted resources remain retained. Both final joint outcomes are 0000.

Full and fast exports contain **225 component calls, 61 coarse events and 116
admitted waves**. Their control flow, event semantics, resource lifecycle, wave
membership and timing match with zero observed differences. The maximum event
probability difference is zero. The fast case, ledger, diagnostic report and
resource audit replay byte for byte. Full physical motion, coverage, replay,
pulse, addressing and timing checks pass; those checks do not certify individual
physical measurement values or decoded logical correctness. Fast still has no
physical bundle or current physical-validation claim. The full/fast diagnostic
relative differences are **4.4141259199406665e-12** and
**3.6218552819772375e-12**, separate from theoretical event agreement.

The completed prespecified scaling study reports:

| Factories | Independent seeds per size | Accepted outputs / line executions |
| ---: | ---: | ---: |
| 1 | 16 | 11 / 16 |
| 2 | 16 | 24 / 32 |
| 4 | 16 | 50 / 64 |
| 8 | 16 | 102 / 128 |
| 16 | 16 | 220 / 256 |

All 80 cases reach valid terminal states at the declared p=0.01. Seeds 0 through
15 are reused across sizes. The 496 line executions must not be pooled as
independent samples, and repeated sizes do not add independent seed trajectories.
Detailed seed 0 is already part of the matrix and is not counted again. The
stored ledgers record 8617 raw attempts, 1177 raw rejections and 2617 S calls.
Software wall times collected during concurrent validation are not presented as
a controlled performance benchmark.

The final combined regression passes **1213 tests in 290.72 seconds**, compared
with the fresh baseline of 1159 in 310.96 seconds. Both use:

```powershell
python -X faulthandler -m pytest modules/logical_compiler/tests modules/codes -q
```

The saved [quality record](../../modules/logical_compiler/artifacts/theoretical-factory-verified/quality.json)
also records Ruff check/format passing for 19 changed Python files and strict
mypy passing for ten production files. Logs are
`artifacts/theoretical-factory-baseline.log` and
`artifacts/theoretical-factory-verified/tests.log` under the logical module.

Fast, replay and scaling exports match the current 86-source snapshot. Full
generation used a stable snapshot; one subsequently changed sentence in the
nonexecuted `fast_report.py` differs from the current broad source list. Its
original bytes are retained and SHA-verified in `full-source-snapshot/fast_report.py`.
No runtime or probability code changed after the runs, and the original full
manifest was not rewritten. The [source provenance record](../../modules/logical_compiler/artifacts/theoretical-factory-verified/source-provenance.json)
documents this exception; full generation is not claimed to match every current
source byte. The corrected ledger and scaling pages also passed automated browser
inspection, which is not user visual sign-off or quantum-state simulation.

The original 80-run study in `artifacts/fast-logical-verified/scaling` remains a
**legacy physical-no-fault-proxy** experiment. Its 496 line executions all acquired
15 accepted raw resources and all rejected at the final proxy event. These are
not theoretical 15-to-1 failures and cannot establish theoretical distillation
throughput. Its timing, resource and software-performance evidence retain their
declared scope; the old outcome labels must accompany any reuse.

## Alternatives and consequences

Waiting for a full noisy factory simulation would delay the explicitly requested
reference experiment and is unnecessary for sampling this known joint model.
Inferring p from raw rejection or physical gate noise would invent an unvalidated
mapping. Multiplying the theoretical acceptance by physical no-fault probability
would create a different, unjustified acceptance model. None is selected.

The existing scheduler and factory state machine remain common to both entries.
The added model contract makes probability selection explicit and prevents cost
diagnostics from silently replacing protocol checks. The resulting experiments
support conditional reference-model scaling and cost comparisons, while decoded
logical correctness and hardware throughput remain separate questions.
