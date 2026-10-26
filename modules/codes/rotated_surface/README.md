# Parameterized rotated surface-code components

This additive family implements odd distances `d >= 3` using the established d3
roles, geometry and immutable atom-template contract. It preserves the established
d3 gate behavior. Raw-T now fixes injection at d3 and grows to the target distance;
acceptance is calculated from the actual small-patch physical trajectory.

```python
from modules.codes.rotated_surface import (
    RawTPostselection,
    TransversalCNOTComponent,
    definition,
    get_component,
)

code = definition(5)
component = get_component("logical_s", 5)
template = component.compile(
    device,
    home_sites=homes,
    origin=origin,
    aod_id="transport",
)
# Template.bind(ComponentBinding).expand(InvocationContext) checks the complete
# caller-owned world, including every spectator atom and result-ID reservation.
```

`definition(d)` exposes `data_count=d*d`, `check_count=d*d-1`,
`atom_count=2*d*d-1`, `checks`, `data_coordinates`, `check_coordinates`,
`reference_coordinates`, `reference_homes`, `roles`, `check_roles`,
`logical_x`, and `logical_z`. Data are row-major on `(2*c+1,2*r+1)`; X checks
are ordered by row, Z checks by column. These are the existing d3 conventions.
The d5 facade exposes the corresponding fixed-distance definitions and lookup.
The d9 and d11 providers expose the complete 16-entry catalog via their local
`components.get_component(name)` APIs. See the
[production report](../../../experiments/msd/D9_D11_COMPONENTS.md) for exported
source, relative templates, full-world actions, resource metrics and viewers.

## Implemented protocols

| API | Concrete operation and exit |
| --- | --- |
| `get_component("initialize_0", d)` | Reset data to zero, complete measured N/Z extraction; symbolic branch corrections |
| `initialize_plus` | Reset/H data, complete measured N/Z extraction; symbolic branch corrections |
| `se_round` | Reset ancillas, four N/Z CNOT slots, measure ancillas and return home |
| `logical_x`, `logical_y`, `logical_z` | Actual physical logical Pauli strings |
| `logical_s`, `logical_sdag` | Actual midpoint fold on data and syndrome atoms inside a separate full S-SE round |
| `prepare_y` | Complete initialize-plus round followed by separate S-SE, retaining both result sets |
| `logical_h` | H on data plus explicit clockwise carrier rotation; return changed `exit_binding` |
| `logical_mx`, `logical_mz` | Destructive retained-atom data readout, ideal logical/check parity metadata |
| `raw_t` | One actual d3 T injection/SE, then d ordinary target-growth rounds (none at d3); raw output requires decoding/frame handling |
| `RawTPostselection(d)` | Three d3 postselected rounds, then conditional target growth and ordinary decoding; version 3 |
| `DirectRawTPostselection(d)`, `raw_t_direct_control` | Historical all-d circuit/postselection retained for explicit controls |
| `TransversalCNOTComponent(d)` | Corresponding-data CNOT between two disjoint same-distance/orientation blocks |

The joint CNOT compile arguments are `control_home_sites`, `target_home_sites`,
`control_origin`, `target_origin`, and `aod_id`. Bind with separate control and
target bindings. Both participants remain explicit in the expansion.

Timing, layout, AOD capacity, readout capacity and device noise parameters remain
caller-owned. Compilation produces actual operations and transport under the
supplied nonzoned Device; it never substitutes a duration-only gate. Immutable
templates cache actions, not measurement outcomes or global runtime state.

H uses one vacant external SLM trap and sequential one-atom transport to break
each four-cycle of the rotation. `compile(..., buffer_site=...)` selects an
explicit buffer; otherwise the nearest candidate is declared. Expansion checks
its real vacancy in the full world. All transfers and movements contribute to
cost. This conservative route is not the specialized six-stroke d3 schedule or
an optimality claim. Subsequent operations must use H's returned `exit_binding`.

## Real S and ideal sign equations

