# Frozen surface-code memory: large-zone comparison

Date: 2026-10-23. Status: Complete; all 16 points independently verified.

## Scope and reproducibility

- Compiler: `ea8c348dc914ba26e42b756ae0d30f7031dba425`; harness: `5dcef89`. The frozen server checkout remained clean.
- One rotated block, d=3/5/7/9, rounds=d, X/Z memory; explicit standard homes for nonzoned and Search Smarter QEC. No initial SA or cross-layer reuse.
- Exactly 1,048,576 shots per point, 16 shards of 65,536; 256 unique seeds and 16,777,216 shots total. No failures, timeouts or incomplete points. Smoke shots are excluded.
- Stim 1.16.0 and PyMatching 2.3.1. Logical failures mean incorrect decoded observables for the entire d-round experiment. Intervals are two-sided Wilson 95%. They are not per-round rates.
- Decoder weights use the declared disjoint-channel DEM approximation; circuit sampling retains the configured Pauli channels. Physical loss, leakage and coherent non-Pauli effects are excluded from these logical rates.
- Identical fixed noise parameters across all points; these are illustrative research parameters, not device calibration. This single-noise-setting study does not estimate a threshold.
- Fixed home grid 19x19 at 8 um; QEC gate array 32x32 pairs, 8/6 um pitch, pair separation 2 um; radius 4.6 um; common 256x256 um readout at (0,380) um. Flexible AOD capacities unbounded. This compares architecture/compiler combinations, not two algorithms on an identical Device.

[Approved configuration](../../experiments/surface_memory_20261023/campaign.json) | [Complete audit](../../artifacts/surface-memory-campaign/completed/campaign/completion-audit.json) | [Manifest](../../artifacts/surface-memory-campaign/completed/campaign/manifest.json) | [Raw summary](../../artifacts/surface-memory-campaign/completed/campaign/summary.json) | [CSV](../../artifacts/surface-memory-campaign/completed/campaign/summary.csv)

![Comparison](../../artifacts/surface-memory-campaign/comparison.png)

## Decoded logical results

All probabilities and interval endpoints in this table are percentages. Each row has N=1,048,576.

| d | Basis | Backend | Failures | Logical rate (%) | Wilson 95% (%) |
|---:|:---:|---|---:|---:|---|
| 3 | X | nonzoned | 2,747 | 0.261974 | [0.252371, 0.271942] |
| 3 | X | qec | 4,491 | 0.428295 | [0.415976, 0.440977] |
| 3 | Z | nonzoned | 1,848 | 0.176239 | [0.168391, 0.184452] |
| 3 | Z | qec | 2,559 | 0.244045 | [0.234782, 0.253673] |
| 5 | X | nonzoned | 1,007 | 0.096035 | [0.090286, 0.102149] |
| 5 | X | qec | 2,395 | 0.228405 | [0.219449, 0.237726] |
| 5 | Z | nonzoned | 644 | 0.061417 | [0.056854, 0.066345] |
| 5 | Z | qec | 1,284 | 0.122452 | [0.115938, 0.129331] |
| 7 | X | nonzoned | 316 | 0.030136 | [0.026992, 0.033646] |
| 7 | X | qec | 1,351 | 0.128841 | [0.122156, 0.135892] |
| 7 | Z | nonzoned | 157 | 0.014973 | [0.012807, 0.017505] |
| 7 | Z | qec | 571 | 0.054455 | [0.050169, 0.059107] |
| 9 | X | nonzoned | 85 | 0.008106 | [0.006556, 0.010022] |
| 9 | X | qec | 812 | 0.077438 | [0.072294, 0.082949] |
| 9 | Z | nonzoned | 34 | 0.003242 | [0.002320, 0.004531] |
| 9 | Z | qec | 316 | 0.030136 | [0.026992, 0.033646] |

## Compilation and physical timing

Compiler time is one observed compilation, not a repeated timing benchmark. Transport sums Load/Move/Store durations; timeline occupancy counts their union. They happen to be equal for every result here. Loads/stores count atom transfers, not batches.

