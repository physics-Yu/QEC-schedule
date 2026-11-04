# L2 pulse lab

Build the validated inputs and the standalone page from the repository root,
using the physical compiler Python environment and Node.js on the command path.

```console
python -m experiments.small_shor_algorithm.simplified_circuit.compile_inputs
python -m experiments.small_shor_algorithm.shot_sampling_l2.build
```

Open `build/SmallShor-Semiclassical-L2-Pulses.html` in a browser, select N=15
or N=21, and set the shot count and seed. The adjacent ZIP contains the page,
plans, circuits and engine provenance. These paths are relative to this
directory. The HTML embeds the same [JS engine](../../small_circuit/shor/browser_engine.js)
used by the CLI. The worker and replay run locally after the page opens.

Each shot samples static detuning and stationary Ornstein–Uhlenbeck noise.
The controls place instantaneous XY4 rotations within the physical schedule.
Storage-zone pulses during readout assume independent zone addressing. False
feedback conditions leave idle slots. A first atom loss ends the shot. The
histogram counts valid readouts and the loss panel reports the other shots.

The pulse chart and atom replay follow the selected parameters and a representative
readout branch. After sampling, the chart can identify the most frequent loss-free
bit string. The graph shows reserved times and pulse centers. The loss parameters
and instantaneous rotations are simulation assumptions.

The [independent model comparison](evidence/README.md) reproduces the historical
short-interval echo discrepancy and compares the current engine with direct
two-qubit evolution and high-precision noise moments.
