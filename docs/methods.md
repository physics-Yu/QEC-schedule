# Run a NADiT method

Start with the artifact you have. The physical package exposes installed
commands through `nadit`. Factory and calibration experiments use their
repository Python modules. Run the examples from the repository root with
the physical compiler environment and the relevant optional extras installed.

| Input and question | Entry point | What to inspect |
| --- | --- | --- |
| A circuit, Device and strategy. Can this hardware model run the circuit? | `nadit compile JOB.json --validate -o result.json` | Atom IR, the chosen measurement case and the independent validation report. The [native CPhase job](../modules/physical_compiler/examples/jobs/cphase-feedback.json) exercises device admission, pulse grouping and feedback. |
| A validated physical result. How does its fixed schedule respond to different timings? | `nadit method retiming/v1 result.json -o timing.json` | Step signatures, reference timing, additive terms and `acceptance.retiming_exact`. Use the exported schedule to vary timings while holding the compiler's decisions fixed. [Supported actions](../experiments/se_tradeoff/README.md) |
| A Clifford memory circuit. What Pauli/readout statistics does the model predict? | `nadit memory prepare`, `nadit method stim/v1`, then `nadit memory sample` | Annotated Stim circuit, detectors and decoded samples. Loss and leakage are reported separately. [Memory workflow](../modules/physical_compiler/docs/stim-memory.md) |
| A small QASM circuit or serialized DAG. What bits are sampled? | `python experiments/small_circuit/run_ideal.py`; for physical Small Shor timing use `run_shor_l2.py` | Output-bit order and histogram. The L2 receipt also counts lost shots. [Runnable examples](../experiments/small_circuit/README.md) |
| A set of surface-memory inputs. Which device/compiler combinations admit them? | `nadit experiment plan`, then `python -m experiments.se_tradeoff.admission` | Admitted and rejected cases with reasons before running a sweep. [Frozen inputs and commands](../experiments/se_tradeoff/README.md) |
| A single-level factory with an explicit cost model. How does it schedule production? | `python -m experiments.msd.single_fast smoke --config experiments/msd/single-level-fast-20261025.json --output NEW_DIRECTORY` | The d3, two-factory smoke case, output ledger and guard against physical compilation. Costs depend on the center-distance and acceptance assumptions. [Model](experiments/single-level-fast-20261025.md) |
| A two-level MSD campaign. When may L1 start another production cycle? | Set `two_level.candidate_rule.supply_mode` to `synchronized_consumption` in the campaign configuration. | A reserved input counts against capacity until use. For the next consumption round, wait for the last member of the L2 group to finish its current consumption, including feedback and correction. The shared-device scheduler admits transport separately. The current campaign supports one AOD. Existing configurations default to `pipelined`. [Supply and scheduling](../experiments/msd/README.md) |
| The stages of one homogeneous component wave. Can they share an exposure or move? | `python -m experiments.msd.object_wave wave.json` | Stage times and exclusive resource leases through release. A shared command needs a matching batch certificate. [Input example](../experiments/msd/README.md#schedule-one-wave-from-explicit-component-stages) |
| An uncached MSD calibration frontier. Which component work can it reuse? | The offline calibration worker calls the [component cache](../experiments/msd/component_reuse.py) before scheduling the combined frontier. | Separate component lowering hits, whole-frontier hits and fresh shared scheduling. [Cache contract and comparison](../experiments/msd/COMPONENT_REUSE.md) |

## Replay and inspect saved studies

- For the original static and semiclassical Shor inputs, build the native
  replay and inspect the selected measurement case. For new shots on the
  simplified N=15 or N=21 circuits, use the shot-sampling or L2 pulse lab.
  [Small Shor replay and sampling](../experiments/small_shor_algorithm/README.md)
- To regenerate the single-level center-distance statistics from saved
  completions, pass the frozen campaign directory to
  `python -m experiments.analysis.single_fast_report --campaign CAMPAIGN --output NEW_DIRECTORY`.
  The published compact bundle records eligible windows and budget stops.
  [Frozen report and ledgers](../experiments/msd/results/single-level-fast-20261025/README.md)
- To inspect a uniform-rigid d3 MOVE-depth problem, prepare and verify its
  frozen inputs. The uniform grid has a per-MOVE pitch and each atom must
  return home. [Depth-study commands](../experiments/surface_smt/README.md#new-studies)
- For the earlier one- and two-level object-factory scans, use the recorded
  source revision and the archived capacity convention. [Historical result index](experiments/msd-historical-scans.md)

## Verify one method through the installed CLI

```console
nadit describe
nadit memory prepare --distance 3 --rounds 1 -o memory-input
nadit compile memory-input/nonzoned.job.json --validate -o memory-result.json
nadit method retiming/v1 memory-result.json -o memory-timing.json
```

Check that `nadit describe` lists `retiming/v1`, and that the reference comparison in
`memory-timing.json` passes. This example needs the simulation extra to prepare
the input circuit. A compatible saved result can be retimed directly.

To inspect the supply barrier without running a factory campaign, run the
[two-consumer regression](../modules/logical_compiler/tests/test_factory_supply.py).
It delays one consumer and checks that the next synchronized L1 round starts
only after both L2 consumers have finished.

```console
python -m pytest -q modules/logical_compiler/tests/test_factory_supply.py::test_synchronized_supply_waits_for_last_consumer
```
