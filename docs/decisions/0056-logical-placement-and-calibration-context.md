# ADR 0056: Logical placement and calibration applicability

Status: Implemented, 2026-10-24.

## Context

Logical block positions were generated inside the MSD physical-world builder and
inside the d3 fast-profile adapter. These are different layouts: MSD factories
are stacked below the storage boundary, while the historical d3 fast reference
places factories horizontally beside a local readout band. Extracting placement
must preserve both geometries instead of silently treating their cost records as
interchangeable.

The user requires a replaceable, lightweight placement module with explicit
positions and the existing vertical factory policy. Placement must not require
atom compilation, probability sampling or a completed physical case for each new
logical run. Reusable calibration still requires evidence for its applicability.

## Decision

### Pure geometry and a common validated result

`modules/logical_compiler/src/placement/` exposes
`place(PlacementRequest, PlacementStrategy) -> PlacementPlan`. Requests contain
block identities, explicit code/distance, optional factory roles, code-owned
geometry, optional initial/return region, and user-specified positions.

Code providers supply `BlockGeometry`: the relative footprint, permitted
orientations, declared minimum spacing and a geometry version. The rotated
surface-code provider uses the existing 10-micrometer reference grid and permits
only the standard orientation. Geometry support at a distance does not register
an executable logical compiler entry at that distance.

Plans contain immutable block/geometry/placement records, the occupied bounds
and a deterministic geometry fingerprint. `validate_plan` rechecks externally
supplied plans, including their stored bounds and fingerprint. Common validation
rejects missing or extra blocks, identity/distance mismatches, unsupported
orientations, overlapping closed footprints, insufficient declared spacing and
positions outside the requested region.

These positions are initial and return positions. Readout destinations, movement
routes, AOD trajectories and temporary operation envelopes remain downstream
decisions. A valid plan neither moves atoms nor establishes physical concurrency.

### Two initial strategies

`ExplicitPlacement` consumes every position supplied by the caller. There is no
implicit placement for an omitted block. `VerticalFactoryPlacement` consumes a
caller-supplied role order, uses each factory's actual code footprint, arranges
roles horizontally, and stacks factory rows from y=0 downwards. A factory uses
one code/distance; separate factory rows may use different sizes. No W1/W2/R
protocol rules are embedded in the generic strategy.

For the uniform rotated-surface reference, factory index i and role index j,
the preserved coordinates in micrometers are:

```text
x(i,j) = j * (20*d + patch_gap_um)
y(i,j) = -20*d - i * (20*d + factory_gap_um)
```

Both default gaps remain 40 micrometers. Every positive integer factory count
is accepted; the earlier power-of-two restriction was an experiment-axis choice,
not a geometry requirement. Automatic placement optimization is deferred.

### Existing compiler and world interfaces remain the consumers

`experiments/msd/standard.py` obtains its positions from placement and retains
Device, SLM-site, atom-identity and binding construction. The default layout keeps
the existing coordinates, site naming, timing and physical entry state. Storage
and gates remain in y<=0, readout remains in y>=50 micrometers, and the gap is
unchanged. Supplying an explicit plan also requires the standard builder's code
geometry and lower-half-plane checks.

The fast factory entry consumes an explicit plan without compiling it. The
historical horizontal default is represented by an explicit plan and an adapter;
the full factory-array builder consumes the same plan and retains its Device and
binding construction. Both envelopes expose the placement fingerprint.
The cost profile no longer owns the placement decision. Logical scheduling still
uses code-declared participants, dependencies, spaces and actual resource claims,
then produces either logical receipts or physical compiler work.

The fast execution input remains the supported code-owned factory recipe and its
resource protocol: raw-T postselection, local correction, retry, T consumption
and final acceptance. This change does not add arbitrary QASM-to-component
execution, inventory management or automatic resource-production planning.

### Calibration is a separate applicability decision

The geometry fingerprint identifies a complete plan; it is not the sole cache
key. Component calibration records retain explicit component identity/version/
fingerprint, parameters and selected correction, participant code/distance/
orientation/relative geometry, Device control/transport/readout context, and the
declared spectator context.

World-scoped records include the complete spectator geometry. Local records
require a provider-declared influence envelope and versioned scope evidence;
intersecting spectator footprints are included conservatively. Global operations
require world scope. A provider declaration records an assumption and does not
itself prove that excluded atoms cannot affect the physical operation.

N is not a direct cache-invalidation field. Adding a remote factory may leave a
properly scoped local key unchanged, while adding a relevant spectator or changing
readout/device geometry invalidates the affected key. There is no blanket rule
that every N change requires recalibration or that every translated block reuses
an old estimate.

Calibration creation saves this context with its records. Production lookup
requires matching context; legacy records without it yield an explicit miss.
Neither placement nor fast lookup implicitly compiles missing atom work. A server
pipeline may separately generate plans, inspect missing keys, run authorized
calibration jobs, populate the cache and then execute logical scans.

### Preserve the two existing geometry domains

The horizontal d3 profile retains its recorded spacing, readout placement and
motion/spectator assumptions. A vertical plan can be generated and inspected
without a matching cost model. That does not make a horizontal record applicable
to a different vertical/readout geometry.

The existing shared-AOD component scheduler remains unchanged. This extraction
does not establish new vertical logical lockstep batching or a complete physical
vertical factory benchmark. Existing joint-SE physical experiments remain separate
evidence; their source DAG is scheduled by the existing physical compiler.

## Verification and limits

Coordinate regressions cover d=3/5/7 and N=1/2/3/4. Existing default-world snapshots
must remain identical apart from added placement metadata. Explicit-position,
overlap, missing-block, region, orientation, fingerprint and cache applicability
tests cover rejection paths. Tests must also forbid physical compilation and
probability sampling during placement and fast cache lookup.

This ADR records interfaces and verification obligations. It contains no new
throughput result, logical-error estimate or physical qualification. Runtime
checks follow [the repository testing workflow](../testing.md), and bench still
requires explicit authorization.

See [logical placement](../../modules/logical_compiler/docs/placement.md),
[mandatory batching](0055-mandatory-component-batching.md), and the
[MSD standard](../../experiments/msd/README.md).
