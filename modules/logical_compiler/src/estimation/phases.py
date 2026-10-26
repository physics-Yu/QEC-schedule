"""Bounded resource scheduling inside one homogeneous component wave.

No atom objects, compiler calls, probability sampling or factory state machines.
The existing cooperative runtime remains responsible for wave-to-wave progress.
"""

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import Any

from modules.codes.contracts.parallel import ComponentPhase

from .metrics import interval_union_us


@dataclass(frozen=True)
class PhaseInvocation:
    """An existing component invocation with already instantiated stage costs."""

    invocation_id: str
    code_id: str
    component_id: str
    stages: tuple[ComponentPhase, ...]

    def __post_init__(self) -> None:
        if (
            not all(
                isinstance(s, str) and s
                for s in (self.invocation_id, self.code_id, self.component_id)
            )
            or not isinstance(self.stages, tuple)
            or not self.stages
            or not all(isinstance(p, ComponentPhase) for p in self.stages)
        ):
            raise ValueError("INVALID_PHASE_INVOCATION")
        held: set[str] = set()
        for phase in self.stages:
            if held.intersection(phase.acquire):
                raise ValueError("DUPLICATE_PHASE_LEASE")
            held.update(phase.acquire)
            if not set(phase.release) <= held:
                raise ValueError("UNKNOWN_PHASE_LEASE_RELEASE")
            held.difference_update(phase.release)
        if held:
            raise ValueError("UNRELEASED_PHASE_LEASE")


@dataclass(frozen=True)
class PhaseSchedule:
    """Relative-time object evidence; not an atom-execution certificate."""

    duration_us: float
    steps: tuple[dict[str, Any], ...]
    waits: tuple[dict[str, Any], ...]
    measurements: dict[str, tuple[tuple[float, float], ...]]
    resource_busy_us: dict[str, float]


def schedule_phases(
    members: tuple[PhaseInvocation, ...], *, timeout_seconds: float = 5.0
) -> PhaseSchedule:
    """Schedule equal components with exclusive channels and persistent leases.

    Disjoint resources may overlap within this wave. Equal certified commands
    execute once for all members. Incompatible AOD users wait through Store.
    Raises ValueError for mixed components, malformed claims or a deadlock;
    TimeoutError includes the unfinished stage and elapsed budget. No partial
    schedule is returned as success.
    """
    if not members or len({m.invocation_id for m in members}) != len(members):
        raise ValueError("INVALID_PHASE_WAVE_MEMBERS")
    if len({(m.code_id, m.component_id) for m in members}) != 1:
        raise ValueError("HETEROGENEOUS_OBJECT_WAVE_FORBIDDEN")
    if (
        type(timeout_seconds) not in (int, float)
        or not isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        raise ValueError("INVALID_OBJECT_WAVE_TIMEOUT")
    started = perf_counter()
    items = {m.invocation_id: m for m in members}
    cursor = dict.fromkeys(items, 0)
    ready = dict.fromkeys(items, 0.0)
    blockers: dict[str, set[str]] = defaultdict(set)
    running: list[tuple[float, tuple[str, ...], ComponentPhase]] = []
    leases: dict[str, tuple[str, ...]] = {}
    busy: set[str] = set()
    intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    lease_start: dict[str, float] = {}
    steps: list[dict[str, Any]] = []
    waits: list[dict[str, Any]] = []
    results: dict[str, list[tuple[float, float]]] = {key: [] for key in items}
    now = 0.0

    def phase(key: str) -> ComponentPhase:
        return items[key].stages[cursor[key]]

    def signature(key: str) -> tuple[ComponentPhase, ...]:
        # An acquired shared lease must have the same complete continuation.
        remaining = items[key].stages[cursor[key] :]
        return remaining if phase(key).acquire else (phase(key),)

    while any(cursor[key] < len(item.stages) for key, item in items.items()):
        if perf_counter() - started >= timeout_seconds:
            timed_out = {
                key: phase(key).name
                for key, item in items.items()
                if cursor[key] < len(item.stages)
            }
            raise TimeoutError(
                f"object_wave budget={timeout_seconds}s exceeded; pending={timed_out}"
            )
        for finish, group, current in tuple(running):
            if finish > now:
                continue
            running.remove((finish, group, current))
            busy.difference_update(current.resources)
            for resource in current.release:
                if leases.get(resource) != group:
                    raise ValueError("PHASE_LEASE_OWNER_CHANGED")
                del leases[resource]
                intervals[resource].append((lease_start.pop(resource), now))
            for key in group:
                cursor[key] += 1
                ready[key] = now
        active = {key for _, group, _ in running for key in group}
        pending = [
            key
            for key, item in items.items()
            if key not in active and cursor[key] < len(item.stages)
        ]
        launched: set[str] = set()
        for key in pending:
            if key in launched:
                continue
            current = phase(key)
            group = tuple(
                other
                for other in pending
                if other not in launched
                and (
                    other == key
                    or (
                        current.batch_key is not None
                        and signature(other) == signature(key)
                    )
                )
            )
            conflicts = {
                r
                for r in current.resources
                if r in busy or (r in leases and leases[r] != group)
            }
            if conflicts:
                for member in group:
                    blockers[member].update(conflicts)
                continue
            for resource in current.acquire:
                leases[resource] = group
                lease_start[resource] = now
            end = now + current.duration_us
            steps.append(
                {
                    "phase": current.name,
                    "category": current.category,
                    "members": list(group),
                    "resources": list(current.resources),
                    "start_us": now,
                    "end_us": end,
                    "results": current.results,
                    "latency_us": current.latency_us,
                    "batch_certificate": current.batch_key,
                }
            )
            busy.update(current.resources)
            for resource in current.resources:
                intervals[resource].append((now, end))
            for member in group:
                if now > ready[member]:
                    waits.append(
                        {
                            "member": member,
                            "phase": current.name,
                            "start_us": ready[member],
                            "end_us": now,
                            "resources": sorted(blockers[member]),
                        }
                    )
                blockers[member].clear()
                results[member].extend(
                    (end, current.latency_us) for _ in range(current.results)
                )
            running.append((end, group, current))
            launched.update(group)
        if running:
            now = min(finish for finish, _, _ in running)
        elif any(cursor[key] < len(item.stages) for key, item in items.items()):
            raise ValueError(
                f"OBJECT_WAVE_DEADLOCK: pending={pending}; leases={leases}"
            )
    return PhaseSchedule(
        now,
        tuple(steps),
        tuple(waits),
        {key: tuple(value) for key, value in results.items()},
        {key: interval_union_us(value) for key, value in intervals.items()},
    )
