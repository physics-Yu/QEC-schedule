"""Metadata-only applicability keys and reusable component calibration records.

Providers declare which device fields and spectator envelope their model depends
on. This module checks and preserves those declarations; a cache hit does not
establish their physical completeness. It never compiles or samples a component.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from nadit_physical_compiler.device import Region

from ..placement import PlacementPlan, block_bounds

_KEY_SCHEMA = "nadit.calibration_applicability/1"
_CACHE_SCHEMA = "nadit.component_calibration_cache/1"


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"INVALID_CALIBRATION_CONTEXT: {label} must be nonempty")
    return value


def _json_value(value: Any) -> Any:
    """Normalize finite JSON without mutable references or signed-zero drift."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and isfinite(value):
        return 0.0 if value == 0 else value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("INVALID_CALIBRATION_JSON: string keys required")
        return {key: _json_value(child) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(child) for child in value]
    raise ValueError("INVALID_CALIBRATION_JSON: finite JSON values required")


def _json_object(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("INVALID_CALIBRATION_JSON: object required")
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))


def _bounds(region: Region, x: float = 0, y: float = 0) -> list[float]:
    if not isinstance(region, Region) or not all(
        type(v) in (int, float) and isfinite(v)
        for v in (region.x_min, region.y_min, region.x_max, region.y_max)
    ):
        raise ValueError("INVALID_CALIBRATION_REGION")
    if region.x_min > region.x_max or region.y_min > region.y_max:
        raise ValueError("INVALID_CALIBRATION_REGION")
    return [
        float(region.x_min - x),
        float(region.y_min - y),
        float(region.x_max - x),
        float(region.y_max - y),
    ]


def _validate_geometry(item: Any) -> None:
    expected = {
        "code",
        "distance",
        "origin",
        "orientation",
        "relative_bounds",
        "geometry_version",
        "minimum_spacing_um",
    }
    if not isinstance(item, Mapping) or set(item) != expected:
        raise ValueError("INCOMPLETE_CALIBRATION_GEOMETRY")
    for name in ("code", "orientation", "geometry_version"):
        _name(item[name], name)
    if type(item["distance"]) is not int or item["distance"] < 1:
        raise ValueError("INVALID_CALIBRATION_DISTANCE")
    for name, length in (("origin", 2), ("relative_bounds", 4)):
        value = item[name]
        if (
            not isinstance(value, (tuple, list))
            or len(value) != length
            or any(
                type(number) not in (int, float) or not isfinite(number)
                for number in value
            )
        ):
            raise ValueError("INVALID_CALIBRATION_GEOMETRY")
    bounds = item["relative_bounds"]
    if bounds[0] > bounds[2] or bounds[1] > bounds[3]:
        raise ValueError("INVALID_CALIBRATION_GEOMETRY")
    spacing = item["minimum_spacing_um"]
    if type(spacing) not in (int, float) or not isfinite(spacing) or spacing < 0:
        raise ValueError("INVALID_CALIBRATION_SPACING")


