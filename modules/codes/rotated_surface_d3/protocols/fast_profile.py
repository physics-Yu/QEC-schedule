"""Frozen component estimates and abstract d3 factory placement.

This module never creates atoms, compiles components, or replays transport. Its
claims are calibrated predictions within the recorded reference profile.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from math import isclose, isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any

from nadit_physical_compiler.device import Position, Region
from nadit_physical_compiler.provenance import canonical_hash

from ...contracts.event_probability import ProbabilityPort
from ...contracts.parallel import ComponentExecutionSpec, SharedAODClaim, SpaceClaim

SCHEMA = "nadit.fast_surface_factory_profile/1"
CODE_ID = "rotated_surface_d3"
FACTORY_ROLES = ("W1", "W2", "W3", "W4", "W5", "R")
DEFAULT_ORIGIN = Position(0, 0)


def _number(value: Any, label: str, *, nonnegative: bool = True) -> float:
    if (
        type(value) not in (int, float)
        or not isfinite(value)
        or (nonnegative and value < 0)
    ):
        raise ValueError(f"INVALID_FAST_PROFILE_NUMBER: {label}")
    return float(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(child) for child in value)
    return value


@dataclass(frozen=True)
class FastPatch:
    """A logical carrier and tile position, without atom identities or state."""

    block_id: str
    factory_id: str
    role: str
    slot: int
    origin: Position
    code_id: str = CODE_ID
    distance: int = 3


@dataclass(frozen=True)
class FastPlacement:
    """Six named patch carriers belonging to one factory."""

    factory_id: str
    patches: tuple[FastPatch, ...]

    @property
    def bindings(self) -> dict[str, FastPatch]:
        """Return role-to-carrier metadata; this is not a physical binding."""
        return {patch.role: patch for patch in self.patches}


@dataclass(frozen=True)
class FastLayout:
    """Only patch metadata, geometric budgets, and one shared control resource."""

    factories: tuple[FastPlacement, ...]
    budget: dict[str, Any]

    @property
    def bindings(self) -> dict[str, FastPatch]:
        """Return all logical carriers by globally unique block identity."""
        return {p.block_id: p for factory in self.factories for p in factory.patches}


@dataclass(frozen=True)
class ComponentCostProfile:
    """Compact repeatable timing and role activity for one calibrated variant.

    Busy records are (relative patch slot, local role, offset, duration, kind,
    holder). Events contain fixed-noise discrete log-survival contributions;
    residence and T2 intervals are assembled from the current schedule instead.
    """

    key: str
    component_id: str
    geometry: tuple[float, ...]
    selection_class: int | None
    waveform_key: str
    phase_durations_us: tuple[float, ...]
    measurement_phases: tuple[tuple[int, float], ...]
    result_ready_offsets_us: tuple[float, ...]
    cost_segments: tuple[Mapping[str, Any], ...]
    primitive_counts: Mapping[str, int]
    events: tuple[Mapping[str, Any], ...]
    busy: tuple[tuple[int, int, float, float, str, str], ...]
    claim: Mapping[str, Any]

    @property
    def action_duration_us(self) -> float:
        """Return ordered phase duration, with identity correction costing zero."""
        return sum(self.phase_durations_us)

    @property
    def results_ready_offset_us(self) -> float:
        """Return the latest result or action-exit offset."""
        return max((self.action_duration_us, *self.result_ready_offsets_us))


def _entry(key: str, item: Mapping[str, Any]) -> ComponentCostProfile:
    phases = tuple(_number(v, "phase") for v in item["phase_durations_us"])
    if any(type(i) is not int for i, _ in item["measurement_phases"]):
        raise ValueError("INVALID_FAST_PROFILE_MEASUREMENT_PHASE")
    measurements = tuple(
        (int(i), _number(t, "latency")) for i, t in item["measurement_phases"]
    )
    if any(i < 0 or i >= len(phases) for i, _ in measurements):
        raise ValueError("INVALID_FAST_PROFILE_MEASUREMENT_PHASE")
    offsets = tuple(
        _number(v, "result offset") for v in item["result_ready_offsets_us"]
    )
    if (
        len(offsets) != len(measurements)
        or len(offsets) != item["claim"]["result_count"]
    ):
        raise ValueError("INVALID_FAST_PROFILE_RESULT_COUNT")
    if any(
        not isclose(offset, sum(phases[: index + 1]) + latency, rel_tol=0, abs_tol=1e-7)
        for offset, (index, latency) in zip(offsets, measurements, strict=True)
    ):
        raise ValueError("INCONSISTENT_FAST_PROFILE_RESULT_OFFSET")
    if any(type(p) is not int or type(r) is not int for p, r, *_ in item["busy"]):
        raise ValueError("INVALID_FAST_PROFILE_ROLE_INDEX")
    busy = tuple(
        (
            int(p),
            int(r),
            _number(s, "busy offset"),
            _number(d, "busy duration"),
            str(k),
            str(h),
        )
        for p, r, s, d, k, h in item["busy"]
    )
    duration = sum(phases)
    resources = {
        "movement": {"aod"},
        "transfer": {"aod"},
        "gate": {"local", "rydberg"},
        "measurement": {"camera"},
        "reset": {"local"},
        "other": {"none"},
    }
    for segment in item["cost_segments"]:
        start = _number(segment["start_offset_us"], "segment start")
        end = _number(segment["end_offset_us"], "segment end")
        if (
            end < start
            or end > duration + 1e-7
            or segment["resource"] not in resources.get(segment["category"], set())
        ):
            raise ValueError("INVALID_FAST_PROFILE_COST_SEGMENT")
    if any(type(v) is not int or v < 0 for v in item["primitive_counts"].values()):
        raise ValueError("INVALID_FAST_PROFILE_PRIMITIVE_COUNT")
    if any(
        not 0 <= r < 17 or h not in ("slm", "aod") or s + d > duration + 1e-7
        for _, r, s, d, _, h in busy
    ):
        raise ValueError("INVALID_FAST_PROFILE_BUSY_INTERVAL")
    for event in item["events"]:
        start, length = (
            _number(event["offset_us"], "event offset"),
            _number(event["duration_us"], "event duration"),
        )
        if (
            start + length > duration + 1e-7
            or _number(event["log_survival"], "event log", nonnegative=False) > 0
        ):
            raise ValueError("INVALID_FAST_PROFILE_EVENT")
    return ComponentCostProfile(
        key,
        str(item["component_id"]),
        tuple(float(v) for v in item["geometry"]),
        item["selection_class"],
        str(item["waveform_key"]),
        phases,
        measurements,
        offsets,
        tuple(_freeze(segment) for segment in item["cost_segments"]),
        _freeze(item["primitive_counts"]),
        tuple(_freeze(event) for event in item["events"]),
        busy,
        _freeze(item["claim"]),
    )


class FastProfile:
    """Validated finite calibration; uncovered variants always raise errors."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = deepcopy(dict(document))
        self._profile_sha256 = canonical_hash(self._document)
        self._entries = {
            key: _entry(key, value) for key, value in document["entries"].items()
        }
        self._index = {
            (entry.component_id, entry.geometry, entry.selection_class): entry
            for entry in self._entries.values()
        }
        if len(self._index) != len(self._entries):
            raise ValueError("DUPLICATE_FAST_PROFILE_VARIANT")
        for prep in ("initialize_plus", "raw_t_postselection"):
            if any(
                (prep + "/canonicalize", (), value) not in self._index
                for value in range(16)
            ):
                raise ValueError(f"INCOMPLETE_CORRECTION_COVERAGE: {prep}")

    @property
    def profile_sha256(self) -> str:
        """Return the immutable calibration content fingerprint."""
        return self._profile_sha256

    @property
    def control(self) -> dict[str, Any]:
        """Return a small independent control configuration snapshot."""
        return deepcopy(self._document["control"])

    @property
    def noise_params(self) -> dict[str, Any]:
        """Return a small independent copy of the calibrated noise parameters."""
        return deepcopy(self._document["noise_params"])

    @property
    def entries(self) -> Mapping[str, ComponentCostProfile]:
        """Expose reusable recursively immutable component records."""
        return MappingProxyType(self._entries)

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> FastProfile:
        """Validate the reference schema/code and construct an immutable snapshot."""
        if (
            document.get("schema") != SCHEMA
            or document.get("code_id") != CODE_ID
            or document.get("distance") != 3
        ):
            raise ValueError("UNSUPPORTED_FAST_PROFILE")
        for key, fingerprint_key in (
            ("control", "control_profile_sha256"),
            ("noise_params", "noise_params_sha256"),
        ):
            fingerprint = document.get(fingerprint_key)
            if fingerprint is not None and fingerprint != canonical_hash(document[key]):
                raise ValueError("INCONSISTENT_FAST_PROFILE_FINGERPRINT")
        return cls(document)

    def to_dict(self) -> dict[str, Any]:
        """Return an independent serializable calibration document."""
        return deepcopy(self._document)

    def lookup(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = (),
    ) -> ComponentCostProfile:
        """Select covered code, geometry, parameters and local correction class.

        No extrapolation, compilation or probability sampling occurs. Unknown
        components, cross-factory pairs and changed raw round counts raise errors.
        """
        component_id = component_id.removeprefix(CODE_ID + "/")
        expected = 2 if component_id == "transversal_cnot" else 1
        if (
            len(participants) != expected
            or any(
                not isinstance(p, FastPatch) or p.code_id != CODE_ID or p.distance != 3
                for p in participants
            )
            or len({p.block_id for p in participants}) != expected
        ):
            raise ValueError("UNSUPPORTED_FAST_PARTICIPANTS")
        values = dict(parameters)
        allowed = {"extra_rounds": 1} if component_id == "raw_t_postselection" else {}
        if values and values != allowed:
            raise ValueError("UNCALIBRATED_FAST_PARAMETERS")
        geometry: tuple[float, ...] = ()
        if expected == 2:
            a, b = participants
            if a.factory_id != b.factory_id or a.origin.y != b.origin.y:
                raise ValueError("UNCALIBRATED_FAST_PAIR_GEOMETRY")
            geometry = (float(b.origin.x - a.origin.x), 0.0)
        value = None
        if component_id.endswith("/canonicalize"):
            if (
                selection is None
                or selection.get("accepted") is not True
                or type(selection.get("byproduct_class")) is not int
                or not 0 <= selection["byproduct_class"] < 16
            ):
                raise ValueError("INVALID_FAST_CORRECTION_SELECTION")
            value = selection["byproduct_class"]
        elif selection:
            raise ValueError("UNEXPECTED_FAST_CORRECTION_SELECTION")
        try:
            return self._index[component_id, geometry, value]
        except KeyError as error:
            raise ValueError(
                f"UNCALIBRATED_FAST_COMPONENT: {component_id}, {geometry}, {value}"
            ) from error

    def describe(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = (),
        *,
        budget: Mapping[str, Any],
    ) -> ComponentExecutionSpec:
        """Translate calibrated footprints and use the current explicit capacities."""
        if component_id.endswith("/canonicalize") and selection is None:
            selection = {"accepted": True, "byproduct_class": 0}
        entry = self.lookup(component_id, participants, selection, parameters)
        origin = participants[0].origin
        claim = entry.claim
        spaces = tuple(
            SpaceClaim(
                Region(origin.x + x0, origin.y + y0, origin.x + x1, origin.y + y1),
                purpose,
            )
            for x0, y0, x1, y1, purpose in claim["spaces"]
        )
        shared = None
        if claim["shared"] is not None:
            data = claim["shared"]
            if (
                budget.get("aod_count") != 1
                or budget["aod_max_rows"] < data["rows"]
                or budget["aod_max_columns"] < data["columns"]
                or budget["max_readout_atoms"] < data["readout_atoms"]
            ):
                raise ValueError("INSUFFICIENT_FAST_COMPONENT_CAPACITY")
            shared = SharedAODClaim(
                str(budget["aod_id"]),
                canonical_hash({"waveform": entry.waveform_key, "y": origin.y}),
                origin.x + data["band"][0],
                origin.x + data["band"][1],
                data["rows"],
                data["columns"],
                budget["aod_max_rows"],
                budget["aod_max_columns"],
                self.control["readout"]["channel"],
                data["readout_atoms"],
                budget["max_readout_atoms"],
                self.control["aod"]["min_spacing"],
            )
        return ComponentExecutionSpec(
            CODE_ID,
            entry.component_id,
            entry.waveform_key,
            tuple(p.block_id for p in participants),
            spaces,
            (),
            claim["parallel_mode"],
            claim["result_count"],
            shared,
        )

    def _port(self, document: Mapping[str, Any], label: str) -> ProbabilityPort:
        copied = deepcopy(dict(document))
        if not copied:
            raise ValueError(f"UNCALIBRATED_FAST_EVENT: {label}")
        source_hash = canonical_hash(copied)
        model = copied["model"]
        model["id"] = label + ".calibrated_reference.v1"
        model["kind"] = "estimated"
        model["evidence"] = {
            "profile_sha256": self.profile_sha256,
            "calibration_port_sha256": source_hash,
            "representation": "logical_estimate",
            "physical_validation_run": False,
            "logical_success_probability": None,
        }
        model["assumptions"] = [
            *model["assumptions"],
            "Frozen calibrated reference distribution; no atom execution in this run",
        ]
        return ProbabilityPort.from_dict(copied)

    def preparation_port(self, preparation: str) -> ProbabilityPort:
        """Return the calibrated joint acceptance/class table, never independent draws."""
        return self._port(
            self._document["preparation_ports"].get(preparation, {}), preparation
        )

    def consumption_port(self) -> ProbabilityPort:
        """Return the explicitly ideal T-routing reference distribution."""
        return self._port(self._document["consumption_port"], "t_consumption")

    def factory_port(
        self,
        calls: Any,
        *,
        layout: FastLayout,
        factory_id: str,
        window: tuple[float, float],
        raw_horizons: Any,
    ) -> ProbabilityPort:
        """Estimate this run's scoped cost and produce a distinct proxy event."""
        from .fast_cost import evaluate_factory_cost, factory_probability_port

        report = evaluate_factory_cost(
            self,
            calls,
            layout=layout,
            factory_id=factory_id,
            window=window,
            raw_horizons=raw_horizons,
        )
        return factory_probability_port(self, report)


