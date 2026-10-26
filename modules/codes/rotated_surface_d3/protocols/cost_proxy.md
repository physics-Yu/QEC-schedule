# Explicit factory and consumer cost proxies

Status: opt-in physical cost experiment. Actual quantum resource quality remains
unknown; neither event defines logical success. Inventory policy and decoding are
outside this protocol.

## Execution contract

Use `factory_proxy_recipe()` and `SurfaceCostProxyBackend(device)` from
[cost_proxy.py](cost_proxy.py). The frozen four-plus-eleven quantum body, raw
reset/repreparation, parity CNOTs, conditional S and final MX operations remain
unchanged. Only the final event selector becomes `factory_cost_proxy` and the
protocol identity explicitly ends in `.cost_proxy`.

Raw preparation uses the actual-source joint Pauli/readout port. Accepted raw
resources retain `actual_quality.status="unsupported"`. The proxy adapter adds
an explicit `routing_reference` and opaque `consumption_parameters` permitting
ideal-reference m0/m1 routing. These are not sampled physical measurement bits
or quantum probabilities asserted for the actual noisy resource. Missing markers,
`input_z_error=0`, and a factory event without scoped cost evidence are rejected.

The logical compiler supplies an admitted, source-dependent interval cost report:

```python
factory_port = backend.factory_proxy_event(noise_report, scope_evidence)
algorithm_port = backend.algorithm_proxy_event(noise_report, scope_evidence)
```

The underlying pure functions are `factory_proxy_port` and `algorithm_proxy_port`
in [probabilities/cost_proxy.py](../probabilities/cost_proxy.py). Factory outcomes
carry `accepted` and `proxy_no_fault`, with deliver/retry transitions. Consumer
outcomes carry identical `proxy_success` and `no_fault` flags; both continue.
Every port records `logical_success_probability=None`. The runtime ledger must
likewise keep `logical_success=null`.

## Disjoint noise ownership

Let tF be readiness of all final factory MX actions/results and tA be completion
and required result readiness of the chosen algorithm route.

| Scope | Included | Excluded or deferred |
| --- | --- | --- |
| Factory attempt start through tF | Actual non-raw operations and exposure, including final MX/readiness wait | Every already-sampled raw interval from its first action through results-ready, for the entire occupied world |
| tF through tA | Accepted output X, delivery waiting, algorithm initialization, T consumption, conditional S and readiness | Earlier factory/raw scopes |

Factory probability is constructed before accepted-only output X. That X is not
moved earlier or included in a probability already sampled. Output quality records
`delivery_assessment.status="pending"` and its start tF; the downstream consumer
owns it. A resource without a consumer has unassessed delivery cost, not a newly
certified fault-free quantum state.

All raw attempts, including rejected attempts, have their complete noise horizon
excluded from the factory proxy. Their physical costs remain in the full trace.
This also excludes other work blocks' memory noise during those raw intervals;
the proxy makes no statement about that residual quality. Independent re-sampling
of the same raw noise as a no-fault event is prohibited.

`included_intervals_us` and `excluded_raw_intervals_us` must be disjoint and
together cover the declared positive-length `window_us`. No unowned gaps are
allowed. For the first consumer experiment, with no raw preparation in that
window, its included interval covers the entire window. Endpoint ownership of
discrete channels follows the complete action, not a bare half-open timestamp.

## Cost report and probability admission

The physical helper first admits and prepares the complete real source. It clips
all retained atoms' idle/busy exposure and keeps complete selected actions; a cut
through any non-Wait action is rejected. It reruns the existing `noise/v1` model
on this selected activity. It does not fabricate a clipped executable program or
scale a whole-trace probability by a duration ratio.

The report includes `time_scope="disjoint_include_intervals"`,
`probability_kind="physical_no_fault_proxy"`, and versioned `interval_selection`
with original event indices/maps, source/selected activity hashes, selected
duration and interval partition rules. Scope evidence supplies the stage, window,
included/raw-excluded intervals and matching source/result/activity identities.
One source Wait may produce several pieces in distinct included intervals. The
source-index list stays unique, while the piece map has consecutive selected IDs
and nondecreasing source IDs. The producer checks their timing and identity;
admission of a splittable source action remains the physical helper's responsibility.
The port producer cross-checks these fields, requires Pauli gate backends and
`rates/v1` transport, validates resolved parameter hashes, and recomputes

`Pproxy = product(channel identity probability) * product(loss event survival)`.

It checks this against `metrics.no_fault_probability`. Loss is already included;
aggregate survival is checked but not multiplied a second time. `fidelity` is a
different diagnostic and is not used.

T2 uses the fixed original-activity-interval intersections with merged included
intervals. Its net-Z channel has `pZ(t)=(1-exp(-t/T2))/2`, so the no-fault product
depends on this partition: two interval identity probabilities do not equal the
unsplit identity probability. The partition is frozen and fingerprinted, and no
equivalence to the old whole-trace no-fault product is claimed.

These proxies describe selected operations under configured channels. They do
not propagate unknown raw-state errors, simulate conditional noisy quantum
states, apply a decoder, or certify an algorithm's answer. A typical-seed sample
and deliberately selected rare-branch witnesses must be reported separately;
witnesses are demonstrations, not an unbiased success-rate estimate.

A false no-fault flag does not identify a realized fault or lost atom. Occupancy
continues to use the declared retained-atom world; the selected retry compiles
reset/repreparation actions but does not simulate loss recovery or replacement
cost. This is a cost-driven control-flow experiment, not a hardware loss trajectory.
