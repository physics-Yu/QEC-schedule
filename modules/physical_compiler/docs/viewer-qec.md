# QEC overlays in the shared viewer

`nadit view` can display explicit X/Z check ancillas, data-qubit labels and
check-to-data support edges. It reads metadata, not inferred gate patterns or
hardcoded atom numbering. The same template is used for every compiler and
experiment. This adds no compilation or quantum simulation step.

```powershell
nadit view RESULT.json -o viewer.html --qec surface-d3-qec.json
```

The sidecar applies to every supplied result; qubit-to-atom bindings are resolved
separately for each. For mixed code definitions, embed a `qec` field in each
result at creation, or use separate exports. A sidecar overrides embedded
annotations. Neither option modifies saved inputs or recompiles a circuit.
Use a sidecar for frozen or noise-evaluated results to preserve their hashes.

## Metadata

```json
{
  "schema": "nadit.qec-overlay/1",
  "title": "Example CSS checks",
  "checks": [
    {"id": "X0", "basis": "X", "ancilla_qubit": 2, "data_qubits": [0, 1]},
    {"id": "Z0", "basis": "Z", "ancilla_qubit": 3, "data_qubits": [0, 1]}
  ]
}
```

| Field | Meaning |
| --- | --- |
| schema | Required `nadit.qec-overlay/1` |
| title | Optional control-group label; defaults to `QEC structure` |
| checks | Array of static CSS checks; an empty array disables the overlay |
| id | Unique visible check label, such as `patch0:X0` |
| basis | `X` or `Z` |
| ancilla_qubit | Physical DAG wire index of the check ancilla |
| data_qubits | Nonempty, unique support wire indices |

References are physical qubit indices, not atom IDs or spatial coordinates.
The exporter resolves them through `entry_state.qubit_to_atom`. Check ancillas
are unique and cannot also be declared as data. Unbound references are rejected.
These annotations are static across a trace; they do not infer changing code
supports during code deformation.

A complete rotated-d3 example is provided in
[`examples/visualization/surface-d3-qec.json`](../examples/visualization/surface-d3-qec.json).
Its check supports come from the code definition, independently of placement.

## Display behavior

- `X checks`: blue check rings/labels and their connected data labels.
- `Z checks`: orange check rings/labels and their connected data labels.
- `Check–data links`: dashed structural support edges; actual CZ pulses retain
  their existing pulse display. Turning this off leaves the role markers visible.
- All three controls default on when annotations exist. Turning X and Z off
  removes the QEC overlay. Unannotated traces hide these controls.
- Lines follow current replay atom positions, including during interpolated
  movement. Spatial rings/line widths scale with the scene; labels use the same
  screen-text convention as existing IDs. The atom-size control also scales rings.
- Holder/loss colors remain the atom core colors. Clicking an atom displays its
  data/check role and associated stabilizer supports in the inspector.

## Python interface

The public export functions remain `build_trace`, `build_result_trace` and
`write_html`. Both trace builders accept optional `qec=metadata`:

```python
trace = build_result_trace(result_document, qec=metadata)
write_html([trace], "viewer.html")
```

`build_result_trace` also reads `result_document["qec"]` when no override is
supplied. An export without annotations retains the previous trace format.
QEC topology does not alter Atom IR, timing, measurement values or noise results.

## Verification

Python tests cover binding, invalid metadata, input immutability, CLI sidecars
and embedded annotations. The DOM-independent JavaScript checks run with:

```text
node --test modules/physical_compiler/tests_js/qec.test.cjs
node modules/physical_compiler/tests_js/qec-viewer-smoke.cjs TRACE.json
```

The second command exercises the actual viewer scripts with a recording canvas
and a DOM fixture: toggles, timeline scrubbing and annotated/unannotated trace
switches. It is not a browser screenshot or a visual acceptance check.
