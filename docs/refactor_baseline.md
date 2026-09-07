# Neutral-Atom Execution Refactor Baseline (R0)

This document records the reproducible baseline required before the execution
layer refactor described in `NEUTRAL_ATOM_EXECUTION_REFACTOR_SPEC.md`.

## Phase

R0 — baseline capture.

## Source snapshot

- Repository: `physics-Yu/QEC-schedule`
- Branch: `main`
- Commit: `a823c4ecf39917dada682c7293ac0f3e478dd3fe`
- Commit subject: `feat: complete step 12 hardware sweeps and end-to-end acceptance`
- Captured: `2026-09-07` (Asia/Shanghai)
- Working tree: clean before this documentation change

## Commands

From the repository root, with the existing Python 3.10+ virtual environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe examples\demo_hardware_layout.py --output-dir results\refactor_baseline\layout
.\.venv\Scripts\python.exe examples\demo_surface_code_cycle.py --output-dir results\refactor_baseline\cycle --no-plot
```

The generated artifacts are intentionally kept under the ignored `results/`
directory so the baseline can be regenerated without adding large binaries to
the source history.

## Observed output

### Tests

`62` tests passed in `6.665 s`.

### Static hardware layout

- Total atoms: `21`
- Mapped qubits: `17`
- Storage occupancy: `17/17`
- Measurement occupancy: `0/8`
- Entangling occupancy: `0/8`
- Reservoir occupancy: `4/6`
- Legacy entangling pair slots: `4`

Artifact directory: `results/refactor_baseline/layout/`

- `hardware_state.json`
- `hardware_layout.png`

### Default d=3 cycle

- Physical gates: `104`
- Actions: `440`
- Movement epochs: `103`
- Entangling batches: `22`
- Total execution time: `5321.582467781746 us`
- Movement distance: `5464.839189095013 um`
- Mean atoms per movement epoch: `1.087378640776699`
- Maximum atoms per movement epoch: `2`
- Measurement batches: `8`
- Maximum pairs per pulse: `2`

Artifact directory: `results/refactor_baseline/cycle/`

- `trace.json`
- `metrics.json`

## Acceptance

The R0 baseline is reproducible from the commands above. The static layout and
current execution trace were captured before introducing the R1 invariant
tests or changing hardware execution semantics.

The layout command emitted a Matplotlib font-cache lock permission warning in
the host profile; it did not prevent `hardware_layout.png` from being written.
