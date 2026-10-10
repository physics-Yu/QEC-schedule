"""Carrier, trap and shared-line state for the R1/R4 public JSON contracts."""

from copy import deepcopy
from itertools import combinations
import math

from na_pipeline.device import validate_device

from .errors import fail

EPS = 1e-8


def _moving_candidates(p, q, moving):
    boxes={a:(min(v[0],q[a][0])-EPS,max(v[0],q[a][0])+EPS,
              min(v[1],q[a][1])-EPS,max(v[1],q[a][1])+EPS) for a,v in p.items()}
    for a in sorted(moving):
        u=boxes[a]
        for b,v in boxes.items():
            if b==a or (b in moving and b<a): continue
            if u[0]<=v[1] and v[0]<=u[1] and u[2]<=v[3] and v[2]<=u[3]:
                yield a,b


def point(value, action=None):
    if not isinstance(value, list) or len(value) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        fail("INVALID_POSITION", "Expected two finite um coordinates", action)
    return value


def near(a, b):
    return all(abs(x-y) <= EPS for x, y in zip(a, b))


def inside(position, zone):
    return all((lo is None or coordinate >= lo) and (hi is None or coordinate <= hi)
               for coordinate, (lo, hi) in zip(position, (zone["x_range_um"], zone["y_range_um"])))


def segment_inside(a, b, zone):
    """Whether a straight segment intersects a closed rectangular zone."""
    low, high = 0., 1.
    for coordinate, end, (lo, hi) in zip(a, b, (zone["x_range_um"], zone["y_range_um"])):
        delta = end-coordinate
        if abs(delta) < EPS:
            if (lo is not None and coordinate < lo) or (hi is not None and coordinate > hi):
                return False
        else:
            entry = -math.inf if lo is None else (lo-coordinate)/delta
            leave = math.inf if hi is None else (hi-coordinate)/delta
            if delta < 0:
                entry, leave = (-math.inf if hi is None else (hi-coordinate)/delta,
                                math.inf if lo is None else (lo-coordinate)/delta)
            low, high = max(low, entry), min(high, leave)
    return low <= high


