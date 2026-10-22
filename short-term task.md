# Short-term task: Magic-state distillation factory

## Goal and assumptions

Build a parameterized magic-state distillation (MSD) factory in QEC-schedule.

- Start with surface codes. Temporarily pretend logical S is transversal, with explicit timing and noise assumptions; its detailed implementation is outside the current scope.
- Keep the implementation modular so we can later switch to color codes in collaboration with YF Wang.

## Task 1: Single-level factory

Compile the complete production cycle into atom movements and operations, including gates, measurements, resets, and error-correction cycles. Document any omitted components.

Vary independently:

- **Code distance:** d = 3, 5, 7, ... up to the practical limit.
- **Number of parallel pipelines:** N = 1, 2, 4, ... up to the practical limit. This is trivial at this stage, but will be useful when we do second round.

Design benchmarks to measure:

- Startup latency and steady-state throughput: accepted output states per unit time.
- Atom count, physical footprint, and spacetime cost per accepted output.
- Movement distance, transport time, and idle time.
- Noise exposure, broken down by operation type.

## Task 2: Two-level factory

Feed accepted first-level outputs into a second distillation level.

Optimize the two-dimensional factory layout, accounting for:

- Routing between levels.
- Buffering and synchronization.
- Rejected batches and retries.
- Competition for shared hardware resources.

Compare alternative layouts under common resource budgets and, when available, matched output-error targets.

## Deliverables

- Reproducible benchmark configurations and results.
- Scaling plots versus code distance and pipeline count.
- Representative layouts and execution schedules.
- A short report explaining assumptions, bottlenecks, and proposed improvements.
