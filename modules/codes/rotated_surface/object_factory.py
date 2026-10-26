"""Recorded d3/d5/d7/d9/d11 objects and the established probability backend.

Inputs are previously saved numeric component costs and probability ports.
There is no compiler, circuit lowering, atom expansion or probability estimator
in this module. Placement changes transport cost; raw probabilities remain the
explicitly selected precomputed reference, as required by the resource model.
"""

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from functools import cache
from hashlib import sha256
from itertools import combinations, pairwise
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any

from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.device import Region

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.parallel import (
    ComponentExecutionSpec,
    ComponentPhase,
    SpaceClaim,
)
from modules.codes.rotated_surface_d3.probabilities.preparation import preparation_port
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    ComponentCostProfile,
    FastLayout,
    FastPatch,
)
from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest

from .geometry import geometry
from .object_readout import SurfaceReadoutCatalog

DEFAULT_INPUT = Path(__file__).with_name("configs") / "object_d3_reference.json"
# Extend the existing code-owned home footprint by its 2 um gate margin.
_HOME_MARGIN_UM = 2.0
_RECORDED_DISTANCES = (3, 5, 7, 9, 11)


@cache
def _home_bounds(distance: int) -> Region:
    return geometry(f"rotated_surface_d{distance}", distance).relative_bounds


def _storage_gate_bounds(participants: tuple[FastPatch, ...]) -> Region:
    return Region(
        min(p.origin.x + _home_bounds(p.distance).x_min for p in participants)
        - _HOME_MARGIN_UM,
        min(p.origin.y + _home_bounds(p.distance).y_min for p in participants)
        - _HOME_MARGIN_UM,
        max(p.origin.x + _home_bounds(p.distance).x_max for p in participants)
        + _HOME_MARGIN_UM,
        max(p.origin.y + _home_bounds(p.distance).y_max for p in participants)
        + _HOME_MARGIN_UM,
    )


def _compatible_translation_bands(
    calls: tuple[tuple[FastPatch, ...], ...],
) -> bool:
    """Certify aligned or separated home bands for congruent object commands.

    All participant patches, including both CNOT ends, must fit coincident or
    disjoint code-owned home bands, and whole-call storage/gate claims must not
    overlap. Unlike a single common axis this admits rectangular and staggered
    arrays. It is an object-model applicability rule, not an atomic route proof.
    """
    distances = {p.distance for participants in calls for p in participants}
    if len(distances) != 1:
        return False
    home = _home_bounds(next(iter(distances)))
    bounds = tuple(_storage_gate_bounds(participants) for participants in calls)
    if any(
        a.x_min <= b.x_max
        and b.x_min <= a.x_max
        and a.y_min <= b.y_max
        and b.y_min <= a.y_max
        for a, b in combinations(bounds, 2)
    ):
        return False
    for axis in ("x", "y"):
        band = (
            getattr(home, axis + "_max")
            - getattr(home, axis + "_min")
            + 2 * _HOME_MARGIN_UM
        )
        starts = sorted(
            {getattr(p.origin, axis) for participants in calls for p in participants}
        )
        if any(b - a < band for a, b in pairwise(starts)):
            return False
    return True


