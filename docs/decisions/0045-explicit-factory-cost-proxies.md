# ADR 0045: Explicit factory and consumer cost proxies

Status: Accepted for the user-selected cost-model experiment only.

## Context

Actual-source raw preparation provides joint detector acceptance and correction
classes. It does not establish the accepted state's noisy quantum quality. The
user selected a physical no-fault cost experiment to exercise factory retries and
downstream T consumption without presenting unknown quality as zero input error.

## Decision

Keep the six-patch four-plus-eleven quantum recipe unchanged. Use a separately
identified proxy protocol and an explicit ideal-reference routing marker for
T-consumption branches. Raw events continue to require actual-source noise/v1
evidence. Resource quality and logical success remain unknown.

The logical compiler owns admitted physical-activity slicing, event sampling,
retry execution and the resulting static case. Code-owned pure probability ports
cross-check scope and report evidence and recompute each Pauli identity and loss
survival factor. Aggregate loss survival is never multiplied a second time.

The factory scope ends when final MX actions/results are ready, before the
accepted-only output X. It excludes every raw attempt's complete horizon for the
whole occupied world. Included and excluded intervals cover the whole declared
window. A downstream consumer scope starts at that factory decision and includes
output X, handoff waiting, initialization, consumption and conditional S. Without
a consumer, delivery assessment remains pending.

Freeze T2 exposure at intersections of original activity intervals and merged
included intervals. This defines a partition-dependent no-fault event; no
equivalence to a different whole-trace partition is claimed. Only the physical
helper may admit a split Wait; ports check its piece timing and source map.

## Alternatives

Inferring output quality from raw rejection or setting unknown input error to
zero would make an unsupported quantum claim. Re-sampling complete raw horizons
as no-fault events would double count independent feedback decisions. A complete
noisy quantum factory with recovery and decoding is a separate future model.

## Consequences

The experiment can exercise real compiled retry/correction actions and compare
their costs. A proxy rejection identifies no particular fault or lost atom, and
does not simulate atom replacement. Typical seeds and selected rare-branch
witnesses must be reported separately. This decision adds neither inventory
policy nor logical-success qualification.

See [the execution contract](../../modules/codes/rotated_surface_d3/protocols/cost_proxy.md).
