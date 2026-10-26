# ADR 0041: Raw-T use requires repeated SE postselection

Status: Accepted on 2026-10-23 following the user's explicit correction.
This supersedes ADR 0040's single-round acceptance as a resource-use boundary.
It preserves the existing raw_t primitive and its selected injection circuit.

## Context

The center-injection primitive produces eight measurements. Four boundary
checks have known ideal values; four bulk signs are initially random.
Its existing local acceptance predicate inspects only the boundaries. It cannot
detect disagreement between successive measurements, including a corrupted
first-round bulk result. Passing this predicate is insufficient to qualify a
resource for use.

The user required at least one additional ordinary SE round and postselection
of all detectors in the completed sequence. The change is local composition
and interpretation, without a global frame manager or a decoding framework.

## Decision

Keep [RawTComponent](../../modules/codes/rotated_surface_d3/components/injection.py)
unchanged. Introduce
[RawTPostselection](../../modules/codes/rotated_surface_d3/protocols/raw_t_postselection.py),
which composes raw_t with `extra_rounds=k >= 1` copies of the existing ordinary
`se_round`. The default is one extra round, hence two total rounds. Both
templates are compiled once with the existing nonzoned backend, then reused.
There are no intermediate data corrections, altered N/Z schedules or implicit
conditional retries.

Let `m[r,j]` be the recorded bit for check `j` at round `r`, starting at zero.
The complete local detector set is:

```text
m[0,b]                              b in {X0,X3,Z0,Z3}
m[r-1,j] XOR m[r,j]                  r=1..k, j in all eight checks
```

Every detector must be zero. There are `4+8*k` detectors and `8*(1+k)`
measurements; the default has twelve detectors from sixteen bits. Random
bulk signs may remain one across rounds. Requiring all raw bits to be zero
would incorrectly reject valid ideal branches.

The primitive's `acceptance_status` remains a local diagnostic. The complete
sequence's `acceptance_status` is pending until all required inputs arrive,
rejected upon a known nonzero detector, or accepted when all detectors are
known and zero. Resource consumers must call `ready_for_use(at_us)`, which
also requires completion of the final atom actions and all result deliveries.
No time or missing outcome is inferred by this method.

## Interface and provenance

`RawTPostselection.compile(...).bind(...).expand(context)` retains the
relative-coordinate component contract. Every part has a distinct invocation
and measurement identity, while all parts keep the same physical block,
canonical roles and home layout. Reserve `8*(1+k)` consecutive result IDs.
Repeated port names are paired with their invocation; detector objects retain
the exact contributing measurement records and their latest availability time.

Later ordinary SE can begin at the preceding action end while previous
measurements are still pending, because it consumes no prior result values.
The first-round correction relations remain declarative output metadata;
accepted later measurements have the same signs. Neither these relations nor
the detector calculation implements a global frame or a decoder.

The sequence explicitly records:

```text
protocol_id = raw_t_postselection
version = 1
postselection_scope = first_boundary_and_adjacent_round_parities
terminal_boundary = open_after_last_se
```

Its content hash covers both immutable primitive content hashes, the round
count, version, scope and terminal boundary. Each primitive retains its source,
device and physical-compiler hashes. A changed sequence hash does not imply a
changed compiler or injected source circuit.

The example exporter includes the complete chain when `--operations raw_t`
is selected, alongside the primitive for inspection. `--raw-t-extra-rounds`
selects a positive integer. Animation review is performed on the whole chain;
pending measurement values remain pending in the artifact.

## Literature scope

[Li, A magic state's fidelity can be superior to the operations that created
it (2015), arXiv:1410.7808v1, Sec. II](https://arxiv.org/pdf/1410.7808v1)
uses two full rounds in the first injection stage, rejecting initialization
mismatches and disagreements between the rounds. Its later growth and normal
correction stage is outside this decision.

[Lao and Criger, Magic state injection on the rotated surface code (2022),
Sec. 3.1 and 3.4](https://doi.org/10.1145/3528416.3530237) uses the two-round
postselection rule for rotated-code injection, including center injection.
The publisher full text was inaccessible during this review; the section
details were checked against a text mirror of the original paper. No reliable
arXiv identifier was identified. Its gate-specific error coefficients are not
assigned to this implementation.

[Gidney, Cleaner magic states with hook injection (2023), arXiv:2302.12292v1,
Sec. 2-3](https://arxiv.org/html/2302.12292v1) uses a different injection
circuit. Fig. 2 shows two rounds, while the benchmark varies the round count
from one to six. It explicitly discusses residual injection errors and errors
escaping the final postselection time boundary. It does not establish that
all injection protocols require exactly two rounds or have the same fault
behavior.

## Verification and remaining boundaries

Interface tests check the default and larger round counts, rejection of zero
extra rounds, detector identities and pending values, immutable result
attachment, timing, resource continuity and provenance.

The complex-state checks independently compare source and actual atom
evolution over all sixteen ideal injection branches and the following SE.
They verify 27 single-data Pauli insertions at one tested inter-round boundary,
four first-round bulk readout-bit flips, and a central-seed Z counterexample
that passes every detector but changes the logical state. See
[the quantum tests](../../modules/codes/rotated_surface_d3/tests/test_raw_t_postselection_quantum.py).

These checks do not enumerate all faults. In particular, the final temporal
boundary remains open, and a seed error can already be logical before ordinary
repetition can distinguish it. Acceptance means the declared finite detector
set passed. It does not imply full fault tolerance, a clean logical magic state,
or a numerical logical-error bound.

No noise model, decoder, global frame, factory, distillation, automatic retry,
or resource-consumption protocol is introduced. Human animation acceptance
remains separate from artifact generation and quantum correctness checks.

See [the protocol and API example](../../modules/codes/rotated_surface_d3/protocols/raw_t.md).
