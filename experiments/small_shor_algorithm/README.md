# Small Shor replay and sampling

## Replay the supplied native circuits

From the repository root, use the physical compiler's Python 3.12 environment
with Qiskit, its QASM 3 importer and NumPy. The four original RAR archives sit
beside the runner. Extraction requires libarchive's `bsdtar` or the compatible
`tar` supplied with Windows and macOS.

```console
python experiments/small_shor_algorithm/run_native_cphase.py
```

Open `experiments/small_shor_algorithm/native_cphase/index.html` after the
build. The index links to the atom-action replay and both sensitivity viewers.
Its directory also contains `inputs.json` with each QASM member's source and
SHA-256, the compiler jobs, serialized results and `summary.json` with
validation results and ideal-state comparisons.

The archives contain eight distinct circuits across N=15 and N=21. Six static
circuits each have one ideal-state sampled trajectory. The two semiclassical
circuits each have one ideal-state sample at seed 17 and three forced feedback
cases (zero, one and alternating). Forced outcomes exercise timing and control
flow and can have zero quantum probability. Each ideal trajectory is checked
against the emitted operations. The static cases also compare the state before
measurement with the original QASM.

The compiler uses one rigid AOD and one entangling row. Native CP has a
study duration of 0.5 µs and shares a pulse only among pairs with equal angles.
The semiclassical inputs use CZ and measurement-conditioned local phase gates.

| Viewer | What can change |
| --- | --- |
| **Time and atom-loss sensitivity** | Explore timing and physical survival on any of the 14 resolved branches. |
| **半经典反馈电路** | Explore timing, expected atom loss and a separate T₂ coherence budget on the two seed-17 semiclassical branches. The displayed average of `1 − survival × coherence` is a sensitivity estimate. Sliders preserve branch outcomes. |

## Draw fresh shots

For QASM → Circuit IR → independent ideal shots and fixed-plan N=15/N=21 L2
sampling, use the [small-circuit CLI](../small_circuit/README.md). The
[shot-sampling browser](shot_sampling/README.md) and
[L2 pulse viewer](shot_sampling_l2/README.md) use the simplified circuits
and fresh trajectories.
