"""Reusable logical-MZ objects under an explicit rigid readout-transport model.

This first acceptance catalog covers destructive Z readout only. It does not
invent costs or probabilities for unprepared factory components. Geometry uses
row/column bands; combinations never create atoms or invoke a physical compiler.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Any

from modules.codes.contracts.parallel import ComponentExecutionSpec, ComponentPhase
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    ComponentCostProfile,
    FastLayout,
    FastPatch,
    FastPlacement,
)
from modules.logical_compiler.src.placement import (
    BlockSpec,
    GridFactoryPlacement,
    PlacementRequest,
    place,
)
from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest

from .definition import definition
from .geometry import geometry

ROLES = ("W1", "W2", "W3", "W4", "W5", "R")
REFERENCE = (
    Path(__file__).parents[1]
    / "rotated_surface_d3/configs/nonzoned_cnot_reference.json"
)


@dataclass(frozen=True)
class ObjectTiming:
    """MSD overrides over the committed device reference, in us and um."""

    load_us: float
    store_us: float
    move_us_per_um: float
    measure_us: float
    processing_us: float
    gap_um: float
    local_us: float
    reset_us: float
    readout_spacing_um: float
    reference_sha256: str

    @classmethod
    def current(cls) -> "ObjectTiming":
        """Read native durations; retain the approved MSD measurement overrides."""
        raw = REFERENCE.read_bytes()
        params = json.loads(raw)["params"]
        return cls(
            10.0,
            10.0,
            params["timing"]["move_us_per_um"],
            100.0,
            0.0,
            50.0,
            params["local"]["rotation_us"],
            params["local"]["reset_us"],
            params["measurement"]["readout"]["min_spacing_um"],
            sha256(raw).hexdigest(),
        )


def _entry(distance: int, timing: ObjectTiming) -> ComponentCostProfile:
    """Prepare one topology from code metadata, independent of instance layout."""
    code = definition(distance)
    aod = ("aod:transport",)
    stages = (
        ComponentPhase("load", timing.load_us, "transfer", aod, acquire=aod),
        ComponentPhase("to_readout", 0, "movement", aod),
        ComponentPhase(
            "measure",
            timing.measure_us,
            "measurement",
            (*aod, "camera"),
            results=code.data_count,
            latency_us=timing.processing_us,
        ),
        ComponentPhase("return_home", 0, "movement", aod),
        ComponentPhase("store", timing.store_us, "transfer", aod, release=aod),
    )
    return ComponentCostProfile(
        f"surface_d{distance}/logical_mz/rigid_readout_v1",
        "logical_mz",
        (),
        None,
        f"surface_d{distance}/logical_mz",
        tuple(p.duration_us for p in stages),
        tuple((2, timing.processing_us) for _ in range(code.data_count)),
        (),
        (),
        {
            "Measure": code.data_count,
            "Load": code.data_count,
            "Move": 2 * code.data_count,
            "Store": code.data_count,
        },
        (),
        (),
        {
            "result_count": code.data_count,
            "atom_count": code.atom_count,
            "transport": "rigid_vertical_return_home/1",
            "physical_validation": "not_run",
        },
        stages,
    )


class SurfaceReadoutCatalog:
    """A fixed prepared component set reused by all N, seeds and combinations."""

    def __init__(self, distances: tuple[int, ...] = (3, 5, 7)) -> None:
        if not distances or len(set(distances)) != len(distances):
            raise ValueError("DISTINCT_CATALOG_DISTANCES_REQUIRED")
        self.timing = ObjectTiming.current()
        self.entries = {d: _entry(d, self.timing) for d in distances}
        self.geometries = {d: geometry(f"rotated_surface_d{d}", d) for d in distances}
        self.template_builds = len(self.entries)
        self.lookups = 0

    def lookup(self, distance: int, component: str) -> ComponentCostProfile:
        """Return an existing immutable object; missing coverage is an error."""
        if component != "logical_mz" or distance not in self.entries:
            raise ValueError(
                f"UNPREPARED_COMPONENT: {component}, d={distance}; no compile fallback"
            )
        self.lookups += 1
        return self.entries[distance]

    def layout(
        self,
        distance: int,
        count: int,
        *,
        placement: str = "vertical",
        columns: int | None = None,
    ) -> FastLayout:
        """Translate whole factories using existing block placement, without atoms.

        Vertical is the unchanged default; horizontal uses count columns. Grid
        requires explicit positive columns (clamped to count by the existing
        strategy). Named non-grid layouts reject columns. Invalid choices raise
        ValueError; no physical compiler or alternative layout is tried.
        """
        entry = self.lookup(distance, "logical_mz")
        if type(count) is not int or count < 1:
            raise ValueError("INVALID_FACTORY_COUNT")
        if placement not in ("vertical", "horizontal", "grid"):
            raise ValueError("INVALID_FACTORY_PLACEMENT")
        if placement == "grid":
            if columns is None:
                raise ValueError("GRID_COLUMNS_REQUIRED")
            selected_columns = columns
        else:
            if columns is not None:
                raise ValueError("COLUMNS_REQUIRE_GRID_PLACEMENT")
            selected_columns = count if placement == "horizontal" else 1
        strategy = GridFactoryPlacement(ROLES, columns=selected_columns)
        effective_columns = min(selected_columns, count)
        code_id = f"rotated_surface_d{distance}"
        plan = place(
            PlacementRequest(
                tuple(
                    BlockSpec(
                        f"factory{i}/{role}", code_id, distance, f"factory{i}", role
                    )
                    for i in range(count)
                    for role in ROLES
                ),
                {code_id: self.geometries[distance]},
            ),
            strategy,
        )
        factories = tuple(
            FastPlacement(
                f"factory{i}",
                tuple(
                    FastPatch(
                        f"factory{i}/{role}",
                        f"factory{i}",
                        role,
                        j,
                        plan.placements[f"factory{i}/{role}"].origin,
                        f"rotated_surface_d{distance}",
                        distance,
                    )
                    for j, role in enumerate(ROLES)
                ),
            )
            for i in range(count)
        )
        return FastLayout(
            factories,
            {
                "aod_count": 1,
                "aod_id": "transport",
                "aod_max_rows": None,
                "aod_max_columns": None,
                "max_readout_atoms": None,
                "factory_count": count,
                "patch_count": 6 * count,
                "atom_count_estimate": 6 * count * entry.claim["atom_count"],
                "storage_bounds_um": [
                    plan.occupied_bounds.x_min,
                    plan.occupied_bounds.y_min,
                    plan.occupied_bounds.x_max,
                    plan.occupied_bounds.y_max,
                ],
                "placement_fingerprint": plan.geometry_fingerprint,
                "factory_placement": {
                    "kind": placement,
                    "requested_columns": selected_columns,
                    "columns": effective_columns,
                    "rows": (count + effective_columns - 1) // effective_columns,
                    "patch_gap_um": strategy.patch_gap_um,
                    "factory_gap_x_um": strategy.factory_gap_x_um,
                    "factory_gap_y_um": strategy.factory_gap_y_um,
                },
                "code_geometry": self.geometries[distance].to_dict(),
                "representation": "logical_estimate",
                "readout_y_min_um": self.timing.gap_um,
            },
        )


class SurfaceReadoutProfile:
    """Bind a reusable MZ catalog to a layout through the existing profile seam.

    Same columns/disjoint row bands or same rows/disjoint column bands permit a
    shared rigid translation. Other members serialize on the single AOD. This is
    an explicit estimation model, not a collision/routing proof for atom actions.
    """

    def __init__(self, catalog: SurfaceReadoutCatalog, layout: FastLayout) -> None:
        self.catalog, self.layout = catalog, layout
        self.wave_timeout_seconds = 5.0
        self.wave_plans = 0
        self.profile_sha256 = sha256(
            json.dumps(
                {
                    "model": "surface_object_readout/1",
                    "distances": sorted(catalog.entries),
                    "reference": catalog.timing.reference_sha256,
                    "timing_overrides": {
                        "load": 10,
                        "store": 10,
                        "measure": 100,
                        "processing": 0,
                    },
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def lookup(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Any = (),
    ) -> ComponentCostProfile:
        """Admit exact logical carriers; no atoms, geometry compilation or fallback."""
        if len(participants) != 1 or selection or parameters:
            raise ValueError("UNSUPPORTED_OBJECT_READOUT_ARGUMENTS")
        patch = participants[0]
        if self.layout.bindings.get(patch.block_id) != patch:
            raise ValueError("UNKNOWN_OBJECT_CARRIER")
        return self.catalog.lookup(patch.distance, component_id)

    def describe(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        parameters: Any = (),
        *,
        budget: Mapping[str, Any],
    ) -> ComponentExecutionSpec:
        """Declare one homogeneous wave; resources are resolved at stage level."""
        entry = self.lookup(component_id, participants, parameters=parameters)
        if budget.get("aod_count") != 1:
            raise ValueError("OBJECT_MODEL_REQUIRES_SINGLE_AOD")
        return ComponentExecutionSpec(
            participants[0].code_id,
            component_id,
            entry.waveform_key,
            (participants[0].block_id,),
            (),
            (),
            "object_wave",
            entry.claim["result_count"],
        )

    def instantiate_wave(
        self, requests: tuple[ExecutionRequest, ...]
    ) -> tuple[ComponentCostProfile, ...]:
        """Evaluate distances/shared commands without rebuilding component internals."""
        patches = [self.layout.bindings[r.participant_blocks[0]] for r in requests]
        bases = [
            self.lookup(r.call.component_id, (p,), r.selection, r.call.parameters)
            for r, p in zip(requests, patches, strict=True)
        ]
        pending = list(range(len(requests)))
        entries = list(bases)
        while pending:
            first = pending.pop(0)
            group = [first]
            for other in tuple(pending):
                candidates = [patches[i] for i in (*group, other)]
                if _compatible_bands(
                    candidates, self.catalog.timing.readout_spacing_um
                ):
                    group.append(other)
                    pending.remove(other)
            lift = max(
                self.catalog.timing.gap_um - (patches[i].origin.y + 10.0) for i in group
            )
            if lift < 0:
                raise ValueError("OBJECT_READOUT_OUTSIDE_STORAGE_MODEL")
            certificate = f"rigid-readout:{first}" if len(group) > 1 else None
            for i in group:
                stages = tuple(
                    replace(
                        p,
                        batch_key=certificate,
                        duration_us=lift * self.catalog.timing.move_us_per_um
                        if p.category == "movement"
                        else p.duration_us,
                    )
                    for p in bases[i].stages
                )
                entries[i] = replace(bases[i], stages=stages)
        self.wave_plans += 1
        return tuple(entries)


def _compatible_bands(patches: list[FastPatch], spacing: float) -> bool:
    if len({p.distance for p in patches}) != 1:
        return False
    extent = 20.0 * (patches[0].distance - 1)
    for common, separate in (("x", "y"), ("y", "x")):
        if len({getattr(p.origin, common) for p in patches}) != 1:
            continue
        starts = sorted(getattr(p.origin, separate) for p in patches)
        if all(b - (a + extent) >= spacing for a, b in pairwise(starts)):
            return True
    return False
