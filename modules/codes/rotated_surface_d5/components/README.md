# Distance-5 components

Status: `get_component(name)` in [__init__.py](__init__.py) selects the concrete
distance-five implementation in the [shared family](../../rotated_surface/README.md).

| Directory | Intended scope |
| --- | --- |
| [initialize_0/](initialize_0/README.md) | Initialize or reinitialize a logical qubit to zero |
| [initialize_plus/](initialize_plus/README.md) | Initialize or reinitialize a logical qubit to plus |
| se/ | Syndrome-extraction components |
| measurement/ | Logical measurement and result interpretation |
| trans_cnot/ | A proposed transversal-CNOT implementation workspace |
| raw_t/ | A proposed raw-T resource preparation workspace |

Implemented names are initialize_0, initialize_plus, se_round, logical_x/y/z,
logical_h, logical_s/sdag, prepare_y, logical_mx/mz, and raw_t. The shared module
also supplies `RawTPostselection(5)` and `TransversalCNOTComponent(5)`. S uses the
actual half-cycle fold protocol; raw T requires its full repeated-SE sequence
before use. H returns a physically permuted exit binding. Other protocols return
atoms to their original homes. No mixed-distance operation is implied.

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
