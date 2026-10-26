# Distance-3 components

Status: measured initialization, SE, physical logical Pauli, H, S/Sdag,
transversal CNOT, raw T and Y preparation implement callable components.
See [ADR 0040](../../../../docs/decisions/0040-approved-d3-logical-components.md).

## Protocols

| Component | Data preparation | Extraction | Returned correction relation |
| --- | --- | --- | --- |
| initialize_0 | Reset all nine data atoms to zero | Full eight-check N/Z SE | Z0^mX0 Z2^mX1 Z6^mX2 Z8^mX3 |
| initialize_plus | Reset then H on all nine data atoms | Same full SE | X6^mZ0 X0^mZ1 X8^mZ2 X2^mZ3 |
| se_round | Preserve input data | Same full SE | None; raw syndrome only |
| logical_x/y/z | Physical logical Pauli strings | None | None |
| logical_h | H9 and physical data rotation | None | Output role and syndrome mapping |
| logical_s / logical_sdag | Dedicated mid-cycle fold | Dedicated S-SE, eight results | Output syndrome parity equations |
| prepare_y | initialize_plus then logical_s | Two rounds, sixteen results | Four local preparation terms |
| raw_t | Center T\|+> injection primitive | Ordinary SE, eight results | Local boundary check only; additional SE required for use |
| transversal_cnot | Nine corresponding data CX | None | Two retained participant bindings |

The first three circuits have 24 CX gates and eight measurements. Both initializers have
17 resets; standalone SE has eight ancilla resets. N/Z slots are preserved by
barriers. X checks visit NW/NE/SW/SE; Z checks visit NW/SW/NE/SE in the documented
code diagram. Missing boundary corners leave empty slots.

For initialization, applying the returned Pauli product to each ideal measured
branch yields the canonical target state. The component **does not apply** that
product. Same-basis checks are ideally zero; their actual values are retained,
not forced to zero or used for postselection. Noise-dependent interpretation and
frame propagation are outside this implementation.

Approved realizations and primary references are documented in
[Pauli](../protocols/pauli.md), [H](../protocols/hadamard.md),
[S/Sdag and Y](../protocols/phase.md), [raw T](../protocols/raw_t.md),
and [transversal CNOT](../protocols/transversal.md).

## Public API

Imports resolve from the repository root; no new package installation is needed
in the existing physical-compiler environment. The component definitions are in
[__init__.py](__init__.py), circuits in [circuits.py](circuits.py), and shared
records/protocols in [component.py](../../contracts/component.py).

```python
from nadit_physical_compiler.device import Position
from modules.codes.contracts.component import (
    ComponentBinding,
    InvocationContext,
    validate_sequence,
)
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES

# device and world are supplied by the caller; all 17 bound atoms already occupy
# the reference homes. Compile once per selected device/layout/timing profile.
templates = {
    name: get_component(name).compile(
        device,
        home_sites=REFERENCE_HOMES,
        origin=Position(0, 0),
        aod_id="transport",
    )
    for name in ("initialize_0", "initialize_plus", "se_round")
}
binding = ComponentBinding("block-A", Position(0, 0), tuple(range(17)), "transport")
initial = (
    templates["initialize_0"]
    .bind(binding)
    .expand(InvocationContext("prepare-A", 0, 100, device, world))
)
following = (
    templates["se_round"]
    .bind(binding)
    .expand(
        InvocationContext(
            "SE-A-1",
            initial.action_end_us,
            108,
            device,
            initial.exit_state,
        )
    )
)
validate_sequence((initial, following))
# When actual values arrive, attach them immutably by physical measurement ID:
# resolved = initial.with_results(received_bits)
```

The caller reserves nonoverlapping measurement-ID ranges and unique invocation
IDs. `program.timeline()` uses local time; add `start_us` for the invocation's
absolute timeline. Measurement availability is already absolute.
`action_end_us` and `results_ready_us` are intentionally distinct.

An expansion retains description/version, participant identity, ordered
`wire_atoms`, source DAG, concrete AtomProgram, operation intervals, entry/exit
worlds, pending measurement ports and bound correction relations. Native DAG
operation IDs are local to the invocation; retain invocation identity when
combining provenance. Sequence validation does not flatten or schedule programs.

`get_component` also returns the single-block gates above. H requires the buffer
geometry in `nonzoned_h_reference.json` and `H_REFERENCE_HOMES`. After H, use
`expansion.exit_binding` and `expansion.exit_state` for the next component:
atom identities have physically moved to new code roles. Optional explicit
`site_ids` maps belong to a particular template; supply the next template's map
when changing templates. Coordinate lookup (the default) needs no such map.

`TransversalCNOTComponent` uses a separate two-participant compile/bind API;
see its protocol document. Both block identities and exits remain explicit.
The jointly compiled relative displacement is part of the geometry profile.

`output_syndrome_parities` carries local XOR equations, using `input.*` for
incoming signs or named measurement ports for measured signs. These equations
are metadata only. In particular, S-SE's `phase.X1` alone is not the output X1
sign.

