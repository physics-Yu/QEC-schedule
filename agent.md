# Engineering Standards (AI Collaboration Rules)

## 0. Communication
- Respond to me in Simplified Chinese.
- Write code, comments, commit messages, and docs in English.

## 1. Core Principles
- **Small steps**: each change solves one problem and can be tested and reverted independently.
- **Verify before claiming done**: run checks appropriate to the change and state exactly what they establish.
- **Ask when uncertain**: stop and confirm on ambiguous requirements, architectural changes, or code deletion.
- **Report honestly**: state failed tests, skipped steps, and unverified parts explicitly, with actual output.

## 2. Workflow (mandatory for every task)
1. **Understand**: restate the requirement; list assumptions and affected files.
2. **Plan**: for changes touching >3 files or >50 lines, present a plan and wait for my approval.
3. **Verification scope**: classify the change using Section 3 and identify affected consumers. For behavior changes, run relevant existing tests as a baseline; do not run unrelated suites. Pure documentation, directory scaffolding and read-only analysis need no test baseline.
4. **Test first**: for production features and behavior bugs, add meaningful tests or a failing regression test. For standalone analysis code, use the evidence checks in Section 3; do not create tests solely because a script was added.
5. **Implement**: make the minimal necessary change. Do not refactor unrelated code.
6. **Verify**: run the selected checks and compare with the relevant baseline where applicable. No new failures in affected behavior are allowed. Expand scope when dependencies, failures or unresolved risks justify it.
7. **Commit**: only after applicable checks pass, following Section 5. Tests and code-quality tools are not prerequisites for changes to which they do not apply.
8. **Report**: use the format in Section 9.

## 3. Testing

Choose verification by impact, not by the existence of a repository test suite.

| Change | Required verification |
| --- | --- |
| Directories, .gitkeep, prose, ADRs or documentation-only policy changes | Check expected paths, links, consistency and diff scope. No runtime baseline, pytest, formatter or type-checker run. |
| Read-only source or architecture analysis | Ground conclusions in inspected sources and state uncertainty. Do not launch tests, builds or experiments just to provide a test count. |
| Standalone analysis, plotting or research scripts | Check syntax/imports as applicable; run a small representative input and independently check relevant calculations, invariants or output. Do not rerun unrelated compiler suites or full experiments. |
| Changes to production behavior in one module | Run focused regression tests and relevant quality checks. Include direct consumers when their behavior may change. |
| Shared interfaces, serialization, dependencies, build/configuration or cross-module behavior | Validate the affected integration paths and consumers; run the affected module's full suite, or repository-wide tests when the impact is repository-wide or cannot be bounded. |

File location and extension do not decide scope: an analysis script imported by
production code is a production change; executable examples and runtime configs
need their corresponding execution/loading checks even when stored with docs.
Changes to scientific calculations require evidence for the claimed result;
successful execution alone is insufficient. Tests are warranted for reusable
analysis logic and regressions, not for mirroring trivial implementation details.

State the selected scope briefly. Routine proportional verification needs no
extra approval. Once appropriate checks pass, do not repeat or broaden them
without new edits, failures, unresolved concerns or an explicit user request.

- Framework: pytest (replace per project).
- New or modified production public behavior must have meaningful test coverage. Behavior bug fixes require regression coverage; document-only corrections use document checks.
- Cover the happy path, edge cases, and invalid input.
- Tests must be deterministic: fix random seeds; no dependence on network, wall-clock time, or execution order.
- Never change a test's assertions just to make it pass, unless you explain why and I approve.
- Never use skip/xfail to hide failures without my approval.
- Commands:
  - Full suite: `pytest -q`
  - Quick check: `pytest -q -x --lf`

### Repository test tiers and selection

The commands below supersede the generic commands above for this repository.
They supplement the impact-based scope rules; documentation-only work still
requires document checks rather than a runtime suite.

- Every collected test must have exactly one tier: `fast` (unit/constraint),
  `slow` (small integration), or `bench` (expensive/reference experiment).
  Maintain file ownership and default tiers in `tests/test-map.json`; use named
  function overrides or one explicit pytest marker for exceptions. Missing
  files, stale overrides, unknown markers, and conflicting tiers fail checks.
