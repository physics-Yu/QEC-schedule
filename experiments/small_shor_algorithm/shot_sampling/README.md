# Stochastic Pauli and atom-loss lab

This sampler applies stochastic Pauli faults, dephasing, readout flips and
first-loss aborts along the validated N=15 or N=21 semiclassical schedule.
The [L2 lab](../shot_sampling_l2/README.md) models detuning, OU noise and pulse
scheduling. Both labs use the [compiler exporter](../simplified_circuit/README.md).

From the repository root with the physical compiler Python environment and
Node.js on the command path, run

```console
python -m experiments.small_shor_algorithm.simplified_circuit.compile_inputs
python -m experiments.small_shor_algorithm.shot_sampling.build_share
```

Open `../simplified_circuit/build/share/SmallShor-Complete.html` or distribute
the adjacent ZIP. The standalone worker uses the JavaScript statevector engine.
Select a circuit and seed to replay a sample. The histogram and per-atom loss
curve label their denominators separately.

The optional local Python service uses Qiskit Aer. Install `qiskit-aer==0.18.2`
in the experiment environment before using this backend. After the builds above,
start the server with

```console
python -m experiments.small_shor_algorithm.shot_sampling.server --host 127.0.0.1 --port 8767
```

Open `http://127.0.0.1:8767/` for the local page. The service also accepts
`POST /api/sample` with `n`, `parameters`, `shots` and `seed`. It accepts
1 to 10,000 shots and an unsigned 32-bit seed. Browser and Aer sampling use
their own random streams. The counts describe the chosen simulation parameters.
