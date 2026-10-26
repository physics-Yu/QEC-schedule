"""Explicit offline extraction from a verified serial physical reference.

Only this builder reads/replays Atom IR and compiles the finite missing local
correction variants. FastProfile lookup and fast experiments never call it.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from math import fsum, hypot, isclose, log1p
from pathlib import Path
from typing import Any

from nadit_physical_compiler.activity import (
    ActivityEvent,
    AtomActivity,
    derive_activity,
)
from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.provenance import canonical_hash

from .fast_profile import CODE_ID, SCHEMA, FastProfile


def _source(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    raw = (directory / "case.json").read_bytes()
    if (
        manifest.get("source_stable") is not True
        or manifest.get("execution_completed") is not True
        or manifest.get("files_sha256", {}).get("case.json") != sha256(raw).hexdigest()
    ):
        raise ValueError("UNSTABLE_OR_CHANGED_CALIBRATION_SOURCE")
    case = json.loads(raw)
    physical = case["physical"]
    if physical.get("validation", {}).get("ok") is not True or physical.get(
        "parallel_batches"
    ):
        raise ValueError("CALIBRATION_REQUIRES_VALIDATED_SERIAL_SOURCE")
    return case, manifest


def _check_sources(manifest: Mapping[str, Any]) -> dict[str, str]:
    root = Path(__file__).resolve().parents[4]
    relevant = {}
    for name, expected in manifest["source_start"].items():
        if name.startswith("runtime-physical:"):
            path = Path(name.removeprefix("runtime-physical:"))
        elif name.startswith(
            ("modules/codes/_support/", "modules/codes/rotated_surface_d3/components/")
        ) or name in (
            "modules/codes/rotated_surface_d3/definition.py",
            "modules/codes/rotated_surface_d3/protocols/parallel.py",
            "modules/codes/rotated_surface_d3/protocols/factory_backend.py",
        ):
            path = root / name
        else:
            continue
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"CHANGED_CALIBRATION_IMPLEMENTATION: {name}")
        relevant[name] = expected
    if not relevant:
        raise ValueError("CALIBRATION_SOURCE_FINGERPRINTS_MISSING")
    return relevant


def _log_identity(error: float) -> float:
    if not 0 <= error < 1:
        raise ValueError("UNSUPPORTED_CALIBRATION_ZERO_SURVIVAL")
    return log1p(-error)


def _event_log(event: ActivityEvent, params: Mapping[str, Any]) -> float:
    count = len(event.atoms)
    if event.kind in ("Rotation", "LocalU", "GlobalRY", "CZPulse"):
        cz = event.kind == "CZPulse"
        config = (
            params["cz"]
            if cz
            else params["single_overrides"].get(
                event.parameters.get("axis", "U"), params["single"]
            )
        )
        if config["backend"] != "pauli":
            raise ValueError("UNSUPPORTED_CALIBRATION_GATE_MODEL")
        result = (len(event.pairs) if cz else count) * _log_identity(
            sum(config["probabilities"])
        )
        if cz:
            result += 2 * len(event.pairs) * _log_identity(params["cz_atom_loss"])
            spectators = count - len({a for pair in event.pairs for a in pair})
            result += spectators * _log_identity(sum(params["spectator_pauli"]))
        return result
    if event.kind in ("Load", "Move", "Store"):
        config = params["transport"]
        name = event.kind.lower()
        result = count * (
            _log_identity(config[name + "_loss"])
            + _log_identity(sum(config[name + "_pauli"]))
        )
        if event.kind == "Move":
            result -= fsum(
                config["loss_per_um"] * hypot(b[0] - a[0], b[1] - a[1])
                + config["loss_per_us"] * event.duration_us
                for a, b in zip(event.starts, event.ends, strict=True)
            )
        return result
    if event.kind in ("Measure", "Reset"):
        return count * _log_identity(
            params["readout_flip" if event.kind == "Measure" else "reset_flip"]
        )
    if event.kind == "Wait":
        return 0.0
    raise ValueError(f"UNCALIBRATED_ACTION_KIND: {event.kind}")


def _claim(spec: Mapping[str, Any], origin: Mapping[str, float]) -> dict[str, Any]:
    shared = spec["shared_aod"]
    return {
        "parallel_mode": spec["parallel_mode"],
        "result_count": spec["result_count"],
        "spaces": [
            [
                s["region"]["x_min"] - origin["x"],
                s["region"]["y_min"] - origin["y"],
                s["region"]["x_max"] - origin["x"],
                s["region"]["y_max"] - origin["y"],
                s["purpose"],
            ]
            for s in spec["spaces"]
        ],
        "shared": None
        if shared is None
        else {
            "band": [
                shared["column_min"] - origin["x"],
                shared["column_max"] - origin["x"],
            ],
            "rows": shared["peak_rows"],
            "columns": shared["peak_columns"],
            "readout_atoms": shared["peak_readout_atoms"],
        },
    }


def _holder_map(activity: AtomActivity) -> dict[tuple[int, float, str], str]:
    return {
        (
            atom.atom_id,
            interval.start_us,
            interval.kind,
        ): interval.holder
        for atom in activity.per_atom
        for interval in atom.busy
    }


def _holder(
    holders: Mapping[tuple[int, float, str], str],
    atom: int,
    event: ActivityEvent,
) -> str:
    # End-start can differ from action duration by a few ulps. Validated roles
    # have no simultaneous busy actions, so the original start/kind is enough.
    return holders[atom, event.start_us, event.kind]


def _entry_document(
    component_id: str,
    geometry: list[float],
    selection: int | None,
    spec: Mapping[str, Any],
    anchor: Mapping[str, Any],
    events: list[ActivityEvent],
    phase_indices: list[int],
    phase_durations: list[float],
    holders: Mapping[tuple[int, float, str], str],
    atom_roles: Mapping[int, tuple[Mapping[str, Any], int]],
    params: Mapping[str, Any],
    result_ids: list[int],
    latency: float,
) -> dict[str, Any]:
    phase_map = {step: index for index, step in enumerate(phase_indices)}
    offsets, cursor = [], 0.0
    for duration in phase_durations:
        offsets.append(cursor)
        cursor += duration
    rows, costs, segments = [], [], []
    counts: Counter[str] = Counter()
    measurements: dict[int, tuple[int, float]] = {}
    categories = {
        "Load": ("transfer", "aod"),
        "Store": ("transfer", "aod"),
        "Move": ("movement", "aod"),
        "Measure": ("measurement", "camera"),
        "Reset": ("reset", "local"),
        "CZPulse": ("gate", "rydberg"),
        "Rotation": ("gate", "local"),
        "LocalU": ("gate", "local"),
        "GlobalRY": ("gate", "local"),
        "Wait": ("other", "none"),
    }
    for event in events:
        index = phase_map[event.step_index]
        offset = offsets[index]
        kind = event.kind
        category, resource = categories[kind]
        segments.append(
            {
                "start_offset_us": offset,
                "end_offset_us": offset + event.duration_us,
                "category": category,
                "resource": resource,
            }
        )
        counts["actions_" + kind] += 1
        counts["targets_" + kind] += len(event.atoms)
        if kind == "CZPulse":
            counts["cz_pairs"] += len(event.pairs)
        costs.append(
            {
                "offset_us": offset,
                "duration_us": event.duration_us,
                "kind": kind,
                "log_survival": _event_log(event, params),
            }
        )
        if kind == "Measure":
            for result in event.measurement_ids:
                measurements[result] = (
                    index,
                    latency + event.duration_us - phase_durations[index],
                )
        if kind == "Wait":
            continue
        for atom in event.atoms:
            patch, role = atom_roles[atom]
            dx = (patch["origin"]["x"] - anchor["origin"]["x"]) / 100
            if (
                not isclose(dx, round(dx), abs_tol=1e-9, rel_tol=0)
                or patch["block_id"].split("/")[0] != anchor["block_id"].split("/")[0]
                or patch["origin"]["y"] != anchor["origin"]["y"]
            ):
                raise ValueError("UNCALIBRATED_ILLUMINATION_GEOMETRY")
            rows.append(
                [
                    round(dx),
                    role,
                    offset,
                    event.duration_us,
                    kind,
                    _holder(holders, atom, event),
                ]
            )
    measured = [measurements[result] for result in result_ids]
    ready = [sum(phase_durations[: index + 1]) + delay for index, delay in measured]
    return {
        "component_id": component_id,
        "geometry": geometry,
        "selection_class": selection,
        "waveform_key": spec["waveform_key"],
        "phase_durations_us": phase_durations,
        "measurement_phases": [list(value) for value in measured],
        "result_ready_offsets_us": ready,
        "cost_segments": segments,
        "primitive_counts": dict(counts),
        "events": costs,
        "busy": rows,
        "claim": _claim(spec, anchor["origin"]),
    }


def _event_owner(
    event: ActivityEvent,
    owners: Mapping[int, str],
    calls: Mapping[str, Mapping[str, Any]],
) -> str | None:
    selected = {owners[index] for index in event.source_ids if index in owners}
    if len(selected) > 1:
        raise ValueError("CALIBRATION_REQUIRES_UNFUSED_SOURCE_ACTIONS")
    if selected:
        return next(iter(selected))
    if event.duration_us == 0:
        return None
    matches = [
        identity
        for identity, call in calls.items()
        if call["start_us"] <= event.start_us < call["end_us"]
        and event.start_us + event.duration_us <= call["end_us"] + 1e-7
    ]
    if len(matches) > 1:
        raise ValueError("CALIBRATION_REQUIRES_NONOVERLAPPING_CALL_WINDOWS")
    return matches[0] if matches else None


def _extract_calls(
    case: Mapping[str, Any], activity: AtomActivity, params: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    physical = case["physical"]
    calls = {call["invocation_id"]: call for call in case["calls"]}
    parts = {part["invocation_id"]: part for part in physical["parts"]}
    bindings = {binding["block_id"]: binding for binding in physical["bindings"]}
    atom_roles = {
        atom: (binding, role)
        for binding in bindings.values()
        for role, atom in enumerate(binding["atom_ids"])
    }
    specs = {node["id"]: node["spec"] for node in case["component_schedule"]["nodes"]}
    invocations = {item["invocation_id"]: item for item in physical["invocations"]}
    owners: dict[int, str] = {}
    for call in calls.values():
        for name in call["part_invocations"]:
            part = parts[name]
            for index in range(
                part["native_operation_base"],
                part["native_operation_base"] + part["native_operation_count"],
            ):
                owners[index] = call["invocation_id"]
    grouped: dict[str, list[ActivityEvent]] = defaultdict(list)
    for event in activity.events:
        selected = _event_owner(event, owners, calls)
        if selected is not None:
            grouped[selected].append(event)
    holders = _holder_map(activity)
    steps = physical["program"]["steps"]
    entries: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    for identity, call in calls.items():
        component = call["component_id"]
        if component.endswith("/canonicalize"):
            continue
        spec = specs[identity]
        anchor = bindings[spec["participant_blocks"][0]]
        geometry = []
        if component == "transversal_cnot":
            target = bindings[spec["participant_blocks"][1]]
            geometry = [float(target["origin"]["x"] - anchor["origin"]["x"]), 0.0]
        key = component + (f"@dx={geometry[0]:g}" if geometry else "")
        events = grouped[identity]
        phase_indices = sorted({event.step_index for event in events})
        phases = [
            max(action["duration_us"] for action in steps[index]["actions"])
            for index in phase_indices
        ]
        if not isclose(
            sum(phases), call["end_us"] - call["start_us"], rel_tol=0, abs_tol=1e-7
        ):
            raise ValueError(f"UNCALIBRATED_INTERNAL_WAIT: {identity}")
        invocation = invocations[identity]
        results = list(
            range(
                invocation["result_id_base"],
                invocation["result_id_base"] + invocation["result_count"],
            )
        )
        item = _entry_document(
            component,
            geometry,
            None,
            spec,
            anchor,
            events,
            phase_indices,
            phases,
            holders,
            atom_roles,
            params,
            results,
            physical["device"]["readout"]["latency_us"],
        )
        if key in entries and canonical_hash(item) != canonical_hash(entries[key]):
            raise ValueError(f"NONREPEATABLE_CALIBRATION_VARIANT: {key}")
        entries[key] = item
        evidence.setdefault(key, {"source_invocations": [], "template_hashes": []})[
            "source_invocations"
        ].append(identity)
        for name in call["part_invocations"]:
            value = parts[name]["template_content_sha256"]
            if value not in evidence[key]["template_hashes"]:
                evidence[key]["template_hashes"].append(value)
    return entries, evidence


def _corrections(
    case: Mapping[str, Any], params: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Explicit offline supplementation: all finite correction classes, not only
    # the classes happened to be sampled by the reference factory seed.
    from nadit_physical_compiler.device import Position, loads_device
    from nadit_physical_compiler.serialization import (
        decode_layout,
        encode_dag,
        encode_device,
        encode_layout,
        encode_program,
    )
    from nadit_physical_compiler.state import SLMHolder

    from ...contracts.component import ComponentBinding, InvocationContext
    from ..components.canonicalization import PreparationCanonicalization
    from ..probabilities.preparation import preparation_port
    from .factory_backend import SurfaceFactoryBackend

    physical = case["physical"]
    device = loads_device(json.dumps(physical["device"]))
    world = decode_layout(physical["entry_state"])
    anchor = next(b for b in physical["bindings"] if b["block_id"] == "factory0/W1")
    binding = ComponentBinding(
        anchor["block_id"],
        Position(**anchor["origin"]),
        tuple(anchor["atom_ids"]),
        anchor["aod_id"],
    )
    backend = SurfaceFactoryBackend(device)
    home_sites = []
    for atom in binding.atom_ids:
        holder = world.atom(atom).holder
        if not isinstance(holder, SLMHolder):
            raise TypeError("CALIBRATION_REFERENCE_REQUIRES_HOME_ATOMS")
        home_sites.append(holder.site_id)
    homes = tuple(home_sites)
    atom_roles = {
        atom: (b, role)
        for b in physical["bindings"]
        for role, atom in enumerate(b["atom_ids"])
    }
    entries, evidence = {}, {}
    assert device.readout is not None
    for prep in ("initialize_plus", "raw_t_postselection"):
        compiled = PreparationCanonicalization(prep).compile(
            device,
            probability_port=preparation_port(prep),
            home_sites=homes,
            origin=binding.origin,
            aod_id=binding.aod_id,
        )
        spec = backend.describe_execution(prep + "/canonicalize", (binding,)).to_dict()
        for value, template in enumerate(compiled.templates):
            source = template.bind(binding).expand(
                InvocationContext(f"calibration/{prep}/{value}", 0, 0, device, world)
            )
            program = encode_program(source.program)
            document = {
                "program": program,
                "device": encode_device(device),
                "entry_state": encode_layout(world),
                "dag": encode_dag(source.dag),
                "measurements": [],
            }
            activity = derive_activity(document)
            phases = [step.duration_us for step in source.program.steps]
            item = _entry_document(
                prep + "/canonicalize",
                [],
                value,
                spec,
                anchor,
                list(activity.events),
                list(range(len(phases))),
                phases,
                _holder_map(activity),
                atom_roles,
                params,
                [],
                device.readout.latency_us,
            )
            key = f"{prep}/canonicalize:{value}"
            entries[key] = item
            evidence[key] = {
                "kind": "offline_finite_class_supplement",
                "template_hashes": [template.content_sha256],
            }
    return entries, evidence


def _compact_port(port: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(port))
    result["model"]["parameters"] = {"calibration_source_model": port["model"]["id"]}
    result["model"]["evidence"] = {"source_port_sha256": canonical_hash(port)}
    return result


def calibrate_fast_profile(
    artifact_dir: str | Path, output_path: str | Path
) -> FastProfile:
    """Build and save a finite profile from a stable verified serial artifact.

    This offline operation replays the existing action program and compiles all
    local correction classes. It rejects source drift, fused reference actions,
    changed repeated variants and unsupported gate noise. The result contains no
    global atom IDs, full atom worlds, or movement coordinate trajectories.
    """
    directory = Path(artifact_dir)
    case, manifest = _source(directory)
    source_hashes = _check_sources(manifest)
    params = resolve(manifest["noise_parameters"])
    if any(
        config["backend"] != "pauli"
        for config in (
            params["single"],
            params["cz"],
            *params["single_overrides"].values(),
        )
    ):
        raise ValueError("UNSUPPORTED_CALIBRATION_NOISE_PROFILE")
    physical = case["physical"]
    source = {**physical, "measurements": physical["pending_measurements"]}
    activity = derive_activity(source)
    entries, evidence = _extract_calls(case, activity, params)
    extra, extra_evidence = _corrections(case, params)
    entries.update(extra)
    evidence.update(extra_evidence)
    ports: dict[str, dict[str, Any]] = {}
    for port in case["probability_models"].values():
        if port["port_id"].endswith(".canonical_preparation") or port[
            "port_id"
        ].endswith(".reference_routing"):
            key = port["port_id"]
            if key in ports and ports[key]["outcomes"] != port["outcomes"]:
                raise ValueError("NONREPEATABLE_CALIBRATION_EVENT_DISTRIBUTION")
            ports.setdefault(key, port)
    device = physical["device"]
    control = {
        key: deepcopy(device[key]) for key in ("timing", "local", "cz", "readout")
    }
    control["readout"].pop("max_atoms", None)
    control["aod"] = {key: device["aods"][0][key] for key in ("motion", "min_spacing")}
    document = {
        "schema": SCHEMA,
        "code_id": CODE_ID,
        "distance": 3,
        "control": control,
        "control_profile_sha256": canonical_hash(control),
        "noise_params": params,
        "noise_params_sha256": canonical_hash(params),
        "entries": entries,
        "preparation_ports": {
            prep: _compact_port(ports[f"{CODE_ID}.{prep}.canonical_preparation"])
            for prep in ("initialize_plus", "raw_t_postselection")
        },
        "consumption_port": _compact_port(
            ports[f"{CODE_ID}.t_consumption.reference_routing"]
        ),
        "provenance": {
            "kind": "offline_physical_calibration",
            "source_directory": str(directory.resolve()),
            "manifest_sha256": sha256(
                (directory / "manifest.json").read_bytes()
            ).hexdigest(),
            "case_sha256": manifest["files_sha256"]["case.json"],
            "calibration_device_sha256": canonical_hash(device),
            "source_hashes": source_hashes,
            "component_evidence": evidence,
            "physical_reference_validation": physical["validation"],
            "fast_run_physical_validation": False,
            "output_scope": "fixed d3 horizontal factory recipe; one extra raw SE round",
            "storage_rule": "preserve role idle interval partitions and clip own raw union",
        },
    }
    profile = FastProfile.from_dict(document)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(profile.to_dict(), separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return profile
