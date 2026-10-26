# Test tiers and module selection

Status: implemented first batch. Existing test files and assertions are retained.
No dependencies, CI jobs, scheduled runs, or test directory moves are introduced.

## Commands

Run from the repository root with the existing Python 3.12 environment. In
PowerShell, select it once for the current shell:

```powershell
$testPython = './modules/physical_compiler/.venv/Scripts/python.exe'
& $testPython -m tools.testing.run fast --changed modules/physical_compiler/src/nadit_physical_compiler/motion.py
& $testPython -m tools.testing.run fast --area physical.scheduling --plan
& $testPython -m tools.testing.run --list-areas
& $testPython -m tools.testing.run check
```

| Profile | Scope | When |
| --- | --- | --- |
| `fast --changed <paths>` or `fast --area <name>` | Related fast tests and mapped consumers | Code iterations; target under 30 seconds |
| `check` | All registered fast + slow tests | Code/testing-policy commit or PR |
| `full` | All tiers including bench | Only explicitly authorized expensive verification |

Both `check` and `full` also accept explicit scopes, but a scoped check does not
replace the all-fast-and-slow pre-commit check. Pure documentation changes use
document checks only. Unknown paths fail with a mapping error. An untested
scaffold may have an empty plan; executing that scope fails with an explicit
error. Add meaningful tests before claiming runtime behavior is verified.

The module-local `pytest -q` command continues to collect its local `tests/`
directory. The root `pytest -q` collects core, code-component, tooling, and
existing optional hsim/Stim suites. Both exclude bench by default. The `check`
runner uses the manifest's complete file list rather than the current working
directory's default discovery. Optional suites still require their existing
extras; missing dependencies remain errors and are not silently skipped.

Direct pytest also accepts `--test-tier fast|check|full`, or an explicit marker
expression such as `-m "fast or slow"`. Use one selection mechanism per command.
An explicit `-m bench` requests bench. Existing node IDs still work. Unknown
markers are errors under the repository configs.

## Classification and ownership

[`tests/test-map.json`](../tests/test-map.json) records each test file's areas,
default tier, and optional function overrides. The pytest plugin adds actual
markers during collection, before marker filtering. Existing flat test layouts
and sibling fixture imports are preserved. File defaults classify new functions
in that file; authors must review their cost and add exceptions when needed.

Example manifest entry:

```json
{
  "tests/example_test_file.py": {
    "areas": ["physical.transport"],
    "tier": "fast",
    "overrides": {"test_large_reference": "bench"}
  }
}
```

Overrides use `test_name` or `TestClass::test_name`, before parameter brackets.
A single explicit `@pytest.mark.slow` may override a file default. An explicit
marker conflicting with a function override, or two distinct tier markers,
fails collection even if `-m` would otherwise exclude that test.

The initial classification puts pure unit/constraint files in fast, most
compiler/component integration in slow, and selected dense source/action
quantum sweeps in bench. Stored reference-trace comparisons are not bench just
because their filenames mention a reference or benchmark. Review measured
durations when revising tiers; never reclassify a failing test to hide it.

Areas contain explicit source paths and consumer edges. The longest matching
source prefix wins; directory changes include descendant areas. Unassigned
physical source files fall back to `physical.core`, which conservatively selects
all downstream areas. Other unmapped runtime changes fail. Add a narrower entry
when introducing a new module. Consumers are followed transitively, including
cross-module component callers. This is a maintained ownership map, not dynamic
execution tracing. Update it when dependencies change.

Changes to test/helper files include statically imported test consumers, followed
transitively. Dynamic imports and pytest fixture discovery are not inferred;
select the owning area explicitly for those changes. Basename matching of
sibling imports may conservatively include extra files. No testmon is used.

Global inventory audit detects unlisted/deleted test files within registered
roots, stale overrides and invalid references, even for narrow runs. Conflicting
markers are checked on collected items. New test roots must be added to both
the manifest and root pytest discovery configuration.

## Evidence and limits

The runner prints selected files and consumer reasons, requests
`--durations=20`, and writes `.pytest_cache/test-report.json`. Direct pytest can
write the same format with `--test-report <path>`. Per-tier counts distinguish
collected, selected, passed, failed, skipped and not run. Setup/teardown failures
remain failures. Collection errors and interruptions remain nonzero exit codes.
Reports describe collected files only; they do not claim coverage of unselected
modules. Do not run concurrent commands against the same report path.

`--plan` audits inventory and prints scope without executing tests. A successful
plan or collect-only command proves selection/collection, not passing behavior.
`--lf` is only a local iteration aid. The first batch adds no timing thresholds,
coverage targets, parallel workers, test deletion, or server automation.

See [ADR 0046](decisions/0046-tiered-test-selection.md) for the rationale and
[engineering standards](../agent.md) for the required workflow.
