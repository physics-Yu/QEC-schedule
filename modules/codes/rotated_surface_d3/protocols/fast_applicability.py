"""Bind frozen cost records to checked layouts without compiling components."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import nadit_physical_compiler
from nadit_physical_compiler.device import Region

from modules.logical_compiler.src.estimation.calibration import (
    CalibrationCache,
    CalibrationMiss,
    CalibrationRecord,
    MissingCalibration,
)
from modules.logical_compiler.src.placement import block_bounds, validate_plan

from .factory import factory_recipe
from .fast_context import capture_applicability, component_context

__all__ = ["BoundFastProfile", "capture_applicability"]
_PROFILE_SLOT_PITCH_UM = 100.0


def _verify_sources(document: Mapping[str, Any]) -> None:
    """Check the running checkout, including relocated physical package paths."""
    provenance = document.get("provenance", {})
    if provenance.get("kind") == "test_fixture":
        return
    sources = provenance.get("source_hashes")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("CALIBRATION_SOURCE_FINGERPRINTS_MISSING")
    root = Path(__file__).resolve().parents[4]
    physical = Path(nadit_physical_compiler.__file__).resolve().parent
    for name, expected in sources.items():
        if name.startswith("runtime-physical:"):
            original = name.removeprefix("runtime-physical:").replace("\\", "/")
            marker = "/nadit_physical_compiler/"
            if marker not in original:
                raise ValueError("UNSUPPORTED_CALIBRATION_SOURCE_PATH")
            path = (physical / original.split(marker, 1)[1]).resolve()
            allowed = physical
        elif name.startswith("modules/codes/"):
            path = (root / name).resolve()
            allowed = root / "modules/codes"
        else:
            raise ValueError("UNSUPPORTED_CALIBRATION_SOURCE_PATH")
        if (
            not path.is_relative_to(allowed)
            or not path.is_file()
            or sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"CHANGED_CALIBRATION_IMPLEMENTATION: {name}")


class BoundFastProfile:
    """A profile lookup scoped to one placement and its declared Device regions.

    Records originate from calibration metadata. Cache misses never compile or
    sample. Synthetic test profiles may explicitly declare their own local model;
    they remain test evidence and cannot supply physical calibration claims.
    """

    def __init__(
        self, profile: Any, layout: Any, *, cache: CalibrationCache | None = None
    ) -> None:
        self._profile, self.layout = profile, layout
        self._document = profile.to_dict()
        self._budget = deepcopy(layout.budget)
        _verify_sources(self._document)
        if layout.placement_plan is None:
            raise ValueError("CALIBRATION_PLACEMENT_REQUIRED")
        self.plan = validate_plan(layout.placement_plan)
        blocks = {block.block_id: block for block in self.plan.blocks}
        recipe = factory_recipe()
        roles = (*recipe.work_roles, recipe.resource_role)
        if set(layout.bindings) != blocks.keys():
            raise ValueError("PLACEMENT_CARRIER_BINDINGS_MISMATCH")
        for identity, patch in layout.bindings.items():
            block = blocks[identity]
            if (
                patch.origin != self.plan.placements[identity].origin
                or patch.code_id != block.code
                or patch.distance != block.distance
                or patch.factory_id != block.factory_id
                or patch.role != block.role
                or patch.role not in roles
                or patch.slot != roles.index(patch.role)
            ):
                raise ValueError(f"PLACEMENT_CARRIER_BINDINGS_MISMATCH: {identity}")
        if layout.budget.get("geometry_fingerprint") != self.plan.geometry_fingerprint:
            raise ValueError("PLACEMENT_BUDGET_IDENTITY_MISMATCH")
        self.cache = CalibrationCache() if cache is None else cache
        self._contexts: dict[str, Any] = {}
        self._missing: dict[str, dict[str, Any]] = {}
        self._fixture = (
            self._document.get("provenance", {}).get("kind") == "test_fixture"
        )
        shared = layout.budget.get("shared_bounds_um")
        if shared is None:
            raise ValueError("CALIBRATION_DEVICE_REGIONS_REQUIRED: shared")
        region = Region(*shared)
        for block in self.plan.blocks:
            bounds = block_bounds(
                self.plan.geometries[block.code], self.plan.placements[block.block_id]
            )
            if not (
                region.x_min <= bounds.x_min <= bounds.x_max <= region.x_max
                and region.y_min <= bounds.y_min <= bounds.y_max <= region.y_max
            ):
                raise ValueError(f"PLACEMENT_OUTSIDE_DEVICE_REGION: {block.block_id}")
        applicability = self._document.get("applicability", {})
        if (
            not self._fixture
            and applicability.get("schema") != "nadit.fast_surface_applicability/1"
        ):
            raise ValueError(
                "UNCALIBRATED_PROFILE_CONTEXT: rebuild layout applicability metadata"
            )
        for item in applicability.get("records", ()):
            self.cache.put(CalibrationRecord.from_dict(item))

    def _check_budget(self, budget: Mapping[str, Any] | None = None) -> None:
        if self.layout.budget != self._budget or (
            budget is not None and dict(budget) != self._budget
        ):
            raise ValueError("CALIBRATION_DEVICE_CONTEXT_CHANGED: bind a new layout")

    def __getattr__(self, name: str) -> Any:
        """Preserve the code profile's event and cost interfaces."""
        return getattr(self._profile, name)

    def _context(self, entry: Any, participants: tuple[Any, ...]) -> Any:
        ids = tuple(p.block_id for p in participants)
        memo = json.dumps((entry.key, ids))
        if memo not in self._contexts:
            self._contexts[memo] = component_context(
                self._document,
                self.plan,
                ids,
                self._document["entries"][entry.key],
                self._budget,
            )
        return self._contexts[memo]

    def lookup(
        self,
        component_id: str,
        participants: tuple[Any, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Any = (),
    ) -> Any:
        """Require a matching component, geometry, Device and spectator record."""
        self._check_budget()
        entry = self._profile.lookup(component_id, participants, selection, parameters)
        anchor = participants[0]
        by_slot = {
            patch.slot: patch
            for patch in self.layout.bindings.values()
            if patch.factory_id == anchor.factory_id
        }
        for relative_slot, *_ in entry.busy:
            affected = by_slot.get(anchor.slot + relative_slot)
            if (
                affected is None
                or affected.origin.x
                != anchor.origin.x + _PROFILE_SLOT_PITCH_UM * relative_slot
                or affected.origin.y != anchor.origin.y
            ):
                raise ValueError("UNCALIBRATED_ACTIVITY_ROLE_LAYOUT")
        context = self._context(entry, participants)
        record = self.cache.lookup(context)
        payload = self._document["entries"][entry.key]
        if isinstance(record, CalibrationMiss) and self._fixture:
            # This is an explicit supplied test model, never measured evidence.
            record = CalibrationRecord(
                context, payload, {"kind": "test_fixture", "variant_key": entry.key}
            )
            self.cache.put(record)
        if isinstance(record, CalibrationMiss):
            self._missing[context.key.fingerprint] = record.to_dict()
            raise MissingCalibration(record)
        if record.payload != payload:
            raise ValueError("CALIBRATION_PAYLOAD_MISMATCH")
        if not self._fixture and record.evidence.get("kind") == "test_fixture":
            raise ValueError("TEST_FIXTURE_IS_NOT_PHYSICAL_CALIBRATION")
        return entry

    def describe(
        self,
        component_id: str,
        participants: tuple[Any, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Any = (),
        *,
        budget: Mapping[str, Any],
    ) -> Any:
        """Validate applicability before exposing code-owned scheduling claims."""
        self._check_budget(budget)
        if component_id.endswith("/canonicalize") and selection is None:
            selection = {"accepted": True, "byproduct_class": 0}
        self.lookup(component_id, participants, selection, parameters)
        return self._profile.describe(
            component_id, participants, selection, parameters, budget=budget
        )

    def calibration_key(
        self,
        component_id: str,
        participants: tuple[Any, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Any = (),
    ) -> str:
        """Return the applicability key retained with an execution receipt."""
        self._check_budget()
        entry = self._profile.lookup(component_id, participants, selection, parameters)
        return str(self._context(entry, participants).key.fingerprint)

    def calibration_evidence(self) -> dict[str, Any]:
        """Return lookup evidence without serializing the cache into every case."""
        return {
            "model_scope": "test_fixture"
            if self._fixture
            else "physical_calibration_metadata",
            "geometry_fingerprint": self.plan.geometry_fingerprint,
            "missing": list(self._missing.values()),
            "physical_compilation_run": False,
        }
