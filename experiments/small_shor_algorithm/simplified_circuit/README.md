# Compile the simplified Small Shor inputs

Run the exporter from the repository root with the physical compiler Python environment.

```console
python -m experiments.small_shor_algorithm.simplified_circuit.compile_inputs
```

Both shot labs use the same N=15 and N=21 QASM, compiler settings and guarded
circuit conversion as the [Small Shor L2 CLI](../../small_circuit/README.md).
The exporter writes validated results to `build/results/`, adaptive QASM to
`build/semiclassical/`, and one seed-17 ideal example branch per circuit to
`build/manifest.json`. Re-run it after changing the inputs or compiler, then
rebuild the desired HTML. Each compilation reserves all feedback slots. Each
sample's measurements determine which conditional rotations actually run.

For an independent comparison of the original and adaptive circuits, run

```console
python -m experiments.small_shor_algorithm.simplified_circuit.check_reference
```

The report in `build/reference-report.json` compares the original coherent
counting-register marginal with all adaptive branches and the finite-register
order formula. This comparison covers ideal output probabilities.

Open the [L2 pulse lab](../shot_sampling_l2/README.md) for static detuning,
OU noise and XY4, or the [Pauli and loss lab](../shot_sampling/README.md) for
the stochastic Pauli model.
