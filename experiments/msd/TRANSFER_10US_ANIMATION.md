# 10 us transfers: complete raw-T injection and growth replay

MSD standard/2 changes LOAD and STORE from 100 us to **10 us each**. Measurement
remains 100 us, classical processing zero, movement 1 us/um, and all remaining
layout, capability and noise parameters are unchanged. The default remains three
d3 injection rounds followed by d ordinary target rounds including deformation
(zero growth rounds at target d3). No SE-round optimization is included here.

## Complete animation

Open the self-contained file:

`modules/physical_compiler/artifacts/msd-small-growth-transfer10-20261024/viewer/index.html`

The viewer starts with d5; its trace selector also offers d7 and d3. Play shows
the full conditional accepted preparation path: all injection rounds, growth,
ordinary SE, reset, gates, transfers, travel and readout. All six patches' atoms
remain in the physical world. This is one resource preparation, not a complete
15-to-1 factory cycle. There are no sampled rejection/retry events or invented
measurement values. It is physical-action replay, not a quantum-state animation.

Default playback preserves relative action durations over a 30-second viewing
period. Direct endpoint interpolation is selected instead of decorative lane
paths. Neither display setting changes recorded physical times. Play/pause,
step/time seeking, zoom/pan, Present, and the action schedule remain available.

| Target d | Full accepted path | Steps | World atoms | Injection acceptance | Expected time including injection retries |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3 | 2.374452 ms | 202 | 102 | 78.3391% | 3.030993 ms |
| 5 | 8.952986 ms | 601 | 294 | 77.9108% | 10.257715 ms |
| 7 | 11.250621 ms | 733 | 582 | 77.9108% | 12.555350 ms |

The animation duration is `injection attempt + growth`, whereas the expected
time is `injection attempt / acceptance + growth`. Faster transfers also reduce
idle/transport noise exposure under the **same** noise parameters, so acceptance
was recalculated rather than copied from the 100 us result. Loss and output
logical-error qualification remain outside this acceptance calculation.

For d5, the injection/growth boundary is at **4601.898464 us**. The first target
readout is at **5217.715954 to 5317.715954 us**, and completion is at
**8952.985916 us**. The complete original programs and per-stage fingerprints are
preserved in the viewer sidecar. No intermediate movement steps are dropped.

## Reproduce

Use the existing Python environment and run from the repository root:

```powershell
$env:PYTHONPATH="$PWD\modules\physical_compiler\src;$PWD"
python -m experiments.msd.small_injection_growth --output modules/physical_compiler/artifacts/my-transfer10-run
python -m experiments.analysis.view_raw_t_growth modules/physical_compiler/artifacts/my-transfer10-run --output modules/physical_compiler/artifacts/my-transfer10-run/viewer/index.html
```

The first output directory must be new. The export reads and revalidates saved
segments, checks stage-world continuity, unique result IDs, recorded duration,
and complete concatenated replay equality. Structural zero records used by the
physical validator are not passed to the viewer as observations.

The [results](results/small-growth-transfer10-20261024.json) and
[animation verification](results/small-growth-transfer10-animation-verification-20261024.json)
are tracked. Full HTML, trace sidecar, worlds and probability caches remain local
generated artifacts. The runtime source snapshot is
`4b5c39f4a0f0d81a02f09ad59fbda724b4309ce84366e37ab78eb96f0c8312fc`.

Verification: 20 baseline standard tests; the new 10 us assertion failed before
the change; **229 tests passed** after the change across MSD and generic surface
components. Strict mypy passed on both changed runtime/export modules. Saved
trace checks confirmed every LOAD/STORE is 10 us, every readout is 100 us, no
occupied-intersection observations, and unchanged noise. Browser playback and d5
growth readout were inspected. The shared viewer and physical compiler were not
modified; the experiment export selects its presentation defaults.

The [100 us report](SMALL_INJECTION_GROWTH.md) remains historical; its source
revision is `75fdb85`. Do not compare its cached timing/probability entries as if
they belonged to standard/2.