The fold is the same pinned CCLP S-SE construction used by d3:
[author phase_gadget.py](https://github.com/Zihan-Chen-PhMA/Dynamical-S-gate-decoding/blob/c3b7a1e2f95d49a5853d5534a4596854317890e9/phase_gadget.py),
mapped from `(u,v)` to `(d-1-v,u)` before converting to the integer grid.
The phase-specific extraction slots remain separate from ordinary SE. Interior
atoms reflect across `x=y`: off-diagonal pairs receive CZ, diagonal data receive
S, diagonal syndrome atoms receive Sdag. Sdag reverses those single-qubit phases.

`phase_sign_matrices` pulls measured Z operators and output checks backwards
through the concrete Clifford circuit using exact signed Pauli algebra. It
rejects any operator that cannot be expressed as a positive input-check parity.
`measured_input_parities` and `output_syndrome_parities` expose the resulting local
equations. These are ideal equations, not a noisy decoder or global frame.

## Small injection, conditional growth, and frame delivery

```python
protocol = RawTPostselection(target_distance)  # fixed d3, three injection rounds
prepared = protocol.compile(device, home_sites=homes, origin=origin, aod_id="transport")
bound = prepared.bind(target_binding)
injection = bound.expand(injection_context)  # only the 17-carrier injection
port = protocol.acceptance_port(injection, device, noise_params=noise)
protocol.validate_acceptance_port(port, prepared, noise_params=noise)

# received_bits must come from actual measurements or an explicit quantum model.
received = injection.with_results(received_bits)
if received.acceptance_status == "accepted":
    # Fresh result IDs, accepted exit world, start >= injection results_ready_us.
    grown = bound.grow(received, growth_context)
    grown = grown.with_results(received_growth_bits)
    frame = grown.decode(caller_time_us)
    # Keep frame.x / frame.z on target data, or physically apply their Paulis.
```

Missing/rejected injection bits cannot execute growth. Injection acceptance is an
intermediate `continue` event, not target-state delivery. Growth bits are **never**
postselection conditions. Target d3 has no deformation and returns the established
injection canonicalization frame. `injection_rounds=2` selects the paper's two-round
variant; the default of three preserves the prior experiment's d3 convention.

`injection_indices(d)` maps the small patch onto the target's upper physical edge.
Only added data are reset: new rows are plus, and new columns alongside the seed
are zero. The extended middle-column X and middle-row Z act as the original seed
axes and commute with target-check projectors. Final gauge corrections preserve
both axes. Ideal X/Y/Z tests validate this rotated-code adaptation at d5/7/9.
It is not a literal reproduction of Li's unrotated circuit or its noise coefficients.

`GrowthDecoder` uses phenomenological MWPM on repeated target syndrome changes,
with open initial/final temporal boundaries, explicit initial-gauge handling and
configurable data/readout weights (unit defaults). It returns a virtual Pauli
correction; it never reads simulation truth or rejects a syndrome. Faults before
the reference growth round and after the final round are not fully protected.
Circuit-level decoder calibration and accepted-output LER remain unmeasured.

Version-3 probability/cache identities include injection/target distance, both
round counts, template/source/device identity and resolved noise. The estimator
reuses the checked d3 arbitrary-T detector engine on the actual occupied-world
trajectory. It does not substitute a numerical d3 constant or count growth faults
as rejection. Physical loss remains separate. A binary acceptance port is not a
joint preparation-class distribution and cannot replace the legacy d3 factory's
canonical preparation cache.

`get_component("raw_t", d)` is the unpostselected primitive: one d3 round followed
by ordinary growth. Its result ports are `injection.*` and `growth[r].*`; pass the
full growth history to `GrowthDecoder` for noisy use. Its correction terms alone
are ideal branch relations, not noisy decoding. At d3 this primitive is unchanged.
The old direct full-d source is available only through explicit reference lookup
`raw_t_direct_control` (or its low-level `SurfaceComponent` definition).

See [ADR 0055](../../../docs/decisions/0055-small-injection-then-growth.md) and the
[new experiment report](../../../experiments/msd/SMALL_INJECTION_GROWTH.md).
Historical [all-d results](../../../experiments/msd/RAW_T_DISTANCE_ROUNDS.md) retain
their old meaning and are not results of the new protocol.

## Evidence and remaining integration

Tests check exact d3 source-QASM equality, commuting independent checks and logical
strings through d11, ideal S/Sdag action and sign-generator sectors at d3/5/7,
preparation channel witnesses at d3/5/7, complete raw correction columns through
d11, and deterministic-seed intersection ranks through d15. Physical integration
uses d5 and d7 templates on the complete six-block standard world: source and
reconstructed actual Clifford actions agree; movement/replay and spectator
occupancy are checked. Raw T retains an actual non-Clifford source gate; its
large-distance quantum argument uses the arbitrary-seed channel, not a dense
49/97-qubit state vector.

Delivered: concrete components, symbolic ideal corrections, retained raw outcomes,
local postselection, binary distance-aware raw-T acceptance probabilities, and
physical compile/bind/expand interfaces. Not delivered:
generic execution of preparation corrections, joint preparation-class probabilities,
generic factory backend adaptation, global frame propagation, or stochastic
factory production/yield. The existing `rotated_surface_d3` canonicalization,
probability and `FactoryBackend` implementations remain d3-specific. The logical
compiler must explicitly consume the generic interfaces before a larger-distance
factory can be called operational. Mixed-distance CNOT or state transfer is not
defined by this module. No hardware execution or human visual acceptance is claimed.