| Point | Compile (s) | Program incl. feedback (ms) | Transport sum / occupancy (ms) | Move (ms) | Load / Store (ms) | Atom loads / stores |
|---|---:|---:|---:|---:|---:|---:|
| d3-x-nonzoned | 2.091 | 4.516 | 4.268 / 4.268 | 3.468 | 0.400 / 0.400 | 177 / 177 |
| d3-x-qec | 6.010 | 20.737 | 20.489 / 20.489 | 18.489 | 1.000 / 1.000 | 321 / 321 |
| d3-z-nonzoned | 2.246 | 3.725 | 3.504 / 3.504 | 2.724 | 0.390 / 0.390 | 177 / 177 |
| d3-z-qec | 6.202 | 19.946 | 19.725 / 19.725 | 17.745 | 0.990 / 0.990 | 321 / 321 |
| d5-x-nonzoned | 9.553 | 6.926 | 6.604 / 6.604 | 5.284 | 0.660 / 0.660 | 945 / 945 |
| d5-x-qec | 71.363 | 49.004 | 48.682 / 48.682 | 43.562 | 2.560 / 2.560 | 1745 / 1745 |
| d5-z-nonzoned | 10.601 | 6.135 | 5.840 / 5.840 | 4.540 | 0.650 / 0.650 | 945 / 945 |
| d5-z-qec | 71.829 | 48.213 | 47.918 / 47.918 | 42.818 | 2.550 / 2.550 | 1745 / 1745 |
| d7-x-nonzoned | 27.510 | 9.336 | 8.940 / 8.940 | 7.100 | 0.920 / 0.920 | 2737 / 2737 |
| d7-x-qec | 331.852 | 93.137 | 92.741 / 92.741 | 81.521 | 5.610 / 5.610 | 5089 / 5089 |
| d7-z-nonzoned | 30.257 | 8.545 | 8.176 / 8.176 | 6.356 | 0.910 / 0.910 | 2737 / 2737 |
| d7-z-qec | 333.926 | 92.346 | 91.977 / 91.977 | 80.777 | 5.600 / 5.600 | 5089 / 5089 |
| d9-x-nonzoned | 63.084 | 11.747 | 11.277 / 11.277 | 8.917 | 1.180 / 1.180 | 5985 / 5985 |
| d9-x-qec | 1090.017 | 163.444 | 162.974 / 162.974 | 140.814 | 11.080 / 11.080 | 11169 / 11169 |
| d9-z-nonzoned | 69.101 | 10.956 | 10.513 / 10.513 | 8.173 | 1.170 / 1.170 | 5985 / 5985 |
| d9-z-qec | 1089.105 | 162.653 | 162.210 / 162.210 | 140.070 | 11.070 / 11.070 | 11169 / 11169 |

## Independent physical loss

Model-derived probabilities, not sampled logical failures. No shot-count confidence interval is attached. Data/ancilla columns are their mean per-atom probabilities. The maximum row also identifies the atom and role.

| Point | Mean (%) | Maximum (%) | Max atom / role | Expected lost atoms | Data mean (%) | Ancilla mean (%) |
|---|---:|---:|---|---:|---:|---:|
| d3-x-nonzoned | 0.384059 | 0.841505 | 12 / ancilla | 0.065290 | 0.204701 | 0.585837 |
| d3-x-qec | 0.831707 | 1.209673 | 7 / ancilla | 0.141390 | 0.704952 | 0.974306 |
| d3-z-nonzoned | 0.385826 | 0.843488 | 12 / ancilla | 0.065590 | 0.206713 | 0.587329 |
| d3-z-qec | 0.833466 | 1.210661 | 7 / ancilla | 0.141689 | 0.706954 | 0.975791 |
| d5-x-nonzoned | 0.656687 | 1.398571 | 19 / ancilla | 0.321777 | 0.297896 | 1.030428 |
| d5-x-qec | 1.497035 | 2.011664 | 8 / ancilla | 0.733547 | 1.288969 | 1.713770 |
| d5-z-nonzoned | 0.659433 | 1.400543 | 19 / ancilla | 0.323122 | 0.300903 | 1.032902 |
| d5-z-qec | 1.499758 | 2.012644 | 8 / ancilla | 0.734881 | 1.291947 | 1.716228 |
| d7-x-nonzoned | 0.924514 | 1.952507 | 26 / ancilla | 0.896778 | 0.389213 | 1.470967 |
| d7-x-qec | 2.103271 | 2.822863 | 11 / ancilla | 2.040173 | 1.815360 | 2.397180 |
| d7-z-nonzoned | 0.928241 | 1.954467 | 26 / ancilla | 0.900394 | 0.393213 | 1.474416 |
| d7-z-qec | 2.106956 | 2.823835 | 11 / ancilla | 2.043747 | 1.819305 | 2.400599 |
| d9-x-nonzoned | 1.187247 | 2.503331 | 33 / ancilla | 1.911467 | 0.479822 | 1.903514 |
| d9-x-qec | 2.647648 | 3.662974 | 14 / ancilla | 4.262714 | 2.283373 | 3.016477 |
| d9-z-nonzoned | 1.191952 | 2.505280 | 33 / ancilla | 1.919043 | 0.484814 | 1.907930 |
| d9-z-qec | 2.652289 | 3.663937 | 14 / ancilla | 4.270186 | 2.288281 | 3.020848 |

## Mean-loss source attribution

Entries are percentage-point contributions to mean per-atom loss, with prior survival included. Simultaneous losses share the increment by hazard. Rows sum to mean loss. Configured CZ loss and other loss are zero.

