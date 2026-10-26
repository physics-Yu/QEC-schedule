# ADR 0037: Code library and logical compiler workspaces

Status: Accepted on 2026-10-23 for workspace structure and responsibility boundaries.
Executable interfaces and implementations remain open.

## Context

Concrete codes determine their encoding, component implementations, logical gate
realizations and interaction protocols. They must remain independently usable
from the logical compiler. Different surface-code distances need explicit local
files, even when much of their interface and construction can be shared.

## Decision

Create modules/codes/ and modules/logical_compiler/ as peers of the existing
modules/physical_compiler/ workspace in the same repository.

List rotated_surface_d3/ and rotated_surface_d5/ directly under modules/codes/.
Each owns its definition, components/, protocols/, layouts/, configs/ and tests/.
Reserve preparation, se, measurement, trans_cnot and raw_t component work areas
for both codes. These names do not declare implemented capabilities.

Place shared interface definitions in codes/contracts/ and cross-code protocols
in codes/protocols/. Internal protocols remain with their concrete code.
Cross-code compatibility is supplied by the relevant protocol, not inferred by
the logical compiler from family names or code distance.

The logical compiler has src/frontend/, translation/, dag/, scheduling/,
expansion/ and state/, plus configs/, tests/ and docs/. It translates source
gates to supported component operations, constructs the Logical DAG, checks
frontier constraints and binds/expands component invocations.

Components target parameterized atom-level operations with explicit participant
and coordinate interfaces. Device-level concurrency and transport remain subject
to the complete device state. This decision does not define the new executable
handoff to the physical compiler.

Use English README and design notes; retain empty directories with .gitkeep.
Keep ADRs in the repository's docs/decisions/. Do not create placeholder circuit
implementations, package manifests, configuration schemas or new dependencies.

## Alternatives

- Codes under logical_compiler/: rejected because codes own their capabilities
  and protocols independently of the orchestration implementation.
- Each code directly under modules/: superseded by the accepted codes/ grouping.
- Family/variant/distance directory nesting: rejected as unnecessary depth.
- One generic distance parameter replacing local files: rejected because
  distance-specific circuits, layouts and measurement interpretation need local
  definitions and independent verification.
- A global component library separate from its codes: rejected for concrete
  code components; each code owns its implementations.

## Consequences

The workspace is available for staged ADR-driven development. Directories are
not executable APIs or claims of code, gate, factory or fault-tolerance support.
Shared helpers can be introduced when concrete duplication justifies them.

Component schemas, language/packaging, code conventions, cross-code protocols,
logical constraints, measurement continuity and simulation/decoding integration
remain open. The existing physical compiler is unchanged.

## Verification scope

Check the directory inventory, local documentation links, English content and
absence of executable placeholders. Check diff scope and consistency with the
accepted ownership. Under the updated root engineering rules, this documentation
and directory change requires no runtime tests, formatter or type checker.
Document checks establish workspace integrity, not logical-compiler behavior.

Verification on 2026-10-23:

- Workspace inventory: 29 required directories and 38 new workspace files.
  All workspace files are Markdown or .gitkeep placeholders.
- Documentation: 15 English Markdown documents and 66 local links checked.

The following checks had already completed under the earlier engineering rules
before the root policy update was observed. They are historical observations,
not prerequisites for future documentation-only changes:

- Existing `uv run --locked pytest -q`: 1,759 passed before (99.93 s) and
  after (100.72 s); no new failures.
- `uv run --locked ruff format --check --no-cache .`: 304 files formatted;
  `uv run --locked ruff check --no-cache .`: passed.
- `uv run --locked mypy --exclude '(^|/)(artifacts|build|dist)/' .`:
  no issues in 288 source files.

The default Ruff checks initially failed with `wrong package cache for file`;
disabling the cache resolved the tool failure. Default `mypy .` initially found
duplicate `finish` modules in generated artifacts. The successful command
excluded generated artifacts/build/dist only. No source, dependency, assertion
or quality-check configuration was changed to obtain these results.

See [codes](../../modules/codes/README.md),
[logical compiler](../../modules/logical_compiler/README.md) and
[architecture](../../modules/logical_compiler/docs/architecture.md).