The `raw_t` primitive's local `acceptance_status` covers only its four boundary
results. It does **not** qualify the resource for use. The required usage entry
is `RawTPostselection(extra_rounds=1)` in
[raw_t_postselection.py](../protocols/raw_t_postselection.py). It composes the
unchanged primitive with at least one ordinary `se_round`, retains every result,
and accepts only when the first four boundary detectors and all eight check
differences between adjacent rounds vanish. Nonzero but repeated bulk bits pass.
Only the sequence's `ready_for_use(at_us)` combines this full predicate with
final physical and result availability. No correction, decoder or retry runs.
The final temporal boundary stays open; no noisy error rate is inferred.

## Binding and reuse

The template contains relative trajectories, AOD grid coordinates and pulse
coverage, plus required SLM-site offsets and relative measurement times. It
contains no outcomes, global clock, pending-result queue or frame.

Binding replaces the origin, atom IDs, actual SLM site IDs, AOD identity, local/
CZ/readout channels and result identities. Site lookup must be unique at the
required coordinates, or an explicit complete `site_ids` map is supplied.
Binding itself does not move a block. `expand` checks its actual entry state.

Expansion uses the cached action structure without recompiling. Changed timing,
missing sites, incompatible geometry/capacity or occupied resources raise
`BindingRejected`; callers may select another binding or explicitly compile a
new template. Fixed external readout is not assumed to translate with the block.
The example profile has a translatable shared-array/readout resource tile.

## Entry and exit

- Entry: all 17 roles occupy their bound SLM homes; the complete world is given,
  including spectators. AODs are inactive. The selected AOD supports flexible
  nonzoned transport and the device supports retained readout. Required guest
  traps, pulse regions and transport intersections must pass physical admission.
- Quantum entry: initialization discards prior data state; SE accepts an encoded
  state in any stabilizer-sign sector and does not initialize it.
- Exit for measured preparation, SE and phase gates: every atom returns to its entry home, AODs are inactive, data remain
  encoded, and ancillas are retained in their measured states without a trailing
  reset. Measurement delivery may still be pending.
- H exit: the same code homes are occupied, with data atom identities permuted;
  the auxiliaries are unchanged. Pauli and CNOT do not measure/reset auxiliaries.
- Frame boundary: only measurement identity/value/availability and symbolic
  correction information are provided. There is no frame manager, cross-gate
  propagation, physical correction, decoder or simulation-truth feedback.

## Reproducible artifacts and checks

```powershell
& modules/physical_compiler/.venv/Scripts/python.exe -m modules.codes.rotated_surface_d3.examples.build_components --output modules/codes/rotated_surface_d3/artifacts/my-components
& modules/physical_compiler/.venv/Scripts/python.exe -m pytest -q modules/codes/rotated_surface_d3/tests
```

Use a fresh output directory. The example records source/profile/compiler hashes,
QASM, relative actions, concrete expansions, pending result ports, an invocation
chain and an HTML action viewer. Tests independently simulate source and actual
atom actions, including all 16 ideal branches of each initializer and repeated
SE on the uncorrected branch. Test-only branch enumeration is not runtime
postselection. Physical admission also covers whole-group readout capacity.

`template_content_sha256` identifies the complete relative program and protocol
metadata, including H transport and physical exits. Source/compiler hashes alone
do not distinguish two component-owned transport plans for the same gate QASM.

Full circuit-level fault distance, noisy logical-failure estimates and global
cost optimality are not claimed. The earlier
[unitary-initialization experiment](../experiments/three_operations/README.md)
is historical and is not the public initialization implementation.

Use `--operations logical_x logical_y logical_z logical_h logical_s logical_sdag
prepare_y raw_t transversal_cnot` to build the selected gates, including the
two-block operation with its own reference resource profile.
Selecting `raw_t` also exports the required `raw_t_postselection` sequence and
its combined animation. `--raw-t-extra-rounds N` selects at least one follow-up
SE round; zero is rejected. The standalone raw_t trace is explicitly labeled as
a primitive and is never reported ready for resource use.
Animation shows the actual compiled pulses and LOAD/MOVE/STORE steps. Quantum
simulation and human visual acceptance are separate checks.

A reusable template defines roles and relative geometry. A case supplies block
instances, actual atom identities, positions and measurement outcomes. Coordinate
rebinding still requires legal Device geometry, transport and resource use;
support at arbitrary input positions is not implied.

See the [code definition scope](../definition.md) and
[compiler architecture](../../../logical_compiler/docs/architecture.md).

## Factory integration additions

`logical_mz` and `logical_mx` destructively read the nine data qubits while retaining
all seventeen atoms and their homes. Their metadata declares ideal logical
parities and four same-basis check equations, without decoding noisy records.
Preparation canonicalization executes the known local Pauli relation selected by
a separate joint event, preserving physical measurement identities and readiness.
See the [six-patch factory protocol](../protocols/factory.md) for entry/exit,
reset boundaries, event provenance and the reference-model limits.
