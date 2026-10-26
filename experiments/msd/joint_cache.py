"""Durable complete-world action and probability caches for explicit offline work.

The fast kernel never uses this producer. Completion records are published last;
the existing experiment journal supplies atomic writes and process-lifetime locks.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.cost.base import require_validated
from nadit_physical_compiler.experiments.journal import directory_lock, write_json
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.rotated_surface.joint_factory_source import factory_component_source
from modules.codes.rotated_surface.translation import BlockTranslationComponent

from .joint_factory_calibration import (
    combine_joint_group,
    compile_joint_actions,
    evaluate_joint_probabilities,
    projected_raw_port,
)
from .joint_transition import (
    TransportTargets,
    check_members,
    member_code_contract,
    member_definition,
    target_document,
    validate_transition,
)
from .standard import ExperimentWorld

_ACTION_SCHEMA = "nadit.joint_action_cache/1"
_PROBABILITY_SCHEMA = "nadit.joint_probability_cache/1"
_READ_INDEX_SCHEMA = "nadit.joint_read_index/1"


class JointCacheMiss(RuntimeError):
    """A read-only lookup has no complete artifact for the requested exact key."""

    def __init__(self, layer: str, key: str) -> None:
        self.layer, self.key = layer, key
        super().__init__(f"JOINT_CACHE_MISS: {layer}: {key}")

    def to_dict(self) -> dict[str, Any]:
        """Expose the missing layer/key so the runner can schedule offline work."""
        return {
            "schema": "nadit.joint_cache_miss/1",
            "layer": self.layer,
            "key": self.key,
            "reason": "no_complete_compatible_record",
        }


class JointCacheDeferred(RuntimeError):
    """A live worker owns this exact key; retry later without starting duplicate work."""

    def __init__(self, layer: str, key: str) -> None:
        self.layer, self.key = layer, key
        super().__init__(f"JOINT_CACHE_DEFERRED: {layer}: {key}")


@dataclass(frozen=True)
class JointCacheResult:
    """Complete profile group and independently measured cache-stage provenance."""

    group: dict[str, Any]
    action_key: str
    probability_key: str
    action_hit: bool
    probability_hit: bool
    trace_path: Path
    action_path: Path
    probability_path: Path
    software_seconds: dict[str, float]
    read_index_hit: bool = False
    artifact_bytes_sha256: dict[str, str] | None = None


def _file_hashes(paths: list[Path], root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(set(paths))
    }


def action_dependency_fingerprints() -> dict[str, Any]:
    """Fingerprint action-producing dependencies, excluding probability models.

    The full physical compiler path is conservatively retained except cost,
    experiment orchestration and visualization. Actual source contracts and the
    whole Device/world are additionally included in every action identity.
    """
    root = Path(__file__).resolve().parents[2]
    package = root / "modules/physical_compiler/src/nadit_physical_compiler"
    excluded = {"cost", "experiments", "visualization"}
    paths = [
        path
        for path in package.rglob("*.py")
        if not excluded.intersection(path.relative_to(package).parts)
    ]
    paths.extend(
        root / name
        for name in (
            "experiments/msd/parallel_se_metrics.py",
            "experiments/msd/standard.py",
            "experiments/msd/component_reuse.py",
            "modules/codes/rotated_surface/joint_factory_source.py",
            "modules/codes/rotated_surface/growth.py",
            "modules/codes/rotated_surface/components.py",
            "modules/codes/rotated_surface/algebra.py",
            "modules/codes/rotated_surface/circuits.py",
            "modules/codes/rotated_surface/definition.py",
            "modules/codes/rotated_surface/measurement.py",
            "modules/codes/rotated_surface/transversal.py",
            "modules/codes/rotated_surface/translation.py",
            "experiments/msd/joint_transition.py",
            "modules/codes/rotated_surface_d3/protocols/factory.py",
        )
    )
    from .calibrate import _union_duration, summarize

    return {
        "version": "joint-actions/1",
        "files": _file_hashes(paths, root),
        "producer": sha256(
            inspect.getsource(compile_joint_actions).encode()
        ).hexdigest(),
        "metrics": sha256(inspect.getsource(summarize).encode()).hexdigest(),
        "interval_union": sha256(
            inspect.getsource(_union_duration).encode()
        ).hexdigest(),
        "qiskit": version("qiskit"),
        "qiskit_qasm3_import": version("qiskit-qasm3-import"),
    }


def probability_dependency_fingerprints() -> dict[str, Any]:
    """Fingerprint noise and acceptance algorithms separately from action costs."""
    root = Path(__file__).resolve().parents[2]
    package = root / "modules/physical_compiler/src/nadit_physical_compiler"
    paths = list((package / "cost").rglob("*.py"))
    paths.extend(
        root / name
        for name in (
            "modules/physical_compiler/src/nadit_physical_compiler/activity.py",
            "modules/codes/_support/detector_probability.py",
            "modules/codes/_support/pauli_detector_events.py",
            "modules/codes/contracts/event_probability.py",
        )
    )
    from modules.codes.rotated_surface.fast_factory import acceptance_port

    return {
        "model": "noise/v1+raw_detector_monte_carlo/1",
        "files": _file_hashes(paths, root),
        "producer": sha256(
            inspect.getsource(evaluate_joint_probabilities).encode()
        ).hexdigest(),
        "projection": sha256(
            inspect.getsource(projected_raw_port).encode()
        ).hexdigest(),
        "port": sha256(inspect.getsource(acceptance_port).encode()).hexdigest(),
        "numpy": version("numpy"),
    }


def joint_action_identity(
    world: ExperimentWorld,
    members: tuple[str, ...],
    dependencies: Mapping[str, Any],
    *,
    transport_targets: TransportTargets | None = None,
) -> dict[str, Any]:
    """Retain complete frontier, source contracts, Device and every spectator."""
    members = tuple(sorted(members))
    if not members or len(set(members)) != len(members):
        raise ValueError("INVALID_JOINT_FRONTIER")
    check_members(members, transport_targets)
    patches = {patch.binding.block_id: patch for patch in world.patches}
    contracts = {}
    for member in members:
        component, block_names = member.split(":", 1)
        selected = tuple(patches[name] for name in block_names.split(","))
        code = member_definition(world, component, selected)
        code_contract = member_code_contract(world, code)
        if component == "block_translation":
            assert transport_targets is not None
            origin, homes = transport_targets[member]
            patch = selected[0]
            BlockTranslationComponent(code.distance).native_goal(
                world.device,
                world=world.state,
                binding=patch.binding,
                target_origin=origin,
                target_home_sites=homes,
                operation_id=0,
            )
            contracts[member] = {
                **code_contract,
                "native_component": "block_translation/1",
                "wire_indices": list(range(len(patch.binding.atom_ids))),
                "active_atoms": list(patch.binding.atom_ids),
                "result_count": 0,
            }
            continue
        source = factory_component_source(component, code.distance)
        atoms = tuple(atom for patch in selected for atom in patch.binding.atom_ids)
        contracts[member] = {
            **code_contract,
            "source_sha256": sha256(source.source_qasm.encode()).hexdigest(),
            "wire_indices": list(source.wire_indices),
            "result_count": source.result_count,
            "active_atoms": [atoms[index] for index in source.wire_indices],
        }
    result: dict[str, Any] = json.loads(
        json.dumps(
            {
                "schema": "nadit.joint_action_identity/1",
                "scope": "complete_world",
                "world": world.document(),
                "members": list(members),
                "source_contracts": contracts,
                "dependencies": dict(dependencies),
            },
            allow_nan=False,
        )
    )
    if transport_targets:
        result["transport_targets"] = target_document(transport_targets)
    return result


@contextmanager
def _key_lock(directory: Path, layer: str, key: str) -> Iterator[None]:
    try:
        with directory_lock(directory):
            yield
    except ValueError as error:
        if str(error).startswith("Experiment already has a writer:"):
            raise JointCacheDeferred(layer, key) from error
        raise


def _read(
    path: Path, *, fingerprints: dict[Path, str] | None = None
) -> dict[str, Any] | None:
    try:
        contents = path.read_bytes()
        value = json.loads(contents.decode("utf-8"))
        if not isinstance(value, dict):
            return None
        if fingerprints is not None:
            fingerprints[path] = sha256(contents).hexdigest()
        return value
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _envelope(
    schema: str, inputs: dict[str, Any], record: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema": schema,
        "key": canonical_hash(inputs),
        "inputs": inputs,
        "record": record,
        "record_sha256": canonical_hash(record),
        "complete": True,
    }


def _record(
    path: Path,
    schema: str,
    inputs: dict[str, Any],
    *,
    fingerprints: dict[Path, str] | None = None,
) -> dict[str, Any] | None:
    envelope = _read(path, fingerprints=fingerprints)
    if envelope is None:
        return None
    record = envelope.get("record")
    try:
        valid = (
            envelope.get("schema") == schema
            and envelope.get("complete") is True
            and envelope.get("key") == canonical_hash(inputs)
            and envelope.get("inputs") == inputs
            and isinstance(record, dict)
            and envelope.get("record_sha256") == canonical_hash(record)
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return None
    return record


def _bytes_hash(path: Path) -> str:
    """Check original bytes without parsing or allocating another large trace."""
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reader_fingerprint() -> str:
    """Invalidate derived attestations independently of scientific cache keys."""
    root = Path(__file__).resolve().parents[2]
    return canonical_hash(
        _file_hashes(
            [
                root / name
                for name in (
                    "experiments/msd/joint_cache.py",
                    "experiments/msd/joint_transition.py",
                    "experiments/msd/joint_factory_calibration.py",
                    "modules/codes/contracts/event_probability.py",
                    "modules/physical_compiler/src/nadit_physical_compiler/cost/base.py",
                    "modules/physical_compiler/src/nadit_physical_compiler/provenance.py",
                )
            ],
            root,
        )
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _check_action(
    action: dict[str, Any],
    trace: dict[str, Any],
    members: tuple[str, ...],
    transport_targets: TransportTargets | None = None,
    *,
    inputs: Mapping[str, Any],
) -> None:
    require_validated(trace)
    if (
        action.get("schema") != "nadit.joint_actions/1"
        or action.get("validation_ok") is not True
        or set(action.get("members", {})) != set(members)
        or action.get("trace_sha256") != canonical_hash(trace)
    ):
        raise ValueError("INVALID_JOINT_ACTION_ARTIFACT")
    _check_requested_world(action, trace, inputs)
    validate_transition(action, trace)
    actual_targets = {
        member: {"origin": update["exit"]["origin"], "home_sites": update["home_sites"]}
        for member, update in action.get("state_transition", {})
        .get("bindings", {})
        .items()
    }
    if actual_targets != target_document(transport_targets):
        raise ValueError("JOINT_TRANSLATION_REQUEST_MISMATCH")


def _check_requested_world(
    action: Mapping[str, Any], trace: Mapping[str, Any], inputs: Mapping[str, Any]
) -> None:
    """Bind producer and cached evidence to the actual requested complete world."""
    world = inputs["world"]
    contracts = inputs["source_contracts"]
    participants = {
        member: contracts[member]["active_atoms"] for member in inputs["members"]
    }
    entry = dict(world["entry_state"])
    entry["qubit_to_atom"] = [
        atom for member in inputs["members"] for atom in participants[member]
    ]
    source_contracts = {
        member: {key: value for key, value in contract.items() if key != "active_atoms"}
        for member, contract in contracts.items()
    }
    actual_participants = action.get("participant_atoms")
    actual_contracts = action.get("source_contracts")
    if (
        trace.get("device") != world["device"]
        or trace.get("entry_state") != entry
        or not isinstance(actual_participants, Mapping)
        or not isinstance(actual_contracts, Mapping)
        or canonical_hash(actual_participants) != canonical_hash(participants)
        or canonical_hash(actual_contracts) != canonical_hash(source_contracts)
    ):
        raise ValueError("JOINT_REQUEST_WORLD_OR_SOURCE_MISMATCH")
    bindings = {
        patch["binding"]["block_id"]: patch["binding"] for patch in world["patches"]
    }
    for member, update in (
        action.get("state_transition", {}).get("bindings", {}).items()
    ):
        if canonical_hash(update["entry"]) != canonical_hash(
            bindings[member.split(":", 1)[1]]
        ):
            raise ValueError("JOINT_REQUEST_SOURCE_BINDING_MISMATCH")


def _check_probability(
    probability: dict[str, Any], action: dict[str, Any], inputs: dict[str, Any]
) -> None:
    expected = {
        member
        for member in action["members"]
        if member.startswith("raw_t_postselection:")
    }
    if (
        probability.get("schema") != "nadit.joint_probabilities/1"
        or probability.get("trace_sha256") != action["trace_sha256"]
        or any(
            probability.get(key) != inputs[key]
            for key in ("noise_params", "shots", "seed")
        )
        or set(probability.get("raw_ports", {})) != expected
    ):
        raise ValueError("INVALID_JOINT_PROBABILITY_ARTIFACT")
    for document in probability["raw_ports"].values():
        port = ProbabilityPort.from_dict(document)
        if (
            port.to_dict()["model"]["evidence"].get("joint_trace_sha256")
            != action["trace_sha256"]
        ):
            raise ValueError("JOINT_PROBABILITY_TRACE_MISMATCH")


class JointCalibrationCache:
    """Exact-key offline cache with process locks and completion-last publication.

    Dependency snapshots can be supplied by a frozen campaign or computed once
    per cache instance. Custom producers exist for bounded tests and explicit
    integrations; default producers compile real shared-device actions.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._action_dependencies: dict[str, Any] | None = None
        self._probability_dependencies: dict[str, Any] | None = None
        self._reader_sha256: str | None = None

    def _read_index(
        self, query: dict[str, Any], index_path: Path
    ) -> tuple[dict[str, Any], str, dict[str, str]] | None:
        """Reuse only the exact bytes certified by the current full reader.

        This is a disposable read accelerator, never a source of calibration.
        Missing or stale evidence falls through to the original full checks.
        """
        index = _read(index_path)
        if index is None:
            return None
        group = index.get("group")
        probability_key = index.get("probability_key")
        fingerprints = index.get("files_sha256")
        try:
            valid = (
                index.get("schema") == _READ_INDEX_SCHEMA
                and index.get("complete") is True
                and index.get("query_key") == canonical_hash(query)
                and index.get("query") == query
                and index.get("reader_sha256") == self._reader_sha256
                and _is_sha256(probability_key)
                and isinstance(fingerprints, dict)
                and set(fingerprints) == {"action", "trace", "probability"}
                and all(_is_sha256(value) for value in fingerprints.values())
                and isinstance(group, dict)
                and group.get("family") == ""
                and group.get("schema") == "nadit.joint_actions/1"
                and group.get("validation_ok") is True
                and group.get("cache_keys")
                == {"action": query["action_key"], "probability": probability_key}
                and index.get("group_sha256") == canonical_hash(group)
            )
        except (TypeError, ValueError):
            return None
        if not valid:
            return None
        assert isinstance(group, dict)
        assert isinstance(probability_key, str)
        assert isinstance(fingerprints, dict)
        paths = self._artifact_paths(query["action_key"], probability_key)
        try:
            observed = {name: _bytes_hash(path) for name, path in paths.items()}
        except FileNotFoundError:
            return None
        if observed != fingerprints:
            return None
        return group, probability_key, observed

    def _artifact_paths(self, action_key: str, probability_key: str) -> dict[str, Path]:
        directory = self.root / "actions" / action_key
        return {
            "action": directory / "action.json",
            "trace": directory / "trace.json",
            "probability": self.root
            / "probabilities"
            / probability_key
            / "probability.json",
        }

    def _publish_read_index(
        self,
        query: dict[str, Any],
        index_path: Path,
        group: dict[str, Any],
        probability_key: str,
        validated_bytes: dict[Path, str],
    ) -> dict[str, str]:
        """Publish after full validation; never rewrite scientific artifacts."""
        paths = self._artifact_paths(query["action_key"], probability_key)
        fingerprints = {name: validated_bytes[path] for name, path in paths.items()}
        query_key = canonical_hash(query)
        with _key_lock(index_path.parent, "read_indexes", query_key):
            # These hashes were collected from the exact bytes parsed above.
            # A concurrent rewrite cannot be certified without full validation.
            if any(
                _bytes_hash(path) != fingerprints[name] for name, path in paths.items()
            ):
                raise ValueError("JOINT_READ_INDEX_ARTIFACT_CHANGED")
            content = {**group, "family": ""}
            write_json(
                index_path,
                {
                    "schema": _READ_INDEX_SCHEMA,
                    "query_key": query_key,
                    "query": query,
                    "reader_sha256": self._reader_sha256,
                    "probability_key": probability_key,
                    "group": content,
                    "group_sha256": canonical_hash(content),
                    "files_sha256": fingerprints,
                    "complete": True,
                },
            )
        return fingerprints

    def get_or_create(
        self,
        world: ExperimentWorld,
        members: tuple[str, ...],
        *,
        family: str,
        transport_targets: TransportTargets | None = None,
        noise_params: dict[str, Any],
        shots: int,
        seed: int,
        action_dependencies: Mapping[str, Any] | None = None,
        probability_dependencies: Mapping[str, Any] | None = None,
        action_producer: Callable[..., tuple[dict[str, Any], dict[str, Any]]]
        | None = None,
        probability_producer: Callable[..., dict[str, Any]] | None = None,
    ) -> JointCacheResult:
        """Reuse or produce exact records; report lock contention as deferred work.

        Partial, corrupt or incompatible files are misses, never successful
        completion. Producer failures propagate; no physical rejection is inferred.
        """
        return self._resolve(
            world,
            members,
            family=family,
            transport_targets=transport_targets,
            noise_params=noise_params,
            shots=shots,
            seed=seed,
            action_dependencies=action_dependencies,
            probability_dependencies=probability_dependencies,
            action_producer=action_producer,
            probability_producer=probability_producer,
            produce=True,
        )

    def lookup(
        self,
        world: ExperimentWorld,
        members: tuple[str, ...],
        *,
        family: str,
        transport_targets: TransportTargets | None = None,
        noise_params: dict[str, Any],
        shots: int,
        seed: int,
        action_dependencies: Mapping[str, Any] | None = None,
        probability_dependencies: Mapping[str, Any] | None = None,
    ) -> JointCacheResult:
        """Read exact validated artifacts or raise a structured JointCacheMiss.

        This path never creates directories, locks, compiles actions or samples
        probabilities. Missing work belongs to an explicit offline runner task.
        """
        return self._resolve(
            world,
            members,
            family=family,
            transport_targets=transport_targets,
            noise_params=noise_params,
            shots=shots,
            seed=seed,
            action_dependencies=action_dependencies,
            probability_dependencies=probability_dependencies,
            action_producer=None,
            probability_producer=None,
            produce=False,
        )

    def _resolve(
        self,
        world: ExperimentWorld,
        members: tuple[str, ...],
        *,
        family: str,
        transport_targets: TransportTargets | None,
        noise_params: dict[str, Any],
        shots: int,
        seed: int,
        action_dependencies: Mapping[str, Any] | None,
        probability_dependencies: Mapping[str, Any] | None,
        action_producer: Callable[..., tuple[dict[str, Any], dict[str, Any]]] | None,
        probability_producer: Callable[..., dict[str, Any]] | None,
        produce: bool,
    ) -> JointCacheResult:
        """Share identities and integrity checks between reader and producer APIs."""
        started = perf_counter()
        if type(shots) is not int or shots < 1 or type(seed) is not int or seed < 0:
            raise ValueError("INVALID_JOINT_PROBABILITY_SAMPLING")
        if action_dependencies is None:
            if self._action_dependencies is None:
                self._action_dependencies = action_dependency_fingerprints()
            action_dependencies = self._action_dependencies
        if probability_dependencies is None:
            if self._probability_dependencies is None:
                self._probability_dependencies = probability_dependency_fingerprints()
            probability_dependencies = self._probability_dependencies
        action_inputs = joint_action_identity(
            world, members, action_dependencies, transport_targets=transport_targets
        )
        action_key = canonical_hash(action_inputs)
        members = tuple(action_inputs["members"])
        directory = self.root / "actions" / action_key
        action_path, trace_path = directory / "action.json", directory / "trace.json"
        query = {
            "schema": "nadit.joint_read_query/1",
            "action_key": action_key,
            "noise_params": noise_params,
            "shots": shots,
            "seed": seed,
            "probability_dependencies": dict(probability_dependencies),
        }
        index_path = self.root / "read_indexes" / canonical_hash(query) / "index.json"
        if self._reader_sha256 is None:
            self._reader_sha256 = _reader_fingerprint()
        indexed = self._read_index(query, index_path)
        if indexed is not None:
            indexed_group, probability_key, fingerprints = indexed
            elapsed = perf_counter() - started
            paths = self._artifact_paths(action_key, probability_key)
            return JointCacheResult(
                {**indexed_group, "family": family},
                action_key,
                probability_key,
                True,
                True,
                trace_path,
                action_path,
                paths["probability"],
                {
                    "cache_load": elapsed,
                    "action_calibration": 0.0,
                    "probability_calibration": 0.0,
                    "total": elapsed,
                },
                read_index_hit=True,
                artifact_bytes_sha256=fingerprints,
            )
        validated_bytes: dict[Path, str] = {}

        def load_action() -> tuple[dict[str, Any], dict[str, Any]] | None:
            action = _record(
                action_path, _ACTION_SCHEMA, action_inputs, fingerprints=validated_bytes
            )
            trace = _read(trace_path, fingerprints=validated_bytes)
            if action is None or trace is None:
                return None
            try:
                _check_action(
                    action, trace, members, transport_targets, inputs=action_inputs
                )
            except (ValueError, KeyError, TypeError, IndexError):
                return None
            return action, trace

        loaded = load_action()
        action_hit = loaded is not None
        load_seconds = perf_counter() - started
        action_seconds = 0.0
        if loaded is None:
            if not produce:
                raise JointCacheMiss("actions", action_key)
            with _key_lock(directory, "actions", action_key):
                loaded = load_action()
                if loaded is None:
                    action_started = perf_counter()
                    producer = action_producer or compile_joint_actions
                    from .component_reuse import ComponentOperationCache

                    action, trace = producer(
                        world,
                        members,
                        family=action_key,
                        **(
                            {
                                "component_cache": ComponentOperationCache(
                                    self.root / "components"
                                )
                            }
                            if action_producer is None
                            else {}
                        ),
                        **(
                            {"transport_targets": transport_targets}
                            if transport_targets
                            else {}
                        ),
                    )
                    _check_action(
                        action, trace, members, transport_targets, inputs=action_inputs
                    )
                    write_json(trace_path, trace)
                    persisted = _read(trace_path)
                    if (
                        persisted is None
                        or canonical_hash(persisted) != action["trace_sha256"]
                    ):
                        raise ValueError("PUBLISHED_JOINT_TRACE_HASH_MISMATCH")
                    write_json(
                        action_path, _envelope(_ACTION_SCHEMA, action_inputs, action)
                    )
                    loaded = load_action()
                    if loaded is None:
                        raise ValueError("PUBLISHED_JOINT_ACTION_MISMATCH")
                    action_seconds = perf_counter() - action_started
                else:
                    action_hit = True
        action, trace = loaded
        probability_inputs = {
            "schema": "nadit.joint_probability_identity/1",
            "trace_sha256": action["trace_sha256"],
            "projection_sha256": canonical_hash(
                {
                    key: action[key]
                    for key in (
                        "participant_atoms",
                        "measurement_ids",
                        "source_contracts",
                    )
                }
            ),
            "noise_params": noise_params,
            "shots": shots,
            "seed": seed,
            "dependencies": dict(probability_dependencies),
        }
        probability_key = canonical_hash(probability_inputs)
        probability_directory = self.root / "probabilities" / probability_key
        probability_path = probability_directory / "probability.json"
        probability_started = perf_counter()

        def load_probability() -> dict[str, Any] | None:
            probability = _record(
                probability_path,
                _PROBABILITY_SCHEMA,
                probability_inputs,
                fingerprints=validated_bytes,
            )
            if probability is not None:
                try:
                    _check_probability(probability, action, probability_inputs)
                except (ValueError, KeyError, TypeError):
                    return None
            return probability

        probability = load_probability()
        probability_hit = probability is not None
        load_seconds += perf_counter() - probability_started
        probability_seconds = 0.0
        if probability is None:
            if not produce:
                raise JointCacheMiss("probabilities", probability_key)
            with _key_lock(probability_directory, "probabilities", probability_key):
                probability = load_probability()
                if probability is None:
                    probability_started = perf_counter()
                    if probability_producer is None:
                        # Both freshly produced and completed cached actions have
                        # passed _check_action and exact publication hash checks.
                        probability = evaluate_joint_probabilities(
                            action,
                            trace,
                            noise_params=noise_params,
                            shots=shots,
                            seed=seed,
                            revalidate=False,
                        )
                    else:
                        probability = probability_producer(
                            action,
                            trace,
                            noise_params=noise_params,
                            shots=shots,
                            seed=seed,
                        )
                    _check_probability(probability, action, probability_inputs)
                    write_json(
                        probability_path,
                        _envelope(_PROBABILITY_SCHEMA, probability_inputs, probability),
                    )
                    if (
                        _record(
                            probability_path,
                            _PROBABILITY_SCHEMA,
                            probability_inputs,
                            fingerprints=validated_bytes,
                        )
                        != probability
                    ):
                        raise ValueError("PUBLISHED_JOINT_PROBABILITY_MISMATCH")
                    probability_seconds = perf_counter() - probability_started
                else:
                    probability_hit = True
        group = combine_joint_group(action, probability, family=family)
        group["cache_keys"] = {"action": action_key, "probability": probability_key}
        artifact_fingerprints = None
        if produce:
            index_started = perf_counter()
            artifact_fingerprints = self._publish_read_index(
                query, index_path, group, probability_key, validated_bytes
            )
            load_seconds += perf_counter() - index_started
        return JointCacheResult(
            group,
            action_key,
            probability_key,
            action_hit,
            probability_hit,
            trace_path,
            action_path,
            probability_path,
            {
                "cache_load": load_seconds,
                "action_calibration": action_seconds,
                "probability_calibration": probability_seconds,
                "total": perf_counter() - started,
            },
            artifact_bytes_sha256=artifact_fingerprints,
        )
