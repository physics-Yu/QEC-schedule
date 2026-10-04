"""Export compact kernel evidence to the shared viewer without legacy state.

The operation stream supplies presentation intervals; committed deltas supply
locations, carrier changes, axes and reports. No execution or route search occurs
in this adapter. Measurements are declared scheduling reports, not Born samples.
"""

from dataclasses import asdict
import json
from math import ceil, floor, hypot, isclose
from pathlib import Path
import re
from collections.abc import Mapping

from neutral_atom_env.visualization.summary import summarize_intervals
from neutral_atom_env.visualization.theme import VisualTheme
from neutral_atom_env.visualization.viewer import write_html


def _field(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _position(point):
    return {"x_um": point[0], "y_um": point[1]}


def _bounds(rectangle):
    if isinstance(rectangle, Mapping):
        if "lower" in rectangle:
            return rectangle
        rectangle = (rectangle["x_min"], rectangle["y_min"], rectangle["x_max"], rectangle["y_max"])
    if len(rectangle) == 2:
        rectangle = (*rectangle[0], *rectangle[1])
    return {"lower": _position(rectangle[:2]), "upper": _position(rectangle[2:])}


def _axes(value):
    return {"rows": list(value["rows"]), "columns": list(value.get("columns", value.get("cols", ()))),
            "active_rows": list(value.get("active_rows", ())), "active_columns": list(value.get("active_columns", ()))}


def _axes_delta(value):
    return dict(zip(("rows", "columns", "active_rows", "active_columns"), map(list, value)))


def _viewer_axes(value):
    return {"x_um": list(value["columns"]), "y_um": list(value["rows"])}


def _axis_index(values, value):
    result = [index for index, coordinate in enumerate(values) if isclose(coordinate, value, rel_tol=0, abs_tol=1e-8)]
    if len(result) != 1:
        raise ValueError("Committed mobile atom has no unique recorded AOD axis")
    return result[0]


def _roles(role_to_atom, initial):
    roles, patch_atoms = {}, {}
    for role, atom in role_to_atom.items():
        if atom not in initial:
            raise ValueError("Role metadata names an unknown atom")
        patch, _, local = role.rpartition(".")
        patch = patch or "protocol"
        basis = re.fullmatch(r"([XZ])\d+", local, re.IGNORECASE)
        item = {"role": role, "patch": patch,
                "kind": "syndrome_ancilla" if basis else "data" if re.fullmatch(r"D\d+", local, re.IGNORECASE) else "protocol_auxiliary"}
        if basis:
            item["stabilizer_basis"] = basis[1].upper()
        roles[atom] = item
        patch_atoms.setdefault(patch, []).append(atom)
    patches = []
    for patch, atoms in patch_atoms.items():
        points = [initial[atom] for atom in atoms]
        rectangle = (min(p[0] for p in points)-5, min(p[1] for p in points)-5,
                     max(p[0] for p in points)+5, max(p[1] for p in points)+5)
        patches.append({"id": patch, "label": patch+" · initial role envelope", "bounds": _bounds(rectangle)})
    return roles, patches


def build_native_kernel_payload(evidence):
    """Return a detached neutral-atom-view/2 payload from append-only evidence."""
    initial = {atom: tuple(point) for atom, point in evidence["initial"].items()}
    profile = evidence["profile"]
    gates = {_field(gate, "id"): gate for gate in evidence["gates"]}
    operations = {_field(operation, "id"): operation for operation in evidence["operations"]}
    if len(operations) != len(evidence["operations"]):
        raise ValueError("Operation evidence must have unique identities")
    journal = evidence["journal"]
    final = evidence["final"]
    holders = dict(evidence.get("initial_holders", {atom: "slm" for atom in initial}))
    locations = {atom: (holders[atom], *point) for atom, point in initial.items()}
    device_axes = {device: _axes(value) for device, value in profile.get("initial_axes", {}).items()}
    if not device_axes:
        device_axes = {"AOD_0": {"rows": [0.], "columns": [0.], "active_rows": [], "active_columns": []}}
    for device in device_axes:
        loaded = [location for location in locations.values() if location[0] == device]
        device_axes[device]["active_rows"] = sorted({location[2] for location in loaded})
        device_axes[device]["active_columns"] = sorted({location[1] for location in loaded})

    trap_points = dict.fromkeys(point for atom, point in initial.items() if holders[atom] == "slm")
    for record in journal:
        for atom, before, after in record.get("changed_atoms", ()):
            if after[0] == "slm":
                trap_points.setdefault(tuple(after[1:]), None)
    trap_ids = {point: f"SLM_{index:04d}" for index, point in enumerate(trap_points)}
    rect = _bounds(profile["bounds_um"])
    pitch = profile.get("slm_grid_um", 5.)
    origin = profile.get("slm_origin_um", (0., 0.))
    xs = [origin[0]+i*pitch for i in range(ceil((rect["lower"]["x_um"]-origin[0])/pitch), floor((rect["upper"]["x_um"]-origin[0])/pitch)+1)]
    ys = [origin[1]+i*pitch for i in range(ceil((rect["lower"]["y_um"]-origin[1])/pitch), floor((rect["upper"]["y_um"]-origin[1])/pitch)+1)]
    role_metadata, patches = _roles(evidence.get("role_to_atom", {}), initial)
    zones = [{"id": "SZ", "zone_type": "storage", "bounds": rect}]
    labels = {"SZ": "SZ · declared 5 μm SLM candidate domain"}
    for zone, bounds in profile.get("cz_zones_um", {"EZ": profile.get("cz_zone_um")}).items():
        if bounds is not None:
            zones.append({"id": zone, "zone_type": "entanglement", "bounds": _bounds(bounds)})
            labels[zone] = "EZ · native finite CZ illumination"
    if "measurement_zone_um" in profile:
        zones.append({"id": "MZ", "zone_type": "measurement", "bounds": _bounds(profile["measurement_zone_um"])})
        labels["MZ"] = "MZ · scheduling readout / reset"
    scene = {"bounds": rect, "spacing_um": pitch, "grid_x": xs, "grid_y": ys,
             "candidates": [_position((x, y)) for x in xs for y in ys],
             "traps": [{"id": id, "position": _position(point), "enabled": False} for point, id in trap_ids.items()],
             "zones": zones, "zone_labels": labels, "atom_roles": role_metadata, "patches": patches,
             "aod_labels": {device: device+" · native row / column" for device in device_axes},
             "slm_clearance_um": profile.get("transport_clearance_um", 1.),
             "aod_minimum_spacing_um": profile.get("aod_axis_spacing_um", 2.),
             "raman_minimum_separation_um": profile.get("raman_separation_um", 5.),
             "display_grid_step_um": pitch, "show_candidate_sites": True,
             "profile_id": profile.get("id", profile.get("profile_id")), "grid_site_scope": "candidate geometry; enabled support comes from committed holders"}

    source = evidence.get("report_source", {})
    model_labels = sorted({record.get("native_provenance", {}).get("report_model") for record in journal
                           if record.get("native_provenance", {}).get("report_model")})
    source_provenance = {"source_id": source.get("source_id", "; ".join(model_labels) or "declared scheduling report source"),
                         "version": source.get("version"), "seed": source.get("seed"),
                         "kind": "declared-scheduling-report", "quantum_projection": False, "fidelity": None}
    if source.get("probability_one") is not None:
        source_provenance["declared_probability_one"] = source["probability_one"]

    activities = {atom: "idle" for atom in initial}
    measured = {atom: False for atom in initial}
    current_atoms, completed, active, reports, report_times = {}, set(), (), {}, {}
    successors, pending = {}, {}
    for id, gate in gates.items():
        parents = tuple(_field(gate, "depends_on", ()))
        pending[id] = len(parents)
        for parent in parents:
            successors.setdefault(parent, []).append(id)
    ready = {id for id, count in pending.items() if count == 0}
    frames, visual_operations = [], []
    masks_before = None
    completed_count, last_effect_us, total_atom_distance, total_aod_distance = 0, None, 0., 0.
    current_block, current_operation, movement = None, None, None

    def holder(atom):
        carrier, x, y = locations[atom]
        if carrier == "slm":
            return {"holder_type": "static", "holder_id": trap_ids[(x, y)]}
        axes = device_axes[carrier]
        return {"holder_type": "mobile", "holder_id": {"row": _axis_index(axes["rows"], y), "column": _axis_index(axes["columns"], x), "aod_id": carrier}}

    def frame(time, version, label, requested=(), report_updates=None, effect_ids=()):
        nonlocal masks_before
        atom_updates = []
        for atom, location in locations.items():
            value = {"id": atom, "holder": holder(atom), "position": _position(location[1:]), "activity": activities[atom], "measured": measured[atom]}
            if current_atoms.get(atom) != value:
                current_atoms[atom] = value
                atom_updates.append(value)
        mask = dict.fromkeys(trap_ids.values(), False)
        for carrier, x, y in locations.values():
            if carrier == "slm":
                mask[trap_ids[(x, y)]] = True
        mask_update = mask if mask != masks_before else None
        masks_before = mask
        arrays, axes_by_aod = {}, {}
        for device, axes in device_axes.items():
            axes_by_aod[device] = _viewer_axes(axes)
            arrays[device] = {"aod_id": device, "rows": len(axes["rows"]), "columns": len(axes["columns"]),
                              "enabled_rows": [y in axes["active_rows"] for y in axes["rows"]],
                              "enabled_columns": [x in axes["active_columns"] for x in axes["columns"]],
                              "is_moving": movement is not None and movement["aod_id"] == device}
        primary = next(iter(arrays))
        movements = {movement["aod_id"]: movement} if movement else {}
        value = {"time": time, "version": version, "atom_updates": atom_updates, "plan_id": current_block,
                 "aod": arrays[primary], "axes": axes_by_aod[primary], "movement": movements.get(primary),
                 "primary_aod_id": primary, "aods": arrays, "axes_by_aod": axes_by_aod, "movements": movements,
                 "slm_enabled": mask_update, "transfer": None, "transfers": {},
                 "gate_status": "running" if active else "completed" if completed_count == len(gates) else "ready",
                 "active_gate_ids": list(active), "active_operations": [current_operation] if current_operation else [],
                 "gate_label": label, "label": label, "requested": list(requested),
                 "ready_frontier": sorted(ready-set(active))[:20], "ready_count": len(ready-set(active)),
                 "gate_counts": {"completed": completed_count, "running": len(active), "ready": len(ready-set(active)),
                                 "blocked": len(gates)-completed_count-len(ready)},
                 "gate_statuses": {}, "quantum_tracking": False,
                 "measurement_updates": dict(report_updates or {}), "completed_gate_ids_delta": list(effect_ids)}
        if not frames:
            value["measurement_results"] = {}
        frames.append(value)

    frame(evidence.get("initial_time_us", 0.), 0, "Initial · declared scheduling reports")
    completed_operations = set()
    for record in journal:
        event = record["event"]
        time, version = record["time_us"], record["version"]
        if version <= frames[-1]["version"] or time < frames[-1]["time"]:
            raise ValueError("Kernel journal must have increasing versions and monotone time")
        current_block = record.get("block_id", current_block)
        report_updates, effects, requested = {}, (), ()
        label = event
        if event == "OPERATION_STARTED":
            id = record["operation_id"]
            operation = operations[id]
            kind, atoms = _field(operation, "kind"), tuple(_field(operation, "atoms", ()))
            metadata = _field(operation, "metadata", {})
            active = tuple(_field(operation, "gate_ids", ()))
            if any(id not in gates for id in active):
                raise ValueError("Operation names an unknown gate effect")
            requested, current_operation = atoms, id
            visual_kind = {"CONFIGURE": "aod_move", "MOVE": "aod_move", "LOAD": "aod_load", "STORE": "aod_offload",
                           "GATE": "raman_rotation", "CZ": "entangling_pulse", "MEASURE": "measurement", "RESET": "reset", "WAIT": "idle"}.get(kind, "raman_rotation")
            carrier = _field(operation, "aod_id", "AOD_0")
            source_axes = _viewer_axes(device_axes[carrier])
            target = metadata.get("target_axes")
            if target is None and kind == "MOVE":
                targets = dict(_field(operation, "positions", ()))
                loaded = {atom: targets.get(atom, location[1:]) for atom, location in locations.items() if location[0] == carrier}
                target = {"rows": sorted({p[1] for p in loaded.values()}), "columns": sorted({p[0] for p in loaded.values()})}
            target_axes = _viewer_axes(target) if target is not None else source_axes
            moving = [atom for atom in atoms if kind == "MOVE" and tuple(dict(_field(operation, "positions", ()))[atom]) != locations[atom][1:]]
            if kind in ("CONFIGURE", "MOVE") and _field(operation, "duration_us") > 0:
                if len(source_axes["x_um"]) != len(target_axes["x_um"]) or len(source_axes["y_um"]) != len(target_axes["y_um"]):
                    raise ValueError("Recorded device moves must preserve explicit full RF dimensions")
                movement = {"aod_id": carrier, "start": record["start_us"], "duration": _field(operation, "duration_us"),
                            "target_axes": target_axes, "profile": "linear"}
            else:
                movement = None
            category = {"CONFIGURE": "empty", "MOVE": "transport", "LOAD": "load", "STORE": "offload",
                        "GATE": "raman", "CZ": "pulse", "MEASURE": "measurement", "RESET": "reset", "WAIT": "idle"}.get(kind, "raman")
            resources = ([carrier] if kind in ("CONFIGURE", "MOVE", "LOAD", "STORE") else
                         ["ENTANGLING_LASER_0"] if kind == "CZ" else ["READOUT_0"] if kind == "MEASURE" else
                         ["RESET_0"] if kind == "RESET" else ["RAMAN:"+atom for atom in atoms] if visual_kind == "raman_rotation" else [])
            resources += ["ATOM:"+atom for atom in atoms]
            gate_type = _field(gates[active[0]], "kind") if active else None
            label = metadata.get("label", kind+" · "+id)
            visual = {"index": len(visual_operations), "id": id, "label": label, "kind": visual_kind, "aod_id": carrier,
                      "start": record["start_us"], "end": record["end_us"], "plan_id": current_block,
                      "gate_ids": list(active), "gate_id": active[0] if len(active) == 1 else None, "gate_type": gate_type,
                      "batch_size": len(active), "applied": True, "qubit_ids": list(atoms), "captured": list(atoms),
                      "intended_pairs": [list(_field(gates[id], "atoms")) for id in active] if kind == "CZ" else [],
                      "actual_pairs": _plain(metadata.get("actual_pairs", ())), "parameters": _plain(metadata.get("parameters", ())),
                      "u_parameters_rad": _plain(metadata.get("u_parameters_rad")), "target_holders": {atom: holder(atom) for atom in atoms},
                      "depends_on": list(dict.fromkeys(parent for id in active for parent in _field(gates[id], "depends_on", ()))),
                      "resources": resources, "category": category, "mode": "translation" if visual_kind == "aod_move" else None,
                      "moving_count": len(moving), "moving_atom_ids": moving, "measurement_results": {},
                      "planner_id": "native-kernel-delta-export", "source_line": metadata.get("source_line")}
            if visual_kind == "aod_move":
                visual.update(source_axes=source_axes, target_axes=target_axes,
                              enabled_rows=list(arr for arr in frames[-1]["aods"][carrier]["enabled_rows"]),
                              enabled_columns=list(arr for arr in frames[-1]["aods"][carrier]["enabled_columns"]))
                if source_axes["x_um"] and source_axes["y_um"]:
                    dx = max((abs(b-a) for a, b in zip(source_axes["x_um"], target_axes["x_um"])), default=0.)
                    dy = max((abs(b-a) for a, b in zip(source_axes["y_um"], target_axes["y_um"])), default=0.)
                    total_aod_distance += hypot(dx, dy)
                visual["mode"] = "axis_deformation" if any(len({round(b-a, 10) for a, b in zip(source_axes[key], target_axes[key])}) > 1 for key in ("x_um", "y_um")) else "translation"
            visual_operations.append(visual)
            for atom in atoms:
                activities[atom] = "moving" if atom in moving else "gating" if kind in ("GATE", "CZ", "H", "X", "Y", "Z", "T") else "measuring" if kind == "MEASURE" else "resetting" if kind == "RESET" else "idle"
        elif event == "OPERATION_COMPLETED":
            id = record["operation_id"]
            if id != current_operation or id in completed_operations:
                raise ValueError("Completion does not match its unique started operation")
            operation = operations[id]
            for atom, before, after in record.get("changed_atoms", ()):
                if tuple(before) != locations[atom]:
                    raise ValueError("Atom delta does not bind the prior committed location")
                total_atom_distance += hypot(after[1]-before[1], after[2]-before[2])
                locations[atom] = tuple(after)
            if record.get("axes_delta") is not None:
                device, before, after = record["axes_delta"]
                if _axes_delta(before) != device_axes[device]:
                    raise ValueError("Axes delta does not bind the prior committed device")
                device_axes[device] = _axes_delta(after)
            effects = tuple(record.get("gate_ids", ()))
            if effects != tuple(_field(operation, "gate_ids", ())):
                raise ValueError("Completion effects differ from declared operation")
            for gate in effects:
                if gate in completed or pending[gate] != 0:
                    raise ValueError("Duplicate or causally invalid completed gate effect")
                completed.add(gate)
                ready.remove(gate)
                completed_count += 1
                for successor in successors.get(gate, ()):
                    pending[successor] -= 1
                    if pending[successor] == 0:
                        ready.add(successor)
            if effects:
                last_effect_us = time
            for report, bit in record.get("reports", ()):
                if report in reports:
                    raise ValueError("Journal repeats a committed report")
                reports[report] = bit
                report_times[report] = time
                report_updates[report] = bit
            visual_operations[-1]["measurement_results"] = dict(report_updates)
            for atom in _field(operation, "atoms", ()):
                activities[atom] = "idle"
                if _field(operation, "kind") == "MEASURE":
                    measured[atom] = True
                elif _field(operation, "kind") == "RESET":
                    measured[atom] = False
            requested = tuple(_field(operation, "atoms", ()))
            label = _field(operation, "kind")+" completed · "+id
            completed_operations.add(id)
            current_operation, movement, active = None, None, ()
        elif event == "BLOCK_COMPLETED":
            current_block = None
        frame(time, version, label, requested, report_updates, effects)

    if current_operation is not None or completed_operations != set(operations):
        raise ValueError("Exporter requires a completely committed operation stream")
    expected_positions = {atom: tuple(point) for atom, point in _field(final, "positions").items()}
    expected_holders = dict(_field(final, "holders"))
    if {atom: value[1:] for atom, value in locations.items()} != expected_positions or {atom: value[0] for atom, value in locations.items()} != expected_holders:
        raise ValueError("Delta replay locations disagree with final kernel evidence")
    if reports != dict(_field(final, "measurement_results")) or completed != set(_field(final, "completed_gate_ids")):
        raise ValueError("Delta replay reports/effects disagree with final kernel evidence")
    if report_times != dict(_field(final, "measurement_completion_times_us")) or frames[-1]["time"] != _field(final, "time_us"):
        raise ValueError("Delta replay timing disagrees with final kernel evidence")
    start, end = frames[0]["time"], frames[-1]["time"]
    metrics = {"simulation_time_us": end, "episode_start_us": start, "completed_gate_count": completed_count,
               "logical_completion_elapsed_us": last_effect_us-start if completed_count == len(gates) and last_effect_us is not None else None,
               "total_aod_distance_um": total_aod_distance, "total_atom_distance_um": total_atom_distance,
               "aod_load_count": sum(_field(op, "kind") == "LOAD" for op in operations.values()),
               "aod_offload_count": sum(_field(op, "kind") == "STORE" for op in operations.values()),
               "fidelity": None,
               "aod_distance_definition": "sum hypot(max RF column travel, max RF row travel) over explicit moves; includes disabled axes"}
    # The shared summarizer derives idle time from gaps in device intervals.
    summary = summarize_intervals([op for op in visual_operations if op["category"] != "idle"], start, end, metrics)
    return {"format": "neutral-atom-view/2", "scene": scene, "frames": frames,
            "theme": asdict(VisualTheme.load()), "backend": "native_kernel_row_column",
            "duration": end, "start_time": start, "operations": visual_operations,
            "plans": [], "summary": summary, "atom_statistics": None,
            "atom_statistics_unavailable": "Per-atom exposure statistics are not implemented for this independent scheduling kernel.",
            "requested": [], "captured": visual_operations[0]["captured"] if visual_operations else [],
            "gate_label": "Declared scheduling run", "scheduling_report_source": source_provenance,
            "offline_audit_status": evidence.get("summary", {}).get("offline_physical_status", "未审核"),
            "measurement_completion_times_us": report_times, "completed_gate_ids": sorted(completed),
            "evidence_scope": "native scheduling operations and committed classical reports; offline geometry review is separate"}


def export_native_kernel_view(evidence, output):
    """Write recording.json and replay.html using the existing shared viewer."""
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    payload = build_native_kernel_payload(evidence)
    recording = directory/"recording.json"
    recording.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    replay = write_html(payload, directory/"replay.html")
    return {"recording": str(recording.resolve()), "replay": str(replay.resolve()),
            "frames": len(payload["frames"]), "operations": len(payload["operations"]),
            "reports": len(payload["measurement_completion_times_us"])}
