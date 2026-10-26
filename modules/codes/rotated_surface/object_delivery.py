"""Whole-block transport costs on the existing object profile and single AOD.

Straight-line Euclidean displacement at recorded speed; each move is Load,
Move, Store. Endpoints are checked for empty block footprints. Transit crossing
clearance is an explicit modeling assumption, not an atomic path certificate.
"""

import json
from collections.abc import Mapping
from dataclasses import asdict, replace
from hashlib import sha256
from math import hypot, isfinite
from typing import Any

from nadit_physical_compiler.device import Position, Region

from modules.codes.contracts.parallel import (
    ComponentExecutionSpec,
    ComponentPhase,
    SpaceClaim,
)
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    ComponentCostProfile,
    FastLayout,
    FastPatch,
)
from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
from modules.logical_compiler.src.protocols.receipts import ComponentReceipt

from .object_factory import FactoryObjectCatalog, FactoryObjectProfile, _home_bounds


def factory_supply_layout(
    catalog: FactoryObjectCatalog,
    *,
    producers: int,
    placement: str = "vertical",
    columns: int | None = None,
    level2_position: str = "below_left",
) -> FastLayout:
    """Reuse L1 whole-factory placement; put one same-distance L2 below it.

    All supported recorded distances use their own geometry. Parking is one
    block to the right of the array, separated by the existing factory gap.
    Invalid counts/layouts propagate existing validation errors without builds.
    """
    upstream = catalog.layout(producers, placement=placement, columns=columns)
    single = catalog.layout(1)
    bounds = upstream.budget["code_geometry"]["relative_bounds"]
    width, height = bounds["x_max"] - bounds["x_min"], bounds["y_max"] - bounds["y_min"]
    gap_x = upstream.budget["factory_placement"]["factory_gap_x_um"]
    gap_y = upstream.budget["factory_placement"]["factory_gap_y_um"]
    if level2_position not in (
        "below_left",
        "below_center",
        "right_center",
        "above_center",
    ):
        raise ValueError("UNKNOWN_LEVEL2_POSITION")
    array = upstream.budget["factory_placement"]
    px = 6 * width + 5 * array["patch_gap_um"] + gap_x
    py = height + gap_y
    center_x = (array["columns"] - 1) * px / 2
    x_offset = 0.0 if level2_position == "below_left" else center_x
    y_offset = upstream.budget["storage_bounds_um"][1] - gap_y
    upstream_y_offset = 0.0
    if level2_position == "right_center":
        x_offset = array["columns"] * px
        y_offset = -(array["rows"] - 1) * py / 2
    elif level2_position == "above_center":
        y_offset = 0.0
        upstream_y_offset = -py
    factories = []
    for index, factory in enumerate((*upstream.factories, single.factories[0])):
        identity = f"L1-factory{index}" if index < producers else "L2-factory0"
        factories.append(
            replace(
                factory,
                factory_id=identity,
                patches=tuple(
                    replace(
                        p,
                        factory_id=identity,
                        block_id=f"{identity}/{p.role}",
                        origin=Position(
                            p.origin.x + (x_offset if index == producers else 0),
                            p.origin.y
                            + (y_offset if index == producers else upstream_y_offset),
                        ),
                    )
                    for p in factory.patches
                ),
            )
        )
    parking = (
        max(p.origin.x + bounds["x_max"] for f in factories for p in f.patches)
        + gap_x
        - bounds["x_min"],
        single.factories[0].patches[0].origin.y,
    )
    all_origins = [p.origin for f in factories for p in f.patches] + [
        Position(*parking)
    ]
    occupied = [
        min(p.x for p in all_origins) + bounds["x_min"],
        min(p.y for p in all_origins) + bounds["y_min"],
        max(p.x for p in all_origins) + bounds["x_max"],
        max(p.y for p in all_origins) + bounds["y_max"],
    ]
    budget = {
        **upstream.budget,
        "factory_count": producers + 1,
        "patch_count": 6 * (producers + 1),
        "atom_count_estimate": single.budget["atom_count_estimate"] * (producers + 1),
        "storage_bounds_um": occupied,
        "level1_placement": dict(upstream.budget["factory_placement"]),
        "level2_placement": level2_position,
        "factory_placement": {
            **upstream.budget["factory_placement"],
            "rows": upstream.budget["factory_placement"]["rows"] + 1,
        },
        "parking": {
            "origin_um": list(parking),
            "width_um": width,
            "height_um": height,
            "atoms": 0,
        },
    }
    budget["placement_fingerprint"] = sha256(
        json.dumps(
            {"factories": [asdict(f) for f in factories], "parking": budget["parking"]},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return FastLayout(tuple(factories), budget)


class DeliveryObjectProfile(FactoryObjectProfile):
    """Extend numeric bindings with versioned carrier movement, retaining templates."""

    def __init__(self, catalog: FactoryObjectCatalog, layout: FastLayout) -> None:
        super().__init__(catalog, layout)
        self._patches = dict(layout.bindings)
        self.versions = {k: 0 for k in self._patches}
        self.moves: list[dict[str, Any]] = []
        self.move_costs: dict[float, ComponentCostProfile] = {}
        self.move_lookups = 0

    def lookup(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Any = (),
    ) -> ComponentCostProfile:
        """Bind ordinary components or one version-checked displacement cost."""
        if component_id != "block_delivery":
            return super().lookup(component_id, participants, selection, parameters)
        params = dict(parameters)
        if (
            len(participants) != 1
            or set(params) != {"x", "y", "version"}
            or selection is not None
        ):
            raise ValueError("INVALID_DELIVERY_PARAMETERS")
        patch = participants[0]
        if (
            self._patches.get(patch.block_id) != patch
            or type(params["version"]) is not int
            or self.versions[patch.block_id] != params["version"]
        ):
            raise ValueError("STALE_DELIVERY_BINDING")
        x, y = params["x"], params["y"]
        if any(type(v) not in (int, float) or not isfinite(v) for v in (x, y)):
            raise ValueError("INVALID_DELIVERY_COORDINATES")
        bounds = _home_bounds(patch.distance)
        if y + bounds.y_max > 0:
            raise ValueError("DELIVERY_OUTSIDE_STORAGE")
        for other in self._patches.values():
            if other.block_id == patch.block_id:
                continue
            if (
                abs(other.origin.x - x) < bounds.x_max - bounds.x_min
                and abs(other.origin.y - y) < bounds.y_max - bounds.y_min
            ):
                raise ValueError("DELIVERY_DESTINATION_OCCUPIED")
        distance = hypot(x - patch.origin.x, y - patch.origin.y)
        self.move_lookups += 1
        if distance not in self.move_costs:
            aod = ("aod:transport",)
            stages = (
                ComponentPhase("load", 10, "transfer", aod, acquire=aod),
                ComponentPhase(
                    "move",
                    distance * self.catalog.document["move_us_per_um"],
                    "movement",
                    aod,
                ),
                ComponentPhase("store", 10, "transfer", aod, release=aod),
            )
            self.move_costs[distance] = ComponentCostProfile(
                "block_delivery",
                "block_delivery",
                (),
                None,
                "object/block_delivery",
                tuple(s.duration_us for s in stages),
                (),
                (),
                (),
                {},
                (),
                (),
                {
                    "result_count": 0,
                    "distance_um": distance,
                    "model": "euclidean_translation/v1",
                },
                stages,
            )
        return self.move_costs[distance]

    def describe(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        parameters: Any = (),
        *,
        budget: Mapping[str, Any],
    ) -> ComponentExecutionSpec:
        """Reserve a movement envelope on the same object scheduler."""
        if component_id != "block_delivery":
            return super().describe(
                component_id, participants, parameters, budget=budget
            )
        self.lookup(component_id, participants, parameters=parameters)
        if budget.get("aod_count") != 1:
            raise ValueError("DELIVERY_REQUIRES_SINGLE_AOD")
        patch, params = participants[0], dict(parameters)
        b = _home_bounds(patch.distance)
        envelope = Region(
            min(patch.origin.x, params["x"]) + b.x_min,
            min(patch.origin.y, params["y"]) + b.y_min,
            max(patch.origin.x, params["x"]) + b.x_max,
            max(patch.origin.y, params["y"]) + b.y_max,
        )
        return ComponentExecutionSpec(
            self.catalog.code_id,
            component_id,
            "object/block_delivery",
            (patch.block_id,),
            (SpaceClaim(envelope, "delivery_envelope"),),
            (),
            "object_wave",
            0,
        )

    def instantiate_wave(
        self, requests: tuple[ExecutionRequest, ...]
    ) -> tuple[ComponentCostProfile, ...]:
        """Keep factory batching; movement legs retain exclusive AOD leases."""
        if requests[0].call.component_id != "block_delivery":
            return super().instantiate_wave(requests)
        return tuple(
            self.lookup(
                r.call.component_id,
                tuple(self._patches[k] for k in r.participant_blocks),
                parameters=r.call.parameters,
            )
            for r in requests
        )

    def commit_transport(
        self, receipt: ComponentReceipt, parameters: Mapping[str, Any]
    ) -> None:
        """Commit a completed leg once, preserving carrier identity and version."""
        if (
            receipt.component_id != "block_delivery"
            or len(receipt.participant_blocks) != 1
        ):
            raise ValueError("DELIVERY_RECEIPT_REQUIRED")
        block = receipt.participant_blocks[0]
        patch = self._patches[block]
        self.lookup("block_delivery", (patch,), parameters=parameters)
        destination = Position(parameters["x"], parameters["y"])
        self.moves.append(
            {
                "invocation_id": receipt.invocation_id,
                "carrier_id": block,
                "version": self.versions[block],
                "start_us": receipt.start_us,
                "end_us": receipt.action_end_us,
                "source": [patch.origin.x, patch.origin.y],
                "destination": [destination.x, destination.y],
            }
        )
        self._patches[block] = replace(patch, origin=destination)
        self.versions[block] += 1
