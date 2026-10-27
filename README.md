# QEC-schedule / NADiT

[![Physical compiler CI](https://github.com/physics-Yu/QEC-schedule/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/physics-Yu/QEC-schedule/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Research software for compiling quantum error-correction circuits into neutral-atom operations and studying their scheduling and resource costs.

The implementation is called **NADiT**. This repository publishes its source, experimental snapshots and research notes. It is a research prototype with working compilation and analysis tools; a general logical-circuit-to-hardware execution system is still under development.

## Purpose

The central question is how a QEC circuit's dependencies interact with neutral-atom hardware: shared AOD rows and columns, atom transport, trapping sites, gate illumination, measurement resources and classical feedback.

We want to make those assumptions explicit, produce inspectable schedules, and compare execution time, transport, waiting and resource use. Magic-state factories provide a concrete workload for studying preparation, rejection, retries and shared-device contention. The longer-term direction is a compiler connected to a configurable digital twin.

## Three modules

| Module | Responsibility | Current boundary |
| --- | --- | --- |
| [Physical compiler](modules/physical_compiler/README.md) | Translate physical QASM into a native dependency graph, then schedule atom loading, motion, storage, gates and readout under a Device model. | Installable Python package and `nadit` CLI; compiles one selected measurement case. |
| [Code library](modules/codes/README.md) | Define codes, physical layouts and reusable QEC components: initialization, syndrome extraction, logical operations, raw-T preparation and code growth. | Rotated surface-code implementations and explicit component contracts; support depends on the operation and code-distance provider. |
| [Logical compiler](modules/logical_compiler/README.md) | Translate a supported logical QASM profile and coordinate code-owned components, factory protocols and resource accounting. | Logical translation and explicit factory workflows exist; general QASM-to-executable-component binding remains incomplete. |

The intended flow is:

```text
Logical circuit -> code-owned QEC components -> physical DAG -> atom-action program
                                      Device constraints -> scheduling and transport
```

Parts of this chain already work through explicit APIs. The diagram is not a claim that arbitrary logical QASM runs end to end.

## What currently works

- **Physical compilation:** OpenQASM 2/3 parsing and native translation; Search Smarter and ENOLA-inspired nonzoned strategies; configurable geometry, capacities, transport rules and readout. Motion support depends on the selected strategy.
- **Case-driven feedback:** supplied or seeded measurement outcomes select conditional operations while retaining measurement identity and feedback timing. These outcomes are compilation inputs, not hardware observations.
- **Inspectable outputs:** self-contained result JSON, Atom IR, independent semantic validation, state replay and offline HTML viewers.
- **QEC components:** parameterized odd-distance rotated surface-code building blocks, including d3 injection followed by accepted-only growth; dedicated d9/d11 component exports.
- **Factory studies:** explicit rejection/retry workflows, compatible component batches on a shared AOD, calibration caches and fast cost estimates. Component reuse can avoid repeated native lowering while world-dependent scheduling remains necessary.
- **Selected simulation and cost paths:** operation/transport/waiting accounting, physical-noise estimates, and optional Stim/PyMatching surface-memory studies. Each path has its own stated assumptions and coverage.

See the [architecture](architecture.md), [configuration reference](modules/physical_compiler/docs/configuration-reference.md), [MSD experiments](experiments/msd/README.md) and [Stim memory method](modules/physical_compiler/docs/stim-memory.md) for details.

## Install and run a small example

Use **Python 3.12**. Run these commands from the repository root in a fresh virtual environment:

```sh
git clone --depth 1 --single-branch https://github.com/physics-Yu/QEC-schedule.git
cd QEC-schedule
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux/macOS, or `.venv\Scripts\Activate.ps1` in PowerShell. Then:

```sh
python -m pip install -e ./modules/physical_compiler
python -c "from pathlib import Path; Path('build').mkdir(exist_ok=True)"
nadit compile modules/physical_compiler/examples/jobs/pair.json --validate -o build/pair-result.json
nadit view build/pair-result.json -o build/pair-viewer.html
```

Open `build/pair-viewer.html` in a browser. This small feedback example exercises the physical compiler, result validator and replay viewer; it is not a complete QEC or distillation experiment. Outputs under `build/` are ignored by Git.

Optional simulation dependencies:

```sh
python -m pip install -e "./modules/physical_compiler[simulation]"
```

Only `physical_compiler` is currently packaged for installation. Logical/code/experiment examples still require the source checkout and, for some entry points, an explicit `PYTHONPATH`. Follow their module instructions; do not assume every script works from an arbitrary directory. There is no unified top-level package yet.

## Tests and CI

The [CI workflow](.github/workflows/ci.yml) runs on pushes and pull requests with Ubuntu and Python 3.12. It installs the physical package, runs its **fast tier**, and compiles, validates and exports the small example above.

To run the same test scope locally:

```sh
python -m pip install "pytest>=8.3,<10"
python -m pytest -c pytest.ini modules/physical_compiler/tests --test-tier fast -q
```

**A green badge covers this scope only.** It does not cover the complete code library, logical compiler, MSD campaigns, optional simulation/hsim suites, slow integration tests or expensive benchmarks. The repository has many parameterized test files; file count is not test-case count. GitHub Actions logs provide the actual executed and deselected counts for each run.

The repository's broader test policy distinguishes `fast`, `slow` and `bench`. See [testing instructions](docs/testing.md) and [test ownership](tests/test-map.json) before selecting a larger run; the hsim path needs its separately configured dependency. Local test reports are evidence for their recorded source, not proof that another branch or snapshot is green.

## Important limitations

1. **The end-to-end logical pipeline is incomplete.** General logical QASM translation is not yet connected to automatic binding and physical execution of every component. Existing factory entry points cover explicit protocols.
2. **Fast estimates are model-dependent.** Cached component/frontier costs require matching geometry, resources and calibration context. They do not provide fresh atom-level validation for each estimated case. More factories do not automatically imply proportional throughput.
3. **Execution and fault tolerance are separate claims.** A legal schedule or successful fake-measurement replay is not hardware execution, decoded logical success, or a fault-tolerance proof. Selected Stim memory studies have bounded noise coverage; physical loss and leakage are reported separately rather than automatically decoded.
4. **Engineering validation is still partial.** CI starts with the physical compiler's fast checks and a CLI smoke example. A clean-install test for the entire repository and broader integration coverage remain work to do.
5. **Packaging and repository organization need consolidation.** Cross-module imports still depend on the checkout layout. Research notes and provenance files coexist with code at the root. Several remote branches are workspace snapshots, including unfinished changes, rather than reviewed feature releases.
6. **Old large artifacts remain in Git history.** Removing an archive from the current tree does not remove its historical blob. A shallow clone reduces the initial download; history cleanup has not been performed. Prefer ignored local outputs or Release attachments for future large deliveries.

Experimental branches include SMT architecture studies, object-level factory scans and QEC viewer work. Their presence in [WORKTREES.md](WORKTREES.md) does not mean those features are in `main`. Check the branch, its recorded source identity and its evidence before reusing a result. This README describes the published `main` source, not unpublished local integrations.

## Where to start

| Goal | Entry point |
| --- | --- |
| Run or configure the compiler | [Physical compiler README](modules/physical_compiler/README.md) |
| Understand module boundaries | [Architecture](architecture.md) and [design decisions](docs/decisions/) |
| Study logical translation | [QASM translation](modules/logical_compiler/docs/qasm-translation.md) |
| Explore QEC components | [Code library](modules/codes/README.md) |
| Reproduce a factory study | [MSD guide](experiments/msd/README.md), then its specific configuration and scope |
| Locate a published workspace snapshot | [WORKTREES.md](WORKTREES.md) |
| Inspect snapshot provenance | [SNAPSHOT-MANIFEST.json](SNAPSHOT-MANIFEST.json); this is a historical publication inventory, not a live index of later commits |
| Read research progress and plans | [Log](log.md), [short-term tasks](short-term%20task.md), [surface-code framework notes](Framework%20%28Surface%20Code%29.md) |
| Contribute code | [Engineering standards](agent.md) and [testing policy](docs/testing.md) |

`agent.md` is a contributor/automation policy, not a user tutorial. Research notes record changing hypotheses and priorities; implemented behavior is established by code, tests and the relevant experiment evidence.

## Development priorities

1. Maintain this landing page, the MIT license and a clearly scoped CI baseline; expand CI as reproducible module environments are established.
2. Move logs, journals, planning and meeting material into `notes/` or a separate documentation space, preserving links. This reorganization has not happened yet.
3. Introduce a top-level `pyproject.toml` and installable logical/code packages with explicit dependencies, then remove implicit import-path wiring.
4. Use a feature branch, pull request, review and merge for new development. Existing snapshot branches remain historical snapshots until explicitly reconciled.
5. Keep generated bulk data out of ordinary commits. Plan any history rewrite separately with collaborators; do not silently rewrite existing references.

## License and third-party code

Original project code and documentation are available under the [MIT License](LICENSE).
Bundled third-party material retains its own license and copyright notices.
In particular, the [ENOLA-derived source](modules/physical_compiler/src/nadit_physical_compiler/placement/enola_source/LICENSE)
and [reference fixtures](modules/physical_compiler/tests/fixtures/enola/LICENSE)
retain their BSD 3-Clause licenses. Installing dependencies does not change their licenses.
