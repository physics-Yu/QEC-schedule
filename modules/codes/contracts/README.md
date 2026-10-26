# Shared code and component contracts

Status: the CodeEntry translation declaration is implemented in __init__.py.
Atom-component invocation and physical-binding interfaces remain open.

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
