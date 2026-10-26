# Distance-5 components

Status: reserved work areas; no executable component is supplied.

| Directory | Intended scope |
| --- | --- |
| [initialize_0/](initialize_0/README.md) | Initialize or reinitialize a logical qubit to zero |
| [initialize_plus/](initialize_plus/README.md) | Initialize or reinitialize a logical qubit to plus |
| se/ | Syndrome-extraction components |
| measurement/ | Logical measurement and result interpretation |
| trans_cnot/ | A proposed transversal-CNOT implementation workspace |
| raw_t/ | A proposed raw-T resource preparation workspace |

These categories do not confirm specific gate protocols. In particular, raw-T
injection and S realization require later decisions. The first SE example has
an agreed return-to-reference-layout exit; other exits must be specified
individually.

Each concrete implementation should keep its interface, atom-action template
or generator, coordinate binding, constraints and measurement interpretation
together. The file format and internal split remain open. Do not create empty
executable circuits or manifests that could be mistaken for supported operations.

A reusable template defines roles and relative geometry. A case supplies block
instances, actual atom identities, positions and measurement outcomes. Coordinate
rebinding still requires legal Device geometry, transport and resource use;
support at arbitrary input positions is not implied.

See the [code definition scope](../definition.md) and
[compiler architecture](../../../logical_compiler/docs/architecture.md).
