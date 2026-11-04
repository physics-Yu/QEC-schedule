# Independent L2 model comparison

From the repository root, run the reference calculation with the existing
physical compiler Python environment and Node.js. It takes no circuit files.

```console
python -m experiments.small_shor_algorithm.shot_sampling_l2.evidence.compare_model
```

The [calculator](compare_model.py) writes `../build/independent-model.json`
relative to this directory. The report identifies the
[engine](../../../small_circuit/shor/browser_engine.js) by its file SHA-256.
Each two-qubit case supplies an ordered stream of gate, measurement and pulse
events. NumPy applies each rotation immediately using a full Kronecker matrix.
At measurement boundaries the calculator compares it with the JS engine's
accumulated local operators, removing one global phase and conditioning on the
same observed measurement outcomes. The six inputs exercise noncommuting gates,
systematic pulse-angle error, both feedback branches, and selective pulse targets.

For the noise calculation, an 85-digit Decimal reference evaluates the echo
and Ramsey functions and the joint conditional endpoint and integral moments of
an Ornstein–Uhlenbeck process. The engine is probed at five interval ratios
from `dt/tau_c = 1e-2` down to `1e-10`. Acceptance tolerances are `1e-12`
maximum complex-amplitude difference and `1e-7` maximum relative moment error.

The earlier attached HTML lost precision in the echo expression
`x + 4*expm1(-x/2) - expm1(-x)`. At `x = 1e-8` it returned
`1.6543612251060553e-24`. The 85-digit value begins
`8.3333333020833334e-26`. The calculator evaluates the historical expression
alongside the current implementation. The [original probe record](historical-reference.json)
identifies that attachment by its HTML hash and records its seven one-qubit
measurements separately.

For engine file `a2cb205bba99bfdb5aae2ae5952c91cd5c0bd51347876e9ef99d7b07c7d27ae1`,
the current comparator returned `8.333333302083334e-26` at that interval.
The largest moment discrepancy across the five ratios was `1.39e-11` or less.
Across 16 amplitude checkpoints the largest difference was `3.35e-16` or less.

The historical schedule could defer diagonal phases across X/Y pulses. Its
readout event occurred at exposure start. The current lab reserves all gate
slots and collapses the state at the end of exposure. The independent
comparison here starts from an event stream and therefore covers numerical
evolution given those events. The browser build and the
[coherent versus adaptive circuit comparison](../../simplified_circuit/README.md)
have separate entry points. The historical document's 4,000- and 10,000-shot
parameter sweeps have not been repeated for this engine.
