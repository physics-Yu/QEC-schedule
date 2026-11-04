# Working on NADiT

Discuss work with the owner in Simplified Chinese. Write repository code,
comments, documentation and commit messages in English.

## From a change request to acceptance

1. **Define the observable change.** Name a supported entry point, one input,
   the current result and what the owner should see after the change. Identify
   the module that owns the decision and the consumers of its output. Start
   with the [architecture](architecture.md) and the [method guide](docs/methods.md).
2. **Agree on scope once.** For a change spanning more than three files or
   50 lines, agree on a short plan before editing. An explicit request that
   already defines that scope supplies approval. Bring a changed contract,
   design assumption or acceptance criterion back to the owner.
3. **Make one reversible change.** Exercise the example through its normal
   entry point. For a known defect, capture the failing input and the wrong
   output. Use the smallest existing or new regression that distinguishes
   the fix. For a new feature, show the resulting artifact for human review.
4. **Hand over the evidence.** Show the diff, expected and observed behavior,
   a way to reproduce it, and any failed, skipped or unverified checks. For
   estimates or simulations, identify the inputs and assumptions behind the
   number. The owner decides when the result meets the criterion and when to
   merge or publish.

## Verification

The [testing workflow](docs/testing.md) defines selection during iteration,
the commit and PR checks, bench authorization and reporting. Its
[retention rule](docs/testing.md#retaining-a-regression) governs permanent
pytest cases. The [test manifest](tests/test-map.json) owns the ceiling and
consumer map. Raising the ceiling requires explicit owner approval.

- For a local change, exercise the affected behavior and its direct consumers.
  A module with no applicable regression can still be reviewed using its
  acceptance example. For a shared contract, follow the changed data through
  the callers that consume it. Expand the checks when the impact warrants it.
- For a scientific calculation, use a reference input or an independent
  calculation that can distinguish the expected result. Keep tests
  deterministic and fix seeds where sampling is part of the reproducer.
- For prose and navigation changes, check paths, links and agreement with
  implementation. For read-only analysis, cite the inspected source. An
  executable example or configuration change needs its normal execution or
  loading check.
- Reuse a passing check for the same revision and scope. If an intended
  change invalidates an assertion, explain the changed expectation for
  review. Report failures directly. Skipping or marking a failure as
  expected requires explicit owner approval.

## Working tree and integration

Inspect the branch, worktree and staged diff before editing. Use a dedicated
task branch. Preserve unrelated edits in their own worktree. If they overlap
the requested change, resolve ownership with the owner before proceeding.

Obtain explicit authorization for file deletion, dependency or CI changes,
schema or public-interface changes, and destructive Git operations such as a
hard reset, rebase or force-push. Approval for the specified action applies
throughout the agreed scope. Merge and push each require an owner request.
If two repair attempts leave a previously passing check failing, report the
counterexample and agree on the next step.

Make one logical change per commit. Use a Conventional Commit subject and
explain the reason in the body. Report the resulting revision and destination.
Keep secrets, large generated data and build output out of commits.

## Code and documentation

Follow the owning module's conventions for types, docstrings, Ruff and mypy.
Reuse existing contracts and helpers. Keep functions focused, preserve error
context and derive results from their inputs. Keep independently computed
checks where the output could disagree with the implementation.

When a contract changes, update its owning reference and the affected
callers. Update the [architecture map](architecture.md) when ownership or a
handoff changes and the [method guide](docs/methods.md) when a runnable
entry point changes. Record significant design decisions in
[ADRs](docs/decisions/) and user-visible changes in the
[changelog](CHANGELOG.md). Dated studies and earlier commits document the
behavior of the revision they examined.
