# Cross-code protocols

Status: workspace accepted; no interaction protocol is implemented.

Place a protocol involving different concrete codes here when its design is
approved. A protocol owns its supported participant combinations, prerequisites,
component composition, result interpretation and output encodings.

Keep one authoritative implementation of a cross-code protocol. A code's local
protocol declarations may reference it. Internal protocols using only that
code's implementation belong in the code's own protocols directory.

The logical compiler uses the protocol's declared conditions and results; it
does not infer interoperability from code-family membership. In particular,
the d3 and d5 workspaces do not establish a mixed-distance CNOT or conversion.

The registration mechanism, schemas and first supported interactions require
later ADRs. See [shared contracts](../contracts/README.md).
