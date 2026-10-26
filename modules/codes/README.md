# Codes

Status: workspace and ownership accepted on 2026-10-23. The d3 measured
initialization, SE and approved logical gates implement the shared invocation
contract; broader code/protocol discovery remains open.

This library is a peer of the [logical compiler](../logical_compiler/README.md)
and [physical compiler](../physical_compiler/README.md). Each concrete code owns
its definition, components, internal protocols, layouts, configurations and tests.
See [ADR 0037](../../docs/decisions/0037-code-library-and-logical-compiler-workspaces.md).

The logical frontend also consumes explicit code-entry declarations; see
[ADR 0039](../../docs/decisions/0039-logical-qasm-translation.md).

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

Both code directories reserve the same component categories. Consult each local
README for implemented capabilities; directory names alone are not evidence.
The additive [odd-distance surface components](rotated_surface/README.md) now
generate definitions and concrete components with distance-selected code IDs,
including d5, d9 and d11 facades. The existing d3 implementation remains unchanged. Generic
factory backend, probability ports and correction execution still require an
explicit adapter; a generated component alone is not a running factory.
New concrete codes
are listed directly under this directory; family, variant and distance do not
add another directory hierarchy.

| Location | Ownership |
| --- | --- |
| [contracts/](contracts/README.md) | Shared code, component and protocol interface definitions |
| [protocols/](protocols/README.md) | Cross-code interaction protocols |
| [rotated_surface_d3/](rotated_surface_d3/README.md) | Local distance-three definitions and implementations |
| [rotated_surface_d5/](rotated_surface_d5/README.md) | Local distance-five definitions and implementations |
| [rotated_surface_d9/](rotated_surface_d9/README.md) | Distance-nine catalog, concrete components and translation declaration |
| [rotated_surface_d11/](rotated_surface_d11/README.md) | Distance-eleven catalog, concrete components and translation declaration |

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
- Codes own [event probability models](contracts/event_probability_v1.md) and
  local branch dependencies. The logical compiler consumes these static ports,
  samples case events and expands the selected path into a static result; see
  [ADR 0042](../../docs/decisions/0042-event-probability-ports.md).

## Open decisions

The first d3 code/protocol and executable invocation interface are recorded in
[ADR 0039](../../docs/decisions/0039-measured-d3-component-contract.md).
Broader file formats, packaging and protocol registration remain open. The d5
definition and components now use the verified odd-distance helper; see
[ADR 0051](../../docs/decisions/0051-msd-experiment-standard.md).
Factory construction, global frame maintenance and decoding remain open.
Approved d3 gate implementations are recorded in
[ADR 0040](../../docs/decisions/0040-approved-d3-logical-components.md).
No dependencies or executable implementations were added
by the original workspace decision. The d3 implementation uses the existing
physical compiler; its quantum tests use the already available simulation extra.

Shared ADRs remain in [docs/decisions/](../../docs/decisions/). All work follows
the root [engineering standards](../../agent.md).