class FactoryObjectCatalog:
    """One immutable component set shared by all production runs and layouts."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = deepcopy(dict(document))
        data = self.document
        if (
            data.get("schema") != "nadit.factory_object_inputs/1"
            or type(data.get("distance")) is not int
            or data["distance"] not in _RECORDED_DISTANCES
        ):
            raise ValueError("UNSUPPORTED_OBJECT_CATALOG_DISTANCE_OR_SCHEMA")
        self.distance = data["distance"]
        self.code_id = f"rotated_surface_d{self.distance}"
        self.protocol = data["protocol"]
        if (
            self.protocol.get("injection_distance"),
            self.protocol.get("injection_rounds"),
            self.protocol.get("growth_rounds"),
            self.protocol.get("postselection_scope"),
            self.protocol.get("target_distance"),
        ) != (
            3,
            3,
            0 if self.distance == 3 else self.distance,
            "d3_injection_only",
            self.distance,
        ):
            raise ValueError("OBJECT_PREPARATION_PROTOCOL_MISMATCH")
        if data["timing"] != {
            "load_us": 10,
            "store_us": 10,
            "measure_us": 100,
            "result_processing_us": 0,
        }:
            raise ValueError("OBJECT_TIMING_CONVENTION_MISMATCH")
        self.noise_params = deepcopy(data["noise_params"])
        self.raw_port = ProbabilityPort.from_dict(data["raw_port"])
        if self.raw_port.to_dict()["model"]["kind"] == "test_fixture":
            raise ValueError("FACTORY_INPUT_CANNOT_BE_A_TEST_FIXTURE")
        self.raw_probability = self.raw_port.outcome("accepted").probability
        raw_model = self.raw_port.to_dict()["model"]
        estimator = raw_model["evidence"]["estimator"]
        if raw_model["kind"] == "pauli_exact":
            valid = (
                estimator.get("kind") == "exact"
                and estimator.get("method") == "exact_xor_convolution"
                and estimator.get("shots") is None
                and estimator.get("accepted") is None
                and type(estimator.get("probability")) in (int, float)
                and estimator["probability"] == self.raw_probability
            )
        else:
            valid = (
                raw_model["kind"] == "estimated"
                and type(estimator.get("shots")) is int
                and estimator["shots"] > 0
                and type(estimator.get("accepted")) is int
                and 0 <= estimator["accepted"] <= estimator["shots"]
                and self.raw_probability == estimator["accepted"] / estimator["shots"]
            )
        if (
            raw_model["parameters"]["staged_protocol"] != self.protocol
            or raw_model["parameters"]["noise"] != resolve(self.noise_params)
            or not valid
        ):
            raise ValueError("PRECOMPUTED_RAW_MODEL_PROVENANCE_MISMATCH")
        if self.distance == 3:
            # Retain the original d3 event identities and sampled local classes.
            self.plus_port = preparation_port("initialize_plus")
        else:
            # The old generic profile uses binary ideal acceptance, not a frame.
            self.plus_port = ProbabilityPort.from_dict(data["plus_port"])
            accepted = self.plus_port.outcome("accepted")
            if (
                accepted.probability != 1
                or dict(accepted.values) != {"accepted": True}
                or self.plus_port.to_dict()["model"]["kind"] != "ideal_exact"
            ):
                raise ValueError("INVALID_RECORDED_PLUS_ACCEPTANCE_REFERENCE")
        self.entries = MappingProxyType(
            {name: self._entry(name, row) for name, row in data["entries"].items()}
        )
        self.layout_catalog = SurfaceReadoutCatalog((self.distance,))
        self.lookups = 0
        self.bound_cost_hits = 0
        self.bound_cost_misses = 0
        self._bound: dict[tuple[Any, ...], ComponentCostProfile] = {}
        self.fingerprint = sha256(
            json.dumps(
                data, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    @classmethod
    def load(
        cls, path: Path | None = None, *, distance: int | None = None
    ) -> "FactoryObjectCatalog":
        """Read one recorded distance; missing coverage never requests a build.

        An omitted path selects the packaged distance file (d3 by default).
        Explicit paths infer their distance unless an expected distance is given.
        Unsupported or mismatching distances raise ValueError.
        """
        if distance is not None and (
            type(distance) is not int or distance not in _RECORDED_DISTANCES
        ):
            raise ValueError(
                "UNSUPPORTED_OBJECT_CATALOG_DISTANCE: available=3,5,7,9,11"
            )
        if path is None:
            selected = 3 if distance is None else distance
            path = DEFAULT_INPUT.with_name(f"object_d{selected}_reference.json")
        catalog = cls(json.loads(path.read_text(encoding="utf-8")))
        if distance is not None and catalog.distance != distance:
            raise ValueError("OBJECT_CATALOG_DISTANCE_MISMATCH")
        return catalog

    def _entry(self, name: str, row: Mapping[str, Any]) -> ComponentCostProfile:
        stages = []
        held = False
        round_index = 0
        measurements: list[tuple[int, float]] = []
        for i, (duration, kind, resource, results, motion) in enumerate(row["phases"]):
            fixed_time = {"load": 10, "store": 10, "measurement": 100}.get(kind)
            if fixed_time is not None and duration != fixed_time:
                raise ValueError("RECORDED_PHASE_TIMING_CONVENTION_MISMATCH")
            if motion not in (None, "readout", "cnot") or (
                motion is not None and kind != "movement"
            ):
                raise ValueError("UNKNOWN_OBJECT_TRANSPORT_COST_MODEL")
            if (
                type(duration) not in (int, float)
                or not isfinite(duration)
                or duration < 0
            ):
                raise ValueError("INVALID_RECORDED_PHASE_DURATION")
            acquire = ("aod:transport",) if kind == "load" and not held else ()
            release = ("aod:transport",) if kind == "store" else ()
            if kind == "load":
                if held:
                    raise ValueError("RECORDED_LOAD_WITH_ACTIVE_LEASE")
                held = True
            resources = (
                set()
                if resource == "none"
                else {"aod:transport" if resource == "aod" else resource}
            )
            if held:
                resources.add("aod:transport")
            if kind == "store":
                if not held:
                    raise ValueError("RECORDED_STORE_WITHOUT_LEASE")
                held = False
            category = "transfer" if kind in ("load", "store") else kind
            prefix = f"round[{round_index}]/" if name == "raw_t_postselection" else ""
            stages.append(
                ComponentPhase(
                    f"{prefix}p{i:03d}:{kind}",
                    float(duration),
                    category,
                    tuple(sorted(resources)),
                    acquire=acquire,
                    release=release,
                    results=results,
                )
            )
            measurements.extend((i, 0.0) for _ in range(results))
            if (
                name == "raw_t_postselection"
                and kind == "store"
                and len(measurements) >= 8 * (round_index + 1)
            ):
                round_index += 1
        if held:
            raise ValueError("RECORDED_COMPONENT_LEAVES_AOD_ACTIVE")
        if name == "raw_t_postselection" and (
            len(measurements) != 24 or round_index != 3
        ):
            raise ValueError("RECORDED_INJECTION_REQUIRES_THREE_EIGHT_CHECK_ROUNDS")
        return ComponentCostProfile(
            name,
            name,
            (),
            None,
            "object/" + name,
            tuple(p.duration_us for p in stages),
            tuple(measurements),
            (),
            (),
            MappingProxyType(dict(row["primitive_counts"])),
            (),
            (),
            MappingProxyType(
                {
                    "result_count": len(measurements),
                    "correction_envelope": row["correction_envelope"],
                    **{
                        key: row[key]
                        for key in ("syndrome_rounds", "growth_rounds")
                        if key in row
                    },
                }
            ),
            tuple(stages),
        )

    def layout(
        self,
        factories: int,
        *,
        distance: int | None = None,
        placement: str = "vertical",
        columns: int | None = None,
    ) -> FastLayout:
        """Build whole-factory placement metadata, with vertical as the default.

        Forward placement/columns to the existing readout layout catalog; invalid
        layouts or unsupported distance coverage raise without compiling atoms.
        """
        distance = self.distance if distance is None else distance
        if type(distance) is not int or distance != self.distance:
            raise ValueError(
                f"UNSUPPORTED_OBJECT_CATALOG_DISTANCE: only d{self.distance} inputs "
                "are loaded"
            )
        return self.layout_catalog.layout(
            distance, factories, placement=placement, columns=columns
        )

    def bind_cost(
        self, component: str, participants: tuple[FastPatch, ...]
    ) -> ComponentCostProfile:
        """Evaluate readout height/CNOT distance without rebuilding component stages."""
        self.lookups += 1
        if component not in self.entries:
            raise ValueError(f"UNPREPARED_COMPONENT: {component}; no compiler fallback")
        delta = 0.0
        if component == "transversal_cnot":
            if (
                len(participants) != 2
                or participants[0].origin.y != participants[1].origin.y
            ):
                raise ValueError("CNOT_REQUIRES_TWO_HORIZONTAL_SAME_DISTANCE_BLOCKS")
            delta = participants[1].origin.x - participants[0].origin.x
        elif len(participants) != 1:
            raise ValueError("SINGLE_BLOCK_COMPONENT_REQUIRES_ONE_PARTICIPANT")
        if any(
            p.distance != self.distance or p.code_id != self.code_id
            for p in participants
        ):
            raise ValueError("OBJECT_PARTICIPANT_DISTANCE_MISMATCH")
        y = participants[0].origin.y
        if y + _home_bounds(self.distance).y_max > 0:
            raise ValueError("OBJECT_BLOCK_OUTSIDE_STORAGE_HALFPLANE")
        key = (component, delta, y)
        if key in self._bound:
            self.bound_cost_hits += 1
            return self._bound[key]
        base = self.entries[component]
        rows = self.document["entries"][component]["phases"]
        speed = self.document["move_us_per_um"]
        stages = tuple(
            replace(
                p,
                duration_us=(
                    abs(delta + self.document["pair_separation_um"]) * speed
                    if r[4] == "cnot"
                    else r[0] + (self.document["reference_origin_y_um"] - y) * speed
                    if r[4] == "readout"
                    else r[0]
                ),
            )
            for p, r in zip(base.stages, rows, strict=True)
        )
        entry = replace(
            base, stages=stages, phase_durations_us=tuple(p.duration_us for p in stages)
        )
        self._bound[key] = entry
        self.bound_cost_misses += 1
        return entry


class FactoryObjectProfile:
    """Existing profile seam with stage resources and precomputed event ports."""

    def __init__(self, catalog: FactoryObjectCatalog, layout: FastLayout) -> None:
        self.catalog, self.layout = catalog, layout
        self.profile_sha256 = catalog.fingerprint
        self.noise_params = catalog.noise_params
        self.wave_timeout_seconds = 5.0
        self._patches = layout.bindings
        self._plus = catalog.plus_port

    def lookup(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Any = (),
    ) -> ComponentCostProfile:
        """Require exact protocol/geometry coverage; never synthesize a missing cost."""
        expected = (
            {"injection_rounds": 3} if component_id == "raw_t_postselection" else {}
        )
        if dict(parameters) != expected:
            raise ValueError("OBJECT_PROTOCOL_PARAMETERS_CHANGED")
        if any(self._patches.get(p.block_id) != p for p in participants):
            raise ValueError("UNKNOWN_OBJECT_CARRIER")
        if selection is not None and (
            not component_id.endswith("/canonicalize")
            or dict(selection)
            != {"accepted": True, "correction_policy": "one_pauli_layer_bound"}
        ):
            raise ValueError("INVALID_OBJECT_CORRECTION_SELECTION")
        return self.catalog.bind_cost(component_id, participants)

    def describe(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        parameters: Any = (),
        *,
        budget: Mapping[str, Any],
    ) -> ComponentExecutionSpec:
        """Reserve participants and a conservative storage/gate envelope per call."""
        entry = self.lookup(component_id, participants, parameters=parameters)
        if budget.get("aod_count") != 1:
            raise ValueError("OBJECT_FACTORY_REQUIRES_SINGLE_AOD")
        bounds = _storage_gate_bounds(participants)
        return ComponentExecutionSpec(
            self.catalog.code_id,
            component_id,
            entry.waveform_key,
            tuple(p.block_id for p in participants),
            (SpaceClaim(bounds, "component_storage_gate_envelope"),),
            (),
            "object_wave",
            entry.claim["result_count"],
        )

    def instantiate_wave(
        self, requests: tuple[ExecutionRequest, ...]
    ) -> tuple[ComponentCostProfile, ...]:
        """Share congruent commands across compatible 2D home bands on one AOD."""
        entries: list[ComponentCostProfile] = []
        groups: list[list[int]] = []
        geometries: list[tuple[tuple[float, float], ...]] = []
        participant_sets: list[tuple[FastPatch, ...]] = []
        for request in requests:
            participants = tuple(self._patches[k] for k in request.participant_blocks)
            base = self.lookup(
                request.call.component_id,
                participants,
                request.selection,
                request.call.parameters,
            )
            transport = any("aod:transport" in p.resources for p in base.stages)
            geometry = tuple(
                (
                    p.origin.x - participants[0].origin.x,
                    p.origin.y - participants[0].origin.y,
                )
                for p in participants
            )
            index = len(entries)
            compatible = next(
                (
                    group
                    for group in groups
                    if entries[group[0]].key == base.key
                    and geometries[group[0]] == geometry
                    and (
                        not transport
                        or _compatible_translation_bands(
                            (*tuple(participant_sets[i] for i in group), participants)
                        )
                    )
                ),
                None,
            )
            if compatible is None:
                groups.append([index])
            else:
                compatible.append(index)
            entries.append(base)
            geometries.append(geometry)
            participant_sets.append(participants)
        for group_index, group in enumerate(groups):
            base = entries[group[0]]
            rows = self.catalog.document["entries"][base.key]["phases"]
            durations = tuple(
                max(entries[i].stages[j].duration_us for i in group)
                if row[4] == "readout"
                else base.stages[j].duration_us
                for j, row in enumerate(rows)
            )
            certificate = f"{base.key}:rigid_bands_v2[{group_index}]"
            for i in group:
                stages = tuple(
                    replace(p, duration_us=t, batch_key=certificate)
                    for p, t in zip(entries[i].stages, durations, strict=True)
                )
                entries[i] = replace(
                    entries[i], stages=stages, phase_durations_us=durations
                )
        return tuple(entries)

    def correction_selection(
        self, preparation: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Retain the recorded correction-layer bound without decoder frame samples."""
        if (
            preparation not in ("initialize_plus", "raw_t_postselection")
            or values.get("accepted") is not True
        ):
            raise ValueError("OBJECT_CORRECTION_REQUIRES_ACCEPTED_PREPARATION")
        return {"accepted": True, "correction_policy": "one_pauli_layer_bound"}

    def preparation_port(self, preparation: str) -> ProbabilityPort:
        """Use the saved raw probability and original ideal plus-byproduct model."""
        if preparation == "initialize_plus":
            return self._plus
        if preparation == "raw_t_postselection":
            return self.catalog.raw_port
        raise ValueError("UNKNOWN_OBJECT_PREPARATION")


