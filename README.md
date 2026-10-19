# Neutral-Atom Compiler and Demonstrations

This publication bundles the current neutral-atom compilation and scheduling software with the seven user-facing demonstrations delivered on 2026-10-09.

## Software

- `src/`: compiler, scheduling, atom-operation planning, validation, and viewer pipeline.
- `configs/`: platform and compilation configuration examples.
- `scripts/`: source tools and demo build/export/check entry points. Historical server outputs and virtual environments are excluded.
- `examples/`: source examples and small fixtures. Large generated scenario traces are excluded here; complete demo artifacts are preserved in the archives below.
- `viewer/`: reusable viewer source. Large generated standalone HTML bundles are included inside the demo archives.
- `tests/`: software regression and viewer contract tests.
- `third_party/`: source-only Enola integration snapshot, with its nested Git internals removed.

Install with Python 3.12 or later: `python -m pip install -e .` (Enola extras: `python -m pip install -e .[enola]`).

## Development environment

Use Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```text
uv sync --extra dev --extra enola
uv run pytest -q
```

`uv.lock` pins the development tools and optional Enola dependencies. Use
`uv sync --frozen --extra dev --extra enola` to reproduce that lock without
updating it. To select a Python version for a new environment, add
`--python 3.12` or `--python 3.13` to `uv sync`.

P0-2 establishes collection and the existing failure baseline; it does not make
the suite green. Historical artifact dependencies and the environment-sensitive
background-job test are addressed in P0-3. No tests are excluded by default.
Pytest uses importlib collection for duplicate module names, with explicit
runtime, backend, QEC, and validation test paths for the existing bare sibling
imports. The backend path precedes QEC so the existing bare
`test_physical_dag` fixture import resolves to the backend helper.
The vendored Enola tree retains its exact committed bytes via `.gitattributes`,
including on Windows with `core.autocrlf=true`, so source-pin checks remain valid.

The original unittest entry point remains available:

```text
uv run python scripts/check.py --suite frontend --suite qec --suite integration
```

Install the local hooks with `uv run pre-commit install`. Ruff uses the version
in `uv.lock` and excludes the legacy source, scripts, tests, viewer, examples,
and third-party code. Whitespace and end-of-file hooks check staged text files;
this setup does not reformat the existing repository in bulk.

The historical validation scripts are documented in
[`scripts/legacy_validation/README.md`](scripts/legacy_validation/README.md).
See the [P0-2 validation report](docs/development/p0-2-validation.md) for exact
collection counts, existing failures and skips, and platform-specific limits.

## Demonstrations

Seven complete delivery folders are preserved as downloadable ZIP archives under `demos/archives/`; each includes its README, viewer, event/data files, and acceptance receipts when present. In the compact-modmul and guarded-Shor packages, the duplicate `animation-library.html` is kept as a small redirect to the byte-identical `full-viewer.html` to avoid storing duplicate viewer bundles. Extract an archive and open its `index.html` or viewer entry file according to that folder's README. Demo receipts describe fake/event-pipeline evidence and are not claims of quantum-state simulation or hardware execution.

- `cnot-t-bottom-20261009`
- `compact-modmul-20261009`
- `dual-aod-linked-20261009`
- `enola-figure2-regenerated-20261009`
- `four-zone-layout-20261009`
- `guarded-shor-20261009`
- `processor-injection-20261009`

## Scope and exclusions

This is a curated software/demo publication. It excludes the local knowledge base, personal task board, server run histories, checkpoints, build outputs, virtual environments, caches, and third-party executable environments. The compact modular-multiplication demo is the first controlled modular multiply for Shor-15, not a full Shor execution. Evidence boundaries in each demo's README and receipts remain authoritative.
