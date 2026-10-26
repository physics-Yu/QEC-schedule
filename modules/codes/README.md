# Codes

Status: ownership accepted on 2026-10-23; translation entries implemented.
Atom-component implementations remain open.

The d3/d5 entry providers now declare the Clifford+T translation scheme and
intended component bindings. Atom-level component implementations remain open.

This library is a peer of the [logical compiler](../logical_compiler/README.md)
and [physical compiler](../physical_compiler/README.md). Each concrete code owns
its definition, components, internal protocols, layouts, configurations and tests.
See [ADR 0037](../../docs/decisions/0037-code-library-and-logical-compiler-workspaces.md).

## Layout

```text
codes/
  contracts/
  protocols/
  rotated_surface_d3/
    definition.md
    components/
      initialize_0/
      initialize_plus/
      se/
      measurement/
      trans_cnot/
      raw_t/
    protocols/
    layouts/
    configs/
    tests/
  rotated_surface_d5/
    definition.md
    components/
    protocols/
    layouts/
    configs/
    tests/
```

Both code directories reserve the same component categories. Directory names
identify work areas, not available or validated operations. New concrete codes
are listed directly under this directory; family, variant and distance do not
add another directory hierarchy.

| Location | Ownership |
| --- | --- |
| [contracts/](contracts/README.md) | Shared code, component and protocol interface definitions |
| [protocols/](protocols/README.md) | Cross-code interaction protocols |
| [rotated_surface_d3/](rotated_surface_d3/README.md) | Local distance-three definitions and implementations |
| [rotated_surface_d5/](rotated_surface_d5/README.md) | Local distance-five definitions and implementations |

## Confirmed boundaries

- A concrete code manages its own components. The compiler consumes the
  supported operations and interaction rules supplied by codes and protocols.
- Distance-specific circuits, layouts and interpretation files remain local.
  Common helpers may be shared explicitly; a distance parameter is not a
  substitute for every local implementation.
- Components target reusable atom-level operations with participant, role and
  coordinate binding. A component may involve several blocks or change an
  encoding; its entry and exit requirements belong to its implementation.
- Cross-code compatibility comes from an explicit protocol. Similar names,
  shared ancestry or matching gate names do not establish compatibility.
- Measurement outcomes belong to invocation cases, not reusable templates.

## Open decisions

Later ADRs will select code conventions, circuits, file formats, executable
interfaces, packaging, protocol registration and validation criteria. The
definition notes are design placeholders, not machine-readable code instances.
Factory construction, S implementations, raw-T injection, Stim integration and
decoding remain open. The original workspace decision introduced no executable
implementation. The subsequent [frontend ADR](../../docs/decisions/0039-logical-qasm-translation.md)
adds entry declarations and logical translation without atom execution.

Shared ADRs remain in [docs/decisions/](../../docs/decisions/). All work follows
the root [engineering standards](../../agent.md).
