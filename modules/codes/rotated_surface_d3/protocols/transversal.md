# Transversal CNOT between two d3 patches

Status: Confirmed protocol; implemented ideal action and physical compilation.
No noisy logical-error rate or complete circuit-level fault-distance claim is made.

## Protocol

The user approved nine CNOTs from `control.data[i]` to `target.data[i]`, for
`i=0..8`, between two patches with the same code orientation. Neither block is
reset. All sixteen syndrome ancillas are spectators. No SE round is inserted.

The source is the same-orientation transversal surface-code CNOT demonstrated in
[Bluvstein et al., Nature 626, 58-65 (2024)](https://www.nature.com/articles/s41586-023-06927-3).
The cited hardware result does not establish the performance of this device
profile or compiler; those are separate implementations.

The logical conjugations are

- `X_control -> X_control X_target`; `Z_control -> Z_control`;
- `X_target -> X_target`; `Z_target -> Z_control Z_target`.

Existing stabilizer signs can therefore change. The component returns sixteen
local `output_syndrome_parities` relations qualified by `control` and `target`.
Control X signs are input control-X XOR target-X; target Z signs are input
control-Z XOR target-Z. The other signs are unchanged. These are static local
relations, not a frame manager, decoder, or newly measured result.

Output keys are `control.X0`, `target.Z0`, and so on. Every incoming reference
is explicitly prefixed with `input.`, for example
`control.X0 = input.control.X0 XOR input.target.X0`. A new measurement port would
be named without that prefix; this measurement-free component has none.

## Two-participant interface

`TransversalCNOTComponent.compile` takes a device, each participant's seventeen
reference home sites, each participant's origin, and a shared AOD ID. It checks
that the two local home layouts agree and the 34 reference sites are disjoint.
The return value has:

- `atomic`: the underlying immutable joint AtomComponentTemplate;
- `relative_displacement`: target origin minus control origin;
- `bind(control, target)`: two separate ComponentBinding objects;
- `description` and `source_qasm`: public protocol identity and source.

For the supplied `nonzoned_cnot_reference.json`, module constants provide
`CONTROL_REFERENCE_HOMES`, `TARGET_REFERENCE_HOMES`, `CONTROL_ORIGIN=(0,0)`
and `TARGET_ORIGIN=(100,0)` in micrometres. The profile is a 7-by-17 shared
home/guest grid and a flexible AOD spanning both blocks.

Each participant has its own block ID, origin and seventeen atom IDs. Block IDs
and atoms must be disjoint, and both bindings must select the same AOD. Explicit
site maps, if supplied, use joint reference-site keys; their merged mapping must
cover all sites required by the underlying template. Omitting them selects
traps by unique coordinates.

`expand(InvocationContext(...))` checks the complete world and returns a normal
ComponentExpansion with both `participant_bindings` and
`exit_participant_bindings`. A collision-free internal composite `block_id`
identifies the joint operation, while the participant records preserve the two
actual block identities. `exit_binding` is `None`: the joint operation must not
be interpreted as a new single block.

## Position reuse and entry/exit

The cached atom program is relative to the control origin. Both participants
may be translated together with the required device resources without
recompiling. Their independently supplied origins must preserve the compiled
relative displacement. Changing only one origin rejects reuse and requests
explicit compilation for that new pair geometry. There is no silent rerouting.

Entry requires both encoded data blocks at their declared SLM homes, inactive
flexible AODs, required guest traps available, and complete world occupancy.
Physical admission checks geometry, illumination, transport and resources.

Exit returns every atom to its own entry home, preserves each role mapping,
and leaves AODs inactive. Both participant bindings can be used for subsequent
single-block components. There are no measurements or pending results, so
action completion and results-ready times coincide.

## Verification

Tests check the source and actual geometry-derived atomic Clifford tableaus,
all logical Pauli conjugations, all stabilizer transformations, and identity on
every ancillary X/Z generator. Each declared syndrome relation is compared with
the inverse conjugation of its output check by the actual atom-action tableau.
They exercise 36 encoded logical Pauli product
inputs and the resulting Bell state from `|+_L>|0_L>`.

Binding tests cover identities, disjoint atoms, shared AOD constraints, changed
relative geometry, whole-pair translation without compilation, and explicit
recompilation of a second 80-micrometre displacement. These checks do not evaluate
correlated decoding, transport noise, loss or fault-tolerant scheduling across
multiple components.
