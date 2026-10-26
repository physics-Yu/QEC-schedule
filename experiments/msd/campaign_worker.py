"""MSD task adapters for the existing isolated experiment worker.

Calibration is explicit worker work. A witness only reads joint records and
returns missing dependencies; it never invokes the physical compiler.
"""

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import file_digest, sha256
from math import isfinite
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.component import ComponentBinding
from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.fast_factory import entry_key
from modules.codes.rotated_surface.joint_factory_contracts import JointComponentContract
from modules.codes.rotated_surface.joint_factory_profile import (
    JointSurfaceFactoryProfile,
    MissingJointCalibration,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory
from modules.logical_compiler.src.estimation.kernel import PreparedProfileUpdate
from modules.logical_compiler.src.placement import PlacementPlan
from modules.logical_compiler.src.protocols.production import (
    ProductionPolicy,
    make_output_sink,
)

from .joint_cache import (
    JointCacheDeferred,
    JointCacheMiss,
    JointCacheResult,
    JointCalibrationCache,
)
from .joint_transition import TransportTargets, apply_joint_transition, target_document
from .production_metrics import summarize_production
from .standard import ExperimentSpec, ExperimentWorld, build_world

_CALIBRATION_INPUTS = (
    "spec",
    "placement",
    "noise_params",
    "sampling",
    "cache_root",
    "dependencies",
)


def _cache_artifacts(cached: JointCacheResult) -> list[dict[str, str]]:
    """Declare every required cache artifact for completion and resume checks."""
    digests = getattr(cached, "artifact_bytes_sha256", None)
    if digests is not None:
        if (
            not isinstance(digests, Mapping)
            or set(digests) != {"trace", "action", "probability"}
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
                for value in digests.values()
            )
        ):
            raise ValueError("INVALID_CACHE_ARTIFACT_BYTE_HASHES")
        return [
            {"path": str(path), "sha256": digests[name], "hash_kind": "bytes"}
            for name, path in (
                ("trace", cached.trace_path),
                ("action", cached.action_path),
                ("probability", cached.probability_path),
            )
        ]
    return [
        {
            "path": str(cached.trace_path),
            "sha256": cached.group["trace_sha256"],
            "hash_kind": "canonical_json",
        },
        *[
            {
                "path": str(path),
                "sha256": canonical_hash(json.loads(path.read_text(encoding="utf-8"))),
                "hash_kind": "canonical_json",
            }
            for path in (cached.action_path, cached.probability_path)
        ],
    ]


def _prepare_cache(task: dict[str, Any]) -> dict[str, Any]:
    """Prepare optional read indexes for completed records without recalibration.

    Queries are explicit, hash-checked input files. Both scientific producers are
    disabled; incomplete or incompatible records fail visibly. This is isolated
    runner work, never a write performed by a fast-kernel lookup.
    """
    started = perf_counter()
    cache = JointCalibrationCache(task["payload"]["cache_root"])
    artifacts: dict[str, dict[str, str]] = {}
    keys = set()
    queries = task["payload"]["queries"]
    if not isinstance(queries, list) or not queries:
        raise ValueError("CACHE_PREPARATION_QUERIES_REQUIRED")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("CACHE_PREPARATION_REQUIRES_EXISTING_SCIENTIFIC_RECORDS")

    for descriptor in queries:
        path = Path(descriptor["path"])
        data = path.read_bytes()
        if sha256(data).hexdigest() != descriptor["sha256"]:
            raise ValueError("CACHE_QUERY_FILE_HASH_MISMATCH")
        query = json.loads(data)
        if query.get("kind") != "msd.calibrate":
            raise ValueError("CACHE_PREPARATION_REQUIRES_CALIBRATION_QUERY")
        world, _, arguments = _context(query["payload"])
        cached = cache.get_or_create(
            world,
            tuple(query["payload"]["members"]),
            **arguments,
            action_producer=forbidden,
            probability_producer=forbidden,
        )
        if not cached.action_hit or not cached.probability_hit:
            raise ValueError("CACHE_PREPARATION_RECALIBRATION_FORBIDDEN")
        keys.add((cached.action_key, cached.probability_key))
        artifacts[str(path)] = {
            "path": str(path),
            "sha256": descriptor["sha256"],
            "hash_kind": "bytes",
        }
        # The readiness task can use byte hashes directly even for legacy caches.
        for saved in (cached.trace_path, cached.action_path, cached.probability_path):
            if str(saved) not in artifacts:
                with saved.open("rb") as stream:
                    digest = file_digest(stream, "sha256").hexdigest()
                artifacts[str(saved)] = {
                    "path": str(saved),
                    "sha256": digest,
                    "hash_kind": "bytes",
                }
    timing = {"cache_readiness": perf_counter() - started}
    return {
        "status": "ok",
        "result": {
            "queries": len(queries),
            "unique_queries": len(keys),
            "physical_compilation_permitted": False,
            "probability_sampling_permitted": False,
            "software_seconds": timing,
        },
        "artifacts": list(artifacts.values()),
        "software_seconds": timing,
    }