@dataclass(frozen=True, slots=True, init=False)
class CalibrationKey:
    """Immutable normalized applicability document; no global plan or N key."""

    _document_json: str

    def __init__(self, document: Mapping[str, Any]) -> None:
        """Freeze a complete applicability document; reject missing context."""
        expected = {
            "schema",
            "component",
            "participants",
            "parameters",
            "selection",
            "device",
            "spectator_scope",
            "influence_bounds",
            "scope_declaration",
            "spectators",
            "global_operation",
        }
        if set(document) != expected or document.get("schema") != _KEY_SCHEMA:
            raise ValueError("INVALID_CALIBRATION_KEY_SCHEMA")
        component = document["component"]
        if not isinstance(component, Mapping):
            raise TypeError("INVALID_CALIBRATION_COMPONENT")
        for key in ("id", "version", "fingerprint"):
            _name(component.get(key), "component " + key)
        if not document["participants"] or not isinstance(
            document["participants"], (list, tuple)
        ):
            raise ValueError("INVALID_CALIBRATION_PARTICIPANTS")
        if not isinstance(document["spectators"], (list, tuple)):
            raise TypeError("INVALID_CALIBRATION_SPECTATORS")
        for item in (*document["participants"], *document["spectators"]):
            _validate_geometry(item)
        if not isinstance(document["parameters"], Mapping) or not isinstance(
            document["selection"], Mapping
        ):
            raise TypeError("INVALID_CALIBRATION_PARAMETERS")
        if document["spectator_scope"] not in ("world", "local"):
            raise ValueError("INVALID_CALIBRATION_SCOPE")
        bounds = document["influence_bounds"]
        if bounds is not None:
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
                raise ValueError("INVALID_CALIBRATION_REGION")
            _bounds(Region(*bounds))
        if not isinstance(document["scope_declaration"], Mapping):
            raise TypeError("INVALID_CALIBRATION_SCOPE_DECLARATION")
        if type(document["global_operation"]) is not bool or (
            document["global_operation"] and document["spectator_scope"] != "world"
        ):
            raise ValueError("GLOBAL_CALIBRATION_REQUIRES_WORLD_SCOPE")
        device = document["device"]
        if (
            not isinstance(device, Mapping)
            or not {"control", "transport", "readout"} <= device.keys()
        ):
            raise ValueError("INCOMPLETE_CALIBRATION_DEVICE_CONTEXT")
        if document["spectator_scope"] == "local":
            declaration = document["scope_declaration"]
            if (
                not isinstance(declaration, Mapping)
                or document["influence_bounds"] is None
            ):
                raise ValueError("LOCAL_CALIBRATION_REQUIRES_SCOPE_DECLARATION")
            _name(declaration.get("provider"), "scope provider")
            _name(declaration.get("version"), "scope version")
        object.__setattr__(self, "_document_json", _json_object(document))

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> CalibrationKey:
        """Validate a serialized key, rejecting missing identity or scope fields."""
        return cls(document)

    @property
    def fingerprint(self) -> str:
        """Return the exact applicability SHA-256, independent of record cost."""
        return sha256(self._document_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Return an independent applicability document."""
        return dict(json.loads(self._document_json))


@dataclass(frozen=True, slots=True)
class CalibrationContext:
    """One lookup's key plus whole-plan provenance and actual participant IDs."""

    key: CalibrationKey
    geometry_fingerprint: str
    participants: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.key, CalibrationKey):
            raise TypeError("INVALID_CALIBRATION_KEY")
        _name(self.geometry_fingerprint, "placement fingerprint")
        if (
            not isinstance(self.participants, tuple)
            or not self.participants
            or len(set(self.participants)) != len(self.participants)
        ):
            raise ValueError("INVALID_CALIBRATION_PARTICIPANTS")
        for identity in self.participants:
            _name(identity, "participant")
        if len(self.key.to_dict()["participants"]) != len(self.participants):
            raise ValueError("CALIBRATION_PARTICIPANT_COUNT_MISMATCH")

    def to_dict(self) -> dict[str, Any]:
        """Return provenance without treating whole-plan identity as applicability."""
        return {
            "key": self.key.to_dict(),
            "key_fingerprint": self.key.fingerprint,
            "geometry_fingerprint": self.geometry_fingerprint,
            "participants": list(self.participants),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> CalibrationContext:
        """Read a stored context and verify the recorded key fingerprint."""
        key = CalibrationKey.from_dict(document["key"])
        if document.get("key_fingerprint") != key.fingerprint:
            raise ValueError("CALIBRATION_FINGERPRINT_MISMATCH")
        return cls(
            key, document["geometry_fingerprint"], tuple(document["participants"])
        )


def calibration_context(
    plan: PlacementPlan,
    participants: tuple[str, ...],
    *,
    component_id: str,
    component_version: str,
    component_fingerprint: str,
    device_context: Mapping[str, Any],
    parameters: Mapping[str, Any] | Sequence[tuple[str, Any]] = (),
    selection: Mapping[str, Any] | None = None,
    scope: Literal["world", "local"] = "world",
    influence_bounds: Region | None = None,
    scope_evidence: Mapping[str, Any] | None = None,
    global_operation: bool = False,
) -> CalibrationContext:
    """Build a key from placed participants and the provider's declared context.

    Device fields must explicitly include control, transport and readout; each
    may be None only when the provider declares that resource irrelevant. Their
    coordinate frame is provider-owned: pass relative geometry to permit joint
    translations, or absolute geometry when translation changes applicability.
    Local scope requires an absolute influence envelope and provider/version
    evidence. Intersecting spectator footprints are included conservatively.
    Global operations must use world scope. A scope declaration is not a proof
    that omitted spectators or device fields cannot affect a physical operation.
    No binding, physical compilation or probability sampling is performed.

    Raises ValueError for incomplete identities, participants, envelopes or JSON.
    """
    blocks = {block.block_id: block for block in plan.blocks}
    if (
        not isinstance(participants, tuple)
        or not participants
        or len(set(participants)) != len(participants)
        or not set(participants) <= blocks.keys()
    ):
        raise ValueError("INVALID_CALIBRATION_PARTICIPANTS")
    anchor = plan.placements[participants[0]].origin
    world_bounds: dict[str, list[float]] = {}
    items: dict[str, dict[str, Any]] = {}
    for identity, block in blocks.items():
        placement = plan.placements[identity]
        geometry = plan.geometries[block.code]
        local = _bounds(geometry.relative_bounds)
        bounds = _bounds(block_bounds(geometry, placement))
        world_bounds[identity] = bounds
        items[identity] = {
            "code": block.code,
            "distance": block.distance,
            "origin": [
                float(placement.origin.x - anchor.x),
                float(placement.origin.y - anchor.y),
            ],
            "orientation": placement.orientation,
            "relative_bounds": local,
            "geometry_version": geometry.version,
            "minimum_spacing_um": float(geometry.minimum_spacing_um),
        }
    if influence_bounds is not None:
        influence = _bounds(influence_bounds)
        for identity in participants:
            b = world_bounds[identity]
            if not (
                influence[0] <= b[0] <= b[2] <= influence[2]
                and influence[1] <= b[1] <= b[3] <= influence[3]
            ):
                raise ValueError("CALIBRATION_ENVELOPE_EXCLUDES_PARTICIPANT")
    elif scope == "local":
        raise ValueError("LOCAL_CALIBRATION_REQUIRES_SCOPE_DECLARATION")
    spectators = []
    for identity, item in items.items():
        if identity in participants:
            continue
        b = world_bounds[identity]
        if (
            scope == "local"
            and influence_bounds is not None
            and (
                b[2] < influence_bounds.x_min
                or b[0] > influence_bounds.x_max
                or b[3] < influence_bounds.y_min
                or b[1] > influence_bounds.y_max
            )
        ):
            continue
        spectators.append(item)
    pairs = (
        list(parameters.items())
        if isinstance(parameters, Mapping)
        else list(parameters)
    )
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("DUPLICATE_CALIBRATION_PARAMETER")
    key = CalibrationKey.from_dict(
        {
            "schema": _KEY_SCHEMA,
            "component": {
                "id": component_id,
                "version": component_version,
                "fingerprint": component_fingerprint,
            },
            "participants": [items[identity] for identity in participants],
            "parameters": values,
            "selection": dict(selection or {}),
            "device": device_context,
            "spectator_scope": scope,
            "influence_bounds": None
            if influence_bounds is None
            else _bounds(influence_bounds, anchor.x, anchor.y),
            "scope_declaration": dict(scope_evidence or {}),
            "spectators": sorted(spectators, key=_json_object),
            "global_operation": global_operation,
        }
    )
    return CalibrationContext(key, plan.geometry_fingerprint, participants)


@dataclass(frozen=True, slots=True, init=False)
class CalibrationRecord:
    """Frozen cost/model payload and evidence from one completed calibration."""

    context: CalibrationContext
    _payload_json: str
    _evidence_json: str

    def __init__(
        self,
        context: CalibrationContext,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> None:
        if not isinstance(context, CalibrationContext):
            raise TypeError("INVALID_CALIBRATION_CONTEXT")
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "_payload_json", _json_object(payload))
        object.__setattr__(self, "_evidence_json", _json_object(evidence))

    @property
    def payload(self) -> dict[str, Any]:
        """Return an independent cost/model payload, never an Atom IR expansion."""
        return dict(json.loads(self._payload_json))

    @property
    def evidence(self) -> dict[str, Any]:
        """Return the producer's recorded evidence without strengthening claims."""
        return dict(json.loads(self._evidence_json))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the original calibration context and immutable evidence."""
        return {
            "context": self.context.to_dict(),
            "payload": self.payload,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> CalibrationRecord:
        """Read a record, rejecting a changed applicability fingerprint."""
        return cls(
            CalibrationContext.from_dict(document["context"]),
            document["payload"],
            document["evidence"],
        )


@dataclass(frozen=True, slots=True)
class CalibrationMiss:
    """Explicit missing work for a separate calibration pipeline, never a fallback."""

    reason: str
    key: CalibrationKey
    geometry_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready request retaining the caller's actual plan identity."""
        return {
            "reason": self.reason,
            "key": self.key.to_dict(),
            "key_fingerprint": self.key.fingerprint,
            "geometry_fingerprint": self.geometry_fingerprint,
        }


class MissingCalibration(ValueError):
    """A required context was not calibrated; the caller may queue explicit work."""

    def __init__(self, missing: CalibrationMiss) -> None:
        self.missing = missing
        super().__init__(f"MISSING_CALIBRATION: {missing.key.fingerprint}")


class CalibrationCache:
    """Exact applicability lookup with deterministic serialization and no compiler."""

    def __init__(self, records: Iterable[CalibrationRecord] = ()) -> None:
        self._records: dict[str, CalibrationRecord] = {}
        for record in records:
            self.put(record)

    def put(self, record: CalibrationRecord) -> None:
        """Insert a record, rejecting different payloads for the same applicability.

        Equivalent costs may have different producer evidence; the first record
        is retained, including its original plan fingerprint. Replacing a model
        requires a changed component/model identity in the context.
        """
        if not isinstance(record, CalibrationRecord):
            raise TypeError("INVALID_CALIBRATION_RECORD")
        key = record.context.key.fingerprint
        previous = self._records.get(key)
        if previous is not None and (
            previous.context.key != record.context.key
            or previous.payload != record.payload
        ):
            raise ValueError(f"CONFLICTING_CALIBRATION: {key}")
        self._records.setdefault(key, record)

    def lookup(
        self, context: CalibrationContext
    ) -> CalibrationRecord | CalibrationMiss:
        """Return an exact record or a structured miss without compiling anything."""
        return self._records.get(context.key.fingerprint) or CalibrationMiss(
            "not_calibrated", context.key, context.geometry_fingerprint
        )

    def require(self, context: CalibrationContext) -> CalibrationRecord:
        """Return a record or raise MissingCalibration with the requested context."""
        result = self.lookup(context)
        if isinstance(result, CalibrationMiss):
            raise MissingCalibration(result)
        return result

    def to_dict(self) -> dict[str, Any]:
        """Return a stable snapshot ordered by applicability fingerprint."""
        return {
            "schema": _CACHE_SCHEMA,
            "records": [self._records[key].to_dict() for key in sorted(self._records)],
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> CalibrationCache:
        """Load an audited cache snapshot, rejecting schema/key/cost conflicts."""
        if (
            set(document) != {"schema", "records"}
            or document.get("schema") != _CACHE_SCHEMA
            or not isinstance(document.get("records"), list)
        ):
            raise ValueError("INVALID_CALIBRATION_CACHE_SCHEMA")
        return cls(CalibrationRecord.from_dict(item) for item in document["records"])

    def save(self, path: str | Path) -> None:
        """Atomically save finite JSON; a failed write leaves the prior cache intact."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=target.name + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(_json_object(self.to_dict()) + "\n")
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @classmethod
    def load(cls, path: str | Path) -> CalibrationCache:
        """Read a UTF-8 cache; no missing entry triggers physical compilation."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
