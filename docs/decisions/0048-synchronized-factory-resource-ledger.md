# Synchronized factory lines and a dynamic resource ledger

Status: Accepted for implementation, 2026-10-24.

## Decision

The first array has two factory lines sharing one AOD and one complete physical
world. Factory count and physical area/capacity budgets are configuration. Code
owns geometry, recipes, component declarations and probability ports. The logical
compiler owns one coordinator, component scheduler, event journal and resource
ledger. Independent completed factory cases must not be overlaid afterward.

Each `FactoryProcess` is a resumable recipe, yielding component, feedback, safe
exit, parallel-preparation and cohort-barrier intents. It does not advance the
physical clock or run its own scheduler. The coordinator settles all ready
continuations, admits a global component frontier, and commits one actual wave.
Resource mutations accompany real execution; failed admission cannot consume or
reset a resource. Local failures cancel unstarted nodes without marking them as
physically completed, while other lines retain their own state.

The requested policy is **cohort stage synchronization**. A line that has prepared
its raw A waits for the other active lines at the same batch/stage. Successful
patches are retained while only failed preparations retry. The same rule joins
feedback branches after any required S correction. Initial preparation, rotation
substeps, final measurements and final decisions have explicit barriers. Raw
attempt numbers do not enter a barrier key; they remain in stochastic identities.
Terminal lines leave the cohort with a recorded reason, so a rejected/exhausted
line cannot block the remaining lines forever or reset successful output.

This synchronization does not exempt a physical component from its constraints.
The existing same-component single-patch sharing rule supports common waves.
Cross-patch CNOTs retain their separate conservative resource checks; matching
protocol stages alone does not make two such gates physically concurrent.

## Dynamic accounting

Every identity includes its factory, batch, preparation and attempt where
applicable. The global resource ledger keeps carrier epochs, ownership, offered,
reserved, consumed and discarded tokens. The line ledger separately records raw
acceptance/rejection, final factory decisions, terminal failures, output readiness
and optional algorithm consumption. A raw rejection is not a failed factory, and
factory proxy acceptance is not decoded logical success.

Line-state transitions distinguish active work, resource waiting, feedback waiting
and waiting for cohort peers. They include physical time, stage and peer names.
The interactive report reconstructs states at a selected time and does not expose
future outcomes. Historical offer timestamps can precede the token's physical
exit; availability replay uses the maximum of audit, ready and exit times.

The first acceptance holds successful outputs as offered resources. It does not
silently consume them, introduce stock watermarks/prefetch, run maintenance SE,
or simulate replacing physically lost atoms.

## Cost and evidence

Raw probabilities continue to use code-owned source-aware joint events. Factory
no-fault proxy evaluation selects each line's atoms from the actual fused global
activity, then intersects its own time windows. A line's raw horizons exclude
only that line's atoms. Within its factory evaluation window, storage while
waiting for another line's retry remains included outside its own raw horizons.
The window stops at that line's final-check evaluation; subsequent decision-barrier
waiting, output correction and held-output storage are not assessed by this proxy.
The inherited whole-line raw exclusion
still omits other activity inside that line's raw windows and is explicitly an
approximation. Cross-line CZ and unsupported correlated/common-mode noise are
rejected rather than silently factorized.

Acceptance requires enlarged shared/readout geometry with explicit budgets,
different seeded preparation paths, an observed positive peer-wait interval,
cross-line membership in a real shared-AOD wave, independent terminal outcomes,
preserved output ownership, full physical validation and fixed-seed replay.
Selected branch-witness seeds are disclosed and do not estimate success rates.