class RuntimeState:
    def __init__(self, initial, device):
        errors = validate_device(device)
        if errors:
            fail("INVALID_DEVICE", str(errors[:3]))
        self.device = device
        self.zones = deepcopy(device["zones"])
        grouped = device.get("grouped_profile", {})
        if grouped:
            initial_layout = grouped.get("layouts", {}).get("patch_initialization", {})
            initial_zone = grouped.get("initialization_zone")
            if initial_layout.get("zone_id") and isinstance(initial_zone, dict):
                self.zones[initial_layout["zone_id"]] = initial_zone
        self.atoms, self.traps = {}, {}
        self.lines = {g: {"rows": {}, "columns": {}} for g in device["aod_groups"]}
        self.active = {}
        for key in ("atoms", "slm_traps", "aod_rows", "aod_columns"):
            if not isinstance(initial.get(key), list):
                fail("INVALID_INITIAL_STATE", f"initial_state.{key} must be a list")
        for trap in initial["slm_traps"]:
            tid = trap.get("trap_id")
            if not isinstance(tid, str) or tid in self.traps:
                fail("INVALID_TRAP", "SLM trap ID must be unique")
            point(trap.get("position_um"))
            if trap.get("zone_id") not in self.zones or not inside(trap["position_um"], self.zones[trap["zone_id"]]):
                fail("INVALID_TRAP_ZONE", "SLM trap must lie in its declared zone", resource_id=tid)
            if "occupant" not in trap:
                fail("INVALID_TRAP", "Trap occupant must be explicit, including null", resource_id=tid)
            self.traps[tid] = deepcopy(trap)
        for key, axis, idkey, coordinate in (("aod_rows", "rows", "row_id", "y_um"), ("aod_columns", "columns", "column_id", "x_um")):
            for line in initial[key]:
                group, line_id = line.get("aod_group"), line.get(idkey)
                if group not in self.lines or line_id is None or line_id in self.lines[group][axis]:
                    fail("INVALID_AOD_LINE", "Initial AOD line binding is invalid")
                value = line.get(coordinate)
                if type(value) not in (int, float) or not math.isfinite(value):
                    fail("INVALID_AOD_LINE", "Initial line coordinate must be finite")
                self.lines[group][axis][line_id] = value
        qubits = set()
        for raw in initial["atoms"]:
            atom = deepcopy(raw)
            for key in ("atom_id", "qubit_id", "position_um", "carrier", "trap_id", "aod_group", "row_id", "column_id"):
                if key not in atom:
                    fail("INVALID_ATOM", f"Initial atom missing {key}")
            aid, qid = atom["atom_id"], atom["qubit_id"]
            if not isinstance(aid, str) or aid in self.atoms or not isinstance(qid, str) or qid in qubits:
                fail("DUPLICATE_IDENTITY", "Atom and qubit identities must be unique")
            point(atom["position_um"])
            if atom["aod_group"] not in self.lines:
                fail("UNKNOWN_AOD_GROUP", "Atom group is not declared", resource_id=aid)
            if atom["carrier"] == "SLM":
                trap = self.traps.get(atom["trap_id"])
                if trap is None or trap["occupant"] != aid or not near(atom["position_um"], trap["position_um"]) or atom["row_id"] is not None or atom["column_id"] is not None:
                    fail("TRAP_BINDING", "SLM atom/trap binding is inconsistent", resource_id=aid)
            elif atom["carrier"] == "AOD":
                lines = self.lines[atom["aod_group"]]
                if atom["row_id"] not in lines["rows"] or atom["column_id"] not in lines["columns"] or not near(atom["position_um"], [lines["columns"][atom["column_id"]], lines["rows"][atom["row_id"]]]):
                    fail("AOD_BINDING", "AOD atom requires explicit matching row and column", resource_id=aid)
            else:
                fail("UNSUPPORTED_CARRIER", "Only SLM and AOD are supported", resource_id=aid)
            atom.setdefault("reset_epoch", 0)
            atom.setdefault("measurement_count", 0)
            atom.setdefault("preparation_status", "unspecified")
            self.atoms[aid] = atom
            qubits.add(qid)
        for tid, trap in self.traps.items():
            aid = trap["occupant"]
            if aid is not None and (aid not in self.atoms or self.atoms[aid]["trap_id"] != tid or self.atoms[aid]["carrier"] != "SLM"):
                fail("TRAP_BINDING", "Trap occupant has no matching resident atom", resource_id=tid)
        for a, b in combinations(self.atoms.values(), 2):
            if a["trap_id"] == b["trap_id"] or near(a["position_um"], b["position_um"]):
                fail("INITIAL_OCCUPANCY", "Distinct atoms cannot share a trap or point position")
        for axes in self.lines.values():
            for coords in axes.values():
                values = sorted(coords.values())
                if any(b-a <= EPS for a, b in zip(values, values[1:])):
                    fail("LINE_COLLISION", "Distinct initial AOD lines cannot coincide")
        sites = {a.get("site_id", a["qubit_id"]): a["trap_id"] for a in self.atoms.values()}
        if len(sites) != len(self.atoms):
            fail("DUPLICATE_SITE_BINDING", "Code-site roles must be one-to-one")
        self.site_homes = deepcopy(initial.get("site_home_traps", {s:t for s,t in sites.items() if t in self.traps}))
        if not set(self.site_homes) <= set(sites) or any(t not in self.traps for t in self.site_homes.values()):
            fail("SITE_HOME_BINDING", "Each code site requires its explicit static destination")
        self.illumination_counts = {aid: 0 for aid in self.atoms}

    def snapshot(self, ids):
        result = {}
        for aid in ids:
            if aid not in self.atoms:
                fail("UNKNOWN_ATOM", "Action references an absent atom", resource_id=aid)
            result[aid] = deepcopy(self.atoms[aid])
        return result

    def positions(self, at, extra=None):
        positions = {aid: list(a["position_um"]) for aid, a in self.atoms.items()}
        for action in [*self.active.values(), *([extra] if extra else [])]:
            if action["kind"] != "move":
                continue
            fraction = min(1., max(0., (at-action["t_start_us"])/(action["t_end_us"]-action["t_start_us"])))
            for tr in action["payload"]["trajectories"]:
                positions[tr["atom_id"]] = [a+(b-a)*fraction for a, b in zip(tr["from_um"], tr["to_um"])]
        return positions

    def broadcast(self, at):
        positions = self.positions(at)
        zone = self.device["zones"][self.device["broadcast"]["zone_id"]]
        illuminated = sorted(aid for aid, p in positions.items() if inside(p, zone))
        geom = self.device["geometry"]
        pairs = [list(pair) for pair in combinations(illuminated, 2)
                 if abs(math.dist(positions[pair[0]], positions[pair[1]])-geom["gate_pair_distance_um"]) <= geom["distance_tolerance_um"]]
        return illuminated, pairs

    def result_lower_bound(self, action):
        return action["t_end_us"] + (self.device["timings_us"]["result_latency"] if action["kind"] == "measure" else 0)

    def check_transfer_group(self, actions):
        """Atomic same-time transfer cohort; shared axes are intentional only here."""
        first = actions[0]
        require_keys = ("kind", "t_start_us", "t_end_us")
        ids = [aid for action in actions for aid in action["atoms"]]
        if len(ids) != len(set(ids)) or any(len(a["atoms"]) != 1 or a.get("condition") is not None or
                any(a[k] != first[k] for k in require_keys) or a["payload"].get("aod_group") != first["payload"].get("aod_group") for a in actions):
            fail("TRANSFER_GROUP_MISMATCH", "Grouped transfer members need identical intervals, kind, AOD and distinct atoms", first)
        if len({a["payload"]["to_trap_id"] for a in actions}) != len(actions):
            fail("TRANSFER_GROUP_MISMATCH", "Group destination traps must be distinct", first)
        for key, coordinate in (("row_id", 1), ("column_id", 0)):
            axes = {}
            for action in actions:
                name, value = action["payload"][key], action["payload"]["position_um"][coordinate]
                if name in axes and abs(axes[name]-value) > EPS:
                    fail("AOD_BINDING", "Shared transfer axis disagrees between members", first)
                if any(other != name and abs(v-value) <= EPS for other, v in axes.items()):
                    fail("LINE_COLLISION", "Distinct transfer axes cannot coincide", first)
                axes[name] = value
        if first["kind"] == "pickup":
            rows = {a["payload"]["position_um"][1] for a in actions}
            columns = {a["payload"]["position_um"][0] for a in actions}
            existing = self.lines[first["payload"]["aod_group"]]
            rows.update(existing["rows"].values())
            columns.update(existing["columns"].values())
            tol = self.device["geometry"]["distance_tolerance_um"]
            captured = {aid for aid, atom in self.atoms.items() if atom["carrier"] == "SLM" and
                        any(abs(atom["position_um"][1]-y) <= tol for y in rows) and
                        any(abs(atom["position_um"][0]-x) <= tol for x in columns)}
            if captured != set(ids):
                fail("PICKUP_CAPTURE_CLOSURE", "Grouped pickup includes an undeclared spectator or omits a captured atom", first)

    @staticmethod
    def transfer_members(action):
        if action["kind"] not in ("pickup", "drop") or "bindings" not in action["payload"]:
            return [action]
        bindings = action["payload"]["bindings"]
        if not isinstance(bindings, list) or not bindings or {b.get("atom_id") for b in bindings} != set(action["atoms"]) or len(bindings) != len(action["atoms"]):
            fail("TRANSFER_GROUP_MISMATCH", "Group bindings must cover every atom exactly once", action)
        members = []
        for b in bindings:
            for key in ("atom_id", "from_trap_id", "to_trap_id", "row_id", "column_id", "position_um"):
                if key not in b:
                    fail("MISSING_BINDING", f"Group binding requires {key}", action)
            member = dict(action, atoms=[b["atom_id"]], payload=dict(b, aod_group=action["payload"]["aod_group"]))
            members.append(member)
        return members

    def resource_keys(self, action):
        if action["kind"] in ("pickup", "drop") and "bindings" in action["payload"]:
            return sorted({key for member in self.transfer_members(action) for key in self.resource_keys(member)})
        keys = set(action["resources"]) | {f"atom:{aid}" for aid in action["atoms"]}
        payload, kind = action["payload"], action["kind"]
        if kind in ("pickup", "drop"):
            keys.update((f"trap:{payload['from_trap_id']}", f"trap:{payload['to_trap_id']}"))
            keys.add(f"aod:{payload['aod_group']}:row:{payload['row_id']}")
            keys.add(f"aod:{payload['aod_group']}:column:{payload['column_id']}")
        if kind == "move":
            for tr in payload["trajectories"]:
                keys.add(f"aod:{payload['aod_group']}:row:{tr['row_id']}")
                keys.add(f"aod:{payload['aod_group']}:column:{tr['column_id']}")
        if kind == "gate" and payload["name"] == "CZ":
            keys.add(self.device["broadcast"]["resource_id"])
            illuminated, _ = self.broadcast(action["t_start_us"])
            keys.update(f"atom:{aid}" for aid in illuminated)
        return sorted(keys)

    def check(self, action):
        if action["kind"] in ("pickup", "drop") and "bindings" in action["payload"]:
            members = self.transfer_members(action)
            self.check_transfer_group(members)
            for member in members:
                self.check(member)
            return
        kind, payload, ids = action["kind"], action["payload"], action["atoms"]
        duration = action["t_end_us"]-action["t_start_us"]
        timing_key = "cz" if kind == "gate" and payload.get("name") == "CZ" else "gate_1q" if kind == "gate" else "classical" if kind == "rebind" else kind
        if timing_key in self.device["timings_us"] and duration + EPS < self.device["timings_us"][timing_key]:
            fail("DURATION_TOO_SHORT", f"{kind} duration is below DeviceSpec", action)
        if kind not in ("wait", "classical") and not ids:
            fail("MISSING_ATOM", "Physical operation needs explicit atom IDs", action)
        if kind in ("pickup", "drop", "measure") and len(ids) != 1:
            fail("UNSUPPORTED_ARITY", "This action requires one atom", action)
        if kind in ("pickup", "drop"):
            atom = self.atoms[ids[0]]
            for key in ("from_trap_id", "to_trap_id", "aod_group", "row_id", "column_id", "position_um"):
                if key not in payload:
                    fail("MISSING_BINDING", f"Transfer payload needs {key}", action)
            point(payload["position_um"], action)
            expected = "SLM" if kind == "pickup" else "AOD"
            if atom["carrier"] != expected or atom["trap_id"] != payload["from_trap_id"] or atom["aod_group"] != payload["aod_group"] or not near(atom["position_um"], payload["position_um"]):
                fail("TRANSFER_BINDING", "Transfer source disagrees with live carrier/trap/position", action)
            if payload["row_id"] is None or payload["column_id"] is None:
                fail("MISSING_BINDING", "Transfers need AOD row and column IDs", action)
            if any(a["trap_id"] == payload["to_trap_id"] for a in self.atoms.values()):
                fail("TRAP_OCCUPIED", "Transfer destination is occupied", action, resource_id=payload["to_trap_id"])
            if kind == "drop":
                trap = self.traps.get(payload["to_trap_id"])
                if trap is None or trap["occupant"] is not None or not near(trap["position_um"], atom["position_um"]):
                    fail("TRAP_BINDING", "Drop needs an aligned, explicitly empty SLM trap", action)
                if any(atom[k] != payload[k] for k in ("row_id", "column_id")):
                    fail("AOD_BINDING", "Drop cannot silently rebind a line", action)
            else:
                if payload["to_trap_id"] in self.traps:
                    fail("TRAP_BINDING", "Pickup destination must be a dynamic trap", action)
                lines = deepcopy(self.lines[payload["aod_group"]])
                # Concurrent pickups reserve line identities before transfer
                # completion; they must not create colliding dynamic axes.
                for active_group in self.active.values():
                    for active in self.transfer_members(active_group):
                        ap = active["payload"]
                        if active["kind"] == "pickup" and ap["aod_group"] == payload["aod_group"]:
                            lines["rows"][ap["row_id"]] = ap["position_um"][1]
                            lines["columns"][ap["column_id"]] = ap["position_um"][0]
                for axis, key, coordinate in (("rows", "row_id", 1), ("columns", "column_id", 0)):
                    for lid, value in lines[axis].items():
                        if lid == payload[key] and abs(value-atom["position_um"][coordinate]) > EPS:
                            fail("AOD_BINDING", "Pickup line is not aligned", action)
                        if lid != payload[key] and abs(value-atom["position_um"][coordinate]) <= EPS:
                            fail("LINE_COLLISION", "Distinct line IDs cannot occupy one coordinate", action)
        elif kind == "rebind":
            if "rebind" not in self.device["operations"]["action_kinds"]:
                fail("SITE_BINDING_UNSUPPORTED", "Device does not declare code-site binding control", action)
            bindings = payload.get("site_bindings", [])
            if (action.get("condition") is not None or payload.get("reads") or payload.get("writes") or
                    payload.get("quantum_effect") != "none" or len(bindings) != len(ids) or
                    {b["atom_id"] for b in bindings} != set(ids)):
                fail("SITE_BINDING_CONTRACT", "Binding commit must cover all carriers and have no quantum/result effect", action)
            old = {self.atoms[a].get("site_id", self.atoms[a]["qubit_id"]) for a in ids}
            if {b["from_site_id"] for b in bindings} != old or {b["to_site_id"] for b in bindings} != old:
                fail("SITE_BINDING_BIJECTION", "Site bindings must be a permutation of the same roles", action)
            for b in bindings:
                atom = self.atoms[b["atom_id"]]
                if (atom.get("site_id", atom["qubit_id"]) != b["from_site_id"] or atom["carrier"] != "SLM" or
                        atom["trap_id"] != b["destination_trap_id"] or
                        self.site_homes[b["to_site_id"]] != atom["trap_id"] or
                        not near(atom["position_um"], b["position_um"])):
                    fail("SITE_BINDING_BEFORE_ARRIVAL", "Binding cannot substitute for actual transport to the destination site", action)
        elif kind == "move":
            self.check_move(action)
        elif kind == "gate":
            name = payload.get("name")
            if name == "CZ":
                if payload.get("broadcast") is not True or payload.get("zone_id") != self.device["broadcast"]["zone_id"]:
                    fail("BROADCAST_CONTRACT", "CZ must use the declared common broadcast", action)
                illuminated, pairs = self.broadcast(action["t_start_us"])
                declared = payload.get("pairs")
                if not isinstance(declared, list) or any(not isinstance(p, list) or len(p) != 2 for p in declared) or sorted(sorted(p) for p in declared) != pairs:
                    fail("BROADCAST_PAIR_MISMATCH", "CZ must include every geometric pair in the full illumination zone", action)
                flattened = [aid for pair in pairs for aid in pair]
                if len(flattened) != len(set(flattened)):
                    fail("UNSUPPORTED_MULTIBODY_BROADCAST", "Geometric pairs share an atom; native disjoint-CZ support does not verify a multibody pulse", action)
                if not {aid for pair in pairs for aid in pair}.issubset(ids):
                    fail("BROADCAST_ATOMS", "Action omits paired atoms", action)
                for active in self.active.values():
                    if active["kind"] == "move" and self.move_intersects_pulse(active, action):
                        fail("BROADCAST_MOTION", "Motion enters or changes illuminated geometry during pulse", action)
            elif name not in self.device["operations"]["native_1q_gates"] or len(ids) != 1:
                fail("UNSUPPORTED_GATE", f"Unsupported native gate {name!r} or arity", action)
            if name in ("RX", "RY", "RZ"):
                params = payload.get("params", {})
                if params.get("angle_unit") != "rad" or type(params.get("angle")) not in (int, float) or not math.isfinite(params["angle"]):
                    fail("INVALID_GATE_PARAMETER", "Rotation requires finite angle and angle_unit=rad", action)
        elif kind == "measure":
            if payload.get("basis") != "Z" or payload.get("origin") != "fake" or "result_ready_us" not in payload:
                fail("MEASUREMENT_CONTRACT", "Measurement needs Z basis, fake origin and result_ready_us", action)
            if not inside(self.atoms[ids[0]]["position_um"], self.device["zones"][self.device["measurement"]["zone_id"]]):
                fail("MEASUREMENT_ZONE", "Measurement atom is outside measurement zone", action)
            if "grouped_profile" in self.device:
                from na_pipeline.device import validate_readout_batch
                entries = []
                for measure in [a for a in self.active.values() if a["kind"] == "measure"] + [action]:
                    p = measure["payload"]
                    if any(k not in p for k in ("bank_id", "site_id", "earliest_ready_us")):
                        fail("READOUT_PROFILE_FIELDS", "Grouped-device measurement needs bank/site/earliest_ready_us", measure)
                    entries.append({"atom_id": measure["atoms"][0], "position_um": self.atoms[measure["atoms"][0]]["position_um"],
                                    "bank_id": p["bank_id"], "site_id": p["site_id"], "basis": p["basis"],
                                    "t_start_us": measure["t_start_us"], "t_end_us": measure["t_end_us"],
                                    "earliest_ready_us": p["earliest_ready_us"], "result_id": p["result_id"], "result_ready_us": p["result_ready_us"]})
                errors = validate_readout_batch(self.device, entries)
                if errors:
                    fail("READOUT_PROFILE_CONFLICT", str(errors[:3]), action)
        elif kind == "reset":
            if payload.get("state") != self.device["reset"]["target"]:
                fail("UNSUPPORTED_RESET", "Reset target must be explicit 0", action)
            for aid in ids:
                if not any(inside(self.atoms[aid]["position_um"], self.device["zones"][zone]) for zone in self.device["reset"]["allowed_zone_ids"]):
                    fail("RESET_ZONE", "Reset outside allowed zones", action)
        elif kind == "classical":
            if payload.get("operation") not in ("fake", "xor", "copy", "all_zero", "postprocess_phase") or not payload.get("writes"):
                fail("UNSUPPORTED_CLASSICAL", "Classical operation must have a supported explicit expression and outputs", action)

    def move_intersects_pulse(self, motion, pulse):
        t0, t1 = max(motion["t_start_us"], pulse["t_start_us"]), min(motion["t_end_us"], pulse["t_end_us"])
        if t1 <= t0:
            return False
        zone = self.device["zones"][self.device["broadcast"]["zone_id"]]
        for tr in motion["payload"]["trajectories"]:
            endpoints = []
            for t in (t0, t1):
                f = (t-motion["t_start_us"])/(motion["t_end_us"]-motion["t_start_us"])
                endpoints.append([a+(b-a)*f for a, b in zip(tr["from_um"], tr["to_um"])])
            if segment_inside(*endpoints, zone):
                return True
        return False

    def check_move(self, action):
        payload = action["payload"]
        group = payload.get("aod_group")
        trajectories = payload.get("trajectories")
        if payload.get("interpolation") != "linear" or group not in self.lines or not isinstance(trajectories, list):
            fail("UNSUPPORTED_MOTION", "Move needs group and explicit linear trajectories", action)
        if len(trajectories) != len(action["atoms"]) or {tr.get("atom_id") for tr in trajectories} != set(action["atoms"]):
            fail("TRAJECTORY_ATOMS", "Each moved atom requires exactly one trajectory", action)
        for tr in trajectories:
            atom = self.atoms[tr["atom_id"]]
            point(tr.get("from_um"), action); point(tr.get("to_um"), action)
            if atom["carrier"] != "AOD" or atom["aod_group"] != group or not near(atom["position_um"], tr["from_um"]) or any(tr.get(k) != atom[k] for k in ("row_id", "column_id")):
                fail("MOTION_BINDING", "Trajectory disagrees with live AOD binding/start", action)
            needed = max(abs(a-b) for a, b in zip(tr["from_um"], tr["to_um"]))/self.device["movement"]["speed_um_per_us"]
            if action["t_end_us"]-action["t_start_us"] + EPS < needed:
                fail("SPEED_EXCEEDED", "Move is faster than the declared axis speed", action)
        if all(near(tr["from_um"], tr["to_um"]) for tr in trajectories):
            fail("NO_MOTION", "Use wait for a stationary interval", action)
        for active in self.active.values():
            if active["kind"] == "gate" and active["payload"].get("name") == "CZ" and self.move_intersects_pulse(action, active):
                fail("BROADCAST_MOTION", "Motion changes geometry during an active broadcast", action)
        cuts = sorted({action["t_start_us"], action["t_end_us"],
                       *(a["t_end_us"] for a in self.active.values() if a["kind"] == "move" and a["t_end_us"] < action["t_end_us"])})
        previous_lines = None
        for at in cuts:
            positions = self.positions(at, action)
            lines = deepcopy(self.lines[group])
            seen = {"rows": {}, "columns": {}}
            for aid, atom in self.atoms.items():
                if atom["carrier"] != "AOD" or atom["aod_group"] != group:
                    continue
                for axis, key, coordinate in (("rows", "row_id", 1), ("columns", "column_id", 0)):
                    lid, value = atom[key], positions[aid][coordinate]
                    if lid in seen[axis] and abs(seen[axis][lid]-value) > EPS:
                        fail("SHARED_LINE_MOTION", "A shared line has omitted or inconsistent carried atoms", action)
                    seen[axis][lid] = value
                    lines[axis][lid] = value
            for axis in ("rows", "columns"):
                ordered = sorted(lines[axis], key=lines[axis].get) if previous_lines is None else sorted(previous_lines[axis], key=previous_lines[axis].get)
                if any(lines[axis][b]-lines[axis][a] <= EPS for a, b in zip(ordered, ordered[1:])):
                    fail("LINE_CROSSING", "AOD line order changes or lines coincide", action)
            previous_lines = lines
        moving = {tr["atom_id"] for tr in trajectories}
        for t0, t1 in zip(cuts, cuts[1:]):
            p0, p1 = self.positions(t0, action), self.positions(t1, action)
            # Only moved-versus-resident pairs can create a new collision.
            # Conservative swept boxes reject remote pairs before the exact
            # closest-approach predicate. No stationary all-pairs scan.
            for a, b in _moving_candidates(p0, p1, moving):
                d = [p0[a][i]-p0[b][i] for i in range(2)]
                v = [(p1[a][i]-p0[a][i])-(p1[b][i]-p0[b][i]) for i in range(2)]
                vv = sum(x*x for x in v)
                f = min(1., max(0., -sum(x*y for x, y in zip(d, v))/vv)) if vv else 0.
                if sum((x+y*f)**2 for x, y in zip(d, v)) <= EPS**2:
                    fail("ATOM_COLLISION", f"Point trajectories collide: {a}, {b}", action)
            # All active Cartesian traps exist, including unoccupied crossings.
            # Their continuous sweep may capture/collide with a spectator even
            # when every occupied atom trajectory itself is collision-free.
            line_endpoints = []
            for positions in (p0, p1):
                axes = deepcopy(self.lines[group])
                for aid, atom in self.atoms.items():
                    if atom["carrier"] == "AOD" and atom["aod_group"] == group:
                        axes["rows"][atom["row_id"]] = positions[aid][1]
                        axes["columns"][atom["column_id"]] = positions[aid][0]
                line_endpoints.append(axes)
            for row in line_endpoints[0]["rows"]:
                for col in line_endpoints[0]["columns"]:
                    crossing = [[axes["columns"][col], axes["rows"][row]] for axes in line_endpoints]
                    for aid, atom in self.atoms.items():
                        if atom["carrier"] == "AOD" and atom["aod_group"] == group and atom["row_id"] == row and atom["column_id"] == col:
                            continue
                        delta = [crossing[0][i]-p0[aid][i] for i in range(2)]
                        velocity = [(crossing[1][i]-crossing[0][i])-(p1[aid][i]-p0[aid][i]) for i in range(2)]
                        vv = sum(v*v for v in velocity)
                        fraction = min(1., max(0., -sum(x*v for x, v in zip(delta, velocity))/vv)) if vv else 0.
                        if sum((x+v*fraction)**2 for x, v in zip(delta, velocity)) <= EPS**2:
                            fail("AOD_INTERSECTION_SWEEP", f"Active Cartesian trap sweeps a nonresident atom {aid}", action)

    def start(self, action):
        if action["kind"] == "gate" and action["payload"]["name"] == "CZ":
            illuminated, _ = self.broadcast(action["t_start_us"])
            for aid in illuminated:
                self.illumination_counts[aid] += 1
        self.active[action["id"]] = action

    def finish(self, action):
        if action["kind"] in ("pickup", "drop") and "bindings" in action["payload"]:
            for member in self.transfer_members(action):
                self.finish(member)
            self.active.pop(action["id"], None)
            return
        kind, payload = action["kind"], action["payload"]
        if kind in ("pickup", "drop"):
            atom = self.atoms[action["atoms"][0]]
            lines = self.lines[payload["aod_group"]]
            if kind == "pickup":
                self.traps[payload["from_trap_id"]]["occupant"] = None
                atom.update(carrier="AOD", trap_id=payload["to_trap_id"], row_id=payload["row_id"], column_id=payload["column_id"])
                lines["rows"][atom["row_id"]] = atom["position_um"][1]
                lines["columns"][atom["column_id"]] = atom["position_um"][0]
            else:
                self.traps[payload["to_trap_id"]]["occupant"] = atom["atom_id"]
                atom.update(carrier="SLM", trap_id=payload["to_trap_id"], row_id=None, column_id=None)
                for axis, key in (("rows", "row_id"), ("columns", "column_id")):
                    if not any(a["carrier"] == "AOD" and a["aod_group"] == payload["aod_group"] and a[key] == payload[key] for a in self.atoms.values()):
                        lines[axis].pop(payload[key], None)
        elif kind == "rebind":
            for b in payload["site_bindings"]:
                self.atoms[b["atom_id"]]["site_id"] = b["to_site_id"]
        elif kind == "move":
            for tr in payload["trajectories"]:
                atom = self.atoms[tr["atom_id"]]
                atom["position_um"] = list(tr["to_um"])
                lines = self.lines[atom["aod_group"]]
                lines["rows"][atom["row_id"]] = tr["to_um"][1]
                lines["columns"][atom["column_id"]] = tr["to_um"][0]
        elif kind == "measure":
            atom = self.atoms[action["atoms"][0]]
            atom["measurement_count"] += 1
            atom["preparation_status"] = "measured_quantum_untracked"
        elif kind == "reset":
            for aid in action["atoms"]:
                self.atoms[aid]["reset_epoch"] += 1
                self.atoms[aid]["preparation_status"] = "reset_0_quantum_untracked"
        self.active.pop(action["id"], None)

    def export(self, at):
        rows, columns = [], []
        for group, axes in self.lines.items():
            rows.extend({"aod_group": group, "row_id": lid, "y_um": value} for lid, value in axes["rows"].items())
            columns.extend({"aod_group": group, "column_id": lid, "x_um": value} for lid, value in axes["columns"].items())
        return {"time_us": at, "atoms": deepcopy(list(self.atoms.values())),
                "slm_traps": deepcopy(list(self.traps.values())), "aod_rows": rows, "aod_columns": columns,
                "site_home_traps": deepcopy(self.site_homes)}
