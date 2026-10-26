"""Portable immutable event-probability definitions, without runtime sampling."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from math import fsum, isfinite
from typing import Any, ClassVar, cast

SCHEMA = "nadit.event_probability/1"
MODEL_KINDS = frozenset(("ideal_exact", "pauli_exact", "estimated", "test_fixture"))
TRANSITIONS = frozenset(("continue", "deliver", "retry"))
PROBABILITY_TOLERANCE = 1e-12
type JSONScalar = str | int | float | bool | None


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a nonempty string.")
    return value


def _object(
    value: object, path: str, fields: tuple[str, ...] | None = None
) -> dict[str, Any]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError(f"{path} must be a JSON object with string keys.")
    if fields is not None and set(value) != set(fields):
        raise ValueError(
            f"{path} must contain exactly these fields: {', '.join(fields)}."
        )
    return cast(dict[str, Any], value)


def _array(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a JSON array.")
    return value


def _scalar(value: object, path: str) -> JSONScalar:
    if value is None or type(value) in (str, int, bool):
        return cast(JSONScalar, value)
    if type(value) is float and isfinite(value):
        return value
    raise ValueError(f"{path} must be a finite JSON scalar.")


def _finite_json(value: object, path: str, active: set[int] | None = None) -> None:
    if not isinstance(value, dict | list):
        _scalar(value, path)
        return
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise ValueError(f"{path} contains a JSON reference cycle.")
    active.add(identity)
    if isinstance(value, dict):
        for key, child in _object(value, path).items():
            _finite_json(child, f"{path}.{key}", active)
    else:
        for index, child in enumerate(value):
            _finite_json(child, f"{path}[{index}]", active)
    active.remove(identity)


def _validate_model(value: object) -> None:
    model = _object(
        value, "model", ("id", "kind", "assumptions", "parameters", "evidence")
    )
    _text(model["id"], "model.id")
    if _text(model["kind"], "model.kind") not in MODEL_KINDS:
        raise ValueError("model.kind is not a supported probability-model kind.")
    for index, assumption in enumerate(
        _array(model["assumptions"], "model.assumptions")
    ):
        _text(assumption, f"model.assumptions[{index}]")
    for key in ("parameters", "evidence"):
        _finite_json(_object(model[key], f"model.{key}"), f"model.{key}")


@dataclass(frozen=True, slots=True)
class BranchStep:
    """A sequential continuation component with late-bound participant roles."""

    component_id: str
    participant_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProbabilityBranch:
    """Run ordered steps, then continue, deliver, or request a fresh retry."""

    key: str
    transition: str
    steps: tuple[BranchStep, ...]


@dataclass(frozen=True, slots=True)
class ProbabilityOutcome:
    """One finite joint event and its local continuation, without a sampled bit."""

    key: str
    probability: float
    values: tuple[tuple[str, JSONScalar], ...]
    branch_id: str


def _branches(value: object) -> tuple[ProbabilityBranch, ...]:
    branches = []
    seen: set[str] = set()
    for index, raw in enumerate(_array(value, "branches")):
        path = f"branches[{index}]"
        item = _object(raw, path, ("key", "transition", "steps"))
        key = _text(item["key"], f"{path}.key")
        if key in seen:
            raise ValueError(f"Duplicate branch key {key!r}.")
        seen.add(key)
        transition = _text(item["transition"], f"{path}.transition")
        if transition not in TRANSITIONS:
            raise ValueError(f"{path}.transition is unsupported.")
        steps = []
        for step_index, raw_step in enumerate(_array(item["steps"], f"{path}.steps")):
            step_path = f"{path}.steps[{step_index}]"
            step = _object(raw_step, step_path, ("component_id", "participant_roles"))
            component_id = _text(step["component_id"], f"{step_path}.component_id")
            roles = tuple(
                _text(role, f"{step_path}.participant_roles[{role_index}]")
                for role_index, role in enumerate(
                    _array(step["participant_roles"], f"{step_path}.participant_roles")
                )
            )
            if len(set(roles)) != len(roles):
                raise ValueError(f"{step_path} repeats a participant role.")
            steps.append(BranchStep(component_id, roles))
        branches.append(ProbabilityBranch(key, transition, tuple(steps)))
    return tuple(branches)


def _outcomes(value: object, branch_keys: set[str]) -> tuple[ProbabilityOutcome, ...]:
    outcomes = []
    seen: set[str] = set()
    value_fields: set[str] | None = None
    for index, raw in enumerate(_array(value, "outcomes")):
        path = f"outcomes[{index}]"
        item = _object(raw, path, ("key", "probability", "values", "branch_id"))
        key = _text(item["key"], f"{path}.key")
        if key in seen:
            raise ValueError(f"Duplicate outcome key {key!r}.")
        seen.add(key)
        probability = item["probability"]
        if type(probability) not in (int, float) or not 0 <= probability <= 1:
            raise ValueError(f"{path}.probability must be a finite number in [0, 1].")
        if not isfinite(probability):
            raise ValueError(f"{path}.probability must be finite.")
        values = _object(item["values"], f"{path}.values")
        if value_fields is not None and set(values) != value_fields:
            raise ValueError("All outcomes must have the same joint value fields.")
        value_fields = set(values)
        pairs = tuple(
            (_text(name, f"{path}.values key"), _scalar(v, f"{path}.values.{name}"))
            for name, v in sorted(values.items())
        )
        branch_id = _text(item["branch_id"], f"{path}.branch_id")
        if branch_id not in branch_keys:
            raise ValueError(f"{path} references unknown branch {branch_id!r}.")
        outcomes.append(ProbabilityOutcome(key, float(probability), pairs, branch_id))
    if abs(fsum(o.probability for o in outcomes) - 1) > PROBABILITY_TOLERANCE:
        raise ValueError("Outcome probabilities must sum to one within 1e-12.")
    return tuple(outcomes)


@dataclass(frozen=True, slots=True, init=False)
class ProbabilityPort:
    """Validated immutable v1 document; no case state or sampling implementation.

    Model metadata is retained as canonical JSON, so nested caller-owned arrays
    and objects cannot mutate the definition or its fingerprint after validation.
    """

    port_id: str
    protocol_id: str
    protocol_version: str
    outcomes: tuple[ProbabilityOutcome, ...]
    branches: tuple[ProbabilityBranch, ...]
    _document_json: str = field(repr=False)
    schema: ClassVar[str] = SCHEMA

    def __init__(self, document: Mapping[str, object]) -> None:
        """Validate all v1 fields and retain immutable records and canonical JSON."""
        if not isinstance(document, Mapping):
            raise ValueError("Probability port must be a JSON object.")
        item = _object(
            dict(document),
            "port",
            (
                "schema",
                "port_id",
                "protocol_id",
                "protocol_version",
                "model",
                "outcomes",
                "branches",
            ),
        )
        if item["schema"] != SCHEMA:
            raise ValueError(f"Expected schema {SCHEMA!r}.")
        for name in ("port_id", "protocol_id", "protocol_version"):
            object.__setattr__(self, name, _text(item[name], name))
        _validate_model(item["model"])
        branches = _branches(item["branches"])
        outcomes = _outcomes(item["outcomes"], {b.key for b in branches})
        encoded = json.dumps(
            item, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "branches", branches)
        object.__setattr__(self, "_document_json", encoded)

    @classmethod
    def from_dict(cls, document: Mapping[str, object]) -> "ProbabilityPort":
        """Return an immutable validated port, or raise ValueError for invalid data."""
        return cls(document)

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-compatible document, including independent metadata."""
        return cast(dict[str, Any], json.loads(self._document_json))

    @property
    def content_sha256(self) -> str:
        """Hash the complete sorted-key compact JSON document without normalization."""
        return sha256(self._document_json.encode("utf-8")).hexdigest()

    def outcome(self, key: str) -> ProbabilityOutcome:
        """Return an outcome by its unique key, or raise KeyError."""
        for outcome in self.outcomes:
            if outcome.key == key:
                return outcome
        raise KeyError(key)

    def branch(self, key: str) -> ProbabilityBranch:
        """Return a continuation branch by its unique key, or raise KeyError."""
        for branch in self.branches:
            if branch.key == key:
                return branch
        raise KeyError(key)
