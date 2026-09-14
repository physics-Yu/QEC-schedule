# 2026-09-12 — Four-patch transport geometry probe

Scope: bounded transport validation, separate from the full four-logical QEC
experiment. Root owns the new `qec_four_layout.py` and
`partitioned_cohort.py`; this subtask changed only
`tests/test_partitioned_cohort.py` and wrote its evidence/log. No backend,
physical rule, range, collision or support check was weakened.

## Executed 68-atom geometry

Command:

```text
C:/python312/python.exe -m pytest -q -s -x -p no:faulthandler --basetemp=artifacts/qec-roadmap/step4C-geometry-attempt4 tests/test_partitioned_cohort.py
```

Result at that revision: **1 passed in 380.08 s**. The second, candidate-only
test was added afterwards and run separately; this command's recorded result
does not claim both tests were present in that run.

The default four-patch platform has 68 atoms (36 data and 32 dedicated check
ancillas), default origins `(0,0),(40,0),(0,40),(40,40)`, and a single 7×14
nonuniform-column AOD with 98 total cells. The explicitly authorized discrete
EZ neighbor guard is off; the remaining physical validators are unchanged.

The test uses actual `ProgramBuilder → Executor` and checks:

- `patch_assignment` translates the whole layout by `(0,-100)` μm to EZ.
- Two LOAD/OFFLOAD bands each carry 34 atoms. Each load activates all 98 cells,
  so all 64 empty active intersections participate in the original sweep and
  capture checks. Every atom appears exactly once in the stage bindings.
- A→C and B→D data pairs use one 18-pair CZ pulse, with the C/D cohort translated
  by `(2,-40)` μm. The actual trace reports exactly 18 intended pairs and each
  of the 18 gates completes once. All 32 ancillas remain physically present.
- The retained cohort is released, then all 68 original SLM holders, AOD
  configuration and SLM switches are restored exactly. LOAD and OFFLOAD counts
  are each 5, and Raman/CZ physics is not approximated by logical events.
- Serialized plans replay from the original checkpoint without calling any
  compiler; final checkpoint strings are identical.
- Four real target-supported handoff checkpoints restore and finish their
  respective pending plans with exactly matching checkpoint strings.

Evidence:
`artifacts/qec-roadmap/step4C-geometry-attempt4/test_all68_stage_parallel18_cz0/`
contains `initial.json`, `plans.json`, `final.json`, four recovery checkpoints,
four expected recovery results, `replay.json` and `verification.json`.

Observed wall stages: initial stage complete 64.65 s; 18-pair CZ complete
67.29 s; cohort release 67.79 s; terminal complete 153.92 s; independent replay
complete 281.53 s; all checkpoint continuations complete 379.86 s. These were
local concurrent-agent samples, not an isolated benchmark. Repeated plan
validation on each Executor event dominated the large transport stages.

## Candidate-only 9-pair A→B geometry

```text
C:/python312/python.exe -m pytest -q -s -x -p no:faulthandler --basetemp=artifacts/qec-roadmap/step4C-geometry-nine-ab tests/test_partitioned_cohort.py -k nine_ab
```

Result: **1 passed, 1 deselected in 2.24 s**. It constructs the complete 68-atom
stage in a pure ProgramBuilder prediction, then creates the 9-pair A→B pulse
with mobile B shift `(-38,0)` μm and runs ordinary finish/exact plan validators.
The original and predicted input states remain unchanged. It **does not execute
that 9-pair candidate through Executor**. Its directory contains stage/pulse
plans and a verification JSON explicitly identifying this restricted scope.

## Preserved engineering attempts

1. Initial test incorrectly accessed `Operation.bindings`; the real field is
   `transfer_bindings`. It failed after the stage plan compiled, before actual
   execution. Corrected the test, without changing physics.
2. Quiet rerun was actively stopped after a bounded diagnosis window because
   its phase was unclear. This was not a physical rejection or proof of no route.
3. Added phase output and a repeating 45-second `faulthandler` stack dump. Real
   stage, CZ, release and terminal passed; the process then suffered a Windows
   native access violation during independent replay, coinciding with periodic
   stack output. Causation is unproven. The observed output excerpt (explicitly
   incomplete because the tool output was truncated) is preserved at
   `artifacts/qec-roadmap/step4C-geometry-attempt3-fatal/observed-output.txt`.
4. Removed the diagnostic timer and disabled only pytest's faulthandler plugin;
   retained all physical/replay assertions and added per-stage persisted evidence.
   The complete test passed as documented above. Floating busy-time comparison
   uses an absolute 1e-9 μs tolerance to avoid an inappropriate binary-float
   equality assertion; its expected duration is still the unchanged hardware
   pulse duration.

These results establish the declared default geometry and finite candidates,
not arbitrary origins/axis masks, a full QEC protocol or global optimality.
Root's full four-patch quantum/protocol/physical/UI work has separate evidence.
