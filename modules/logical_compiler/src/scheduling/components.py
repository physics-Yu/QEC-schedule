"""Deterministic component frontiers; no binding, atom expansion or sampling.

Patch order follows submission order. Explicit call, event and token dependencies
add causal gates without a global last-call edge. A committed lockstep batch must
finish before another batch is admitted; asynchronous physical overlap is outside
this contract. Resource/token lifecycle transitions remain the caller's concern.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from math import isfinite
from typing import Any

from modules.codes.contracts.parallel import ComponentExecutionSpec

from .compatibility import compatible_specs


def _name(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"INVALID_SCHEDULE_INPUT: {field} must be nonempty")


def _names(values: tuple[str, ...], field: str) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"INVALID_SCHEDULE_INPUT: {field} must be a tuple")
    for value in values:
        _name(value, field)
    if len(set(values)) != len(values):
        raise ValueError(f"INVALID_SCHEDULE_INPUT: repeated {field}")


def _time(value: float) -> float:
    try:
        valid = type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("INVALID_SCHEDULE_TIME: expected finite nonnegative time")
    return float(value)


@dataclass(frozen=True, slots=True)
class ComponentNode:
    """One code-declared invocation and its scheduling prerequisites.

    Token dependencies assert readiness only, not reservation or consumption.
    Event/token keys are caller-owned stable identities. Lower priority numbers
    win, with stable ID as the tie-breaker. Invalid names, duplicate prerequisites
    or invalid times raise ValueError; incorrect record/container types raise
    TypeError.
    """

    id: str
    spec: ComponentExecutionSpec
    after_calls: tuple[str, ...] = ()
    event_dependencies: tuple[str, ...] = ()
    token_dependencies: tuple[str, ...] = ()
    not_before_us: float = 0
    priority: int = 0

    def __post_init__(self) -> None:
        _name(self.id, "node ID")
        if not isinstance(self.spec, ComponentExecutionSpec):
            raise TypeError("INVALID_COMPONENT_SPEC: expected execution claims")
        for field in ("after_calls", "event_dependencies", "token_dependencies"):
            _names(getattr(self, field), field)
        _time(self.not_before_us)
        if type(self.priority) is not int:
            raise ValueError("INVALID_COMPONENT_PRIORITY: expected an integer")

    def to_dict(self) -> dict[str, Any]:
        """Return independent JSON-ready declarations and effective dependencies."""
        return {
            "id": self.id,
            "spec": self.spec.to_dict(),
            "after_calls": list(self.after_calls),
            "event_dependencies": list(self.event_dependencies),
            "token_dependencies": list(self.token_dependencies),
            "not_before_us": self.not_before_us,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class Admission:
    """Immutable proposal bound to caller-supplied physical snapshot identity.

    This is a declaration-level decision, not proof of physical feasibility.
    The physical owner must verify snapshot_id before expanding or committing.
    Revision binds the proposal to one scheduler state, preventing stale commits.
    """

    batch_id: str
    nodes: tuple[ComponentNode, ...]
    start_us: float
    snapshot_id: str
    revision: int = 0

    def __post_init__(self) -> None:
        _name(self.batch_id, "batch ID")
        _name(self.snapshot_id, "snapshot ID")
        _time(self.start_us)
        if (
            not isinstance(self.nodes, tuple)
            or not self.nodes
            or any(not isinstance(node, ComponentNode) for node in self.nodes)
            or len({node.id for node in self.nodes}) != len(self.nodes)
            or type(self.revision) is not int
            or self.revision < 0
        ):
            raise ValueError(
                "INVALID_ADMISSION: immutable distinct nodes and revision required"
            )

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Return the exact ordered invocation IDs admitted together."""
        return tuple(node.id for node in self.nodes)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable declaration certificate without atom actions."""
        return {
            "batch_id": self.batch_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "start_us": self.start_us,
            "snapshot_id": self.snapshot_id,
            "revision": self.revision,
        }


def _validate_dag(
    nodes: dict[str, ComponentNode],
    existing: Mapping[str, ComponentNode] | None = None,
) -> None:
    """Validate new edges against an immutable previously accepted DAG.

    Existing nodes cannot refer to these new IDs: their dependencies were checked
    when inserted and their frozen records are never replaced. Consequently any
    newly introduced cycle lies entirely inside this submission.
    """
    remaining = {key: 0 for key in nodes}
    successors: dict[str, list[str]] = {key: [] for key in nodes}
    for node in nodes.values():
        for dependency in node.after_calls:
            if dependency in nodes:
                successors[dependency].append(node.id)
                remaining[node.id] += 1
            elif existing is None or dependency not in existing:
                raise ValueError(
                    f"UNKNOWN_DEPENDENCY: {node.id!r} needs {dependency!r}"
                )
    ready = [key for key, count in remaining.items() if not count]
    visited = 0
    while ready:
        visited += 1
        for successor in successors[ready.pop()]:
            remaining[successor] -= 1
            if not remaining[successor]:
                ready.append(successor)
    if visited != len(nodes):
        raise ValueError("DEPENDENCY_CYCLE: component calls are not acyclic")


class ComponentScheduler:
    """Own DAG progress and always fill a compatible frontier batch.

    The first ready node anchors a deterministic greedy batch. Every later ready
    node joins when the complete group's declared constraints permit it. Actual
    device capacities belong in execution claims, never a policy width override.
    This guarantees an inclusion-maximal batch, not a globally optimal schedule.
    Raises:
        ValueError: Policy, dependencies, readiness or state transitions are invalid.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, ComponentNode] = {}
        self._pending: set[str] = set()
        self._last_patch: dict[str, str] = {}
        self._completed: dict[str, float] = {}
        self._running: dict[str, float] = {}
        self._cancelled: dict[str, str] = {}
        self._events: dict[str, float] = {}
        self._tokens: dict[str, float] = {}
        self._admissions: list[Admission] = []
        self._revision = 0

    def add(self, *nodes: ComponentNode) -> tuple[ComponentNode, ...]:
        """Atomically append nodes, deriving only same-patch ordering edges.

        The supplied order is semantic order for repeated patches. Explicit call
        predecessors must exist or occur in this submission. Returns the stored
        nodes with inferred predecessors; duplicates and cycles raise ValueError.
        A non-ComponentNode argument raises TypeError without changing the graph.
        """
        proposed: dict[str, ComponentNode] = {}
        last = dict(self._last_patch)
        added = []
        for node in nodes:
            if not isinstance(node, ComponentNode):
                raise TypeError("INVALID_COMPONENT_NODE: expected ComponentNode")
            if node.id in proposed or node.id in self._nodes:
                raise ValueError(f"DUPLICATE_NODE: {node.id!r}")
            predecessors = set(node.after_calls)
            predecessors.update(
                last[patch] for patch in node.spec.participant_blocks if patch in last
            )
            stored = replace(node, after_calls=tuple(sorted(predecessors)))
            proposed[node.id] = stored
            last.update((patch, node.id) for patch in node.spec.participant_blocks)
            added.append(stored)
        _validate_dag(proposed, self._nodes)
        if added:
            self._nodes.update(proposed)
            self._pending.update(proposed)
            self._last_patch = last
            self._revision += 1
        return tuple(added)

    def frontier(self, now_us: float) -> tuple[ComponentNode, ...]:
        """Return ready unstarted nodes sorted by priority and stable ID.

        Frontier membership does not promise resource compatibility or capacity.
        Pending prerequisites are absent until their declared availability time.
        """
        now = _time(now_us)
        return tuple(
            node
            for node in sorted(
                (self._nodes[key] for key in self._pending),
                key=lambda item: (item.priority, item.id),
            )
            if node.not_before_us <= now
            and all(
                self._completed.get(key, float("inf")) <= now
                for key in node.after_calls
            )
            and all(
                self._events.get(key, float("inf")) <= now
                for key in node.event_dependencies
            )
            and all(
                self._tokens.get(key, float("inf")) <= now
                for key in node.token_dependencies
            )
        )

    def admit(self, now_us: float, *, snapshot_id: str) -> Admission | None:
        """Choose a batch without mutating progress, binding or expanding bodies.

        A running lockstep batch blocks further admissions. Shared patches,
        exclusive resources or closed space envelopes block grouping. Shared AOD
        claims require compatible rows/columns and aggregate grid/readout capacity.
        Matching components may name multiple ordered participants. Local Pauli
        families can group different corrections without a transport claim.
        Unknown/exclusive declarations run alone. Repeated calls return the same
        proposal; the caller owns the physical meaning of snapshot_id.
        """
        now = _time(now_us)
        _name(snapshot_id, "snapshot ID")
        if self._running:
            return None
        if self._completed and now < max(self._completed.values()):
            raise ValueError("SCHEDULE_TIME_REVERSED: admission precedes completion")
        candidates = self.frontier(now)
        if not candidates:
            return None
        if candidates[
            0
        ].spec.parallel_mode == "shared_aod_lockstep" and not compatible_specs(
            (candidates[0].spec,)
        ):
            raise ValueError(
                "INVALID_SHARED_AOD_DECLARATION: singleton violates claims"
            )
        selected = [candidates[0]]
        for node in candidates[1:]:
            if compatible_specs(tuple(member.spec for member in (*selected, node))):
                selected.append(node)
        payload = {
            "nodes": [node.to_dict() for node in selected],
            "start_us": now,
            "snapshot_id": snapshot_id,
            "revision": self._revision,
        }
        digest = sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        return Admission(
            "components/" + digest, tuple(selected), now, snapshot_id, self._revision
        )

    def commit_admission(self, admission: Admission) -> None:
        """Mark an unchanged proposal running; reject stale or altered proposals.

        The caller coordinates this transition with its physical transaction.
        This method neither verifies nor mutates the external physical snapshot.
        """
        if not isinstance(admission, Admission):
            raise TypeError("INVALID_ADMISSION: expected Admission")
        if admission.revision != self._revision:
            raise ValueError("STALE_ADMISSION: scheduler state changed")
        if admission != self.admit(
            admission.start_us, snapshot_id=admission.snapshot_id
        ):
            raise ValueError("INVALID_ADMISSION: proposal differs from current choice")
        self._running.update((node.id, admission.start_us) for node in admission.nodes)
        self._pending.difference_update(admission.node_ids)
        self._admissions.append(admission)
        self._revision += 1

    def mark_completed(self, node_id: str, end_us: float) -> None:
        """Finish a committed invocation, publishing its actual physical exit.

        Repeating the same completion is harmless. Unknown/unstarted calls,
        changed completion times or exits preceding admission raise ValueError.
        """
        end = _time(end_us)
        if node_id in self._completed:
            if self._completed[node_id] != end:
                raise ValueError(f"COMPLETION_CHANGED: {node_id!r}")
            return
        if node_id not in self._running:
            raise ValueError(f"NOT_RUNNING: {node_id!r}")
        if end < self._running[node_id]:
            raise ValueError(f"COMPLETION_BEFORE_START: {node_id!r}")
        self._completed[node_id] = end
        del self._running[node_id]
        self._revision += 1

    def cancel_pending(self, node_ids: tuple[str, ...], *, reason: str) -> None:
        """Atomically cancel unstarted work without fabricating completion.

        Dependents remain blocked unless separately cancelled. Running/completed
        nodes and unknown identities are rejected before any change. Repeating
        an identical cancellation is harmless; changing its reason is rejected.
        Physical/resource cleanup belongs to the caller, not this DAG operation.
        """
        _names(node_ids, "cancellation nodes")
        _name(reason, "cancellation reason")
        for node_id in node_ids:
            if node_id not in self._nodes:
                raise ValueError(f"UNKNOWN_CANCELLATION_NODE: {node_id!r}")
            if node_id in self._running or node_id in self._completed:
                raise ValueError(f"CANNOT_CANCEL_STARTED_NODE: {node_id!r}")
            if node_id in self._cancelled and self._cancelled[node_id] != reason:
                raise ValueError(f"CANCELLATION_CHANGED: {node_id!r}")
        if any(node_id not in self._cancelled for node_id in node_ids):
            self._cancelled.update((node_id, reason) for node_id in node_ids)
            self._pending.difference_update(node_ids)
            self._revision += 1

    def _release(self, target: dict[str, float], key: str, ready_at_us: float) -> None:
        _name(key, "readiness identity")
        ready = _time(ready_at_us)
        if key in target:
            if target[key] != ready:
                raise ValueError(f"READINESS_CHANGED: {key!r}")
            return
        target[key] = ready
        self._revision += 1

    def release_event(self, key: str, ready_at_us: float) -> None:
        """Publish an event's actual release time; never sample or invent bits."""
        self._release(self._events, key, ready_at_us)

    def release_token(self, key: str, ready_at_us: float) -> None:
        """Publish token readiness without reserving, consuming or issuing it."""
        self._release(self._tokens, key, ready_at_us)

    def snapshot(self) -> dict[str, Any]:
        """Return fresh JSON evidence for the graph, committed batches and progress.

        Uncommitted proposals are absent. Readiness records contain caller-owned
        identities/times only, not event outcomes or resource-quality claims.
        """
        return {
            "schema": "nadit.component_schedule/1",
            "policy": {"batching": "maximal_compatible_frontier"},
            "revision": self._revision,
            "nodes": [self._nodes[key].to_dict() for key in sorted(self._nodes)],
            "admissions": [admission.to_dict() for admission in self._admissions],
            "completed": dict(sorted(self._completed.items())),
            "running": dict(sorted(self._running.items())),
            "cancelled": dict(sorted(self._cancelled.items())),
            "event_releases": dict(sorted(self._events.items())),
            "token_releases": dict(sorted(self._tokens.items())),
        }
