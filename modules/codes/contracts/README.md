# Shared code and component contracts

[BlockGeometry](geometry.py) declares code-owned initial/return footprints,
permitted orientations, minimum spacing and geometry versions. Logical placement
consumes this declaration; component motion and execution conditions remain
separate contracts.

Status: the minimal invocation/template contract is implemented in
[component.py](component.py) and consumed by the d3 components. Expansions retain
physical exit bindings, local acceptance conditions, syndrome parity metadata,
and explicit participant bindings for the two-block transversal CNOT.
Broader code/protocol discovery remains open. None of these records manages a
global Pauli frame or evaluates a decoder.

The [event probability v1 contract](event_probability_v1.md) is implemented by
[event_probability.py](event_probability.py). It validates immutable joint event
distributions, local continuation steps and model provenance. Codes estimate
these distributions; the logical compiler binds occurrences, samples outcomes
and expands one completed static case. Detailed syndrome simulation and decoder
feedback remain a separate reserved backend.

The CodeEntry translation declaration is implemented in [__init__.py](__init__.py).
The [parallel declarations](parallel.py) describe component participants,
implementation compatibility, spaces and shared/exclusive device claims for
logical admission. Actual atom composition still requires physical validation.

This directory owns the common vocabulary used by concrete codes, interaction
protocols and the logical compiler. It must not depend on the compiler's
internal scheduling or case implementation.

The immutable [factory recipe records](factory_recipe.py) declare preparation,
rotation, consumption, event dependencies and batch reset boundaries. They carry
no mutable inventory, scheduler, decoder or sampler. The concrete d3 supports and
Pauli conventions live in the code-owned [factory protocol](../rotated_surface_d3/protocols/factory.md).

The initial design topics are:

- Code identity, supported logical operations and implementation selection.
- Encoded-block identity and logical-qubit roles; one block is not universally
  required to encode exactly one logical qubit.
- Component participants, parameters, physical roles and coordinate bindings.
- Entry requirements, logical resource use, measurement outputs and exits.
- Protocol applicability and the component composition it returns.

These topics do not prescribe a schema, class hierarchy or universal gate set.
CodeEntry currently carries the explicit code/scheme, gate names and code-owned
component-name mapping. The surface vocabulary is shared by explicit selection
in each code entry; the generic contract does not choose a CNOT implementation.
Concrete code algorithms remain in their owning code directories. Shared
interfaces must allow different numbers of physical qubits and measurements,
as well as components with different entry and exit encodings.

See the [code library](../README.md) and
[compiler architecture](../../logical_compiler/docs/architecture.md).
