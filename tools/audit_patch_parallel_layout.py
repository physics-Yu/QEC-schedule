"""Independent protocol and Cartesian AOD evidence audit for the fixed d=3 prefix.

The existing independent prefix audit supplies source/effect identities, Stim,
dependency times, and every global CZ/Raman/MZ geometry check. This supplement
pins the canonical extraction phases independently of the production frontend
and binds recorded row/column motion to committed trace/configuration evidence.
It does not replace Executor's continuous collision and support validation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from math import hypot, isfinite, sqrt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_native_parallel_physical import audit as audit_prefix


# Pinned official Stim ticks, reflected into the project's established roles.
# These constants deliberately do not import the production protocol generator.
LAYERS = (
    (("X0", 3), ("X1", 7), ("X2", 1), ("Z0", 4), ("Z1", 6), ("Z3", 8)),
    (("X0", 4), ("X1", 8), ("X2", 2), ("Z0", 1), ("Z1", 3), ("Z3", 5)),
    (("X0", 0), ("X1", 4), ("X3", 6), ("Z0", 5), ("Z1", 7), ("Z2", 3)),
    (("X0", 1), ("X1", 5), ("X3", 7), ("Z0", 2), ("Z1", 4), ("Z2", 0)),
)
COORDINATES = {
    "d0": (5, 1), "d1": (3, 1), "d2": (1, 1),
    "d3": (5, 3), "d4": (3, 3), "d5": (1, 3),
    "d6": (5, 5), "d7": (3, 5), "d8": (1, 5),
    "X0": (4, 2), "X1": (2, 4), "X2": (2, 0), "X3": (4, 6),
    "Z0": (2, 2), "Z1": (4, 4), "Z2": (6, 2), "Z3": (0, 4),
}
ENOLA_PROPOSAL_SHA256 = "b04b39ba29e6345c26404d289b6d3b441e1f3a92d9fb7ab249cd1b9b2d1b68ae"
ENOLA_MAPPING_SHA256 = "49a2c2d531af2bad5e77d8d368c6809dd8386ffe19c3fe166c7e23882b44337c"
ENOLA_COORDINATES_UM = {
    "d0": (40, 20), "d1": (30, 30), "d2": (20, 40),
    "d3": (30, 10), "d4": (20, 20), "d5": (10, 30),
    "d6": (20, 0), "d7": (10, 10), "d8": (0, 20),
    "X0": (30, 20), "X1": (10, 20), "X2": (30, 40), "X3": (10, 0),
    "Z0": (20, 30), "Z1": (20, 10), "Z2": (40, 10), "Z3": (0, 30),
}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _gate_ids(effect):
    return effect.get("gate_ids") or ([effect["gate_id"]] if effect.get("gate_id") else [])


def _patches_and_bindings(source):
    patches = tuple(f["context"]["patch"] for f in source["original_functions"]
                    if f["kind"] == "canonical_check")
    if not patches or len(set(patches)) != len(patches):
        raise ValueError("Selected canonical patches must be distinct and nonempty")
    bindings = {row["role"]: row["id"] for row in source["roles"]["roles"]}
    return patches, bindings


def verify_canonical_protocol(source, gates):
    """Check literal couplings, all H boundaries, own-reset edges and CSS chain."""
    patches, bindings = _patches_and_bindings(source)
    by_id = {gate["id"]: gate for gate in gates}
    originals = source["original_native_gates"]
    phase_count, dependency_count = 0, 0
    canonical, css = {}, {}
    for patch in patches:
        namespace = "shot0.encode." + patch
        base = namespace + ".check." + patch + ".r1"
        encoded = [gate for gate in originals if gate["id"].startswith(namespace + ".encode.")]
        if len(encoded) != 136 or Counter(g["gate_type"] for g in encoded) != {"H": 92, "CZ": 44}:
            raise ValueError("The unchanged CSS encoder must contain its 136 native gates")
        reset_ids = tuple(namespace + f".reset{i}" for i in range(17))
        for index, gate in enumerate(encoded):
            expected = reset_ids if index == 0 else (encoded[index - 1]["id"],)
            if set(by_id[gate["id"]].get("depends_on", ())) != set(expected):
                raise ValueError("CSS encoder serial chain or reset entry was changed")
        css[patch] = tuple(g["id"] for g in encoded if g["gate_type"] == "CZ")
        previous = (encoded[-1]["id"],)

        def phase(key, kind, supports, *, ids=None, own_parents=None):
            nonlocal previous, phase_count, dependency_count
            ids = tuple(ids) if ids is not None else tuple(f"{key}.{i}" for i in range(len(supports)))
            for index, (gate_id, support) in enumerate(zip(ids, supports)):
                gate = by_id.get(gate_id)
                targets = tuple(bindings[patch + "." + role] for role in support)
                parents = previous if own_parents is None else own_parents[index]
                if gate is None or gate["gate_type"] != kind or tuple(gate["qubit_ids"]) != targets:
                    raise ValueError("Canonical gate identity, coupling or H target was changed")
                if set(gate.get("depends_on", ())) != set(parents):
                    raise ValueError("Canonical phase barrier or own-report RESET edge was changed")
                dependency_count += len(parents)
            previous = ids
            phase_count += 1
            return ids

        phase(base + ".ancilla_h", "H", tuple((f"X{i}",) for i in range(4)))
        patch_cz = []
        for layer, pairs in enumerate(LAYERS, start=1):
            targets = tuple((f"d{data}" if ancilla.startswith("X") else ancilla,)
                            for ancilla, data in pairs)
            supports = tuple((ancilla, f"d{data}") if ancilla.startswith("X") else (f"d{data}", ancilla)
                             for ancilla, data in pairs)
            layer_base = base + f".layer{layer}"
            phase(layer_base + ".target_h", "H", targets)
            ids = phase(layer_base + ".cz", "CZ", supports)
            patch_cz.extend((gid, layer, ancilla[0]) for gid, (ancilla, _) in zip(ids, pairs))
            phase(layer_base + ".target_restore", "H", targets)
        phase(base + ".ancilla_readout_h", "H", tuple((f"X{i}",) for i in range(4)))
        roles = tuple(f"{kind}{i}" for kind in ("X", "Z") for i in range(4))
        measured = phase(base + ".measure", "MEASURE", tuple((role,) for role in roles),
                         ids=tuple(base + "." + role for role in roles))
        phase(base + ".reset", "RESET", tuple((role,) for role in roles),
              own_parents=tuple((gid,) for gid in measured))
        canonical[patch] = tuple(patch_cz)
    return {"patches": patches, "bindings": bindings, "canonical_cz": canonical, "css_cz": css,
            "canonical_phases_checked": phase_count, "canonical_dependency_edges_checked": dependency_count,
            "css_native_gates_checked": 136 * len(patches)}


def verify_cz_batches(protocol, effects, mode):
    """Require the authored four-layer protocol and the declared physical split."""
    if mode not in {"layer", "role", "enola"}:
        raise ValueError("Expected CZ mode is layer, role or enola")
    patches = protocol["patches"]
    canonical = {gid: (patch, layer, kind) for patch, entries in protocol["canonical_cz"].items()
                 for gid, layer, kind in entries}
    css = {gid: (patch, index) for patch, entries in protocol["css_cz"].items()
           for index, gid in enumerate(entries)}
    per_patch, family_pulses, css_pulses, syndrome_pulses = defaultdict(list), defaultdict(list), 0, 0
    covered = Counter()
    for pulse in effects:
        if pulse["kind"] != "entangling_pulse":
            continue
        ids = _gate_ids(pulse)
        covered.update(ids)
        if all(gid in css for gid in ids):
            if len(ids) != len(patches) or len({css[gid][1] for gid in ids}) != 1:
                raise ValueError("CSS pulse must preserve one serial encoder CZ per selected patch")
            css_pulses += 1
            continue
        if not ids or not all(gid in canonical for gid in ids):
            raise ValueError("A CZ pulse mixed CSS and canonical gates or introduced a foreign gate")
        layers = {canonical[gid][1] for gid in ids}
        if len(layers) != 1:
            raise ValueError("A CZ pulse crossed a canonical layer barrier")
        layer = next(iter(layers))
        counts = Counter(canonical[gid][0] for gid in ids)
        allowed_sizes = (tuple(range(1, 7)) if mode == "enola" else
                         (1,) if mode == "role" else ((6,) if layer in (1, 4) else (1, 2)))
        if set(counts) != set(patches) or len(set(counts.values())) != 1 or next(iter(counts.values())) not in allowed_sizes:
            raise ValueError("CZ pulse does not have the declared per-patch matching size")
        if mode == "layer" and layer in (2, 3) and len({canonical[gid][2] for gid in ids}) != 1:
            raise ValueError("Opposite X/Z displacement families must use separate physical pulses")
        if mode == "role":
            ordinal = {protocol["canonical_cz"][canonical[gid][0]].index(
                (gid, canonical[gid][1], canonical[gid][2])) for gid in ids}
            if len(ordinal) != 1:
                raise ValueError("Role baseline must pulse the same canonical coupling across patches")
        elif mode == "layer" and layer in (2, 3):
            family_pulses[(layer, canonical[ids[0]][2])].append(next(iter(counts.values())))
        for patch in patches:
            per_patch[patch].append((layer, counts[patch]))
        syndrome_pulses += 1
    if covered != Counter((*css, *canonical)):
        raise ValueError("CZ batches must contain every source CZ exactly once")
    expected = 10 if mode == "layer" else 24
    if css_pulses != 44 or (mode != "enola" and syndrome_pulses != expected):
        raise ValueError("Unexpected physical CZ pulse count for the declared mode")
    if mode == "layer" and any(sorted(family_pulses[(layer, kind)]) != [1, 2]
                               for layer in (2, 3) for kind in ("X", "Z")):
        raise ValueError("Each middle-layer displacement family must split into its closed two-pair and one-pair captures")
    return {"mode": mode, "css_cz_pulses": css_pulses, "canonical_round_cz_pulses": syndrome_pulses,
            "total_cz_pulses": css_pulses + syndrome_pulses,
            "cz_native_effects": sum(covered.values()),
            "per_patch": {patch: {"maximum_pairs_in_one_canonical_pulse": max(size for _, size in rows),
                                  "round_pulses": len(rows),
                                  "pairs_per_pulse_histogram": dict(Counter(size for _, size in rows)),
                                  "pulses_per_layer": dict(Counter(layer for layer, _ in rows))}
                          for patch, rows in per_patch.items()}}


def verify_enola_proposal(path):
    """Authenticate the exact frozen author-placer output and independent map."""
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ENOLA_PROPOSAL_SHA256:
        raise ValueError("Enola proposal raw bytes differ from the frozen authenticated output")
    value = json.loads(raw)
    mapping = value["coordinates_um"]
    canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if (hashlib.sha256(canonical).hexdigest() != ENOLA_MAPPING_SHA256 or
            value["placement_sha256"] != ENOLA_MAPPING_SHA256):
        raise ValueError("Enola placement mapping hash differs from the frozen output")
    if {role.removeprefix("A."): tuple(point) for role, point in mapping.items()} != ENOLA_COORDINATES_UM:
        raise ValueError("Enola role placement differs from the independent seventeen-role fixture")
    expected_roles = ["A." + role for role in COORDINATES]
    if value["role_order"] != expected_roles:
        raise ValueError("Enola role order differs from the fixed canonical data/X/Z convention")
    expected_layers = [[[expected_roles.index("A." + ancilla), expected_roles.index("A.d" + str(data))]
                        for ancilla, data in layer] for layer in LAYERS]
    if value["layers"] != expected_layers or value["protocol"]["protocol_reordered"] is not False:
        raise ValueError("Enola proposal changed canonical coupling layers")
    return {"proposal_raw_sha256": ENOLA_PROPOSAL_SHA256,
            "placement_mapping_sha256": ENOLA_MAPPING_SHA256,
            "official_placer_commit": value["source"]["expected_commit"],
            "official_placer_sha256": value["source"]["placer_sha256"],
            "coordinates_um": ENOLA_COORDINATES_UM,
            "physical_evidence_scope": "frozen placement authenticated; physical run audited separately"}


def verify_home_layout(initial, protocol, scale_um=10.0, *, proposal=None, recording=None):
    """Check a translation of the standard coordinate layout, fixed 5 um sites."""
    hardware = initial["hardware"]
    if (hardware["interaction_distance_um"] != 6 or (proposal is None and
            hardware["interaction_offset"] != {"x_um": -3, "y_um": 0})):
        raise ValueError("The layout must preserve finite 6 um CZ and its declared 3 um pairing offset")
    if proposal is not None and hypot(hardware["interaction_offset"]["x_um"],
                                      hardware["interaction_offset"]["y_um"]) > 6:
        raise ValueError("A declared pairing offset exceeded the finite 6 um CZ radius")
    aod = initial.get("aod") or initial["aods"]["AOD_0"]
    if aod["rows"] * aod["columns"] != 9 * len(protocol["patches"]):
        raise ValueError("Algorithm AOD capacity must be the declared 3 by 3 footprint per selected patch")
    positions = {}
    for atom, holder in initial["placement"]["atom_to_holder"].items():
        if holder["holder_type"] != "static":
            raise ValueError("The layout comparison requires all original carriers on SLM")
        point = initial["world"]["traps"][holder["holder_id"]]["position"]
        positions[atom] = (point["x_um"], point["y_um"])
        origin = initial["world"].get("grid_origin", {"x_um": 0, "y_um": 0})
        if any(abs((point[axis] - origin[axis]) / 5 - round((point[axis] - origin[axis]) / 5)) > 1e-8
               for axis in ("x_um", "y_um")):
            raise ValueError("An occupied home is not on the fixed 5 um SLM candidate lattice")
    enola = verify_enola_proposal(proposal) if proposal is not None else None
    for patch in protocol["patches"]:
        anchor = positions[protocol["bindings"][patch + ".d0"]]
        coordinates = enola["coordinates_um"] if enola else COORDINATES
        for role, coordinate in coordinates.items():
            actual = positions[protocol["bindings"][patch + "." + role]]
            multiplier = 1 if enola else scale_um
            expected = tuple(anchor[axis] + multiplier * (coordinate[axis] - coordinates["d0"][axis])
                             for axis in range(2))
            if any(abs(a - b) > 1e-8 for a, b in zip(actual, expected)):
                raise ValueError("Occupied patch homes are not the declared canonical coordinate layout")
    minimum = min(hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(positions.values())
                  for b in tuple(positions.values())[i + 1:])
    if minimum < 10.0 - 1e-8 or initial["world"]["grid_spacing_um"] != 5:
        raise ValueError("All occupied homes must be at least 10 um apart on the fixed 5 um candidate grid")
    result = {"canonical_coordinate_scale_um": None if enola else scale_um, "minimum_occupied_home_distance_um": minimum,
            "slm_candidate_grid_um": 5, "occupied_carriers_checked": len(positions),
            "algorithm_aod_capacity": aod["rows"] * aod["columns"],
            "finite_cz_distance_um": 6, "cz_pair_offset_um": "searched finite offsets" if enola else [-3, 0]}
    if enola:
        if recording is None:
            raise ValueError("Enola placement acceptance also requires the actual initial observer geometry")
        scene_traps = {trap["id"]: trap["position"] for trap in recording["scene"]["traps"]}
        initial_frame = {atom["id"]: atom for atom in recording["frames"][0]["atom_updates"]}
        for patch in protocol["patches"]:
            for role in ENOLA_COORDINATES_UM:
                full_role = patch + "." + role
                atom = protocol["bindings"][full_role]
                holder = initial["placement"]["atom_to_holder"][atom]
                point = {"x_um": positions[atom][0], "y_um": positions[atom][1]}
                observed = initial_frame[atom]
                meta = recording["scene"]["atom_roles"][atom]
                if (scene_traps.get(holder["holder_id"]) != point or observed["position"] != point or
                        observed["holder"] != holder or meta["role"] != full_role or meta["patch"] != patch):
                    raise ValueError("Enola role/coordinate binding differs between initial state and observer scene")
        result["enola_proposal"] = {key: value for key, value in enola.items() if key != "coordinates_um"}
    return result


def verify_move_evidence(recording, trace_path, initial):
    """Bind all Cartesian endpoints and carrier positions to committed moves.

    Common monotone cubic progress makes endpoint axis gaps sufficient for
    all-time axis order/spacing. Atom/SLM sweep safety is still independently
    replayed by Executor; this helper does not certify it from endpoints.
    """
    moves = {(op["plan_id"], op.get("aod_id", "AOD_0"), op["start"]): op
             for op in recording["operations"] if op["kind"] == "aod_move"}
    if len(moves) != sum(op["kind"] == "aod_move" for op in recording["operations"]):
        raise ValueError("Duplicate observer move boundary")
    started, completed = {}, {}
    with Path(trace_path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("operation_type") != "aod_move":
                continue
            event = row["event"]
            key = (event["plan_id"], event["operation_id"])
            if event["event_type"] == "operation_started":
                if key in started:
                    raise ValueError("Duplicate committed move start")
                started[key] = row
            elif event["event_type"] == "operation_completed":
                if key in completed:
                    raise ValueError("Duplicate committed move completion")
                completed[key] = row
    if set(started) != set(completed) or len(started) != len(moves):
        raise ValueError("Every observer move needs exactly one committed start and completion")
    frames_at, atoms = defaultdict(list), {}
    for frame in recording["frames"]:
        atoms.update({atom["id"]: atom for atom in frame["atom_updates"]})
        frames_at[frame["time"]].append((frame, dict(atoms)))
    hardware = initial["hardware"]
    backend = hardware["backend"]
    if backend not in {"rigid", "row_column"}:
        raise ValueError("Declared Cartesian backend must be rigid or row_column")
    minimum_axis = max(1.01, hardware["minimum_axis_spacing_um"])
    checks, deforming = 0, 0
    for key, start in started.items():
        end = completed[key]
        aod_id = start.get("aod_id", "AOD_0")
        time = start["event"]["time_us"]
        op = moves.get((key[0], aod_id, time))
        if op is None or abs(end["event"]["time_us"] - op["end"]) > 1e-8:
            raise ValueError("Observer move interval differs from committed trace")
        source, target = start["source_configuration"], start["target_configuration"]
        if (op["source_axes"] != source or op["target_axes"] != target or
                set(op["moving_atom_ids"]) != set(start["moving_atom_ids"])):
            raise ValueError("Observer axes or transported carriers differ from committed row/column move")
        if start["motion_profile"] != ("cubic" if backend == "row_column" else "linear"):
            raise ValueError("The committed motion profile differs from the declared Cartesian backend")
        for axis in ("x_um", "y_um"):
            if len(source[axis]) != len(target[axis]):
                raise ValueError("Row/column axis identities or capacity changed during a move")
            for coordinates in (source[axis], target[axis]):
                if (not all(isfinite(value) for value in coordinates) or
                        any(b - a <= minimum_axis + 1e-12 for a, b in zip(coordinates, coordinates[1:]))):
                    raise ValueError("All Cartesian axes must retain ordered legal spacing including empty intersections")
            offsets = [b - a for a, b in zip(source[axis], target[axis])]
            if backend == "rigid" and max(offsets) - min(offsets) > 1e-8:
                raise ValueError("A rigid MOVE changed an axis offset instead of translating the full Cartesian array")
            deforming += int(bool(offsets) and max(offsets) - min(offsets) > 1e-8)
        distance = hypot(max(abs(b - a) for a, b in zip(source["x_um"], target["x_um"])),
                         max(abs(b - a) for a, b in zip(source["y_um"], target["y_um"])))
        required = (max(1.5 * distance / hardware["speed_um_per_us"],
                        sqrt(6 * distance / hardware["max_acceleration_um_per_us2"]),
                        (12 * distance / hardware["max_jerk_um_per_us3"]) ** (1 / 3))
                    if backend == "row_column" else distance / hardware["speed_um_per_us"])
        if op["end"] - op["start"] + 1e-8 < required:
            raise ValueError("Committed row/column duration violates cubic kinematic limits")
        for boundary, axes, committed_version in ((time, source, start["state_version"]),
                (end["event"]["time_us"], target, end["state_version"])):
            candidates = [(frame, states) for frame, states in frames_at[boundary]
                          if frame["version"] == committed_version and frame["axes_by_aod"].get(aod_id) == axes]
            if not candidates:
                raise ValueError("Observer geometry has no committed move endpoint configuration")
            frame, states = candidates[0]
            if boundary == time:
                device = frame["aods"][aod_id]
                if (op["enabled_rows"] != device["enabled_rows"] or
                        op["enabled_columns"] != device["enabled_columns"]):
                    raise ValueError("Observer activation masks differ from the committed move source")
                mobile = {atom for atom, value in states.items()
                          if value["holder"]["holder_type"] == "mobile" and
                          value["holder"]["holder_id"].get("aod_id", "AOD_0") == aod_id}
                if mobile != set(start["moving_atom_ids"]):
                    raise ValueError("Move evidence omitted an actual mobile spectator carrier")
            for atom in start["moving_atom_ids"]:
                value = states[atom]
                holder = value["holder"]
                if holder["holder_type"] != "mobile" or holder["holder_id"].get("aod_id", "AOD_0") != aod_id:
                    raise ValueError("Transported carrier lacks its actual AOD cell identity")
                cell = holder["holder_id"]
                expected = (axes["x_um"][cell["column"]], axes["y_um"][cell["row"]])
                if any(abs(value["position"][axis] - expected[i]) > 1e-8
                       for i, axis in enumerate(("x_um", "y_um"))):
                    raise ValueError("Actual carrier endpoint does not match its row/column configuration")
                checks += 1
    return {"committed_moves_checked": len(started), "carrier_endpoint_checks": checks,
            "deforming_axis_move_count": deforming,
            "backend": backend,
            "axis_order_and_spacing_certified_for_shared_monotone_progress": True,
            "continuous_atom_slm_sweep_validation": "Executor plus complete original-initial-state plan replay"}


def verify_nonpair_spacing(recording, gates, initial, minimum_um=10.0):
    """Check every nonpartner pair of actual live atoms at every CZ pulse."""
    by_id = {gate["id"]: gate for gate in gates}
    positions, cursor, minimum, checks = {}, 0, float("inf"), 0
    frames = recording["frames"]
    for pulse in sorted((op for op in recording["operations"] if op["kind"] == "entangling_pulse"),
                        key=lambda op: op["start"]):
        while cursor < len(frames) and frames[cursor]["time"] <= pulse["start"]:
            positions.update({atom["id"]: atom["position"] for atom in frames[cursor]["atom_updates"]})
            cursor += 1
        if set(positions) != set(initial["atoms"]) or any(point is None for point in positions.values()):
            raise ValueError("Nonpair-spacing audit requires all actual live carriers")
        intended = {frozenset(by_id[gid]["qubit_ids"]) for gid in _gate_ids(pulse)}
        values = list(positions.items())
        for i, (a, p) in enumerate(values):
            for b, q in values[i + 1:]:
                if frozenset((a, b)) in intended:
                    continue
                distance = hypot(p["x_um"] - q["x_um"], p["y_um"] - q["y_um"])
                if distance < minimum_um - 1e-8:
                    raise ValueError("A nonpartner atom pair violates the declared 10 um CZ design spacing")
                minimum = min(minimum, distance)
                checks += 1
    if not checks:
        raise ValueError("No nonpartner geometry was checked")
    return {"minimum_required_nonpair_spacing_um": minimum_um,
            "minimum_actual_nonpair_spacing_um": minimum,
            "nonpair_distance_checks": checks,
            "scope": "all alive atoms including resource carriers at every actual CZ pulse"}


def audit(directory, *, mode="layer", baseline=None, proposal=None):
    directory = Path(directory)
    core = audit_prefix(directory)
    summary = read(directory / "summary.json")
    if summary["audit"].get("independent_plan_replay_equal") is not True:
        raise ValueError("A complete original-initial-state plan replay is required")
    source = read(directory / "source-prefix.json")
    gates = read(directory / "prefix-circuit.json")["gates"]
    initial = read(directory / "initial.json")
    if isinstance(initial, str):
        initial = json.loads(initial)
    recording = read(directory / "recording.json")
    if mode == "enola" and proposal is None:
        raise ValueError("Enola mode requires the explicit frozen proposal path")
    protocol = verify_canonical_protocol(source, gates)
    batches = verify_cz_batches(protocol, recording["operations"], mode)
    result = {"schema": "patch-parallel-layout-independent-audit/1", "passed": True,
              "scope": "unchanged deterministic native prefix; declared placement and legal intra-patch CZ batches",
              "prefix_independent_audit": core,
              "protocol": {key: protocol[key] for key in ("canonical_phases_checked",
                           "canonical_dependency_edges_checked", "css_native_gates_checked")},
              "batches": batches, "home_layout": verify_home_layout(initial, protocol, proposal=proposal, recording=recording),
              "move_evidence": verify_move_evidence(recording, directory / "trace.jsonl", initial),
              "nonpair_cz_spacing": verify_nonpair_spacing(recording, gates, initial),
              "artifact_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                  for name in ("initial.json", "source-prefix.json", "prefix-circuit.json", "recording.json")},
              "physical_time_us": core["physical_time_us"], "complete_physical_shor": False,
              "magic_factory_or_fault_tolerance_claimed": False}
    if baseline is not None:
        baseline = Path(baseline)
        other = audit(baseline, mode="role", proposal=proposal)
        for name in ("initial.json", "source-prefix.json", "prefix-circuit.json"):
            if result["artifact_sha256"][name] != other["artifact_sha256"][name]:
                raise ValueError("Timing comparison requires byte-identical initial platform, source and circuit")
        before, after = other["physical_time_us"], result["physical_time_us"]
        result["equal_platform_baseline"] = {
            "baseline_mode": "role", "optimized_mode": mode,
            "initial_source_and_circuit_byte_identical": True,
            "baseline_physical_time_us": before, "optimized_physical_time_us": after,
            "physical_time_change_us": after - before,
            "physical_time_ratio_optimized_over_baseline": after / before,
            "baseline_cz_pulses": other["batches"]["total_cz_pulses"],
            "optimized_cz_pulses": batches["total_cz_pulses"],
            "baseline_recording_sha256": other["artifact_sha256"]["recording.json"]}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--mode", choices=("layer", "role", "enola"), default="layer")
    parser.add_argument("--proposal", type=Path, help="Exact frozen author-placer output required in Enola mode")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.directory, mode=args.mode, baseline=args.baseline, proposal=args.proposal)
    text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
