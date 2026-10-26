# ADR 0039: Measured d3 components and relative action binding

Status: Protocol and scope confirmed by the user on 2026-10-23; implemented
for initialize_0, initialize_plus and one full SE round.

## Confirmed protocol

Both initializers prepare all nine data atoms in zero or plus, then reuse
the complete eight-check N/Z extraction circuit. The selected implementation
does not substitute an eight-CX unitary encoder or omit half the checks.

The shared SE resets only its eight ancillas, uses the four fixed N/Z CX slots,
and measures all eight ancillas. Ancillas are retained without a trailing reset.
All components return every atom to its entry reference home with inactive AODs.

Initialization returns the eight physical result ports and a symbolic relation
to the canonical logical state. For initialize_0 the relation is
Z0^mX0 Z2^mX1 Z6^mX2 Z8^mX3. For initialize_plus it is
X6^mZ0 X0^mZ1 X8^mZ2 X2^mZ3. Results are not forced to zero or postselected.
The same-basis check outcomes are ideally zero but remain ordinary result ports
whose actual values are retained, including unexpected/noisy outcomes.

## Contract and ownership

`codes/contracts/component.py` defines immutable descriptions, bindings,
invocations, outputs and correction relations. The concrete d3 implementation
owns its code definition, circuits and correction mapping. The nonzoned adapter
and coordinate mapper live in `codes/_support/`; they do not replace the
physical compiler or introduce a logical compiler.

The calling sequence is definition.compile(reference profile), template.bind(
participant/role/origin/resources), then bound.expand(current world/context).
Compilation happens once per chosen implementation/resource profile. Expansion
rebinds actual atoms, SLM sites, AOD grids, channels, coverage, result identities
and relative coordinates without calling the compiler. It validates the expanded
actions against the complete current world, including spectators and capacity.

Changing timing or losing geometric/resource equivalence rejects template reuse.
The caller can select another binding or explicitly compile a suitable reference.
Expansion does not silently replan. A coordinate translation alone is not an
admission certificate. In particular, fixed external readout need not be
translation-equivalent to a component's compiled readout path.

Templates retain source/profile/compiler hashes and measurement timing, never
measurement values, invocation clocks, pending queues or frames. Each invocation
has caller-supplied identity, start time and a reserved integer measurement-ID
range. Action times are local to its program; output availability is absolute.
Native operation IDs remain scoped by invocation, with component identity
preserved in the expansion record.

The current concrete components use one participant. This is not a decision that
all future codes encode one logical qubit or all future components use one block.
Multi-participant protocols remain separate follow-up designs.

## Frame boundary

Outputs start pending (`value=None`). `with_results` attaches received bits to a
new immutable expansion, without changing the template or advancing time.
Correction relations are declarative information only. No production path
evaluates them, applies physical correction gates, accumulates frames, propagates
frames through gates, performs decoding, or consults simulation truth.

`validate_sequence` checks an explicitly ordered invocation chain for entry/exit
continuity, non-overlap and unique identities. It does not select operations or
manage time. A following SE can start at the preceding action end while earlier
results remain pending, because it consumes no earlier result bits.

## Verification

Focused backend baseline: 32 existing nonzoned/replay tests passed before changes.
The code-library suite checks code distance, all 16 ideal outcome branches of each
initializer, source/action quantum agreement, declared correction relations,
84 encoded-input/preexisting-error SE cases, four representative N/Z hooks,
initialization-to-SE composition without frame management, actual translated
reuse without recompilation, renamed resources/atoms, result timing/isolation,
and rejected geometry, occupancy and whole-readout-capacity bindings.

The physical compiler source is unchanged. Existing nonzoned/replay regression
tests and the full currently executable code-library suite are the affected
integration scope. Formatting, lint and strict typing cover the new production
modules; the example is executed to produce inspectable artifacts.

Recorded verification: 18 code-library tests plus 32 existing backend/replay
tests passed (50 total). Strict mypy passed for the six new production modules;
the example generated all three measured protocols and a sequential call chain.

Open: circuit-level fault-distance qualification, noisy logical failure,
cost-minimal protocol/layout selection, multi-participant protocols and global
frame/decoder integration. None is required for these three callable components.

See [component API](../../modules/codes/rotated_surface_d3/components/README.md).