def _context(payload: dict[str, Any]) -> tuple[ExperimentWorld, str, dict[str, Any]]:
    plan = PlacementPlan.from_dict(payload["placement"])
    spec = ExperimentSpec(**payload["spec"])
    if "world_snapshot" in payload:
        if canonical_hash(payload["world_snapshot"]) != payload.get("world_sha256"):
            raise ValueError("WORLD_SNAPSHOT_HASH_MISMATCH")
        world = ExperimentWorld.from_document(payload["world_snapshot"])
        if world.spec != spec or world.placement_plan.to_dict() != plan.to_dict():
            raise ValueError("WORLD_SNAPSHOT_CONFIGURATION_MISMATCH")
    else:
        world = build_world(spec, placement_plan=plan)
    dependencies = payload["dependencies"]
    if not dependencies["actions"] or not dependencies["probabilities"]:
        raise ValueError("FROZEN_CALIBRATION_DEPENDENCIES_REQUIRED")
    family = canonical_hash(
        {"world": world.document(), "actions": dependencies["actions"]}
    )
    arguments = {
        "family": family,
        "noise_params": payload["noise_params"],
        "shots": payload["sampling"]["shots"],
        "seed": payload["sampling"]["seed"],
        "action_dependencies": dependencies["actions"],
        "probability_dependencies": dependencies["probabilities"],
    }
    if payload.get("transport_targets"):
        arguments["transport_targets"] = {
            member: (Position(**target["origin"]), tuple(target["home_sites"]))
            for member, target in payload["transport_targets"].items()
        }
    return world, family, arguments


