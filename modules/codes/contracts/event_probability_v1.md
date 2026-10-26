# Event probability ports v1

Status: the user authorized this shared contract and parallel implementation on
2026-10-23. Numerical nonideal profiles remain explicitly selected inputs.

## Agreed execution model

Compilation expands dynamically from sampled protocol events. Its completed
output is one static case: selected invocations, dependencies, events and timing
are fixed. A different seed can produce another static case. Do not leave an
unresolved probabilistic branch in a result labeled complete.

Codes own event semantics, probability estimation and local continuation rules.
The logical compiler owns the seeded event backend, occurrence identities,
availability checks, retries, DAG expansion and static-case serialization.
Physical compilation retains ownership of atom actions and physical legality.

This first backend samples a finite joint protocol event. It does not generate
physical syndrome records. A detailed syndrome/decoder backend is an explicit
reserved capability, not a fallback that silently returns uniform bits.

## Portable document

The schema is `nadit.event_probability/1`. The code-owned Python entry point is
`modules.codes.contracts.event_probability.ProbabilityPort`:

- `ProbabilityPort.from_dict(document)` validates and makes an immutable port.
- `port.to_dict()` returns a fresh JSON-compatible document.
- `port.content_sha256` identifies the complete canonical port document.
- `port.outcomes` contains immutable records with `key`, `probability`, `values`
  (immutable key/value pairs), and `branch_id`.
- `port.branches` contains immutable records with `key`, `transition`, `steps`.
- `port.outcome(key)` and `port.branch(key)` resolve records or raise `KeyError`.
- A step has `component_id` and `participant_roles`. Ordered steps execute in
  sequence before the branch transition. Actual atoms and times are late-bound.

The wire representation is:

```json
{
  "schema": "nadit.event_probability/1",
  "port_id": "rotated_surface_d3.t_injection.logical_z",
  "protocol_id": "rotated_surface_d3.t_injection.data_to_magic_mz",
  "protocol_version": "1",
  "model": {
    "id": "ideal_equatorial_magic",
    "kind": "ideal_exact",
    "assumptions": [
      "Independent canonical T|+> magic resource",
      "Ideal logical CNOT(data, magic), then logical Z measurement of magic"
    ],
    "parameters": {},
    "evidence": {}
  },
  "outcomes": [
    {"key": "m0", "probability": 0.5, "values": {"logical_m": 0}, "branch_id": "no_correction"},
    {"key": "m1", "probability": 0.5, "values": {"logical_m": 1}, "branch_id": "apply_s"}
  ],
  "branches": [
    {"key": "no_correction", "transition": "continue", "steps": []},
    {"key": "apply_s", "transition": "continue", "steps": [
      {"component_id": "rotated_surface_d3/logical_s", "participant_roles": ["data"]}
    ]}
  ]
}
```

Model kinds are `ideal_exact`, `pauli_exact`, `estimated`, and `test_fixture`.
Model parameters and evidence are finite JSON objects; they carry explicit input,
noise, protocol, calculation and statistical assumptions as applicable. A port
is not an unconditional property of a code family. Unsupported state/model
conditions must be rejected rather than silently assigned a probability.

Outcome probabilities are finite numbers in [0,1], sum to one within absolute
tolerance 1e-12, and are never silently normalized. Outcome keys and branch keys
are unique; every outcome references a declared branch. All outcomes have the
same set of joint value fields, whose values are JSON scalars. Related events
belong in one joint outcome rather than independent samplings of marginals.

Transitions are `continue`, `deliver`, and `retry`. `retry` means a fresh attempt
of this invocation's protocol after its declared steps and physical exit; its
initialization/cleanup work is not free. The caller owns a finite retry budget.
Exhaustion is an explicit incomplete/failed case, never a successful static case.
An unsupported continuation component is an explicit capability failure.

## Bound event occurrence and outcome

The logical compiler defines its occurrence/result records using these fields:

```text
Occurrence identity = (case_id, invocation_id, attempt, port_id)
Bound input = identity + port.content_sha256 + available_at_us
Result = bound input + outcome_key + evidence_kind="coarse_probability"
```

`attempt` is a nonnegative integer. The bound availability is finite and
nonnegative and comes from the component/protocol's complete result dependency,
plus any explicitly modeled classical-processing delay. Static ports contain no
case clock, seed, actual outcome or mutable measurement/attempt state.

For a fixed case seed, an occurrence samples exactly once. Repeated requests
return the same stored result. Reusing an identity with a changed port fingerprint
or availability time is an error. A new retry gets a new attempt/invocation;
changing frontier visitation order must not reassign outcomes to occurrences.

The compiler may calculate the random outcome offline, but no branch dependency
may be released before `available_at_us` and the relevant physical/resource exit.
Physical compilation failure is not a random protocol rejection.

The completed static artifact must retain the occurrence, selected outcome,
probability-model fingerprint, chosen branch, expanded steps and timing. An
abstract case graph must identify itself as such; it is not an AtomProgram until
actual component binding/expansion and physical validation have completed.

## Initial surface-code ports

`rotated_surface_d3.raw_t_postselection.acceptance` covers the full approved
`raw_t + k*se_round`, k>=1. Outcomes have `values={"accepted": true/false}`;
accepted transitions to `deliver`, rejected to `retry`. Its ideal exact
probabilities are 1 and 0. Any nonideal rejection probability requires an explicit
model and evidence. It is not inferred from uniform syndrome bits or from a
physical loss estimate alone.

This coarse acceptance does not resolve the first-round random bulk signs or
apply their Pauli correction relations. The current un-applied relations remain
metadata. Using a canonical magic resource in a subsequent abstract T model is an
explicit input assumption, not evidence of implemented frame propagation.

`rotated_surface_d3.t_injection.logical_z` uses the precise convention in the JSON
example. Ideal m0/m1 probabilities are each 1/2 for arbitrary data input and an
independent canonical equatorial magic state; m1 requests S on data. This is a
logical measurement result and correction branch, not an individual physical
syndrome bit or the probability that a T gate succeeds. Factory distillation
acceptance is a separate port/protocol and is not implied by this definition.

The code-side probability estimator does not establish that the complete T
consumption component has been implemented at the atom level. Capability checks
must retain that distinction during integration.

## Parallel ownership and acceptance

The surface-code task owns this contract, `event_probability.py`, its tests,
surface probability estimators, model artifacts and code-local continuation
declarations. It does not edit the logical compiler implementation.

The logical-compiler task owns its backend/case implementation, tests and local
docs. It imports the shared contract, rather than adding another independent
schema or editing surface probability producers. It may test retry mechanics
using a model explicitly marked `test_fixture`; that is not a physical estimate.

The shared-contract commit can be cherry-picked independently into the logical
worktree. Surface implementation/probability data are supplied separately. Do not
reset either worktree, overwrite `agent.md`, or merge whole divergent branches
merely to exchange these files. Global ADR numbers already diverge between these
worktrees; this named contract is the common authority.

Validation covers schema/provenance rejection, exact ideal distributions,
code-specific quantum checks, identity-stable sampling, event readiness, fresh
retry identities, both T correction branches, finite retry exhaustion, and
reproducible static-case export. It does not implement a syndrome backend,
decoder, global frame manager, full factory protocol or multi-AOD scheduling.
