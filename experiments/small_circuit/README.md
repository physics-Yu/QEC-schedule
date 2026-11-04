# Small circuits from QASM to shots

Both samplers use the compiler's device-independent `PhysicalDAG` as Circuit IR.
Use the repository's Python 3.12 physical-compiler environment. The L2 sampler
also requires Node.js on the command path. Run these examples from the repository root.

## Import and sample an ideal circuit

```console
python experiments/small_circuit/run_ideal.py experiments/small_circuit/feedback.qasm3 --ir-out feedback.dag.json --shots 256 --seed 17
python experiments/small_circuit/run_ideal.py feedback.dag.json --shots 256 --seed 17
```

Supply an OpenQASM 2/3 circuit in the supported static frontend profile, with
bound parameters and explicit measurements. The importer lowers gates into H,
T, T†, P, CZ and CP, and retains resets, barriers and single-bit feedback.
The serialized DAG includes ordered quantum and classical wires, source IDs,
measurement references and dependencies. Atom positions and times are assigned
during physical compilation.

The [example](feedback.qasm3) measures the first qubit, uses that result to
conditionally flip the second, then overwrites the first classical bit after a
reset. The condition refers to the original measurement. The ideal final
outputs `00` and `10` have probability 1/2 each. Every shot starts in the
all-zero state. The sampler accepts up to 16 qubits. Bit zero is the rightmost
printed bit. For a marginal, use e.g. `--bits 0 2` on a circuit with those
classical wires, listing the least significant selected bit first.

## Compile and sample a Small Shor circuit

```console
python experiments/small_circuit/run_shor_l2.py --compile --n 15 --shots 32 --seed 17 --save-result n15.result.json --ir-out n15.dag.json --out n15.l2.json
python experiments/small_circuit/run_ideal.py n15.dag.json --shots 32 --seed 17
python experiments/small_circuit/run_shor_l2.py --n 15 --result n15.result.json --shots 32 --seed 18
```

Choose N=15 or N=21. The experiment replaces the terminal coherent inverse QFT
with adaptive measurement and conditional phases, preserving the counting-register
marginal. It builds the DAG, compiles it for the rigid zoned device, and validates
the resulting Atom IR. Compilation reserves a slot for each possible correction
using an all-one measurement fixture. Sampling draws fresh measurements and uses
the reported bits for feedback. A false condition leaves its slot idle.

The L2 engine evolves a statevector with static detuning, Ornstein–Uhlenbeck
noise and instantaneous, targeted XY4 pulses on the physical timeline. The
receipt records the model parameters, bit order, seed, content hashes and
shot counts. The histogram counts surviving shots. First-loss events are
accounted for separately. This is a simulated device model. The guarded-plan
adapter covers the two supplied semiclassical circuits with individually
controlled local gates and one measurement per output bit.
