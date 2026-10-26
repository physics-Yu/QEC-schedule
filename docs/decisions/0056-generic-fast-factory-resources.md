# 0056: Generic surface factory resource profiles

Status: superseded for shared-device parallel execution by ADR 0057. The
whole-component exclusive-AOD policy did not satisfy the requested interface.

## Decision

Reuse `ProfileExecutionKernel`, `FactoryProcess`, `CooperativeFactoryRuntime`, the
frontier scheduler and resource ledger from the fast logical compiler. Do not
implement a second 15-to-1 scheduler. The code library adapts the same 4+11 circuit
to any odd distance >=3 and any positive integer number of factory modules.
Experimental coverage is distinct from API capability: d3/5/7 and N1/2/4 are the
first fixed acceptance grid, while unit tests also use N3 and N7.

`SurfaceFactoryProfile` is code-owned. Lookups include code distance, ordered
participant identities, their absolute positions and preparation parameters.
Missing variants fail rather than falling back to physical compilation or a
zero-duration receipt. Calibration is an explicit separate command. It lowers
all 33 component/role variants for each factory in the complete spectator world,
including actual logical S and directed CNOTs. Template reuse is accepted only
after its bound trajectory validates in that world.

Raw preparation receipts cover three d3 injection rounds only. A binary accepted
event schedules the canonicalization continuation, which contains d target SE
rounds (including deformation) and a one-Pauli-layer correction cost envelope.
Target d3 has no growth. Rejects retry injection only. No unobserved byproduct
class is fabricated to satisfy the older kernel contract: a profile may supply
its code-owned correction selection after the normal event/source checks.
Legacy joint-class profiles retain their original strict behavior.

The correction envelope calibrates an addressed Pauli on every target data atom.
X, Y and Z have the same one-layer local timing in this device model. Actual
decoder outcomes choose their support and axes; an identity outcome can be cheaper.
The estimate therefore charges at most one unnecessary local layer per accepted
preparation. It is not a sampled frame or a claim that the logical runtime now
simulates general noisy frame propagation.

## Concurrency and geometry

The new `profile_parallel` claim is estimation-only. Compatible calls have
disjoint participant and exclusive-resource claims and may have different
durations or component identities. Physical execution rejects this claim mode.
The existing synchronous-wave coordinator still retains its peer barriers.

The default `shared_aod` budget reserves the one AOD for the full duration of a
transport-bearing component, until it has returned home. This is a conservative
resource schedule, not a prediction of optimal joint AOD batching. Local-only
Pauli corrections can overlap on disjoint participants. Resource reservation
time and actual movement/transfer busy time remain separately inspectable.

`independent_aod_control` adds one AOD per factory and assumes independently
addressable module gate/readout control. It is a different hardware budget used
to expose protocol dependencies and position effects. It is not presented as
parallel speedup on the original single-AOD device.

Keep the agreed vertical factory arrangement, upper readout and lower storage,
50 um gap, unlimited explicit row/column/readout counts, LOAD/STORE 10 us,
measurement 100 us, processing zero, and the other standard/2 parameters.
Changing factory depth changes the actual readout trip; ordinary local gates
need not change. Neither effect is replaced by multiplication by N.

## Statistical and physical scope

Injection acceptance is estimated on each actual position-specific physical
trajectory under the unchanged illustrative noise model. The fixed initial grid
uses 65,536 shots per calibrated port, with reported Wilson intervals and fixed
seed. Retained-atom conditioning and the separate physical-loss exclusion remain.
The theory study holds accepted-input iid Z error p=0.01 across distances; it is
not inferred from acceptance and is not a measured logical error rate.

Final joint MX checks and conditional S calls use the established reference
model. Calibration does not certify a complete noisy factory. No additional SE
is silently inserted after each CNOT; the existing recipe's SE occurs in
initialization, injection, growth and measured S. One-batch throughput is a finite
trajectory ratio, not a demonstrated steady-state production rate.

Time-schedule acceptance includes full component/event records and CSVs, a
resource/patch Gantt viewer, fixed seed counts, calibrated profile hashes, and
independent checks of result availability and non-overlapping resource leases.
