# 0057: Joint factory profiles on the original shared AOD

Status: implemented; nine single-AOD representative cases completed and audited.

## Correction

The previous generic adapter converted transport-bearing components into
exclusive whole-component AOD reservations. This bypassed the existing shared
AOD interface and serialized independent factory work. It was an implementation
error, not a user-approved resource assumption. Its parallel acceptance is
withdrawn; historical traces are preserved.

## Decision

Extend `SharedAODClaim` and `shared_aod_lockstep` to name a complete-world joint
calibration family and member. Legacy horizontal band claims keep their existing
row/column constraints and serialized identity. Joint proposals permit vertical
and mixed-component frontiers on disjoint participants. They require an exact
group lookup before the logical kernel commits any receipt, time or result ID.
Missing calibration raises explicitly and never causes singleton fallback.

A joint claim's unknown peak demands are `None`, not zero or fabricated counts.
The offline compiler determines actual grid and readout peaks, resolves native
resource conflicts and validates the full spectator world. Group lookup checks
the resulting peaks against the declared device limits. Shared waveform identity
means the members use one validated joint timeline, not equal singleton durations.

Code-owned component sources retain three-round d3 injection, accepted-only
ordinary d-round growth, the correction-layer resource envelope, actual S and the
existing factory recipe. The offline builder submits every current component
frontier in one physical DAG through `compile_physical/NonZonedStrategy`. It adds
no cross-member source barriers. Patch dependencies and conditional protocol
branches remain owned by the existing factory runtime.

The fast kernel reads per-member result phases and work from that joint timeline.
It does not compile atoms, multiply singleton time by N, take an unverified maximum
of singleton times, or add AOD devices. Frozen profiles are reusable for covered
frontiers. New branch combinations need explicit additional offline calibration.

Raw acceptance is recalculated from the actual joint trajectory. Before forming
per-member ports, prove that ideal pairs and multi-atom noise channels do not
cross that member. Retain shared-pulse spectator and transport exposure on the
member's actual atoms and times. Detector propagation still checks the actual T
seed; a spectator-only CZ illumination with no ideal pair is not entanglement.
Raw ports carry the exact joint trace and noise hashes and are selected from the
same source receipt. Physical output LER is still not inferred from acceptance.

## Evidence and limits

The original layout, timing, noise and preparation protocol remain unchanged.
Joint atom traces, source/ownership maps, resource peaks, scheduler choices,
measurement times and probability evidence accompany the calibration. Fast run
statistics exclude calibration work. Keep the existing cohort stage barriers:
the user explicitly confirmed these as an intentional grouping strategy for
one shared AOD. Joint compilation removes incorrect component-exclusive leases;
it does not remove this coordination policy. Multi-AOD independent progression
is paused and is not part of this change.

Acceptance requires visible cross-factory raw-A/SE activity and shared transport
batches in the actual joint traces, plus complete factory schedules with trace
references. Fast scheduling is resource estimation over physically validated
wave fragments; it does not simulate a noisy complete factory or establish
decoded output quality.
