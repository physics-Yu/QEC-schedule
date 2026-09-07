# Four-logical GHZ experiment

The GHZ demo is implemented in `experiments/ghz4` and uses the normal
QECschedule path:

```text
LogicalProgram
  -> PhysicalCircuit / PhysicalCircuitDAG
  -> GateLowerer
  -> SemanticRequestPlan
  -> RuntimeScheduler
  -> execution trace
  -> animation + timeline + metrics
```

The logical DAG is:

```text
prepare L0=|+>, L1=L2=L3=|0>
  -> initial QEC
  -> CNOT L0 -> L1
  -> QEC
  -> CNOT L0 -> L2   ||   CNOT L1 -> L3
  -> QEC
  -> logical measurement
```

Each logical CNOT is lowered to nine corresponding data-qubit CZ requests
with target-side `H/CZ/H` basis changes.  The compiler emits atom IDs and
provenance metadata only; coordinates, pair destinations, AOD movements and
measurement placements remain runtime decisions.

## Run

From the repository root:

```bash
python -m experiments.ghz4.run \
  --config configs/ghz4_rich.yaml \
  --output results/ghz4_rich \
  --basis both
```

The rich profile intentionally leaves dynamic entanglement and measurement
parallelism uncapped and gives the AOD controller a large tone budget.  It
should expose an 18-pair GHZ fanout epoch, a 24-pair four-block QEC slot, and
large multi-atom 2-D AOD movements.  `configs/ghz4_constrained.yaml` is an
optional comparison profile; it keeps the same logical/physical DAG and lets
the runtime split interaction and imaging batches.

Outputs include:

```text
logical_program.json
physical_gate_dag.json
semantic_requests.json
execution_trace.json
animation.html        # offline trace player
animation_x.html      # X-basis shot player
timeline.png
metrics.json
verification.json
z/ and x/              # complete per-shot artifacts
```

The verification report records `Z0Z1=Z1Z2=Z2Z3=+1` for the Z shot and
`X0X1X2X3=+1` for the X shot.  These are ideal symbolic stabilizer
expectations: the repository's execution model schedules hardware and does
not simulate amplitudes, noise, loss, or a decoder.
