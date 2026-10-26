# Rotated Surface Code d5

Status: concrete-code workspace accepted on 2026-10-23. Code and component
implementations remain open.

The local entry.py supplies the implemented logical translation declaration.
It selects Clifford+T and the intended component names for this distance;
it does not claim that the atom-level components are executable.

This directory owns the distance-5 code's local definitions and operations.
It is a direct member of the [code library](../README.md), independent of the
logical compiler.

| Location | Responsibility |
| --- | --- |
| [definition.md](definition.md) | Code identity and unresolved encoding conventions |
| entry.py | Explicit code-selected logical translation scheme |
| [components/](components/README.md) | Local atom-level component templates and binding logic |
| protocols/ | Internal gate realizations and interaction declarations |
| layouts/ | Reference layouts, coordinate conventions and role placement |
| configs/ | Code-specific implementation profiles and parameters |
| tests/ | Code, circuit, binding and component verification |

Local files may explicitly reuse common helpers, but another distance's
implementation is not an automatic fallback. Different measurements, circuits
and layouts must remain independently inspectable.

Use [shared contracts](../contracts/README.md) for external interfaces and
[cross-code protocols](../protocols/README.md) for interactions involving other
concrete codes. Directory membership establishes no mixed-distance gate support.
