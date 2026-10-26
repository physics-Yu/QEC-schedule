# Declared joint, measurement and local component parallelism

Status: Accepted for implementation, 2026-10-24.

## Decision

Component admission uses code-owned execution declarations rather than a blanket
single-patch restriction. A shared-AOD wave requires matching code, component,
waveform and participant count, with disjoint participant blocks and atoms,
compatible spaces, shared row trajectories, column bands and aggregate device
capacities. A declaration is necessary but does not establish physical validity:
the complete combined atom program is still expanded, replayed and validated.

This extends the conservative single-patch boundary recorded in
[ADR 0048](0048-synchronized-factory-resource-ledger.md). Its one-writer runtime,
cohort barriers, retry policy, resource ledger and probability boundaries remain
in force. The earlier ADR remains the record of that delivery.

## Corresponding transversal CNOT pairs

The d3 code supplies a bounded profile for translated horizontal CNOT pairs.
Participant order is control then target. The waveform identity includes the
signed relative displacement and physical timing/control parameters; reversing
the pair or changing its separation does not declare the same waveform. The row
trajectory and spatial envelope cover both patches and the intervening motion.
Unsupported geometry retains exclusive execution.

Each admitted CNOT member owns two complete 17-atom participants. Joint expansion
must return every declared participant, in order, at both entry and exit, with no
undeclared binding. Both bindings survive composition. The scheduler checks all
participants for collisions, and the physical layer checks actual action targets,
shared-grid mappings, footprints, timings and participant projections. Being
transversal or appearing at the same protocol stage alone is insufficient for
concurrent execution.

The present profile declares three active rows, three columns per pair and zero
readout demand. Zero measurement demand does not remove its transport, pulse or
space requirements. Peak demand is checked against actual expanded actions and
the real Device; it is not inferred only from a component name.

## Logical measurements

The d3 `logical_mx` and `logical_mz` components each reserve nine physical data
measurement identities and declare three active rows, three columns and a peak
readout demand of nine. They use
different waveform identities. MX and MZ are not interchangeable members of one
shared wave.

Global result ranges are allocated independently for every member and remain
unique across later waves. Original measurement ports, availability times and
source identities survive the physical handoff. Feedback still waits for the
specific source results and required exits. Physical values remain unobserved;
batching does not supply syndrome bits or change code-owned probability rules.

## Local physical corrections

`local_parallel` is a separate declaration mode for one-patch, zero-result local
operations with no exclusive or shared-AOD claim. Calls may have different
component names or correction classes when the selected code declares a common
local pulse family. Patch, atom and spatial conflicts still exclude overlap.

The physical alignment helper retains each original addressed Rotation/LocalU
action, its targets, angles, source IDs and start/end times. Different pulse
counts and lane lengths are allowed only when their actual boundaries compose.
Incompatible durations are rejected; pulses are not padded, split or replaced.
Transport, reset, measurement, CZ and global pulses are excluded from this mode.

An identity correction adds no physical pulse or artificial positive-duration
wait. A shorter member retains its own exit time while the shared wave ends at
the latest member exit. Subsequent admission still uses the one global physical
clock. Existing zero-duration no-op records may remain as provenance.

These corrections remain real physical operations with their associated gate and
storage costs. This is not a global software Pauli frame, and no frame propagation
or decoder is introduced.

## Transactions, comparison and evidence

The cooperative runtime checks ownership and epochs for all participating
carriers. Resource consumption is prepared in a private ledger and committed
with a successful physical wave. A malformed member or failed physical
validation must not partially consume tokens, update bindings or allocate global
results. A committed consuming CNOT cannot be repeated after a later failure.

The same factory-array entry supplies both comparison modes. Set `max_parallel`
to 1 for the serial control and retain the same code, seed, Device, placement,
noise parameters, retry limits and cohort policy. Occurrence identities stay
fixed. Changing timing can change a physical-cost probability; comparison must
record model evidence and sampled outcomes rather than assuming identical final
acceptance.

Acceptance requires actual multi-member physical batches, complete participant
entry/exit and source-action projections, disjoint measurement identities,
unobserved physical values, resource transaction checks, whole-program physical
validation and frozen-source replay. Logical DAG admission alone is not that
evidence. Same-stage waiting and all factory proxy cutoffs remain as documented
in [factory arrays](../../modules/logical_compiler/docs/factory-array.md).

General QASM-to-physical execution, arbitrary joint-gate batching, asynchronous
admission, shared-control common-mode noise and decoded logical success remain
outside this change.
