# 0055: Fixed-distance raw injection followed by ordinary code growth

Status: Accepted for the component and resource experiment scope.

## Context

Version 2 postselected every check in every target-distance round. Increasing
both spatial and temporal coverage therefore rejected many correctable faults.
The user requests the two-stage approach of Li, Phys. Rev. A 91, 022316 (2015),
[arXiv:1410.7808](https://arxiv.org/abs/1410.7808): postselect a small injected code,
then enlarge it using ordinary syndrome extraction and decoding.

## Decision

- Injection distance is fixed at three. Preserve the previously agreed **three**
  injection rounds by default; `injection_rounds=2` explicitly selects the paper's
  two-round timing variant. This distinction is recorded in every cache identity.
- Embed the 17 small-patch carriers at the upper physical edge of the target
  patch. Reuse their target carrier identities; no logical state is copied.
  Initialize new rows in plus and new columns alongside the seed in zero.
  Measure target checks, then run ordinary SE until a total of d growth rounds
  has completed. Target d3 has no growth stage.
- The physical code is our rotated patch and extraction order, not a reproduction
  of the paper's unrotated corner circuit or its reported error coefficients.
- `get_component("raw_t", d)` contains one d3 injection round and ordinary growth.
  It remains an unqualified raw primitive, with no retry control.
- Public `RawTPostselection(d)` is a staged version-3 protocol. `expand` returns
  injection only. `grow` requires received accepted results, their ready time,
  the matching source/binding, and a fresh result-ID allocation. Growth has no
  acceptance predicates. Delivery requires complete growth results and an
  explicitly returned Pauli frame.
- Initial target syndromes are gauge outcomes. Decode temporal changes using
  phenomenological MWPM with open temporal ends and configurable positive edge
  weights; correct the initial gauge using inferred measurement faults. Default
  unit weights are a decoder choice, not a change to physical noise. This does
  not claim circuit-level optimality, a fault-distance proof, or output LER.
- Keep target/world geometry, timing and noise unchanged. Add stationary outer
  homes to injection template planning: otherwise AOD intersections can capture
  unused target atoms. Every bound trajectory is checked in the complete world.
- A staged probability port describes **injection acceptance only** and continues
  to the growth phase. It cannot deliver a target output. Its identity includes
  both templates and stage policy; cache admission also checks resolved noise.
  Historical all-d profiles remain reproducible through `DirectRawTPostselection`
  and `raw_t_direct_control`; they are not defaults.
- Conditional additive resource cost is `C_injection / P_accept + C_growth`.
  The benchmark compiles an unobserved continuation cost reference, without
  fabricating accepted measurement results. Physical loss remains separate.

## Consequences and boundaries

The logical caller must retain or physically apply the returned frame before
using the output. Existing d3 factory/canonicalization interfaces still describe
three d3 rounds and remain valid for d3; their canonical-class caches do not admit
the new binary staged port. A generic d5/d7 full distillation factory backend and
its joint preparation-class table were already absent and are not supplied by
this component change. A future fast compiler must use both stages, distinguish
intermediate acceptance from final delivery, and retain this cache identity.

Tests cover ideal X/Y/Z seed channels through growth, actual nonzoned compilation
in occupied worlds, postselection gating, cache rejection, nonzero growth gauges,
persistent data faults, and readout blips. These checks do not establish the
accepted output error under the illustrative circuit-level noise model.
