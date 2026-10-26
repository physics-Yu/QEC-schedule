"""Bounded dynamic expansion into one static abstract case, without a device."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from modules.codes.contracts.event_probability import ProbabilityBranch

from .backend import EventBackendError, Occurrence, SeededEventBackend
from .model import AbstractComponent, CaseLimits, CaseResult, Invocation

_DEFAULT_LIMITS = CaseLimits()


def _identity(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return "@" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_graph(roots: tuple[Invocation, ...]) -> dict[str, list[str]]:
    ids = {root.invocation_id for root in roots}
    if len(ids) != len(roots) or any(name.startswith("@") for name in ids):
        raise ValueError("INVALID_CASE_INPUT: duplicate or reserved invocation ID")
    successors: dict[str, list[str]] = {name: [] for name in ids}
    remaining = {root.invocation_id: len(root.after) for root in roots}
    for root in roots:
        for predecessor in root.after:
            if predecessor not in ids:
                raise ValueError(f"INVALID_CASE_DEPENDENCY: unknown {predecessor!r}")
            successors[predecessor].append(root.invocation_id)
    frontier = [name for name, count in remaining.items() if not count]
    visited = 0
    while frontier:
        visited += 1
        for successor in successors[frontier.pop()]:
            remaining[successor] -= 1
            if not remaining[successor]:
                frontier.append(successor)
    if visited != len(roots):
        raise ValueError("INVALID_CASE_DEPENDENCY: dependency cycle")
    return {key: sorted(value) for key, value in successors.items()}


@dataclass
class _Node:
    invocation: Invocation
    parent: str | None = None
    attempt: int = 0
    completed: bool = False
    terminal_call: str = ""
    after_calls: tuple[str, ...] = ()
    call_index: int = -1
    event_index: int = -1
    branch: ProbabilityBranch | None = None
    next_step: int = 0


@dataclass
class _Engine:
    roots: tuple[Invocation, ...]
    catalog: dict[str, AbstractComponent]
    case_id: str
    seed: int
    limits: CaseLimits
    backend: SeededEventBackend
    successors: dict[str, list[str]]
    nodes: dict[str, _Node] = field(default_factory=dict)
    queue: list[tuple[float, str, int, str]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    deliveries: list[dict[str, Any]] = field(default_factory=list)
    failure: dict[str, Any] | None = None
    status: str = "complete"
    clock: float = 0.0
    serial: int = 0

    def enqueue(self, time: float, node: _Node, action: str) -> None:
        self.serial += 1
        heapq.heappush(
            self.queue, (time, node.invocation.invocation_id, self.serial, action)
        )

    def fail(
        self, code: str, node: _Node, detail: str, *, budget: bool = False
    ) -> None:
        self.status = "budget_exhausted" if budget else "failed"
        self.failure = {
            "code": code,
            "invocation_id": node.invocation.invocation_id,
            "attempt": node.attempt,
            "at_us": self.clock,
            "detail": detail,
        }

    def start(self, node: _Node) -> None:
        invocation = node.invocation
        component = self.catalog.get(invocation.component_id)
        if component is None:
            self.fail("UNSUPPORTED_COMPONENT", node, invocation.component_id)
            return
        if set(dict(invocation.bindings)) != set(component.participant_roles):
            self.fail("INVALID_PARTICIPANT_BINDING", node, invocation.component_id)
            return
        if len(self.calls) >= self.limits.max_expansions:
            self.fail(
                "EXPANSION_BUDGET_EXHAUSTED",
                node,
                "Body expansion limit reached",
                budget=True,
            )
            return
        exit_time = self.clock + component.exit_after_us
        ready_time = (
            None
            if component.result_ready_after_us is None
            else self.clock + component.result_ready_after_us
        )
        if not math.isfinite(exit_time) or (
            ready_time is not None and not math.isfinite(ready_time)
        ):
            self.fail("INVALID_CASE_TIME", node, "Accumulated time is not finite")
            return
        call_id = _identity(
            "call", self.case_id, invocation.invocation_id, node.attempt
        )
        node.call_index = len(self.calls)
        node.terminal_call = call_id
        self.calls.append(
            {
                "call_id": call_id,
                "invocation_id": invocation.invocation_id,
                "component_id": invocation.component_id,
                "attempt": node.attempt,
                "parent_invocation_id": node.parent,
                "bindings": dict(invocation.bindings),
                "after_calls": sorted(node.after_calls),
                "start_us": self.clock,
                "exit_at_us": exit_time,
                "event_available_at_us": ready_time,
            }
        )
        self.enqueue(max(exit_time, ready_time or 0.0), node, "release")

    def release(self, node: _Node) -> None:
        component = self.catalog[node.invocation.component_id]
        port = component.probability_port
        if port is None:
            self.finish(node)
            return
        call = self.calls[node.call_index]
        occurrence = Occurrence(
            self.case_id, node.invocation.invocation_id, node.attempt, port.port_id
        )
        try:
            result = self.backend.sample(
                port, occurrence, available_at_us=call["event_available_at_us"]
            )
        except EventBackendError as exc:
            self.fail("EVENT_BACKEND_FAILURE", node, str(exc))
            return
        outcome = port.outcome(result.outcome_key)
        node.branch = port.branch(outcome.branch_id)
        node.next_step = 0
        node.event_index = len(self.events)
        self.events.append(
            {
                **result.to_dict(),
                "call_id": call["call_id"],
                "values": dict(outcome.values),
                "branch_id": node.branch.key,
                "transition": node.branch.transition,
                "released_at_us": self.clock,
                "expanded_step_invocations": [],
            }
        )
        self.enqueue(self.clock, node, "advance")

    def advance(self, node: _Node) -> None:
        branch = node.branch
        assert branch is not None
        if node.next_step < len(branch.steps):
            self.expand_step(node, branch)
            return
        if branch.transition == "retry":
            if node.attempt + 1 >= node.invocation.max_attempts:
                self.fail(
                    "RETRY_BUDGET_EXHAUSTED",
                    node,
                    "All permitted attempts rejected",
                    budget=True,
                )
                return
            node.attempt += 1
            node.after_calls = (node.terminal_call,)
            self.enqueue(self.clock, node, "start")
            return
        if branch.transition == "deliver":
            event = self.events[node.event_index]
            self.deliveries.append(
                {
                    "invocation_id": node.invocation.invocation_id,
                    "attempt": node.attempt,
                    "ready_at_us": self.clock,
                    "bindings": dict(node.invocation.bindings),
                    "occurrence": event["occurrence"],
                    "port_sha256": event["port_sha256"],
                    "evidence_kind": "coarse_probability",
                    "quality_verified": False,
                }
            )
        self.finish(node)

    def expand_step(self, node: _Node, branch: ProbabilityBranch) -> None:
        step_index = node.next_step
        step = branch.steps[step_index]
        component = self.catalog.get(step.component_id)
        if component is None:
            self.fail("UNSUPPORTED_COMPONENT", node, step.component_id)
            return
        parent_bindings = dict(node.invocation.bindings)
        if len(step.participant_roles) != len(component.participant_roles) or any(
            role not in parent_bindings for role in step.participant_roles
        ):
            self.fail(
                "INVALID_PARTICIPANT_BINDING",
                node,
                f"Branch {branch.key!r}, step {step_index}",
            )
            return
        child_id = _identity(
            "step", node.invocation.invocation_id, node.attempt, branch.key, step_index
        )
        bindings = tuple(
            zip(
                component.participant_roles,
                (parent_bindings[role] for role in step.participant_roles),
                strict=True,
            )
        )
        child = _Node(
            Invocation(
                child_id,
                step.component_id,
                bindings,
                max_attempts=node.invocation.max_attempts,
            ),
            parent=node.invocation.invocation_id,
            after_calls=(node.terminal_call,),
        )
        self.nodes[child_id] = child
        node.next_step += 1
        self.events[node.event_index]["expanded_step_invocations"].append(child_id)
        self.enqueue(self.clock, child, "start")

    def finish(self, node: _Node) -> None:
        node.completed = True
        # Body exit and whole invocation completion are deliberately separate.
        self.calls[node.call_index]["invocation_completed_at_us"] = self.clock
        if node.parent is not None:
            parent = self.nodes[node.parent]
            parent.terminal_call = node.terminal_call
            self.enqueue(self.clock, parent, "advance")
            return
        for successor in self.successors[node.invocation.invocation_id]:
            target = self.nodes[successor]
            predecessors = [self.nodes[name] for name in target.invocation.after]
            if all(predecessor.completed for predecessor in predecessors):
                target.after_calls = tuple(
                    predecessor.terminal_call for predecessor in predecessors
                )
                self.enqueue(self.clock, target, "start")

    def run(self) -> CaseResult:
        self.nodes = {root.invocation_id: _Node(root) for root in self.roots}
        for root in self.roots:
            if not root.after:
                self.enqueue(0.0, self.nodes[root.invocation_id], "start")
        actions = {
            "start": self.start,
            "release": self.release,
            "advance": self.advance,
        }
        while self.queue and self.failure is None:
            self.clock, invocation_id, _, action = heapq.heappop(self.queue)
            actions[action](self.nodes[invocation_id])
        return self.export()

    def export(self) -> CaseResult:
        unresolved = sorted(
            name for name, node in self.nodes.items() if not node.completed
        )
        assert self.failure is not None or not unresolved
        duration = max(
            [self.clock]
            + [
                max(call["exit_at_us"], call["event_available_at_us"] or 0.0)
                for call in self.calls
            ]
        )
        document = {
            "schema": "nadit.abstract_case/1",
            "artifact_kind": "abstract_case",
            "case_id": self.case_id,
            "seed": self.seed,
            "backend_kind": "coarse_probability",
            "status": self.status,
            "execution_ready": False,
            "physical_validation": "not_run",
            "frame_status": "unresolved",
            "timing_model": "declared_offsets_and_dependencies",
            "resource_scheduling": "not_performed",
            "duration_us": duration,
            "processed_until_us": self.clock,
            "limits": {"max_expansions": self.limits.max_expansions},
            "roots": [
                {
                    "invocation_id": root.invocation_id,
                    "component_id": root.component_id,
                    "bindings": dict(root.bindings),
                    "after": list(root.after),
                    "max_attempts": root.max_attempts,
                }
                for root in self.roots
            ],
            "components": [
                {
                    "component_id": component.component_id,
                    "participant_roles": list(component.participant_roles),
                    "exit_after_us": component.exit_after_us,
                    "result_ready_after_us": component.result_ready_after_us,
                    "port_sha256": None
                    if component.probability_port is None
                    else component.probability_port.content_sha256,
                }
                for component in sorted(
                    self.catalog.values(), key=lambda item: item.component_id
                )
            ],
            "calls": self.calls,
            "events": self.events,
            "deliveries": self.deliveries,
            "probability_models": {
                component.probability_port.content_sha256: component.probability_port.to_dict()
                for component in self.catalog.values()
                if component.probability_port is not None
            },
            "probability_models_usage": "evidence_only",
            "unresolved_invocations": unresolved,
            "failure": self.failure,
        }
        return CaseResult(
            json.dumps(
                document,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        )


def compile_case(
    invocations: Iterable[Invocation],
    *,
    components: Iterable[AbstractComponent],
    case_id: str,
    seed: int,
    limits: CaseLimits = _DEFAULT_LIMITS,
    mode: str = "abstract",
    backend_kind: str = "coarse_probability",
) -> CaseResult:
    """Expand a dependency DAG with selected protocol continuations and retries.

    Args:
        invocations: Root calls with explicit dependencies and finite attempt budgets.
        components: Caller-supplied abstract bodies and code-owned probability ports.
        case_id: Stable case identity used by the seeded backend.
        seed: Integer selecting one reproducible static case.
        limits: Global expansion bound, including recursive continuations.
        mode: Only abstract mode is supported.
        backend_kind: Only coarse_probability is supported.

    Returns:
        Immutable complete or partial case with a selected call DAG, event evidence
        and causal timing. Failure or exhaustion never produces complete status.

    Raises:
        ValueError: Unsupported mode, invalid case inputs or malformed root DAG.
        Runtime capability/budget failures are retained in the returned artifact.

    Independent roots may overlap abstractly. No resource, participant-exclusivity
    or device checks are performed. AOD quantity belongs to a future device adapter.
    """
    if mode != "abstract" or backend_kind != "coarse_probability":
        raise ValueError(f"UNSUPPORTED_CASE_MODE: {mode!r}, backend {backend_kind!r}")
    backend = SeededEventBackend(case_id, seed, backend_kind=backend_kind)
    roots = tuple(sorted(invocations, key=lambda item: item.invocation_id))
    catalog: dict[str, AbstractComponent] = {}
    for component in components:
        if component.component_id in catalog:
            raise ValueError(
                f"INVALID_CASE_INPUT: duplicate component {component.component_id!r}"
            )
        catalog[component.component_id] = component
    successors = _validate_graph(roots)
    return _Engine(roots, catalog, case_id, seed, limits, backend, successors).run()
