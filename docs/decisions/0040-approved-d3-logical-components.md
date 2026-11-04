# 0040: Approved d3 logical components and physical exits

Status: Accepted on 2026-10-23 following explicit user protocol choices.

Raw-T resource-use acceptance is amended by
[ADR 0041](0041-raw-t-repeated-se-postselection.md). The one-round primitive
remains unchanged; using its output requires subsequent SE and temporal detectors.

## Context

The measured initialization and SE contract in ADR 0039 supplies relative atom
templates but does not imply that every surface-code gate is transversal.
Additional components require explicit quantum protocols, output encodings and
physical resource requirements. The user requested paper-grounded choices and
source/action quantum verification, followed by animation review.

## Decision

- Logical Pauli uses the current code's physical strings, not a software frame.
- H applies nine physical H gates and a real single-AOD data permutation. The
  output occupies canonical code homes with changed atom-role identities.
- S and Sdag use independent Chen et al. mid-cycle S-SE circuits. Their gate
  order does not modify ordinary N/Z SE. Sdag reverses the phase core, not the
  nonunitary measurement circuit.
- CNOT couples corresponding data atoms of two same-oriented d3 blocks using
  nine physical CX gates. SE remains separately composable.
- Raw T means T|+> with relative phase pi/4. It uses center injection and one
  complete ordinary SE round, accepting only four deterministic boundary checks.
  Random bulk results are retained and do not cause rejection.
- Y preparation composes the existing measured initialize_plus with approved S.
  It retains all sixteen measurement identities and local correction relations.

Primary sources, exact role conventions and evidence boundaries are in the
[local protocol documents](../../modules/codes/rotated_surface_d3/protocols/).
The existing nonzoned fixed-reference compiler remains the physical backend.
H appends explicit transport primitives checked by that backend's motion,
replay, timing and semantic validators. Transport is not a fictitious SWAP gate.

## Interface

Reusable templates contain relative geometry and static protocol metadata.
Invocation expansions contain concrete atoms, result identities and availability,
complete physical entry/exit worlds, and declared output role bindings.
`wire_atoms` always describes source wires on stable atoms; `exit_binding`
describes canonical output roles. A caller composing H with SE must use the
latter with the actual exit world.

Joint CNOT templates retain separate control and target participants. Their
relative displacement is part of the compiled geometry profile. Both origins
translate without recompiling when the complete resources translate with them;
changing their separation requires an explicit compatible template compilation.
This avoids hiding transport planning inside a nominal coordinate substitution.

Optional explicit site maps are template-specific. Missing or occupied buffers,
ambiguous sites, changed timing and incompatible resources reject expansion.
Other atoms in the world are included in admission checks.

Local `output_syndrome_parities`, correction terms and raw-T acceptance predicates
are returned as interpretation data. Actual values attach immutably using
`with_results`; pending values are never treated as zero. No global frame,
cross-gate frame propagation, decoder, retry controller or factory is introduced.

## Validation and limits

Tests independently interpret source circuits and pulses/CZ geometry from actual
atom actions. Pauli and H include logical-axis and syndrome-sector checks; phase
gates include all 256 input sectors; raw T uses a non-Clifford complex statevector
and checks all sixteen ideal branches. CNOT checks encoded joint action and
participant binding. These are ideal quantum checks, not noisy fault-distance
qualification. Device times are illustrative, not measured hardware data.

Animation renders the compiled actions and actual atom identities. Rendering,
agent inspection and user acceptance are distinct; an exporter completing does
not establish visual acceptance. Existing motion rules validate their stated
endpoint constraints, not unmodeled continuous transport physics.

No global resource optimum is claimed. Alternative injected S protocols,
different raw-T acceptance depths, fused Y preparation, extra CNOT SE rounds and
global frame management remain outside the selected routes.
