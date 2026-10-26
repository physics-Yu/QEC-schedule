# Rotated surface code d11

This concrete provider uses the shared rotated-code circuits and atom-template
ABI. It contains 121 data atoms and 120 syndrome atoms (241 total).
The current six-patch MSD world contains 1446 atoms; idle patches are
retained during complete-world physical validation.

```python
from modules.codes.rotated_surface_d11.components import COMPONENT_NAMES, get_component

se = get_component("se_round")
phase = get_component("logical_s")
raw = get_component("raw_t")
selected_raw = get_component("raw_t_postselection")
cnot = get_component("transversal_cnot")
```

The catalog includes initialize_0, initialize_plus, se_round, logical_x/y/z,
logical_s/sdag, prepare_y, logical_mx/mz, raw_t, logical_h, transversal_cnot,
grow_from_d3, and raw_t_postselection. Single blocks use `.compile(device,
home_sites=..., origin=..., aod_id=...)` and `.bind(binding).expand(context)`.
CNOT takes two home lists/origins and two bindings. H returns a permuted
`exit_binding` that the caller must retain. Its QASM alone omits physical carrier
rotation; the template/Atom IR includes that transport.

Raw-T injects a single actual T at d3, then performs ordinary target growth.
Postselected raw-T keeps three d3 rounds and only then conditionally executes
11 target SE rounds, including deformation. It requires received accepted bits
before runtime `grow`, and delivers an explicit decoded Pauli frame. Growth
syndromes are never postselected. Exported measurement values remain pending.

`entry.compilation_entry()` registers `rotated_surface_d11` / `clifford_t` in the
logical translation registry. As with d3/d5, this declaration is not a generic
physical factory adapter: the translation's intended T/TDG names are not standalone
physical transversal-T components. The physical lookup rejects `logical_t`.

Generate inspectable artifacts using the [production command and report](../../../experiments/msd/D9_D11_COMPONENTS.md).
The [shared contract](../rotated_surface/README.md) describes layout, noise,
canonicalization and decoder limits. No mixed-distance gate, calibrated output
LER, stochastic factory execution or hardware result is claimed.
