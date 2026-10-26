# Logical compilation and code-library boundaries

The [QASM frontend](qasm-translation.md) now implements explicit code selection,
gate synthesis, initialize_0/initialize_plus simplification and logical DAG edges.
The separate [factory pipeline](factory-pipeline.md) implements bounded recipe
execution and a serial shared physical context. General QASM-to-component binding
and concurrent scheduling below remain design work.

## Confirmed

The code library, logical compiler and physical compiler are peer workspaces.
Each concrete code is listed directly under modules/codes/ and owns its
components. Distance-three and distance-five rotated surface codes have
independent local workspaces.

```text
Logical circuit
  -> translate using code/protocol capabilities
  -> construct Logical DAG and component invocations
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
and its abstract case consumer are implemented. Device/resource contracts and
multi-AOD scheduling algorithms remain open. Abstract causal timing does not
perform logical participant-exclusivity checks or establish physical concurrency.

## Component binding

A component is intended to contain a designed atom-level operation template
and an interface for binding participating blocks and physical roles. For
example, a transversal CNOT implementation defines the correspondence between
roles in control and target blocks; bindings supply their actual coordinates.

Relative coordinates describe parameterization, not unconditional executability
at arbitrary positions. The component must expose its applicable entry and exit
conditions. Binding, transport planning and timing must respect the Device.
The first d3 component contract is implemented in the code library under
[ADR 0039](../../../docs/decisions/0039-measured-d3-component-contract.md).
Its nonzoned adapter compiles relative templates and binds concrete actions
without modifying the physical compiler. It exposes entry/exit state, pending
result identities/times and symbolic preparation corrections. Global frame
management and logical orchestration are not prerequisites for using these
components and are not implemented by that adapter.

The factory path invokes these components and carries their exits through the
shared physical context and scheduler.

Preserve component identity through expansion. Different components may expose
physical work to a shared scheduling context. Independently compiled action
tables cannot simply be overlaid to establish legal concurrency.

## Constraints and case state

Frontier selection checks dependencies, block use, auxiliary resources and
protocol prerequisites. Pairwise exclusions and whole-group capacity constraints
are separate requirements. Physical admission additionally checks actual geometry,
AOD occupancy, transport, illumination and measurement capacity.

A running case connects measurement identities, result availability, global
time, block bindings and component exits. The serial factory path implements
these connections while retaining pending physical values separately from
sampled coarse events. General concurrent ownership and handoff remain open.
Logical compilation must not use simulation truth as measurement feedback.

## Proposed implementation directions

- Represent reusable definitions separately from bound invocation state.
- Allow common helpers while retaining local d3/d5 component files and evidence.
- Express a factory as a composition of components with explicit acceptance,
  rejection and output conditions.
- Retain code/protocol/component versions in compiled artifacts so reuse can
  check its assumptions.

These directions do not select schemas, algorithms or a factory protocol.

## Open ADR topics

- Code and component contracts, supported-operation discovery and selection.
- Code definitions, bit ordering, reference layouts and first SE implementation.
- Extensions to the implemented finite QASM profile and logical DAG representation.
- Logical constraints and device-wide scheduling handoff.
- Atom-template format, coordinate binding, valid reuse and replanning.
- Measurement identity, pending results, logical observables and frame updates.
- Raw-T preparation, S realization, factory protocols and cross-code operations.
- Stim/noise integration, decoding interfaces and correctness criteria.

Physical loss estimates and corrected logical failure rates are distinct outputs.
Neither a fake case nor a valid atom-action schedule establishes fault tolerance.

See [ADR 0037](../../../docs/decisions/0037-code-library-and-logical-compiler-workspaces.md)
and the [code library](../../codes/README.md).
