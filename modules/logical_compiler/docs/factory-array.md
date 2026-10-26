# Synchronized factory array

The explicit `examples.factory_array` entry compiles multiple resumable factory
recipes into one physical world. The default configuration has two lines and one
AOD. Each line uses the current six-patch 15-to-1 recipe and finite retry budgets.
The general QASM frontend is not automatically connected to this factory entry.

## Coordination

`FactoryProcess` yields typed intents. `CooperativeFactoryRuntime` owns the only
physical writer, scheduler, event journal and resource ledger. It collects ready
calls across all lines before declaring a shared wave. Measurements remain
unobserved physical outputs; seeded coarse events select protocol branches.

At an explicit stage barrier, a line waits for its active peers in the same
factory-batch epoch. For example, when line 1 rejects raw A and line 2 accepts,
line 2 retains its state while line 1 resets and retries only the rejected patch.
Once both arrive, their next matching components can be admitted together. The
same join occurs after conditional S branches. Different raw attempts do not
split the cohort. A failed or completed line leaves the cohort explicitly.

Sharing retains row/column, space, capacity and full-world checks. The d3 code
declares a bounded shared profile for corresponding horizontal transversal CNOT
pairs: ordered control/target roles and signed relative geometry must match.
Both patches, their complete atom sets, their transport envelope and both exit
bindings belong to each member. Arbitrary cross-patch gates remain exclusive.
A stage barrier synchronizes logical progress; actual admission and physical
validation determine whether its ready calls can overlap.

`logical_mx` and `logical_mz` can each form matching shared waves. Each member
measures nine data atoms, reserves nine distinct global result IDs and retains
its own result-ready dependencies. The two measurement bases do not share one
waveform identity; physical output values remain unobserved.

Code-declared `local_parallel` families combine addressed Pauli/canonicalization
pulses on disjoint patches even when correction classes differ. Every original
pulse, target and time remains in the actual program and its cost. Identity
corrections add no physical pulse or positive-duration padding. This mode claims
no AOD and introduces no global software Pauli frame. The global writer still
waits for the admitted wave to finish before admitting another wave.

## Device budget

`FactoryArrayConfig` creates actual home/guest sites and operation regions, not
only display margins. Default two-line resources are:

- 204 atoms in 12 disjoint patches, all at the same vertical origin.
- Shared region: x = [-22, 1205], y = [-2, 80] micrometers.
- Readout region: x = [-20, 1205], y = [90, 130] micrometers.
- One flexible AOD: workspace [-25, -5] to [1210, 135] micrometers, minimum line
  spacing 1 micrometer, capacity 4 rows and 48 columns.
- Camera capacity 96 simultaneous atoms. Eight initial raw bodies require at
  most 4 rows, 32 columns and 64 simultaneously read auxiliary atoms.

These are configured model capabilities, not calibrated hardware measurements.
Columns/readout limits can be reduced explicitly; admission then limits wave
width. Local templates retain their existing readout trajectories and durations.
Logical measurement waves use three rows, three columns and nine simultaneous
data results per patch, rather than the four-row/four-column, eight-auxiliary
profile of an SE round. The current translated
CNOT profile uses three rows and three columns per pair, with no readout demand;
all shared capacity and actual trajectory checks still apply.

## Run and inspect

Use the documented physical Python runtime and put its source ahead of this
worktree on PYTHONPATH.

```powershell
python -m modules.logical_compiler.examples.factory_array --config modules/logical_compiler/configs/factory_array_reference.json --noise-params modules/physical_compiler/cost_params/noise_illustrative.json --input-z-error 0.01 --seed 0 --output modules/logical_compiler/artifacts/factory-array-theory-seed-0
```

The default acceptance model is `theory`; `--input-z-error` is required. The
confirmed reference value for the current experiment is 0.01. This parameter
describes independent Z errors of accepted, locally canonicalized A inputs. It
is not inferred from the raw rejection rate, a physical gate error or a physical
no-fault probability. Final acceptance follows the existing joint four-MX event,
with all four checks zero iff accepted. For p = 0.01 the theoretical acceptance
probability is approximately 0.860090333670424. Conditional output Z error is
reference metadata, not a separately sampled feedback bit. Factory Clifford
gates, storage and readout are ideal in this reference model.

Raw preparation still uses the noisy detector/byproduct event and retains local
rejection, reset and retry. The raw event controls supply; the assumed p controls
the reference input quality. These are independent model declarations. The full
and fast entries share the same recipe, event ports, p and seeded occurrence
identities under `factory-array-theory-v1`.

Every output directory must be new. `--sampling-role witness` labels a deliberately
selected seed. A normal experiment can finish with a rejected line; the CLI's
execution-completed flag distinguishes expected production outcomes from a
compiler/protocol/physical failure.

For a serial control, copy the configuration and change only `max_parallel` to 1.
Run the same entry with that configuration, the same seed and noise parameters,
and a different new output directory. This keeps the code implementation, Device,
cohort barriers, event identities and retry budgets fixed. Physical timing and
physical cost diagnostics may differ. They do not change the theoretical MX
distribution at a fixed p.

Outputs include the actual global case and Atom IR, atom replay, an interactive
dynamic ledger, line summaries, resource transition JSONL, line-scoped physical-cost
evidence and content hashes. The time slider reveals only outcomes available at
that time. Successful factory outputs remain offered; no algorithm consumer is
implicitly added in this entry.

`physical-costs.json` selects each line's actual atoms from its first component
through final-check evaluation. It includes raw actions, raw physical loss, and
already successful patches' idle exposure during another patch's raw retry.
Raw horizon records remain provenance and are not removed. The physical no-fault
probability is a separate diagnostic and never controls theoretical acceptance.
Later final-decision barrier waiting, output correction and output holding have
no downstream assessment in this output-hold entry. Reference conditional output
quality does not establish actual accepted-state quality or decoded logical
success. Loss remains cost metadata, not a realized atom-removal/replacement
trajectory. No waiting-SE or prefetch policy is implied.

For historical reproduction only, pass `--acceptance-model physical_no_fault_proxy`
and omit `--input-z-error`. This explicitly selects the old
`factory-array-cost-proxy-v1` case and writes `proxy-costs.json`. It preserves the
historical scope excluding the complete own-line raw horizon union. That scope
omits raw physical loss and other patches' waiting in those intervals; it is not
a complete cost diagnostic. Historical proxy outputs must remain separately
labeled and cannot be interpreted as theoretical 15-to-1 acceptance results.

See [ADR 0048](../../../docs/decisions/0048-synchronized-factory-resource-ledger.md)
for synchronized production and
[ADR 0049](../../../docs/decisions/0049-component-parallel-admission.md) for joint,
measurement and local component admission.
