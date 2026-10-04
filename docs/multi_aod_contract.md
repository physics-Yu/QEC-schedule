# Independent AOD devices on one physical clock

This extension supports real `Executor` execution with multiple independently
controlled AOD arrays inside separated, fixed work envelopes. It is a declared
research platform model, not a calibrated claim about a particular device.
Each array still has Cartesian row/column intersections, dynamic axis masks,
its selected rigid/ordered backend, and all existing support and motion rules.

The accepted family uses one global world, placement, circuit DAG, quantum
state, RNG, event queue and clock. Arrays are not independent simulations whose
animations are overlaid. Only `Executor` installs a complete next state.

## Identities and immutable state

`MobileCellIndex(row, column, aod_id='AOD_0')` gives mobile holders a device
identity. Two devices may both have a `(0, 0)` cell without sharing a holder.
`AODRuntimeState` adds `aod_id` and an optional `envelope: Rectangle`.

`SimulationState.aods` is a read-only registry containing every runtime.
The original positional `state.aod` remains the compatibility primary,
`AOD_0`, and is authoritative when normalizing that entry. New device updates
use the pure `hardware.multi_aod.with_aod(state, id, next_runtime)` helper so the
primary and registry stay consistent. `state.transfers` records each lane's
unfinished handoff; `state.transfer` is the compatibility primary handoff.

`PlacementState.position(atom, world, state.aods)` resolves the holder's actual
device. Passing a singular array for an atom held by a different array fails
instead of producing a position with the wrong axes. Public
`NeutralAtomEnv.observe()` exposes all physical device runtimes and resolves
all positions; its observation still omits quantum state, RNG and trace.

`Platform` accepts its original primary plus an optional `aods` registry. Its
JSON loader accepts either historical `aod` or explicit `aods` entries. Atom
ownership is still determined by placement, and no device flag on an atom
substitutes for its actual committed holder.

## Geometry and permissions

Every device in a multi-device state needs an in-world, fixed envelope. The
complete axes, including disabled capacity cells, must remain inside it.
Device envelopes must be separated by at least
`max(minimum_clearance_um, slm_clearance_um)`. Bounds and identities cannot be
changed by an operation.

Rigid and ordered motion stay inside the envelope by convex interpolation.
Thus the distance between separated envelopes proves cross-device swept
clearance for arbitrary relative starts and unequal durations. The backend
also checks all own loaded atoms, all global live static/foreign atoms,
enabled SLM exclusions, and all active empty intersections. Own-device
active-trap versus loaded-atom checks use relative start/end trajectories,
rather than treating another moving atom's old position as static.

The world may consist of one ENTANGLEMENT/compute region and an MZ, with the
resource placement on the compute region's right side. Zone layout and a
5 µm SLM grid belong to the platform input, not a hidden viewer coordinate
change. There is no imposed logical nearest-neighbor graph. CZ remains a
finite-distance physical pulse: actual pairs from **all** live atoms in the
compute region, including the resource side and spectators, must equal the
entire intended set.

This first implementation rejects overlapping AOD work envelopes and direct
AOD-to-AOD transfers. A real SLM unload/reload can change which device holds an
atom when its sites are reachable under the declared envelope family; general
cross-workspace delivery and crossing trajectories require a later contract.

## Operations and concurrent programs

`Operation.aod_id` selects a transport/mask lane. The default remains `AOD_0`.
`ProgramBuilder.add(..., aod_id=...)` predicts actual selected-device
operations. `hardware.multi_aod.backend_for(state, id)` performs read-only
legality checks on the complete state, retaining all foreign atoms.

Concurrent arrays share one scheduled `CompiledPlan`. They do not submit two
plans against a stale global fingerprint. `build_scheduled_program(state,
intent, operations, intervals, planner_id=...)` takes caller-selected relative
intervals, independently derives actual resources/bindings/affected atoms,
audits the complete event timeline, and binds all device origins and predicted
terminals. `TaskTarget.aod_targets` can state multiple terminal configurations.

