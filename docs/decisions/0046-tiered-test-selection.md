# ADR 0046: Tiered tests with explicit module and consumer selection

Status: Accepted for the first implementation batch.

## Context

The repository has compiler, code-component, optional backend and expensive
quantum-reference tests. Repeated full execution during local edits is costly.
Existing flat test files import sibling fixtures, so moving directories would
mix test-organization changes with behavior risk. The user authorized tiering
and selection while retaining existing tests and agent.md content, without
new dependencies, test deletion, or CI changes.

## Decision

Keep existing files. Maintain an explicit JSON manifest of source areas, their
consumers, test ownership, and fast/slow/bench classification. A pytest plugin
audits inventory and assigns markers before deselection; ambiguous or missing
classification is an error. Individual functions may override file defaults.

Use related fast tests during iteration and all fast + slow before a code commit
or PR. Bench requires explicit authorization. Direct pytest excludes bench by
default. Existing documentation-only verification exemptions remain applicable.
Print selection reasons and per-tier outcomes, and expose the slowest tests.

The selector follows consumer edges transitively, recognizes changed test-helper
importers, and rejects unknown runtime paths. It does not claim automatically
complete dependency discovery. Owners must update the map when adding modules,
roots, dependencies, or tests. Shared physical interfaces use a conservative
fallback. Existing optional backends remain required for their respective tests.

## Alternatives

- Move tests to mirror every source package now: deferred to avoid breaking
  sibling fixture imports and broadening this batch.
- Add explicit decorators to every existing file: unnecessary churn; a central
  manifest provides reviewable ownership and tiers while still using pytest
  markers for selection.
- Add testmon, xdist, hypothesis, coverage, or mutation testing: deferred;
  dependency changes and their operational tradeoffs need a separate decision.
- Run only the edited module: rejected because direct and transitive consumers
  can break even when the module's own tests pass.

## Consequences

Routine checks become smaller and their scope inspectable. The map needs
maintenance; conservative edges can select extra tests. First-batch timing
targets are goals, not hard test thresholds. A validator does not replace
independent semantic/oracle coverage, and deselected bench cases remain unverified.
No nightly jobs or CI changes are installed by this decision.
