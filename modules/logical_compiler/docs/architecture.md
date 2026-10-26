# Logical compilation and code-library boundaries

The [QASM frontend](qasm-translation.md) now implements explicit code selection,
gate synthesis, initialize_0/initialize_plus simplification and logical DAG edges.
The separate [factory pipeline](factory-pipeline.md) implements bounded recipe
execution in a shared physical context. The [component scheduler](component-scheduling.md)
admits code-declared synchronous waves, and [factory arrays](factory-array.md)
share that scheduler with stage barriers, independent retries and resource ledgers.
The [fast entry](fast-experiments.md) reuses the protocol runtime with calibrated
component receipts. `FactoryExecutor` is the single-process envelope and identity
adapter for that same cooperative runtime. All paths fill compatible ready
batches under code/device declarations; they expose no serial or policy-width
selector. General QASM-to-component binding and asynchronous scheduling remain
design work. See [ADR 0055](../../../docs/decisions/0055-mandatory-component-batching.md).

The [placement interface](placement.md) now separates initial/return geometry
from Device construction and calibration. Code modules own block footprints and
allowed orientations. `place` supplies explicit positions or the existing vertical
factory policy; the physical and fast adapters consume the resulting validated
plan without transferring protocol definitions into placement.

## Confirmed

The code library, logical compiler and physical compiler are peer workspaces.
Each concrete code is listed directly under modules/codes/ and owns its
components. Distance-three and distance-five rotated surface codes have
independent local workspaces.

```text
Logical circuit
  -> translate using code/protocol capabilities
  -> construct Logical DAG and component invocations
  -> place logical blocks using code-owned geometry
  -> inspect frontier and logical constraints
  -> bind and expand component interfaces
  -> resolve atom actions under complete device state
  -> record results and advance the case
```

The code library supplies the meaning and implementation of supported logical
operations. Protocols supply interaction conditions and compositions. The
logical compiler organizes these capabilities rather than defining code-specific
gate or cross-code rules itself.

The first SE example returns to its reference layout. Measurement outcomes
belong to a case and are not cached as template content. The initial backend
direction remains seeded fake measurement; real-device integration is future work.

The confirmed [case-compilation direction](case-driven-compilation.md) uses
protocol-defined result distributions, unique invocation/attempt measurement
identities and availability-gated feedback. Factory rejection and retry advance
the same shared case state. One AOD is the first study assumption, not a fixed
compiler limit; Device/resource interfaces must permit other configurations.
The shared [event probability contract](../../codes/contracts/event_probability_v1.md)
and its abstract case consumer are implemented. Component admission separately
checks participants, spaces, shared AOD grids and readout capacity. General
multi-AOD allocation policies remain open. Abstract causal timing alone does not
establish physical concurrency.

## Component binding

A component is intended to contain a designed atom-level operation template
and an interface for binding participating blocks and physical roles. For
example, a transversal CNOT implementation defines the correspondence between
roles in control and target blocks; bindings supply their actual coordinates.

Relative coordinates describe parameterization, not unconditional executability
at arbitrary positions. The component must expose its applicable entry and exit
conditions. Binding, transport planning and timing must respect the Device.
Placement validity covers initial/return footprints. It does not choose temporary
readout sites or certify component envelopes. The MSD world builder retains the
existing lower storage/gate half-plane, upper readout half-plane and 50-micrometer
gap; default coordinate extraction preserves the previous physical world.
The first d3 component contract is implemented in the code library under
[ADR 0039](../../../docs/decisions/0039-measured-d3-component-contract.md).
Its nonzoned adapter compiles relative templates and binds concrete actions
without modifying the physical compiler. It exposes entry/exit state, pending
result identities/times and symbolic preparation corrections. The factory path
invokes this adapter and carries component exits through the shared physical
context, including admitted component waves. Global frame management is not
implemented by the adapter; general QASM component selection and binding remain
separate work.

Preserve component identity through expansion. Different components may expose
physical work to a shared scheduling context. Independently compiled action
tables cannot simply be overlaid to establish legal concurrency.

## Constraints and case state

Frontier selection checks dependencies, block use, auxiliary resources and
protocol prerequisites. Pairwise exclusions and whole-group capacity constraints
are separate requirements. Physical admission additionally checks actual geometry,
AOD occupancy, transport, illumination and measurement capacity.

The first ready node anchors a deterministic batch. Every later ready node that
can join under the whole group's constraints is included. This is an
inclusion-maximal legal batch, not a globally optimal schedule. Initial supply,
local correction groups and independent final MX calls all expose their ready
members to this frontier. Expansion budgets stop a whole admitted wave when
insufficient; they do not shrink a legal wave into an artificial smaller batch.

A running case connects measurement identities, result availability, global
time, block bindings and component exits. Factory execution implements these
connections while retaining pending physical values separately from sampled
coarse events. Its resource ledger records carrier generations, reservation,
consumption, discard and per-line output. Cross-code handoff and general
asynchronous ownership remain open.
Logical compilation must not use simulation truth as measurement feedback.

The fast kernel uses logical receipts and profiled timing without compiling atom
movements. Its artifacts mark physical validation as not run. Theoretical joint
15-to-1 checks control final acceptance using an explicit accepted-input Z-error
parameter; physical no-fault estimates remain separate diagnostics. Neither
backend supplies decoded logical success.

Fast factory execution consumes a plan and saved applicable cost records, with
no mandatory physical compilation for each run. Calibration context includes
code/distance, component version, parameters, Device/readout and declared
spectator scope. N is not itself a reuse or invalidation rule. Missing context
is an explicit miss; lookup never silently compiles the missing record. The
historical horizontal d3 profile does not automatically cover the separate
vertical MSD domain. New vertical logical batching remains separate qualification.

## Implemented design choices

- Represent reusable definitions separately from bound invocation state.
- Allow common helpers while retaining local d3/d5 component files and evidence.
- Express a factory as a composition of components with explicit acceptance,
  rejection and output conditions.
- Retain code/protocol/component versions in compiled artifacts so reuse can
  check its assumptions.

The code-owned d3 factory recipe and shared contracts implement these choices
for the current bounded factory path; they do not define a universal code schema.

## Open ADR topics

- Broader code/protocol registration and component selection for general QASM.
- Distance-specific protocol/event/calibration coverage beyond the d3 factory path.
- Extensions to the implemented finite QASM profile and logical DAG representation.
- Asynchronous scheduling, multi-AOD allocation and general replanning policies.
- Logical observables, global frame updates and decoder feedback.
- Inventory, prefetch, factory cascades and cross-code operations.
- Full noisy factory simulation, decoding interfaces and fault-tolerance criteria.

Physical loss estimates and corrected logical failure rates are distinct outputs.
Neither a fake case nor a valid atom-action schedule establishes fault tolerance.

See [ADR 0037](../../../docs/decisions/0037-code-library-and-logical-compiler-workspaces.md)
and the [code library](../../codes/README.md).
