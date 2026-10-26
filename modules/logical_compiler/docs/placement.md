# Logical block placement

`place(request, strategy)` decides initial/return positions for code blocks. It
performs geometry checks only: no atom allocation, physical compilation,
measurement sampling or calibration. Both physical world builders and fast
logical execution can consume the same `PlacementPlan`.

## Records and ownership

| Record | Contents and responsibility |
| --- | --- |
| `BlockSpec` | `block_id`, explicit `code` and `distance`, optional `factory_id` and role |
| Code-owned `BlockGeometry` | Relative bounds in micrometers, allowed orientations, minimum spacing and version |
| `BlockPlacement` | Initial/return origin and orientation |
| `PlacementRequest` | Immutable blocks and geometry mapping, optional permitted region, explicit positions |
| `PlacementPlan` | Immutable placements, original block/geometry records, occupied bounds and geometry fingerprint |

The code library supplies footprint definitions. The rotated-surface provider,
`modules.codes.rotated_surface.geometry.geometry(code_id, distance)`, uses the
existing 10-micrometer local grid. Its footprint is `[0,20d]` on each axis and
its current allowed orientation is `standard`. Generic geometry supports
code-authorized orthogonal rotations, but that does not add rotated bindings to
surface components. d7 geometry is supported independently of code-entry
registration and complete factory cost coverage.

Factory roles come from the existing recipe. Placement does not define their
gate order, magic-state meaning or interaction protocol. Component interfaces
continue to decide which relative positions and orientations they can execute.

## Strategies

`ExplicitPlacement` uses `request.positions` exactly. Missing and additional
block IDs are errors. `VerticalFactoryPlacement(role_order, patch_gap_um=40,
factory_gap_um=40)` uses the first appearance order of factory IDs in the request
and the supplied role order within each factory. Roles run left to right and
factory rows run downward from y=0. A factory must have exactly those roles and
one code/distance. Different factories may have different footprints.

```python
from dataclasses import replace

from modules.codes.rotated_surface.geometry import geometry
from modules.codes.rotated_surface_d3.protocols.factory import factory_recipe
from modules.logical_compiler.src.placement import (
    BlockSpec, ExplicitPlacement, PlacementRequest, VerticalFactoryPlacement, place,
)

recipe = factory_recipe()
roles = (*recipe.work_roles, recipe.resource_role)
code = "rotated_surface_d3"
request = PlacementRequest(
    tuple(
        BlockSpec(f"factory{i}/{role}", code, 3, f"factory{i}", role)
        for i in range(3)
        for role in roles
    ),
    {code: geometry(code, 3)},
)
plan = place(request, VerticalFactoryPlacement(roles))
# A caller can replace this mapping with independently chosen positions.
explicit = place(replace(request, positions=plan.placements), ExplicitPlacement())
assert explicit.geometry_fingerprint == plan.geometry_fingerprint
```

The preserved default coordinates are:

| d | W1..W5,R x positions (micrometers) | First four factory y origins (micrometers) |
| --- | --- | --- |
| 3 | 0, 100, 200, 300, 400, 500 | -60, -160, -260, -360 |
| 5 | 0, 140, 280, 420, 560, 700 | -100, -240, -380, -520 |
| 7 | 0, 180, 360, 540, 720, 900 | -140, -320, -500, -680 |

There is no power-of-two restriction on factory count. Automatic optimization is
not part of these strategies. User positions are not silently ignored by the
vertical strategy: use `ExplicitPlacement` when supplying them.

## Validation and downstream binding

Every strategy result passes the same checks for identity, code/distance,
completeness, permitted orientations, occupied closed bounds, minimum spacing and
the optional request region. Touching closed footprints count as overlap.
Declared spacing is the shortest Euclidean distance between the two footprints;
it is not an inferred component motion margin.

`block_bounds(geometry, placement)` returns one oriented footprint.
`validate_plan(plan)` rechecks external records, including occupied bounds and
the fingerprint; directly constructing or replacing a record does not bypass
these checks. The fingerprint includes block metadata, geometry versions and
positions in canonical identity order. `to_dict()` returns an independent
`nadit.logical_placement/1` document.

The plan does not retain a physical Device or readout route. Consumers still
check their own Device and initial/return region. In particular,
`experiments.msd.standard.build_world(spec, placement_plan=plan)` requires the
declared code geometry and storage half-plane y<=0. It retains Device construction
and uses readout y>=50 micrometers. Default plans preserve all previous Device,
SLM-site, atom-order and entry-state values; the world document adds `placement`
metadata separately.

```text
Factory recipe / logical block requirements
  -> PlacementRequest + strategy
  -> validated PlacementPlan
  -> existing code bindings and execution declarations
  -> existing logical frontier scheduler
  -> calibrated logical receipts OR existing physical compiler
```

Layout validity does not imply a gate or shared-AOD wave is legal. Temporary
movement, pulse coverage, transport ordering and readout placement remain under
their existing interfaces and validators.

## Fast execution and calibration

The d3 fast factory entry accepts a `placement_plan` and uses its existing
code-owned factory recipe. It retains raw preparation, postselection, local
correction, retry, T consumption and final acceptance. It does not require a
new physical compilation before each logical run, and it does not add an
arbitrary-QASM execution path or automatic inventory supply.

The historical horizontal default is produced as an explicit placement plan.
The full `make_factory_array` builder and fast adapter consume that same plan;
their existing Device, site names, atom IDs and patch coordinates are retained.
`layout_from_plan` associates a plan with logical carriers and declared budgets;
it does not choose positions. Profiles provide calibrated costs and applicability
context. The horizontal profile cannot silently acquire a new vertical/common
readout domain merely because its component names match.

`src/estimation/calibration.py` contains metadata-only `CalibrationContext`,
`CalibrationKey`, `CalibrationRecord` and `CalibrationCache` interfaces. Keys
check component version/fingerprint, parameters, code/distance, orientation,
participant-relative geometry, Device control/transport/readout and relevant
spectators. World scope includes every spectator; local scope requires an
explicit influence envelope and provider/version evidence. Global operations
require world scope. A provider's locality declaration is an assumption that
still needs physical evidence.

The full-plan fingerprint and factory count are provenance, not automatic
invalidation rules. A remote added factory can preserve a local key; a newly
relevant spectator, changed readout region or changed component version must
change it. Missing or incompatible calibration is reported explicitly. Production
profiles lacking saved applicability context need regeneration, not silent
acceptance or an implicit physical-compilation fallback.

Vertical layouts for d3/5/7 can therefore be generated independently of cost
coverage. New vertical logical batching and full vertical factory throughput are
not established by this extraction. See [fast experiments](fast-experiments.md),
[component scheduling](component-scheduling.md), and
[ADR 0056](../../../docs/decisions/0056-logical-placement-and-calibration-context.md).
