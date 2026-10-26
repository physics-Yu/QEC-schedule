# Raw T resource preparation

Status: corrected by the user on 2026-10-23. The existing
[RawTComponent](../components/injection.py) remains the unchanged low-level
center-injection primitive. Resource use requires
[RawTPostselection](raw_t_postselection.py): that primitive followed by at
least one additional complete ordinary SE round, with all declared detectors
postselected. The default has two total rounds, sixteen results and twelve
detectors. See [ADR 0041](../../../../docs/decisions/0041-raw-t-repeated-se-postselection.md).

A primitive `acceptance_status == "accepted"` only reports its four boundary
checks. It does not qualify a resource for use. Consumers must use the complete
sequence's `ready_for_use(at_us)`.

## Target and source

Here `raw_t` means the resource

```text
T|+>_L = (|0>_L + exp(i*pi/4)|1>_L) / sqrt(2).
```

Ye et al., [arXiv:2305.15972v2, Fig. 1(a), Eq. (1)](https://arxiv.org/pdf/2305.15972v2)
describe a central-qubit seed surrounded by product-state regions, followed
by a surface-code cycle. Deterministic checks support a local postselection
rule. Their paper calls the target above `|A^(pi/4)>_L`; its separately named
T-type magic state is not this component's target. The protocol is published
as [Phys. Rev. Lett. 131, 210603 (2023)](https://doi.org/10.1103/PhysRevLett.131.210603).
Published hardware fidelities and noise results are not imported as evidence
for this compiler implementation.

Under this repository's [data numbering](../definition.py), the product seed
is:

```text
|+>     |+>      |0>
|0>     T|+>     |0>
|0>     |+>      |+>
```

The source resets all data, applies H to `data0,data1,data4,data7,data8`, and
applies one actual T gate to `data4`. It then resets the eight auxiliary atoms
and runs the unchanged complete N/Z SE. It does not substitute a Clifford
state, a unitary encoder, or a direct logical T gate.

## Primitive results and correction relations

Ports retain the ordinary order `X0,X1,X2,X3,Z0,Z1,Z2,Z3`. An ideal primitive
branch has the following local canonicalization relation:

| Port equals one | Pauli product |
| --- | --- |
| X1 | Z2 |
| X2 | Z6 |
| Z1 | X0 |
| Z2 | X8 |

These products are returned as metadata and are not applied to atoms. The
four boundary checks are the ideal deterministic checks. The unchanged
primitive's local predicate is exactly:

```text
accept iff X0 = X3 = Z0 = Z3 = 0
```

The individual bulk results `X1,X2,Z1,Z2` are not rejection criteria. All their
ideal combinations occur. The primitive expansion exposes
`acceptance_conditions` with bound result identities. `acceptance_status` is
`pending` while required boundary results are missing, `rejected` after a
known failed boundary condition, and `accepted` after all four boundary
results satisfy the predicate. Consumers must still respect result
availability times.

This primitive predicate omits temporal consistency and is insufficient for
resource use. It is retained for provenance and low-level inspection.

## Required repeated-SE postselection

`RawTPostselection(extra_rounds=k)` requires an integer `k >= 1`. It composes
`raw_t` with `k` ordinary `se_round` invocations on the same block, homes,
role identities and encoding. It reuses their original templates; it does not
fuse, replace, or insert corrections between their circuits.

For first-round results `m[0,j]` and later results `m[r,j]`, the detectors are:

```text
boundary.b = m[0,b]                         for b in {X0,X3,Z0,Z3}
round[r].j = m[r-1,j] XOR m[r,j]            for r=1..k, all eight checks j
accept iff every detector equals zero
```

Thus there are `4 + 8*k` detectors and `8*(1+k)` measurement bits. With the
default `k=1`, the complete rule has twelve conditions. It does not require
all sixteen raw bits to be zero. An ideal bulk result of one in both rounds
has zero detector parity and remains accepted. The first-round correction
relations remain the sequence's correction relations because accepted later
syndrome values agree with them.

Each `PostselectionDetector` retains its contributing measurement records,
including invocation identity, physical result ID and availability time.
Detector names are local to the sequence; repeated check-port names are
disambiguated by their invocation. A detector becomes available at the latest
delivery time among its inputs. The sequence returns `pending` if required
bits are missing, `rejected` if a known detector is one, and `accepted` only
when every detector is known and zero. Missing results are never replaced by
zero.

`ready_for_use(at_us)` additionally requires the caller's time to reach
`results_ready_us`, which includes final atom completion and all measurement
deliveries. A following SE can begin at the preceding action end while
earlier results remain pending because there is no measurement-controlled
action in this composition. Neither readiness nor acceptance advances time.
Rejection preserves the exit world and records; retry and resource disposal
remain caller decisions.

The repeated-check decision has direct precedent in
[Li 2015, Sec. II](https://arxiv.org/pdf/1410.7808v1): the first injection stage
uses two full X/Z rounds, checking both initialization-compatible outcomes
and inter-round consistency. Li subsequently grows the code and performs
normal correction, which this local protocol does not implement.
[Lao and Criger 2022, Sec. 3.1 and 3.4](https://doi.org/10.1145/3528416.3530237)
apply the two-round rule to rotated-code injection, including a center seed.
Their exact gate ordering and error-rate analysis are not assumed to match
the present compiler. The publisher full text was inaccessible in this review;
section details were checked against a text mirror of the original paper.
[Gidney 2023, Sec. 2-3 and Fig. 2](https://arxiv.org/html/2302.12292v1)
studies a different hook-injection circuit: its figure uses two rounds, while
its benchmark varies the number of postselection rounds from one through six.
These papers do not establish a common fixed-round optimal protocol.

## Calling the complete protocol

```python
from nadit_physical_compiler.device import Position
from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
)

# device and world contain the real resource profile and all occupied atoms.
template = RawTPostselection(extra_rounds=1).compile(
    device,
    home_sites=REFERENCE_HOMES,
    origin=Position(0, 0),
    aod_id="transport",
)
binding = ComponentBinding("resource-A", Position(0, 0), tuple(range(17)), "transport")
# Reserve sixteen unique IDs, 1000 through 1015, for this default sequence.
sequence = template.bind(binding).expand(
    InvocationContext("prepare-resource-A", 0, 1000, device, world)
)
resolved = sequence.with_results(received_bits)
usable = resolved.ready_for_use(at_us)
```

`received_bits` and `at_us` are caller-provided observations and time. For
general `k`, reserve `8*(1+k)` consecutive IDs. Child invocation identities
are `prepare-resource-A/round[0]`, `.../round[1]`, and so on. Compilation
occurs once for each primitive; binding/expansion reuses their relative actions.

## Resource and physical contract

One invocation occupies the existing 9 data and 8 syndrome roles. Its source
has 17 resets, 13 H gates, one T gate, 24 CX gates and eight measurements.
Each additional SE adds eight resets, eight H gates, 24 CX gates and eight
measurements without adding atoms. The default complete sequence therefore
has 25 resets, 21 H gates, one T gate, 48 CX gates and sixteen measurements.
Source counts are not the compiled pulse count or duration. The current
`nonzoned` compiler realizes the one- and two-qubit operations using the
supplied Device and verifies actual transport, coverage and timing.

Entry requires all roles at their bound reference homes, inactive flexible
AODs and complete occupancy information. Previous data state is discarded.
Exit returns all atoms to the same homes, leaves AODs inactive and retains
ancillas in measured states. Atom action end and measurement availability
are distinct. Templates cache relative actions and local interpretation
metadata, without outcomes, global clocks, or a frame manager.

The complete protocol records `postselection_scope` as
`first_boundary_and_adjacent_round_parities` and `terminal_boundary` as
`open_after_last_se`. Its content hash includes both primitive content hashes,
the round count, protocol version, detector scope and terminal boundary. The
original source/device/compiler provenance remains attached to each primitive;
changing the composition does not mean that the physical compiler changed.

## Quantum evidence and limitations

[dense_quantum.py](../tests/dense_quantum.py) evolves complex state vectors
with the actual `exp(i*pi/4)` T phase. It is a bounded ideal preparation oracle
with leading deterministic resets and terminal measurements, not a general
runtime simulator. Its atom path derives single-qubit matrices and CZ pairs
from actual actions and illuminated geometry; it does not copy the source DAG
gate list.

[test_injection.py](../tests/test_injection.py) compares the source and atom
states and all 16 nonzero ideal measurement branches, each with probability
`1/16`. After applying the returned relation only inside the test, it checks
all eight stabilizers and the logical Bloch expectations
`(<X_L>,<Y_L>,<Z_L>)=(1/sqrt(2),1/sqrt(2),0)`. It also checks the boundary
predicate, pending-result isolation and that removing a compiled CZ pulse
changes the quantum result.

[test_raw_t_postselection.py](../tests/test_raw_t_postselection.py) checks
the composition, detector identities, pending bits, timing and additional
rounds. [test_raw_t_postselection_quantum.py](../tests/test_raw_t_postselection_quantum.py)
uses [injection_sequence_checks.py](../tests/injection_sequence_checks.py) to
carry the actual complex data amplitudes into the second source or atom SE.
The focused checks cover:

- All sixteen ideal injection branches; the second round preserves each data
  state and repeats its syndrome with conditional probability one.
- All 27 single-data-qubit Pauli insertions at the tested inter-round boundary,
  on one representative nonzero-syndrome branch; each produces a rejection.
- Four first-round bulk readout-bit flips that pass the primitive boundary
  rule but fail the complete temporal rule.
- A Z fault on the central seed after its T gate that passes both rounds while
  changing the logical state. This is an explicit acceptance limitation.

The 27-case boundary check is not an enumeration of all gate, transport,
reset, measurement, or idle fault locations. Errors after a data atom's final
relevant interaction can remain outside the last recorded time boundary.
Such a remaining data error is not automatically a logical failure, but the
local predicate cannot certify an error-free output.

```powershell
& modules/physical_compiler/.venv/Scripts/python.exe -m pytest -q modules/codes/rotated_surface_d3/tests/test_injection.py
& modules/physical_compiler/.venv/Scripts/python.exe -m pytest -q modules/codes/rotated_surface_d3/tests/test_raw_t_postselection.py modules/codes/rotated_surface_d3/tests/test_raw_t_postselection_quantum.py
```

Animation review must expose the complete injection plus repeated-SE sequence,
including every readout and return to homes. The displayed acceptance
metadata must not invent measurement outcomes. Human visual acceptance is
recorded separately from quantum and physical legality checks.

```powershell
& modules/physical_compiler/.venv/Scripts/python.exe -m modules.codes.rotated_surface_d3.examples.build_components --operations raw_t --raw-t-extra-rounds 1 --output modules/codes/rotated_surface_d3/artifacts/raw-t-postselection-review
```

Selecting `raw_t` exports the low-level primitive for inspection and the
complete `raw_t_postselection` chain for resource-use review. The
`--raw-t-extra-rounds` flag must be a positive integer.

This component prepares a raw resource. It does not implement resource
consumption, distillation, a magic factory, decoding, complete error
correction, or an error-qualified logical T gate. No noisy fidelity,
circuit-level fault-distance, or globally minimal-cost claim is made.
