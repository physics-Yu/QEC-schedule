# Complete d9 and d11 surface component production

Both distances now have concrete providers, logical translation declarations,
and generated artifacts for all **16 currently supported protocols**. Production
uses the established MSD standard/2: LOAD/STORE 10 us, measurement 100 us, result
processing zero, unchanged geometry/noise, and six patches in one device world.

| Distance | Data | Syndrome | Atoms per patch | Complete world | Catalog entries |
| --- | ---: | ---: | ---: | ---: | ---: |
| 9 | 81 | 80 | 161 | 966 | 16 |
| 11 | 121 | 120 | 241 | 1446 | 16 |

## Entry points and output

```python
from modules.codes.rotated_surface_d9.components import get_component as d9
from modules.codes.rotated_surface_d11.components import get_component as d11

se9 = d9("se_round")
s11 = d11("logical_s")
raw11 = d11("raw_t")
postselected11 = d11("raw_t_postselection")
cnot9 = d9("transversal_cnot")
```

Single-block compilation and binding retain the shared API. CNOT compiles two
explicit patch geometries and binds both participants. H returns its actual
permuted carrier binding. The postselected preparation keeps the separate
injection event, conditional growth invocation, and decoded Pauli-frame handoff.

Artifacts are in:

`modules/physical_compiler/artifacts/surface-d9-d11-components-20261024/`

- `d9/index.html` and `d11/index.html`: links to every component's atom animation.
- `d*/<component>/source.qasm3`: concrete source circuit.
- `template.json`: complete relative atom template, source/device/compiler hashes,
  correction terms, port roles and output permutation.
- `expansion.json`: actual bound world, atom program, native DAG, measurement IDs,
  pending values, correction relations and exit bindings.
- `result.json`: semantically validated physical result, with explicitly labeled
  structural measurement placeholders rather than sampled quantum outcomes.
- `actions.atom.txt` and `index.html`: inspectable transport/gates and playback.
- `raw_t_postselection/`: separate injection/growth stages, protocol identity,
  conditional-path animation, and actual-source binary acceptance cache.
- Root `manifest.json`, `source-snapshot.json`, `noise.json`, and `verification.json`:
  complete production provenance and saved-result readback checks.

There are **56 independently saved physical results**: 15 ordinary entries plus
12 postselection stages at d9, and 15 plus 14 stages at d11. Each stage keeps the
entire occupied world. Full generated artifacts remain outside Git; the compact
[resource results](results/d9-d11-components-20261024.json) are tracked.

## Compiled resource times

Times are microseconds for a component invocation in the selected fixed layout.
They include the emitted transport and retained-atom readout. They are not
optimized lower bounds or a complete factory cycle.

| Component | d9 (us) | d11 (us) |
| --- | ---: | ---: |
| initialize_0 | 1033.817490 | 1113.817490 |
| initialize_plus | 1035.817490 | 1115.817490 |
| se_round | 1028.817490 | 1108.817490 |
| logical_x | 1.000000 | 1.000000 |
| logical_y | 3.000000 | 3.000000 |
| logical_z | 1.000000 | 1.000000 |
| logical_s | 9157.923396 | 15601.455922 |
| logical_sdag | 9157.923396 | 15601.455922 |
| prepare_y | 10193.740886 | 16717.273413 |
| logical_mx | 562.000000 | 642.000000 |
| logical_mz | 560.000000 | 640.000000 |
| raw_t | 10805.656902 | 13743.291883 |
| logical_h | 11245.880746 | 20100.274945 |
| transversal_cnot | 488.500000 | 568.500000 |
| grow_from_d3 | 1035.817490 | 1115.817490 |
| raw_t_postselection, conditional accepted path | 13868.255878 | 16805.890859 |

S/Sdag use the actual mid-cycle fold construction. H includes the existing
conservative one-buffer carrier rotation; its QASM alone does not represent
that transport. Their larger times are not substituted transversal-gate costs.
`grow_from_d3` is the first enlargement/SE round, not the full growth history.

Raw-T uses one fixed-d3 injection SE followed by d ordinary target rounds.
Postselection uses three fixed-d3 rounds, then conditionally performs d ordinary
target rounds including deformation. The resulting measurement counts are:

| Distance | raw_t results | Postselection-path results | Injection detectors |
| --- | ---: | ---: | ---: |
| 9 | 728 | 744 | 20 |
| 11 | 1328 | 1344 | 20 |

Both actual injection traces give acceptance **0.7791076605693193** under the
unchanged illustrative noise profile. This is computed from each trace, not
assigned from d3. Growth checks are decoded and never postselected. The table
lists the successful conditional path; it excludes failed injection retries.
Expected preparation cost remains `injection_cost / acceptance + growth_cost`.

## Verification and testing workflow

The `83ed2a8` test-tier workflow was integrated into this experiment branch. The
existing uncommitted agent guidance was preserved exactly within the updated
file, with both a recovery stash and a local backup retained. The only textual
integration conflict was the changelog; both sets of entries were retained.
Ownership/consumer mappings were extended for the already-present logical/MSD
tests, generic surface codes, new providers, and viewer export consumers.

- Related fast baseline: 372 passed; final component iteration: **380 passed**.
- Pre-commit `python -m tools.testing.run check`: **fast 949 passed, slow 2418
  passed, bench 14 not run**; no failures or skips. Total elapsed: 480.46 seconds.
- Slowest cases: shared-AOD two-factory raw wave 44.75 s; real noisy factory
  canonicalization boundary 39.79 s. The new d11 raw channel witness took 5.03 s.
- Bounded independent X/Y/Z preparation-channel tests cover d9/d11, including
  actual raw seed T via channel witnesses, real S/Sdag action and output-sector
  equations, and both logical CNOT axes.
- Saved-result verification checks every complete-world trajectory, template and
  source hash, unobserved result semantics, 10 us transfer timing, H carrier
  endpoints/canonical role mapping, and analytic interaction/result counts.

See [tier counts](results/d9-d11-test-tiers-20261024.json) and
[saved-artifact verification](results/d9-d11-components-verification-20261024.json).
The runtime source snapshot is
`ea0b714be73ef4c818577fbf0e2f36a78fc0aa7f4a84684363e073e881dc1d8f`.

## Reproduce

With the existing Python 3.12 environment, from the repository root:

```powershell
$env:PYTHONPATH="$PWD\modules\physical_compiler\src;$PWD"
python -m experiments.msd.build_components --distances 9 11 --output modules/physical_compiler/artifacts/my-d9-d11-components
python -m experiments.analysis.verify_surface_components modules/physical_compiler/artifacts/my-d9-d11-components --output modules/physical_compiler/artifacts/my-d9-d11-components/verification.json
```

The output directory must be new. Production freezes runtime source fingerprints
and checks them again on completion. This explicitly requested component build
is separate from running the excluded bench pytest tier.

The catalog covers the existing family, not invented direct logical T/TDG or
mixed-distance CNOT gates. Logical translation declarations retain their existing
intended operation names and do not claim a complete d9/d11 factory adapter.
Generic joint preparation-class distributions, global frame propagation, calibrated
decoded output LER, stochastic distillation execution and hardware execution remain
outside this component delivery. Growth retains the documented phenomenological
MWPM/open-boundary limitations; the generated acceptance cache is not a quality
certificate.