| Point | Load (pp) | Store (pp) | Move (pp) | Residence (pp) |
|---|---:|---:|---:|---:|
| d3-x-nonzoned | 0.103885 | 0.103857 | 0.174630 | 0.001688 |
| d3-x-qec | 0.188066 | 0.188002 | 0.451227 | 0.004413 |
| d3-z-nonzoned | 0.103885 | 0.103857 | 0.176389 | 0.001696 |
| d3-z-qec | 0.188066 | 0.188001 | 0.452978 | 0.004421 |
| d5-x-nonzoned | 0.192041 | 0.191995 | 0.270004 | 0.002647 |
| d5-x-qec | 0.353462 | 0.353348 | 0.782419 | 0.007806 |
| d5-z-nonzoned | 0.192041 | 0.191994 | 0.272742 | 0.002656 |
| d5-z-qec | 0.353462 | 0.353348 | 0.785134 | 0.007814 |
| d7-x-nonzoned | 0.280419 | 0.280354 | 0.360143 | 0.003598 |
| d7-x-qec | 0.519080 | 0.518921 | 1.054428 | 0.010842 |
| d7-z-nonzoned | 0.280419 | 0.280354 | 0.363863 | 0.003606 |
| d7-z-qec | 0.519080 | 0.518921 | 1.058105 | 0.010850 |
| d9-x-nonzoned | 0.368725 | 0.368643 | 0.445338 | 0.004541 |
| d9-x-qec | 0.684455 | 0.684259 | 1.265878 | 0.013056 |
| d9-z-nonzoned | 0.368725 | 0.368642 | 0.450036 | 0.004549 |
| d9-z-qec | 0.684455 | 0.684258 | 1.270511 | 0.013064 |

## Maximum-loss atom attribution

The same decomposition for each maximum-loss atom (percentage points).

| Point | Atom | Load (pp) | Store (pp) | Move (pp) | Residence (pp) |
|---|---:|---:|---:|---:|---:|
| d3-x-nonzoned | 12 | 0.268992 | 0.268934 | 0.300723 | 0.002856 |
| d3-x-qec | 7 | 0.268493 | 0.268399 | 0.666314 | 0.006467 |
| d3-z-nonzoned | 12 | 0.268992 | 0.268934 | 0.302706 | 0.002856 |
| d3-z-qec | 7 | 0.268493 | 0.268399 | 0.667302 | 0.006467 |
| d5-x-nonzoned | 19 | 0.447061 | 0.446965 | 0.499797 | 0.004747 |
| d5-x-qec | 8 | 0.445675 | 0.445518 | 1.109693 | 0.010778 |
| d5-z-nonzoned | 19 | 0.447061 | 0.446965 | 0.501769 | 0.004747 |
| d5-z-qec | 8 | 0.445675 | 0.445518 | 1.110673 | 0.010778 |
| d7-x-nonzoned | 26 | 0.624129 | 0.623996 | 0.697753 | 0.006628 |
| d7-x-qec | 11 | 0.621367 | 0.621147 | 1.565168 | 0.015182 |
| d7-z-nonzoned | 26 | 0.624129 | 0.623996 | 0.699714 | 0.006628 |
| d7-z-qec | 11 | 0.621367 | 0.621146 | 1.566140 | 0.015182 |
| d9-x-nonzoned | 33 | 0.800203 | 0.800033 | 0.894597 | 0.008498 |
| d9-x-qec | 14 | 0.795458 | 0.795171 | 2.052427 | 0.019918 |
| d9-z-nonzoned | 33 | 0.800203 | 0.800033 | 0.896547 | 0.008498 |
| d9-z-qec | 14 | 0.795458 | 0.795171 | 2.053390 | 0.019918 |

## Interpretation

- Under these fixed configurations, nonzoned has lower decoded X/Z logical failure rates at every tested distance. Both curves fall as distance grows; mean per-atom physical loss rises with the longer experiment.
- At d9, QEC/nonzoned logical-rate ratios are 812/85 = 9.55 for X and 316/34 = 9.29 for Z. This is a configuration-specific observation, not an algorithm-independent advantage.
- At d9 Z, transport occupies 10.513 ms for nonzoned versus 162.210 ms for QEC. Atom loads/stores are 5,985 each versus 11,169 each. The QEC result therefore has substantially more motion time and transfer opportunities.
- At d9 Z, mean loss is 1.191952% versus 2.652289%; expected lost atoms are 1.919043 versus 4.270186. These losses are not propagated through the decoder. The lower Pauli-only logical rate cannot be taken as full loss-aware memory performance.
- No causal error-budget ablation was run. Motion/exposure statistics are consistent with the observed difference, but do not isolate each noise source's contribution to logical failure.

## Verification and retained evidence

All 16 saved results were independently revalidated against their embedded DAG/Device and replayed to the fixed initial homes. All 256 stage-result hashes, seeds, shot counts and failure sums were checked; Wilson intervals were recomputed with SciPy. Per-atom loss was independently recomputed from survival products and source sums reconciled. Source, input and harness hashes match the original manifest. No compilation or sampling was repeated during this completion audit.

Manifest SHA-256: `ae7b707ea3be3b5f3184bb2bf893be21dde7a71094f87e897280ec1dc2f3c2c1`.

Raw server originals remain under `/home/yyq/nadit-experiments/surface-memory-ea8c348-large-zones/`. The local archive, all inputs, validated results, Stim/noise exports, stage logs and shard records are retained under `modules/physical_compiler/artifacts/surface-memory-campaign/completed/`. The archive checksum was verified after transfer.

The transport connection outage affected monitoring only; the server completed all work independently.
