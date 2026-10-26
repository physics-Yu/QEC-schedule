"""Name the existing asynchronous factory policy without changing scheduling.

The descriptor selects independent cohorts and the existing parallel scheduler.
Fair-service ordering, correction priority and homogeneous waves remain owned by
the cooperative runtime and scheduler. No distance, layout or probability enters
this policy, and its name must not become part of an event-sampling identity.
"""

from dataclasses import dataclass, field

from ..scheduling import ComponentScheduler


@dataclass(frozen=True, slots=True)
class AsynchronousStrategy:
    """Immutable description of the current ready-frontier scheduling policy."""

    strategy_id: str = field(default="asynchronous/v1", init=False)
    name: str = field(default="asynchronous", init=False)

    def cohort_id(self, factory_id: str) -> str:
        """Return the unchanged factory ID as its independent cohort.

        Raises ValueError when the identifier is not a nonempty string, matching
        the existing factory/cohort identity contract without normalizing it.
        """
        if not isinstance(factory_id, str) or not factory_id.strip():
            raise ValueError("INVALID_FACTORY_ID: expected a nonempty string")
        return factory_id

    def make_scheduler(self) -> ComponentScheduler:
        """Return a fresh existing parallel scheduler with no new capacity limit."""
        return ComponentScheduler()

    def to_dict(self) -> dict[str, str | int | bool]:
        """Return independent policy metadata, separate from physical feasibility."""
        return {
            "id": self.strategy_id,
            "name": self.name,
            "selection": "greedy_ready_frontier",
            "service_order": "fair_service",
            "correction_priority": -1,
            "cohorts": "independent_per_factory",
            "retries": "independent",
            "deliberate_hold": False,
            "scheduler_mode": "parallel",
            "wave_policy": "homogeneous_same_component",
            "wave_completion": "all_members_before_next_wave",
        }


@dataclass(frozen=True, slots=True)
class SynchronousStrategy(AsynchronousStrategy):
    """Align production stages and rounds independently of output acceptance."""

    strategy_id: str = field(default="synchronous/v2", init=False)
    name: str = field(default="synchronous", init=False)

    def cohort_id(self, factory_id: str) -> str:
        """Validate the factory identity and place it in the shared stage cohort."""
        AsynchronousStrategy.cohort_id(self, factory_id)
        return "synchronous"

    def to_dict(self) -> dict[str, str | int | bool]:
        """Describe barrier waits without changing the underlying resource model."""
        result = AsynchronousStrategy.to_dict(self)
        result.update(
            cohorts="fixed_production_round_members",
            deliberate_hold=True,
            retries="raw_local_final_rejection_advances_round",
            stage_alignment="raw_ready_deterministic_steps_and_conditional_join",
            output_delivery="immediate_ideal_sink_then_round_barrier",
            member_failure="abort_estimate",
        )
        return result


def resolve_factory_strategy(name: str = "asynchronous") -> AsynchronousStrategy:
    """Resolve the named policy without changing probability or event identities.

    ``async`` and the stable policy ID are aliases for ``asynchronous``.
    ``sync`` and ``synchronous/v2`` select round synchronization. The superseded
    ``synchronous/v1`` is rejected rather than reinterpreted. Unknown names
    raise ValueError. Both strategies use the same single-device scheduler.
    """
    if isinstance(name, str) and name in ("asynchronous", "async", "asynchronous/v1"):
        return AsynchronousStrategy()
    if name == "synchronous/v1":
        raise ValueError(
            "SUPERSEDED_SYNCHRONOUS_V1: use synchronous/v2 production rounds"
        )
    if isinstance(name, str) and name in ("synchronous", "sync", "synchronous/v2"):
        return SynchronousStrategy()
    raise ValueError(f"UNKNOWN_FACTORY_STRATEGY: {name!r}")