def calibration_dependency(
    task: dict[str, Any],
    members: tuple[str, ...],
    *,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one seed-independent calibration task for an exact full frontier."""
    payload = task["payload"]
    budget = payload["calibration_budget"]
    child = {
        "kind": "msd.calibrate",
        "payload": {
            **{key: deepcopy(payload[key]) for key in _CALIBRATION_INPUTS},
            "members": sorted(members),
        },
        "dependencies": [],
        "timeout_s": budget["timeout_s"],
        "max_attempts": budget["max_attempts"],
        "memory_bytes": budget["memory_bytes"],
    }
    if request is not None:
        snapshot = deepcopy(request["world"])
        child["payload"].update(
            world_snapshot=snapshot,
            world_sha256=canonical_hash(snapshot),
            transport_targets=deepcopy(request["transport_targets"]),
        )
    return {**child, "task_id": canonical_hash(child)}


class _CachedProfile(JointSurfaceFactoryProfile):
    def __init__(
        self,
        document: dict[str, Any],
        world: ExperimentWorld,
        cache: JointCalibrationCache,
        arguments: dict[str, Any],
        *,
        transport_slots: TransportTargets | None = None,
    ) -> None:
        super().__init__(document)
        self._initial_layout = super().layout()
        self.world, self.cache, self.arguments = world, cache, arguments
        patches = {p.binding.block_id: p for p in world.patches}
        if patches.keys() != self._patches.keys():
            raise ValueError("PROFILE_WORLD_CARRIER_COVERAGE_MISMATCH")
        for key, patch in self._patches.items():
            distance = world.block_definition(key).distance
            if (
                patch.distance != distance
                or patch.code_id != f"rotated_surface_d{distance}"
            ):
                raise ValueError("PROFILE_WORLD_CODE_DISTANCE_MISMATCH")
        self._patches = {
            key: replace(patch, origin=patches[key].binding.origin)
            for key, patch in self._patches.items()
        }
        self._physical_patches = patches
        self._world_sha256 = canonical_hash(world.document())
        self._contract_templates = {
            (contract.code_id, contract.distance, contract.component_id): contract
            for contract in self.contracts.values()
        }
        self.transport_slots = dict(transport_slots or {})
        self._transport_history: dict[str, list[dict[str, Any]]] = {}
        self._transport_by_id: dict[str, dict[str, Any]] = {}
        self._transition_ordinal = 0
        self.cache_load_seconds = 0.0
        self.cache_records: dict[str, dict[str, str]] = {}
        self.artifacts: dict[str, dict[str, str]] = {}
        self._trace_paths: dict[str, Path] = {}

    def group(self, members: tuple[str, ...]) -> dict[str, Any]:
        return self._current_group(members, {})

    def layout(
        self,
        hardware: str = "shared_aod",
        *,
        placement_plan: PlacementPlan | None = None,
    ) -> Any:
        """Retain the original plan while exposing explicitly committed origins."""
        if hardware != "shared_aod" or (
            placement_plan is not None
            and placement_plan.to_dict() != self.world.placement_plan.to_dict()
        ):
            raise ValueError("JOINT_FACTORY_REQUIRES_ORIGINAL_SHARED_DEVICE")
        return replace(
            self._initial_layout,
            factories=tuple(
                replace(
                    factory,
                    patches=tuple(self._patches[p.block_id] for p in factory.patches),
                )
                for factory in self._initial_layout.factories
            ),
        )

    def lookup(
        self,
        component_id: str,
        participants: tuple[Any, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = (),
    ) -> Any:
        """Read static interfaces on current carriers, without routing or sampling."""
        if any(self._patches.get(p.block_id) != p for p in participants):
            raise ValueError("UNCALIBRATED_GENERIC_POSITION")
        blocks = tuple(p.block_id for p in participants)
        if len(set(blocks)) != len(blocks) or len(blocks) != (
            2 if component_id == "transversal_cnot" else 1
        ):
            raise ValueError("JOINT_STATIC_PARTICIPANTS_MISMATCH")
        code_id, distance = self.member_identity(component_id, participants)
        if component_id == "block_translation":
            params = dict(parameters)
            if (
                set(params) != {"destination"}
                or params["destination"] not in self.transport_slots
                or selection is not None
            ):
                raise ValueError("EXPLICIT_TRANSLATION_DESTINATION_REQUIRED")
            count = definition(distance).atom_count
            return JointComponentContract(
                entry_key(component_id, blocks),
                component_id,
                blocks,
                0,
                canonical_hash(
                    {
                        "native_component": "block_translation/1",
                        "distance": distance,
                    }
                ),
                tuple(range(count)),
                tuple(params.items()),
                code_id,
                distance,
            )
        existing = self.contracts.get(entry_key(component_id, blocks))
        if existing is not None and (existing.code_id, existing.distance) == (
            code_id,
            distance,
        ):
            return super().lookup(component_id, participants, selection, parameters)
        template_key = code_id, distance, component_id
        if template_key not in self._contract_templates:
            raise ValueError("UNCALIBRATED_GENERIC_COMPONENT")
        expected = (
            {"injection_rounds": 3} if component_id == "raw_t_postselection" else {}
        )
        if dict(parameters) != expected or (
            selection is not None
            and (
                not component_id.endswith("/canonicalize")
                or dict(selection)
                != {"accepted": True, "correction_policy": "one_pauli_layer_bound"}
            )
        ):
            raise ValueError("UNCALIBRATED_GENERIC_PARAMETERS")
        return replace(
            self._contract_templates[template_key],
            key=entry_key(component_id, blocks),
            participant_blocks=blocks,
        )

    def group_for_requests(self, requests: tuple[Any, ...]) -> dict[str, Any]:
        targets = {}
        for request in requests:
            if request.call.component_id == "block_translation":
                destination = dict(request.call.parameters)["destination"]
                targets[
                    entry_key(request.call.component_id, request.participant_blocks)
                ] = self.transport_slots[destination]
        return self._current_group(
            tuple(
                entry_key(r.call.component_id, r.participant_blocks) for r in requests
            ),
            targets,
        )

    def _current_group(
        self, members: tuple[str, ...], targets: TransportTargets
    ) -> dict[str, Any]:
        key = canonical_hash(
            {
                "members": sorted(members),
                "world_sha256": self._world_sha256,
                "transport_targets": target_document(targets),
            }
        )
        if key not in self.groups:
            started = perf_counter()
            try:
                lookup_arguments = {**self.arguments, "transport_targets": targets}
                result = self.cache.lookup(self.world, members, **lookup_arguments)
                self.artifacts.update(
                    (item["path"], item) for item in _cache_artifacts(result)
                )
            except JointCacheMiss as error:
                raise MissingJointCalibration(
                    members,
                    family=self.joint_family,
                    profile_sha256=self.profile_sha256,
                    placement_fingerprint=self.world.placement_plan.geometry_fingerprint,
                    request={
                        "world": self.world.document(),
                        "transport_targets": target_document(targets),
                    },
                ) from error
            finally:
                self.cache_load_seconds += perf_counter() - started
            self.groups[key] = {**result.group, "profile_group_key": key}
            self.cache_records[key] = {
                "action_key": result.action_key,
                "probability_key": result.probability_key,
                "trace_path": str(result.trace_path),
                "trace_sha256": result.group["trace_sha256"],
            }
            self._trace_paths[result.group["trace_sha256"]] = result.trace_path
        # Reuse the base validator without storing a member-only cache alias.
        return self._validate_group_record(self.groups[key], members)

    def prepare_wave_update(
        self, requests: tuple[Any, ...], entries: tuple[Any, ...]
    ) -> PreparedProfileUpdate | None:
        """Prepare an exact native world transition; lookup never mutates bindings."""
        keys = {entry.claim["joint_group_key"] for entry in entries}
        if len(keys) != 1:
            raise ValueError("STATEFUL_PROFILE_GROUP_MISMATCH")
        key = keys.pop()
        group = self.groups[key]
        if "state_transition" not in group:
            return None
        before, previous = self.world, dict(self._patches)
        trace = self.load_trace(group["trace_sha256"])
        after = apply_joint_transition(before, group, trace)
        patches = {p.binding.block_id: p for p in after.patches}
        updated = {
            name: replace(patch, origin=patches[name].binding.origin)
            for name, patch in previous.items()
        }
        before_hash, after_hash = self._world_sha256, canonical_hash(after.document())
        history = []
        for request in requests:
            member = entry_key(request.call.component_id, request.participant_blocks)
            if member not in group["state_transition"]["bindings"]:
                continue
            update = group["state_transition"]["bindings"][member]
            carrier = update["entry"]["block_id"]
            history.append(
                {
                    **deepcopy(update),
                    "invocation_id": request.invocation_id,
                    "ordinal": self._transition_ordinal,
                    "entry_homes": list(
                        next(
                            p.home_sites
                            for p in before.patches
                            if p.binding.block_id == carrier
                        )
                    ),
                    "trace_sha256": group["trace_sha256"],
                    "entry_world_sha256": group["state_transition"][
                        "entry_state_sha256"
                    ],
                    "exit_world_sha256": group["state_transition"]["exit_state_sha256"],
                }
            )
        evidence = {
            "joint_group_key": key,
            "trace_sha256": group["trace_sha256"],
            "entry_world_sha256": before_hash,
            "exit_world_sha256": after_hash,
            "bindings": deepcopy(group["state_transition"]["bindings"]),
        }

        def commit() -> None:
            if self.world is not before or self._world_sha256 != before_hash:
                raise ValueError("STALE_PROFILE_WORLD_UPDATE")
            # All validation/allocation precedes these assignments; no callback or I/O.
            for item in history:
                self._transport_history.setdefault(
                    item["entry"]["block_id"], []
                ).append(item)
                self._transport_by_id[item["invocation_id"]] = item
            self.world, self._patches, self._world_sha256 = after, updated, after_hash
            self._physical_patches = patches
            self._transition_ordinal += 1

        return PreparedProfileUpdate(
            updated, commit, evidence, previous_bindings=previous
        )

    def transport_evidence(self, receipt: Any) -> dict[str, str]:
        """Reference the already committed native transport, without issuing a token."""
        item = self._transport_by_id.get(receipt.invocation_id)
        if (
            item is None
            or receipt.component_id != "block_translation"
            or receipt.participant_blocks != (item["entry"]["block_id"],)
            or receipt.provenance.get("joint_trace_sha256") != item["trace_sha256"]
        ):
            raise ValueError("UNKNOWN_COMMITTED_NATIVE_TRANSPORT")
        return {
            key: item[key]
            for key in ("trace_sha256", "entry_world_sha256", "exit_world_sha256")
        } | {
            "entry_binding_sha256": canonical_hash(item["entry"]),
            "exit_binding_sha256": canonical_hash(item["exit"]),
        }

    def validate_handoff_transport(
        self, receipts: tuple[Any, ...], *, expected_bindings: tuple[Any, ...]
    ) -> None:
        """Prove committed whole-carrier slot exchange from native transition history."""
        if (
            len(expected_bindings) != 2
            or len({b.block_id for b in expected_bindings}) != 2
        ):
            raise ValueError("HANDOFF_REQUIRES_TWO_CARRIERS")
        current = {p.binding.block_id: p for p in self.world.patches}
        if any(current[b.block_id].binding != b for b in expected_bindings):
            raise ValueError("HANDOFF_CURRENT_BINDING_MISMATCH")
        provided = {r.invocation_id: r for r in receipts}
        selected, endpoints = set(), []
        for binding in expected_bindings:
            history = self._transport_history.get(binding.block_id, [])
            chosen = [item for item in history if item["invocation_id"] in provided]
            if not chosen:
                raise ValueError("HANDOFF_TRANSPORT_HISTORY_MISSING")
            complete = [
                item for item in history if item["ordinal"] >= chosen[0]["ordinal"]
            ]
            if complete != chosen:
                raise ValueError("HANDOFF_TRANSPORT_HISTORY_INCOMPLETE")
            for item in chosen:
                receipt = provided[item["invocation_id"]]
                if receipt.provenance["joint_trace_sha256"] != item["trace_sha256"]:
                    raise ValueError("HANDOFF_TRANSPORT_TRACE_MISMATCH")
                selected.add(item["invocation_id"])
            endpoints.append((chosen[0]["entry_homes"], chosen[-1]["home_sites"]))
        if (
            selected != set(provided)
            or endpoints[0][0] != endpoints[1][1]
            or endpoints[1][0] != endpoints[0][1]
        ):
            raise ValueError("HANDOFF_CARRIER_SLOTS_NOT_EXCHANGED")

    def load_trace(self, trace_sha256: str) -> dict[str, Any]:
        """Load a saved joint trace; metric admission verifies its exact identity."""
        path = self._trace_paths.get(trace_sha256)
        if path is None:
            raise ValueError(
                f"PRODUCTION_TRACE_NOT_IN_EXECUTED_PROFILE: {trace_sha256}"
            )
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def current_bindings(self, blocks: tuple[str, ...]) -> tuple[ComponentBinding, ...]:
        """Read current code-owned physical bindings without scanning trace history."""
        return tuple(self._physical_patches[block].binding for block in blocks)


def _continuous_arguments(task: dict[str, Any]) -> dict[str, Any]:
    payload = task["payload"]
    sink = make_output_sink(payload["output_sink"])
    if task["kind"] == "msd.pilot":
        cycles = payload["pilot_cycles"]
        if type(cycles) is not int or cycles < 2:
            raise ValueError("PILOT_REQUIRES_AT_LEAST_TWO_CYCLES")
        policy = ProductionPolicy(cycles)
    else:
        window = payload["observation_policy"]
        low, stop = window["warmup_us"], window["stop_us"]
        if (
            any(type(v) not in (int, float) or not isfinite(v) for v in (low, stop))
            or not 0 <= low < stop
        ):
            raise ValueError("INVALID_FROZEN_OBSERVATION_WINDOW")
        if payload["seed"] != payload["production_seed"]:
            raise ValueError("CAMPAIGN_PRODUCTION_SEED_MISMATCH")
        policy = ProductionPolicy(payload["limits"]["max_cycles"], stop_at_us=stop)
    return {
        "production_policy": policy,
        "output_sink": sink,
        "max_component_calls": payload["limits"]["max_component_calls"],
    }


def _policy_artifacts(task: dict[str, Any]) -> list[dict[str, str]]:
    if task["kind"] != "msd.produce":
        return []
    payload = task["payload"]
    descriptor = payload["observation_policy_artifact"]
    if (
        set(descriptor) != {"path", "sha256", "hash_kind"}
        or descriptor["hash_kind"] != "canonical_json"
    ):
        raise ValueError("INVALID_FROZEN_POLICY_ARTIFACT")
    envelope = json.loads(Path(descriptor["path"]).read_text(encoding="utf-8"))
    if (
        canonical_hash(envelope) != descriptor["sha256"]
        or envelope.get("schema") != "nadit.msd.frozen_observation_policy/1"
        or envelope.get("policy") != payload["observation_policy"]
        or envelope.get("policy_sha256")
        != canonical_hash(payload["observation_policy"])
        or any(
            envelope.get("identity", {}).get(key) != payload[key]
            for key in ("layout_id", "config_sha256", "source_sha256")
        )
    ):
        raise ValueError("FROZEN_PRODUCTION_POLICY_ARTIFACT_MISMATCH")
    return [dict(descriptor)]


def _continuous_result(
    task: dict[str, Any],
    result: dict[str, Any],
    world: ExperimentWorld,
    profile: _CachedProfile,
) -> None:
    payload, case = task["payload"], result["case"]
    policy = (
        payload.get("observation_policy") if task["kind"] == "msd.produce" else None
    )
    started = perf_counter()
    result["metrics"] = summarize_production(
        case,
        world,
        profile.load_trace,
        warmup_us=0.0 if policy is None else policy["warmup_us"],
        stop_us=case["duration_us"] if policy is None else policy["stop_us"],
    )
    result["software_seconds"]["validation"] = perf_counter() - started
    result["software_times_seconds"] = dict(result["software_seconds"])
    result["case_sha256"] = canonical_hash(case)
    result["output_sink"] = deepcopy(payload["output_sink"])
    result["scope"] = (
        "continuous resource estimate from validated joint traces; "
        "output delivery follows the explicit sink assumptions; no logical-error estimate"
    )
    if policy is not None:
        result.update(
            {
                key: payload[key]
                for key in (
                    "trajectory_id",
                    "layout_id",
                    "seed",
                    "config_sha256",
                    "source_sha256",
                )
            }
        )
        result["observation_policy_sha256"] = canonical_hash(policy)


def execute_task(task: dict[str, Any]) -> dict[str, Any]:
    """Execute explicit calibration, pilot or production work under worker limits.

    Missing calibration returns a deterministic dependency, not a failed
    physical trial or a serial fallback. Production requires an explicitly
    acknowledged sink and a frozen window; pilots require multiple cycles.
    """
    if task["kind"] in (
        "msd.layout_driver",
        "msd.two_level_driver",
        "msd.two_level_layout_driver",
        "msd.summarize",
    ):
        from .campaign_driver import execute_task as execute_driver

        return execute_driver(task)
    if task["kind"] == "msd.prepare_cache":
        return _prepare_cache(task)
    if task["kind"] == "msd.transport_witness":
        from .transport_witness import execute_transport_witness

        return execute_transport_witness(task)
    if task["kind"] in (
        "msd.two_level_witness",
        "msd.two_level_pilot",
        "msd.two_level_produce",
    ):
        from .two_level import execute_two_level_task

        return execute_two_level_task(task)
    started = perf_counter()
    payload = task["payload"]
    continuous = task["kind"] in ("msd.pilot", "msd.produce")
    execution_arguments = _continuous_arguments(task) if continuous else {}
    policy_artifacts = _policy_artifacts(task)
    world, family, arguments = _context(payload)
    cache = JointCalibrationCache(Path(payload["cache_root"]))
    setup_seconds = perf_counter() - started
    if task["kind"] == "msd.calibrate":
        try:
            cached = cache.get_or_create(world, tuple(payload["members"]), **arguments)
        except JointCacheDeferred as error:
            return {"status": "deferred", "reason": str(error)}
        result = asdict(cached)
        for name in ("trace_path", "action_path", "probability_path"):
            result[name] = str(result[name])
        result["software_seconds"]["setup"] = setup_seconds
        inventory_started = perf_counter()
        artifacts = _cache_artifacts(cached)
        result["software_seconds"]["artifact_inventory"] = (
            perf_counter() - inventory_started
        )
        result["software_seconds"]["cold_calibration"] = sum(
            result["software_seconds"].get(key, 0.0)
            for key in ("action_calibration", "probability_calibration")
        )
        if cached.action_hit:
            result["software_seconds"]["validation"] = 0.0
        elif "validation" in cached.group.get("software_seconds", {}):
            result["software_seconds"]["validation"] = cached.group["software_seconds"][
                "validation"
            ]
        return {
            "status": "ok",
            "result": result,
            "artifacts": artifacts,
            "software_seconds": result["software_seconds"],
        }
    if task["kind"] != "msd.witness" and not continuous:
        raise ValueError(f"UNSUPPORTED_MSD_TASK_KIND: {task['kind']}")
    profile = _CachedProfile(
        JointSurfaceFactoryProfile.from_placement(
            world.placement_plan, family=family, noise_params=payload["noise_params"]
        ).to_dict(),
        world,
        cache,
        arguments,
    )
    execution_started = perf_counter()
    setup_seconds = execution_started - started
    try:
        result = run_surface_factory(
            profile,
            seed=payload["production_seed"],
            input_z_error=payload["input_z_error"],
            raw_attempts=payload["limits"]["raw_attempts"],
            batches=payload["limits"]["batches"],
            placement_plan=world.placement_plan,
            **execution_arguments,
        )
    except MissingJointCalibration as error:
        return {
            "status": "needs_dependencies",
            "reason": error.to_dict(),
            "dependency_requests": [
                calibration_dependency(task, error.members, request=error.request)
            ],
            "software_seconds": {
                "setup": setup_seconds,
                "cache_load": profile.cache_load_seconds,
                "fast_prefix": max(
                    0.0, perf_counter() - execution_started - profile.cache_load_seconds
                ),
            },
        }
    elapsed = perf_counter() - execution_started
    result["software_seconds"] = {
        "setup": setup_seconds,
        "cache_load": profile.cache_load_seconds,
        "fast_execution": max(0.0, elapsed - profile.cache_load_seconds),
    }
    result["calibration_records"] = profile.cache_records
    artifacts = [*profile.artifacts.values(), *policy_artifacts]
    result["scope"] = (
        "one-cycle witness; not continuous production or steady-state throughput"
    )
    if continuous:
        try:
            _continuous_result(task, result, world, profile)
        except (ValueError, KeyError, TypeError, OSError) as error:
            return {
                "status": "software_error",
                "reason": f"PRODUCTION_METRIC_AUDIT_FAILED: {type(error).__name__}: {error}",
                "result": result,
                "artifacts": artifacts,
                "software_seconds": result["software_seconds"],
            }
    case = result["case"]
    statuses = {line["status"] for line in case["factories"].values()}
    if statuses & {"expansion_budget_exhausted", "production_cycle_budget_exhausted"}:
        return {
            "status": "budget_exceeded",
            "reason": sorted(statuses),
            "result": result,
            "artifacts": artifacts,
            "software_seconds": result["software_seconds"],
        }
    if (
        case["status"] not in ("complete", "partial_failure")
        or case.get("failure") is not None
        or statuses
        - {
            "complete",
            "distillation_rejected",
            "input_supply_exhausted",
            "external_supply_exhausted",
        }
    ):
        return {
            "status": "software_error",
            "reason": {
                "case_status": case["status"],
                "failure": case.get("failure"),
                "lines": sorted(statuses),
            },
            "result": result,
            "artifacts": artifacts,
            "software_seconds": result["software_seconds"],
        }
    return {
        "status": "ok",
        "result": result,
        "artifacts": artifacts,
        "software_seconds": result["software_seconds"],
    }
