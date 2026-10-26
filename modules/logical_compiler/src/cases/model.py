"""Explicit inputs and immutable output of abstract protocol-case expansion."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from modules.codes.contracts.event_probability import ProbabilityPort


def _name(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"INVALID_CASE_INPUT: {field} must be a nonempty string")


def _time(value: float, field: str) -> None:
    try:
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (float, int))
            and math.isfinite(value)
            and value >= 0
        )
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"INVALID_CASE_INPUT: {field} must be finite and nonnegative")


def _positive_integer(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"INVALID_CASE_INPUT: {field} must be a positive integer")


@dataclass(frozen=True)
class AbstractComponent:
    """Describe an abstract body and its optional code-owned event.

    Times are caller-declared offsets from body start, not physical estimates.
    An event requires an explicit result-ready offset, including processing
    latency. Participant roles define positional binding of continuation steps.
    Invalid identifiers, times or event/timing combinations raise ValueError.
    """

    component_id: str
    participant_roles: tuple[str, ...]
    exit_after_us: float
    probability_port: ProbabilityPort | None = None
    result_ready_after_us: float | None = None

    def __post_init__(self) -> None:
        _name(self.component_id, "component_id")
        roles = tuple(self.participant_roles)
        for role in roles:
            _name(role, "participant_role")
        if len(set(roles)) != len(roles):
            raise ValueError("INVALID_CASE_INPUT: duplicate participant roles")
        object.__setattr__(self, "participant_roles", roles)
        _time(self.exit_after_us, "exit_after_us")
        if self.probability_port is not None and not isinstance(
            self.probability_port, ProbabilityPort
        ):
            raise ValueError("INVALID_CASE_INPUT: expected a shared ProbabilityPort")
        if (self.probability_port is None) != (self.result_ready_after_us is None):
            raise ValueError(
                "INVALID_CASE_INPUT: event and result-ready offset required together"
            )
        if self.result_ready_after_us is not None:
            _time(self.result_ready_after_us, "result_ready_after_us")


@dataclass(frozen=True)
class Invocation:
    """Bind a component to participants and root-invocation dependencies.

    ``max_attempts`` includes the initial attempt and bounds every nested
    continuation's own attempts. IDs beginning with @ are reserved by the engine.
    Invalid names, duplicate bindings/dependencies or budgets raise ValueError.
    """

    invocation_id: str
    component_id: str
    bindings: tuple[tuple[str, str], ...]
    after: tuple[str, ...] = ()
    max_attempts: int = 1

    def __post_init__(self) -> None:
        _name(self.invocation_id, "invocation_id")
        _name(self.component_id, "component_id")
        bindings = tuple(tuple(pair) for pair in self.bindings)
        for pair in bindings:
            if len(pair) != 2:
                raise ValueError(
                    "INVALID_CASE_INPUT: bindings require role/participant pairs"
                )
            _name(pair[0], "binding role")
            _name(pair[1], "participant")
        if len({pair[0] for pair in bindings}) != len(bindings):
            raise ValueError("INVALID_CASE_INPUT: duplicate binding role")
        dependencies = tuple(self.after)
        for predecessor in dependencies:
            _name(predecessor, "predecessor")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("INVALID_CASE_DEPENDENCY: duplicate predecessor")
        _positive_integer(self.max_attempts, "max_attempts")
        object.__setattr__(self, "bindings", tuple(sorted(bindings)))
        object.__setattr__(self, "after", tuple(sorted(dependencies)))


@dataclass(frozen=True)
class CaseLimits:
    """Bound total body expansions, including retries and recursive steps.

    ``max_expansions`` must be a positive integer or construction raises ValueError.
    """

    max_expansions: int = 4096

    def __post_init__(self) -> None:
        _positive_integer(self.max_expansions, "max_expansions")


@dataclass(frozen=True)
class CaseResult:
    """Keep an immutable JSON snapshot of a complete or partial abstract case.

    Created by compile_case. Complete means all selected abstract invocations
    finished; it does not certify physical execution, frames or quantum states.
    """

    _document_json: str

    @property
    def status(self) -> str:
        """Return complete, failed or budget_exhausted."""
        return str(self.to_dict()["status"])

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-compatible copy, including model fingerprints."""
        document: dict[str, Any] = json.loads(self._document_json)
        return document

    def to_json(self) -> str:
        """Return canonical JSON suitable for byte-reproducible static export."""
        return self._document_json
