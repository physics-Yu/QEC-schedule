# ADR 0052: Joint SE scheduling with matched position controls

Status: User-directed implementation, 2026-10-24.

## Context

The earlier N-axis component calibration selected only the bottom factory W1.
It measured increasing readout distance, not concurrent execution. The user
requested a replacement measurement with all N SE instances submitted together
while retaining the agreed layout, timing and single-AOD hardware.

## Decision

Compose one existing SE source per W1 into separate registers, preserving only
each source's internal barriers/dependencies. Import the complete source once
and compile it once through the existing physical global frontier, nonzoned
placement/transport/readout and complete-world state. All 6N patches remain
present. The physical compiler, strategy and hardware are unchanged.

Use three actual schedules at every d,N: joint, explicitly serialized sources,
and each factory solo at its existing position in the same world. The primary
quantity is whole-round time including every final home return and result
availability. Keep the same total-slowest solo i* when decomposing every phase.
Separate solo position effect from the signed net effect of joint execution;
report actual shared transport batches, control exposure and motion distances.
No unobserved resource-blocking causes are invented from aggregate idle time.

## Alternatives

The separately active logical compiler's component-level lockstep adapter is
currently specialized for horizontal tiles. Importing that subsystem would add
unrelated factory/event machinery and still require vertical support. This fixed
SE kernel has no logical branch or resource-consumption decisions; the existing
physical global scheduler already operates over its full ready frontier. It is
therefore used directly and identified explicitly in the results.

Overlaying separate atom traces is not an executable shared-world control.
Adding independent AODs would change hardware and require another physical
scheduler. Neither approach is used. `max(solo)` is only a comparison reference,
not a claim of feasible independent execution or an optimal hardware bound.

## Consequences

The [frozen plan](../../experiments/msd/parallel_se_plan.json) specifies 39 actual
joint/control schedules over d=3/5/7, N=1/2/4. All complete schedules and observed
layer/batch evidence are retained. Instance/result identities, initial readiness,
true multi-owner operations, physical semantic validation, exact return replay,
and a lossless elapsed-time partition form the acceptance checks.

This establishes a simultaneous SE-kernel experiment, not sustained factory
production or a decoded logical error rate. The observation wrapper is tested
to leave the original strategy's exact CompilationResult unchanged.
