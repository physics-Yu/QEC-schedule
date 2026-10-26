# Frozen surface-memory campaign

Approved on 2026-10-23: d=3,5,7,9; rounds=d; X/Z; nonzoned and Search Smarter
QEC; standard initial homes; fixed large zones and noise. The compiler commit is
ea8c348dc914ba26e42b756ae0d30f7031dba425. `campaign.json` is the authoritative
configuration. This standalone harness imports the frozen package and changes no
compiler code. The generated manifest binds source, inputs, scripts and seeds.

Budget: 16 points, 1,048,576 shots each, 16 shards of 65,536, internal batches 4096.
Compile timeout 7200 s; export timeout 1800 s; shard timeout 1800 s. Four compile
workers, then sixteen sampling workers; numerical libraries use one thread.

Run on Linux using the frozen checkout's Python 3.12 environment with its locked
simulation extra. Keep the harness outside the frozen source checkout:

```text
python prepare.py CAMPAIGN_DIRECTORY FROZEN_CHECKOUT
python run.py smoke CAMPAIGN_DIRECTORY
python run.py run CAMPAIGN_DIRECTORY
python report.py CAMPAIGN_DIRECTORY
```

The smoke uses d3 Z on both backends and 128 shots each, excluded from formal
counts. Each exported circuit is checked for noiseless deterministic parities
and expected detector/observable counts. Formal samples use frozen unique shard
seeds. Repeating `run` resumes interrupted stages and skips all terminal stages;
failed/time-limited stages are retained, not silently retried with extra budget.
A file lock prevents concurrent coordinators. Stage outputs are hashed, and
source/input/script changes reject subsequent work and acceptance.

Results preserve validated Atom IR, source-bound Stim circuits, noise reports,
per-shard counts, logs and statuses. Loss is saved once per export; shard JSON
references that report. `summary.json` and CSV show decoded per-experiment X/Z
failure rates with Wilson intervals, compiler/transport times, and independent
mean/max/data/ancilla loss. Source attribution uses prior-survival-weighted
first-loss increments; simultaneous causes split by hazard, as in the viewer.
Incomplete points have no final logical-error-rate estimate. Existing failed
statuses remain visible. This is a comparison of architectures plus compilers,
not a same-Device algorithm comparison and not a loss-aware logical simulation.
