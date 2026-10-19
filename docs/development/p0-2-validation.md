# P0-2 toolchain and test collection validation

Date: 2026-10-19. Base: `develop@20e2edc1ecc79dd660275d5f10b3347ea5e5c843`, after PR #5 was merged with a merge commit. Branch: `codex/p0-2-toolchain`.

P0-2 adds development tools, reproducible dependency resolution, pytest collection, and a separate location for historical validation scripts. It preserves all existing test methods and production logic. Missing artifacts remain failures until P0-3; this is not a green-suite claim.

## Reproduction

From a clean checkout with uv installed, create a new Python 3.13 environment:

```text
uv sync --frozen --python 3.13 --extra dev --extra enola
uv run --frozen pytest --collect-only -q
uv run --frozen pytest -q
uv run --frozen python scripts/check.py --suite frontend --suite qec --suite integration
```

The completed full run used Windows, CPython 3.13.16, uv 0.13.1, pytest 9.1.1, networkx 3.5, rustworkx 0.17.1, and numpy 2.3.5. The virtual environment was newly created from `uv.lock`, with no historical artifacts supplied. `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `MKL_NUM_THREADS` were set to 1. Full-suite elapsed time was 159.33 seconds.

## Collection and outcomes

| Suite | Collected | Passed | Skipped | Failed | Setup errors |
|---|---:|---:|---:|---:|---:|
| backend | 115 | 115 | 0 | 0 | 0 |
| device | 91 | 90 | 0 | 1 | 0 |
| frontend | 53 | 53 | 0 | 0 | 0 |
| integration | 2 | 2 | 0 | 0 | 0 |
| qec | 64 | 64 | 0 | 0 | 0 |
| runtime | 152 | 136 | 3 | 5 | 8 |
| tooling | 30 | 30 | 0 | 0 | 0 |
| validation | 171 | 134 | 0 | 2 | 35 |
| **Total** | **678** | **624** | **3** | **8** | **43** |

Pytest additionally reported 184 passing subtests and one warning. Those subtests are not added to the 678 collected primary tests.

The supplied specification's 628 count is not the complete collection count. Independent unittest discovery also collects 678 occurrences. There are seven existing repeated occurrences of imported `TestCase` methods: three `PipelineTests` methods imported into `test_component_pipeline.py`, and four `PoolTests` methods imported into `test_factory_ports.py`. In addition, 43 methods cannot run because their six class fixtures fail in `setUpClass`. These distinctions account numerically for `678 - 7 - 43 = 628`; the complete collection and outcome table above is the reproducible baseline for this PR. No methods or imported classes were removed to force a particular count.

The original pytest path configuration was insufficient for existing bare imports. Added `tests/qec` and `tests/validation` to resolve their sibling helpers, plus `tests/backend` before `tests/qec` so `from test_physical_dag import fixture_instance` selects the backend helper. Importlib mode keeps the collected backend/QEC modules distinct. No test package files or test renames were needed.

## The 14 existing missing-artifact sites

| Existing failing method or class setup | Pytest outcome | Missing input |
|---|---|---|
| `device/test_inventory.py::InventoryTests::test_recorded_real_algorithm_entry_still_valid_without_rerunning_placer` | 1 failed | `knowledge/roles/R1/evidence/T103/full-shor-entry/patch-placement.json` |
| `runtime/test_canonical_cz_recipe.py::CanonicalCZRecipeTests.setUpClass` | 2 errors | `artifacts/demos/aod-held-cz-20261007/CZ/physical-plan.json` |
| `runtime/test_logical_scheduler.py::LogicalSchedulerTests::test_classical_ready_condition_and_skip` | 1 failed | `knowledge/roles/R5/dag-scheduler-example.json` |
| `runtime/test_logical_scheduler.py::LogicalSchedulerTests::test_cycle_and_missing_producer_edges_rejected` | 1 failed | same scheduler input |
| `runtime/test_logical_scheduler.py::LogicalSchedulerTests::test_independent_SE_ready_selected_together_then_CX` | 1 failed | same scheduler input |
| `runtime/test_logical_scheduler.py::LogicalSchedulerTests::test_shared_resource_defers_second_without_global_patch_barrier` | 1 failed | same scheduler input |
| `runtime/test_logical_scheduler.py::LogicalSchedulerTests::test_stale_or_modified_proposal_is_atomic` | 1 failed | same scheduler input |
| `runtime/test_producer_recipe.py::ProducerRecipeTests.setUpClass` | 4 errors | `artifacts/demos/joint-factory-repaired-20261008/factory.initialize/physical-plan.json` |
| `runtime/test_shor17_demo_intake.py::Shor17DemoIntakeTests.setUpClass` | 2 errors | `artifacts/demos/shor17-four-factory-layout-20261009/layout.json` |
| `validation/test_factory_stage.py::FrozenFactorySourceTests.setUpClass` | 4 errors | `scripts/outputs/T704/server/20261006T152602272401Z-r4-factory-first-stage-205/result/examples/atom/t405/factory-stage-v1/input.json.gz` |
| `validation/test_hierarchical.py::GraphAndScheduleTests::test_published_examples` | 1 failed | `knowledge/roles/R6/hierarchical-minimal.json` |
| `validation/test_hierarchical.py::EntryAndGateTests::test_H07_unused_real_placer_result` | 1 failed | `knowledge/roles/R6/evidence/T605/frontend-placement-inputs.json.gz` |
| `validation/test_resources.py::ResourceBoundaryTests.setUpClass` | 11 errors | `examples/atom/t405/resource-world-server-v1/world.json.gz` |
| `validation/test_strategies.py::RealStrategyMutations.setUpClass` | 20 errors | `knowledge/roles/R6/evidence/T604/inputs.json.gz` |

The environment-sensitive `tooling/test_tooling.py::ToolingTests::test_background_job_logs_and_budget_exhaustion` passed on this Windows host. The specification describes a container failure, so it is not asserted that this test must fail on every host. Its assertions and default inclusion are unchanged.

## Existing skips

No skips were added. The three existing skipped occurrences are:

- `runtime/test_component_pipeline.py::PipelineTests::test_attempt_scenarios_bind_physical_terminal_bits_with_fresh_epochs`: actual R4 world artifact not present.
- `runtime/test_pipeline.py::PipelineTests::test_attempt_scenarios_bind_physical_terminal_bits_with_fresh_epochs`: actual R4 world artifact not present.
- `runtime/test_factory_fleet.py::FactoryFleetTests::test_real_consumer_suffix_completes_while_peer_inventory_remains_live`: frozen qualified component package not installed.

## Other verification and limits

- CPython 3.12.14: `scripts/check.py` completed frontend 53, qec 64, and integration 2 tests; all 119 passed.
- A full 3.12 run before the final backend import-path correction completed with 623 passed, 3 skipped, 9 failed, and 43 errors. The extra failure was the incorrect `test_physical_dag` import, which was corrected and its focused test passed. A subsequent full 3.12 process exited with Windows access violation `0xC0000005` while in `frontend/program.py::precedes`; no final result was produced. Its cause is unresolved. The 3.13 full run above is complete, but it does not establish that the 3.12 crash is fixed.
- Ruff check and format check, pre-commit configuration validation, whitespace/end-of-file hooks on the changed configuration and documentation, `uv lock --check`, and `git diff --check` passed. The Ruff hooks had no Python files to check in that file list; legacy Python directories remain excluded.
- Windows initially converted vendored Enola LF files to CRLF, causing byte-pin failures. `.gitattributes` disables text conversion for `third_party/enola/**`. All 15 pinned source files and the dependency lock match their original hashes; a fresh checkout-index probe with `core.autocrlf=true` preserved all 42 tracked vendor files byte-for-byte. Neither vendor blobs nor hash constants were changed.
- Exactly 18 non-test scripts moved via `git mv` into `scripts/legacy_validation/`. Twelve retain their original content; six only adjust paths affected by the move. All parse as Python. The original remote-launch guard remains disabled.
- Existing runtime tests generated `examples/atom/t405/restore-author-*` evidence directories. This run's outputs were moved to local Git metadata after testing and were not committed. Test-output isolation remains a P0-3 task; cleanup does not establish hermetic tests.
- `src/na_pipeline/` and all `test_*.py` files are unchanged relative to the base commit. This PR adds no CI workflow and does not implement P0-3 or P0-4.