- After a code edit, run related fast tests using repository-relative changed
  paths: `python -m tools.testing.run fast --changed <path> [<path> ...]`.
  The selector includes mapped transitive consumers and prints selection
  reasons. Use `--plan` to inspect scope or `--list-areas` to inspect the map.
  Do not silently ignore unknown paths or an empty runtime-test selection.
- For a code/testing-policy commit or PR, run
  `python -m tools.testing.run check` (all fast + slow). Routine iterations do
  not require this repository-wide run. Direct `pytest` defaults to excluding
  bench within its configured/explicit paths; it is not the full suite.
- Only run bench with explicit task authorization:
  `python -m tools.testing.run full`. Nightly/main-branch runs are intended
  future server policy; this change does not schedule jobs or change CI.
- Use the existing Python 3.12 environment. Do not assume `-n auto`, testmon,
  coverage, mutation testing, or hypothesis is installed. No dependency is
  required beyond the repository's existing pytest environment.
- Existing test directories stay in place. New tests belong with their module;
  update the ownership/consumer map in the same change. Shared test helpers
  require their importers; new dependencies require updating consumer edges.
- Prefer parameterization for behaviorally equivalent cases; do not delete
  assertions or replace meaningful regression checks solely to reduce counts.
  Preserve independent validator tests. A production validator is not an
  independent oracle for its own correctness.
- Report selected scope, per-tier pass/fail/skip/not-run counts and slow cases.
  `--lf` is an iteration aid, not the final check. Less than 30 seconds for
  related fast tests is a target, not evidence until measured. See
  [Testing workflow](docs/testing.md) for commands and limitations.

## 4. Rollback & Safety
- Before starting, confirm the working tree is clean (`git status`). If not, ask me.
- Work on a dedicated branch per task: `feat/xxx`, `fix/xxx`, `refactor/xxx`.
- Commit after each verifiable step so there is always a known-good state to return to.
- If tests go from passing to failing and two fix attempts don't resolve it:
  stop, propose reverting to the last passing commit, and explain the cause. Ask before running `git reset --hard`.
- Always ask before:
  - `git push`, `git push --force`, `git reset --hard`, `git rebase`
  - Deleting files or directories
  - Changing dependencies (requirements / pyproject / package.json)
  - Changing CI config, database schemas, or public interfaces
- Never commit secrets, tokens, large data files, or build artifacts.

## 5. Commit Messages (Conventional Commits)
Format: `<type>(<scope>): <short summary>`
- `feat`: new feature
- `fix`: bug fix
- `test`: tests only
- `refactor`: restructuring, no behavior change
- `docs`: documentation
- `chore`: build, dependencies, misc
- `perf`: performance

One logical change per commit. The body explains *why*, not just *what*.

## 6. Code Quality
- Formatter: `ruff format`; linter: `ruff check`; type checker: `mypy` (replace per project).
- Before commit, run applicable formatting, lint, type and test checks at the scope selected in Section 3. Use `ruff format --check .`, `ruff check .`, `mypy .` and `pytest -q` from the relevant module when module-wide verification is warranted; do not apply this whole sequence to every task.
- Public functions and classes require type hints and docstrings (args, returns, raises).
- Use clear names without cryptic abbreviations. Functions do one thing; consider splitting beyond ~50 lines.
- Never swallow exceptions: no bare `except:`. Error messages must include context.
- No dead code, debug prints, or commented-out code blocks.
- Extract magic numbers into named constants or config.
- Match the style of surrounding code; reuse existing utilities before writing new ones.

## 7. Documentation
- Update README and docstrings when public interfaces change.
- Record significant design decisions in `docs/decisions/NNNN-title.md`
  (ADR: context, decision, alternatives, consequences).
- Add user-visible changes to the `Unreleased` section of `CHANGELOG.md`.

## 8. Never
- Claim behavior or correctness beyond the checks actually performed.
- Hardcode expected values or special-case test inputs to pass tests.
- Rewrite large amounts of code that weren't part of the request.
- Add a dependency without justifying it.
- Guess at uncertain APIs or parameters. Check the docs or ask.

## 9. Report Format (end of every task)
- **Changes**: files touched and what changed in each
- **Verification**: selected scope, commands and results; baseline comparison when applicable. For documentation-only work, report document checks and state that runtime tests were not applicable.
- **Commits**: hash and message
- **Open items / Risks**: what's not done, not verified, or needs my decision