| Operation | Actual locking and overlap in this version |
|---|---|
| MOVE, LOAD, OFFLOAD | Selected device plus actual atoms/sites; different separated devices may overlap |
| Partial recapture/park | Selected device and all affected supports; explicit existing capability is required |
| SLM/TRAP_SWITCH | All device lanes, because the operation carries a complete global SLM mask; serial mask preparation prevents stale support overwrite |
| CZ | All device lanes plus the global entangling resource; every device must be stationary and outside handoff |
| MEASURE/RESET | All device lanes plus readout/reset resource; actual targets must be in MZ and tracked |
| Identical 1Q batch | Actual atom/Raman resources and devices holding lit mobile targets; independent stable targets may share one batch |

The existing rule allowing only identical gate types to overlap is preserved.
Raman light retains the ≥5 µm all-neighbor rule. For a moving foreign array,
the point-to-envelope lower bound must retain that margin throughout its
motion; unsupported overlap is rejected conservatively. Device transport
dependencies and LOAD/depart/approach/OFFLOAD exemptions are audited per lane.

Concurrent handoff completion applies only its actual source-to-target SLM
deltas to the latest state, preserving supports created by another lane.
The complete state is validated before any commit. An invalid plan or event
does not partly change holder, masks, queue, trace, RNG or quantum state.

The historical aggregate `aod_busy_time_us` is retained as a compatibility
service counter. Multi-device reports additionally save
`aod_busy_by_device` from actual resource intervals, and `aod_utilization`
uses their sum divided by device count × wall time. Unfinished operations do
not yet add busy time. Busy times of distinct resources may overlap.

## Checkpoints and existing single-device behavior

Multi-device snapshots use schema20 and save the complete device/transfer
registries, full plan origins, future event suffix, actual reports and RNG.
Recovery reconstructs and checks each lane and the global quantum state.
Changing a secondary lane's pose/masks, plan origin or prediction is detected.

Historical single-device inputs retain schema19. New default fields are omitted
from canonical serialization. The old `.aod`/`.transfer` fields and historical
gate/trace data are not silently reinterpreted as multiple devices. A new
single-device plan with an explicit envelope also saves the exact runtime
origin, so explicitly supplied uniform offset tuples survive origin replay.

Read-only compatibility checks restored historical ZZ and XX initial snapshots
and reproduced their exact bytes and fingerprints: respectively 3,436,201
bytes / `857af4d2c1cf64c771ba44bf818b0d9b073f706578b233ee422e691a3b4285dc`
and 3,393,904 bytes /
`ab55938e7a02f955601546049fb494fdde19650717ca70cdf23d11b031700c68`.
These are old saved inputs, not newly generated round-trip fixtures.

A second independent compatibility check archived old committed source
`fd7abf38c2a3bde007950283588057d4530b1730`, then ran that source and the current
source in separate fresh Python processes. Its actual
LOAD/MOVE/H/MZ-MEASURE/RESET/RETURN/OFFLOAD program committed 16 events and
17 snapshots, ending at 883.4621125123532 µs with report `m=0`. The complete
12,567-byte plan, all 703,744 bytes of snapshots, and the 22,135-byte trace
matched byte-for-byte. Their SHA256 values were respectively
`2ba331b4dd9eea02dcc77c353ef18b11c107f385423e497580ae2490e8e4467e`,
`8695b8488c5244c3450167242a86095fc945c4c750c6816629a119b97907d9f5`,
and `2ee2939cd3f29d6fc052ae9669378bb3a1d051aa70f3a227dda1a47e2b2f8a02`.
The local evidence is under `artifacts/multi-aod-visual-validation`; it is an
independent compatibility audit, not additional pytest cases.

## Verification and limits

`tests/test_multi_aod.py` exercises device-address uniqueness, two real MOVE
lanes, simultaneous LOAD/OFFLOAD, per-event restore, original-state replay,
device-resource conflicts, fixed-envelope and empty-trap negatives, original
state atomicity, complete secondary-device tamper checks, public observation,
global CZ spectators, actual MZ RESET/H/MEASURE/RESET and mobile Raman batches.
The observer's separate tests replay two committed arrays and check both
coordinate sets and independent interpolation.

This supports only the declared separated-envelope family and scheduled
programs; multi-device legacy serial plans are explicitly rejected. It does
not implement general crossing-array routes, arbitrary dual-plan submission,
factories, non-Clifford tracked Born execution, noisy QEC, or complete physical
Shor. In particular, a scheduled ordinary T pulse does not make a tracked
magic-state production or consumption protocol executable.
