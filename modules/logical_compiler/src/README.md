# Source responsibilities

Status: frontend, translation, logical dependencies, abstract protocol cases and
synchronized factory execution are implemented. Physical and calibrated logical
execution kernels share the protocol runtime. General QASM-to-atom binding and
asynchronous device scheduling remain open.

| Directory | Responsibility |
| --- | --- |
| compilation.py | Select the code entry and run the logical translation pipeline |
| model.py | Immutable operations, guards, synthesis evidence and result records |
| frontend/ | Parse the chosen logical-circuit source and preserve its meaning |
| translation/ | Resolve gates into operations or compositions supported by selected codes and protocols |
| dag/ | Represent logical dependencies and component invocations |
| placement/ | Produce and validate initial/return block positions from code-owned geometry without compiling or sampling |
| cases/ | Bind seeded joint events, expand selected continuations/retries and serialize static abstract cases |
| protocols/ | Execute code-owned factory recipes with carrier/token lifecycles, typed execution receipts and bounded feedback/retries |
| scheduling/ | Inspect the frontier and check logical resource and protocol constraints |
| estimation/ | Check calibration applicability, execute admitted logical receipts, and separate member work, shared busy time and statistical summaries |
| expansion/ | Invoke component binding/expansion and arrange the physical-compiler handoff |
| state/ | Track block instances, bindings, frames, case results and progress |

Concrete circuits, stabilizer definitions and code-specific gate algorithms
belong in [codes/](../../codes/README.md), not in these directories.
Shared externally visible contracts belong in
[codes/contracts/](../../codes/contracts/README.md).

The source-checkout API is exposed through modules.logical_compiler. See
[QASM translation](../docs/qasm-translation.md) for its result format and limits.
See [abstract cases](../docs/case-driven-compilation.md#implemented-abstract-case-api)
for the separate API; it does not automatically consume QASM translation output.
The [factory pipeline](../docs/factory-pipeline.md) has a separate public entry;
[factory arrays](../docs/factory-array.md) use one physical writer and scheduler.
[Fast experiments](../docs/fast-experiments.md) reuse those protocol and scheduling
semantics with logical estimates and no per-case atom compilation. State-aware
quantum feedback remains open. Later ADRs should introduce one independently
verifiable capability at a time. See
[architecture](../docs/architecture.md).
