# Rotated Surface Code d3

Status: measured initialization, single SE, logical Pauli/H/S/Sdag, transversal
CNOT, raw T and Y preparation are implemented. Fault-tolerance qualification and
frame management remain open; see the [component API](components/README.md).

Raw-T resource use requires [repeated-SE postselection](protocols/raw_t.md):
the unchanged single-round primitive must be followed by at least one ordinary
SE round, and acceptance includes every adjacent-round syndrome difference.

The local entry.py supplies the implemented logical translation declaration.
It selects Clifford+T and the intended component names for this distance;
general QASM-to-component binding remains separate from the executable factory
pipeline.

This directory owns the distance-3 code's local definitions and operations.
It is a direct member of the [code library](../README.md), independent of the
logical compiler.

The [serial six-patch factory](protocols/factory.md) declares the frozen 4+11
15-to-1 recipe, local preparation correction, retained-atom logical readout and
joint reference probabilities. Logical execution owns retries and resource
lifetimes; inventory policies and full noisy factory simulation remain reserved.
Code-owned parallel declarations support logical scheduling of compatible
components, and calibrated profiles support fast logical factory experiments.
Their theoretical joint final checks remain separate from physical cost diagnostics.

| Location | Responsibility |
| --- | --- |
| [definition.md](definition.md) | Executable d3 convention and verification scope |
| entry.py | Explicit code-selected logical translation scheme |
| [components/](components/README.md) | Local atom-level component templates and binding logic |
| protocols/ | Internal gate realizations and interaction declarations |
| [probabilities/](probabilities/README.md) | Offline protocol-event estimates and local branch declarations |
| layouts/ | Reference layouts, coordinate conventions and role placement |
| configs/ | Code-specific implementation profiles and parameters |
| tests/ | Code, circuit, binding and component verification |

Local files may explicitly reuse common helpers, but another distance's
implementation is not an automatic fallback. Different measurements, circuits
and layouts must remain independently inspectable.

Use [shared contracts](../contracts/README.md) for external interfaces and
[cross-code protocols](../protocols/README.md) for interactions involving other
concrete codes. Directory membership establishes no mixed-distance gate support.