class FactoryObjectBackend:
    """The established fake-backend semantics with real recorded model inputs."""

    def __init__(
        self,
        profile: FactoryObjectProfile,
        execution: Any,
        model: FactoryExperimentModel,
    ) -> None:
        self.profile, self.execution, self.model = profile, execution, model

    def preparation_event(
        self, preparation: str, source: Any, parameters: Any = None
    ) -> ProbabilityPort:
        """Return the precomputed port after its object receipt is committed."""
        if self.execution.source(
            source.invocation_id
        ) != source or parameters != self.model.parameters(self.profile.noise_params):
            raise ValueError("INVALID_OBJECT_PREPARATION_SOURCE")
        return self.profile.preparation_port(preparation)

    def preparation_quality(
        self, preparation: str, parameters: Any = None
    ) -> dict[str, Any]:
        """Keep accepted-input p separate from raw rejection and physical quality."""
        return self.model.reference_quality(preparation)

    def resolve_event(self, selector: str, parameters: Any = None) -> ProbabilityPort:
        """Use the existing T-consumption reference, including its conditional S."""
        if selector != "t_consumption":
            raise ValueError("OBJECT_FINAL_EVENT_REQUIRES_SOURCES")
        return self.model.consumption_event(parameters)

    def resolve_event_from_sources(
        self, selector: str, parts: tuple[Any, ...], parameters: Any, *, event_id: str
    ) -> ProbabilityPort:
        """Sample final joint checks only after all four original measurements."""
        if selector != "factory_mx":
            return self.resolve_event(selector, parameters)
        if len(parts) != 4 or any(
            self.execution.source(p.invocation_id) != p
            or p.results_ready_us > self.execution.clock_us
            for p in parts
        ):
            raise ValueError("OBJECT_FACTORY_CHECKS_NOT_READY")
        return self.model.final_theory_event(parameters)

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        """Return only the already-defined theoretical output quality."""
        return self.model.output_quality(factory_port)