def load_fast_profile(path: str | Path) -> FastProfile:
    """Load explicit calibration; this never rebuilds a missing or stale profile."""
    return FastProfile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def make_fast_layout(
    profile: FastProfile,
    factory_count: int,
    *,
    aod_max_rows: int = 4,
    aod_max_columns: int = 48,
    max_readout_atoms: int = 96,
    origin: Position = DEFAULT_ORIGIN,
    factory_gap_columns: int = 2,
    block_spacing_columns: int = 10,
    aod_id: str = "transport",
    factory_id_prefix: str = "factory",
) -> FastLayout:
    """Place six patch descriptions per line with fixed explicit device capacity.

    Only the calibrated horizontal 100-um patch spacing is supported. Increasing
    line count expands the reported area, never rows, columns or camera budget.
    """
    if not isinstance(profile, FastProfile) or block_spacing_columns != 10:
        raise ValueError("UNCALIBRATED_FAST_LAYOUT")
    for name, value, minimum in (
        ("factories", factory_count, 1),
        ("rows", aod_max_rows, 1),
        ("columns", aod_max_columns, 1),
        ("readout", max_readout_atoms, 1),
        ("gap", factory_gap_columns, 0),
    ):
        if type(value) is not int or value < minimum:
            raise ValueError(f"INVALID_FAST_LAYOUT_BUDGET: {name}")
    if not aod_id or not factory_id_prefix:
        raise ValueError("INVALID_FAST_LAYOUT_IDENTITY")
    stride = 6 * block_spacing_columns + factory_gap_columns
    factories = tuple(
        FastPlacement(
            f"{factory_id_prefix}{index}",
            tuple(
                FastPatch(
                    f"{factory_id_prefix}{index}/{role}",
                    f"{factory_id_prefix}{index}",
                    role,
                    slot,
                    Position(
                        origin.x + 10 * (index * stride + slot * block_spacing_columns),
                        origin.y,
                    ),
                )
                for slot, role in enumerate(FACTORY_ROLES)
            ),
        )
        for index in range(factory_count)
    )
    right = origin.x + 10 * ((factory_count - 1) * stride + 56) + 25
    budget = {
        "aod_count": 1,
        "aod_id": aod_id,
        "aod_max_rows": aod_max_rows,
        "aod_max_columns": aod_max_columns,
        "max_readout_atoms": max_readout_atoms,
        "factory_count": factory_count,
        "patch_count": factory_count * 6,
        "atom_count_estimate": factory_count * 102,
        "shared_bounds_um": [origin.x - 22, origin.y - 2, right, origin.y + 80],
        "readout_bounds_um": [origin.x - 20, origin.y + 90, right, origin.y + 130],
        "capacity_scales_with_factory_count": False,
        "representation": "logical_estimate",
    }
    return FastLayout(factories, budget)
