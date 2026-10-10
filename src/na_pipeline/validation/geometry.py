"""Independent boundary sweep over the public R1/R4 JSON contracts."""
from collections import defaultdict
from copy import deepcopy
from itertools import combinations
import math

from .checker import EPS, _finite, _hash
from .strategy_capture import transfer_records


def inside(point, zone):
    return all((lo is None or p >= lo - EPS) and (hi is None or p <= hi + EPS)
               for p, (lo, hi) in zip(point, (zone["x_range_um"], zone["y_range_um"])))


def _segment_enters(p, q, zone):
    lower, upper = 0., 1.
    for k, key in enumerate(("x_range_um", "y_range_um")):
        lo, hi = zone[key]
        delta = q[k] - p[k]
        if abs(delta) < EPS:
            if (lo is not None and p[k] < lo - EPS) or (hi is not None and p[k] > hi + EPS):
                return False
        else:
            bounds = [((x - p[k]) / delta) if x is not None else None for x in (lo, hi)]
            if delta < 0:
                bounds.reverse()
            if bounds[0] is not None:
                lower = max(lower, bounds[0])
            if bounds[1] is not None:
                upper = min(upper, bounds[1])
    return lower <= upper + EPS


def _point(point):
    return isinstance(point, list) and len(point) == 2 and all(_finite(v) for v in point)


def _pairs(atoms, zone, device):
    visible = [key for key, atom in atoms.items() if inside(atom["position_um"], zone)]
    d = device["geometry"]["gate_pair_distance_um"]
    tol = device["geometry"]["distance_tolerance_um"]
    return visible, {tuple(sorted((a, b))) for a, b in combinations(visible, 2)
                     if abs(math.dist(atoms[a]["position_um"], atoms[b]["position_um"]) - d) <= tol}


def _axes(audit, atoms, positions, end_positions, action_id):
    """An affine difference stays positive iff both endpoints are positive."""
    for coordinate, field in ((0, "column_id"), (1, "row_id")):
        groups = defaultdict(dict)
        for aid, atom in atoms.items():
            if atom["carrier"] != "AOD":
                continue
            group, line = atom["aod_group"], atom[field]
            pair = (positions[aid][coordinate], end_positions[aid][coordinate])
            if line is None:
                audit.fail("geometry", "MISSING_AXIS", "AOD resident requires both axis bindings", action_id=action_id, resource=aid)
            previous = groups[group].get(line)
            if previous and any(abs(x - y) > EPS for x, y in zip(previous, pair)):
                audit.fail("geometry", "SHARED_AXIS", "Atoms on the same line do not follow the same trajectory", action_id=action_id, resource=f"{group}/{field}/{line}")
            groups[group][line] = pair
        for group, axes in groups.items():
            order = sorted(axes, key=lambda key: axes[key][0])
            for left, right in zip(order, order[1:]):
                if axes[right][0] - axes[left][0] <= EPS or axes[right][1] - axes[left][1] <= EPS:
                    audit.fail("geometry", "AXIS_CROSSING", "Shared axis order collides or reverses within a linear interval", action_id=action_id, resource=f"{group}/{field}/{left},{right}")


def _collision(a0, a1, b0, b1):
    # Solve equality in each coordinate, intersect the candidate time constraints.
    root = None
    for k in (0, 1):
        offset = a0[k] - b0[k]
        slope = a1[k] - a0[k] - b1[k] + b0[k]
        if abs(slope) <= EPS:
            if abs(offset) > EPS:
                return False
        else:
            candidate = -offset / slope
            if root is not None and abs(root - candidate) > EPS:
                return False
            root = candidate
    return root is None or -EPS <= root <= 1 + EPS


def _swept_candidates(p, q):
    """Conservative broad phase; the original affine predicate is unchanged.

    Its root tolerance permits a time slightly outside [0,1], or two coordinate
    roots differing by EPS. Expand by velocity-scaled padding before rejecting
    a pair. Stationary coincidences are included, not assumed impossible.
    """
    boxes=[]
    for key, a in p.items():
        b=q[key]
        pad=EPS*(1+4*max(abs(b[0]-a[0]),abs(b[1]-a[1])))
        boxes.append((min(a[0],b[0])-pad,max(a[0],b[0])+pad,
                      min(a[1],b[1])-pad,max(a[1],b[1])+pad,key))
    active=[]
    for box in sorted(boxes):
        active=[v for v in active if v[1]>=box[0]]
        for old in active:
            if old[3]>=box[2] and box[3]>=old[2]:
                yield old[4],box[4]
        active.append(box)


def check_geometry(audit, plan, device):
    if device["movement"]["model"] != "parallel_axes_linear" or device["geometry"]["pair_metric"] != "euclidean" or device["geometry"]["pair_rule"] != "distance_equal_with_tolerance":
        audit.need("geometry", "UNSUPPORTED_DEVICE_MODEL", "Only the published affine-axis/distance-equality model is implemented")
        audit.need("broadcast", "UNSUPPORTED_DEVICE_MODEL", "Broadcast geometry cannot be interpreted")
        return None
    if plan.get("complete") is not True:
        audit.fail("contract", "INCOMPLETE_PLAN", "A truncated or incomplete plan cannot pass")
    device_ref = plan.get("device_ref")
    if isinstance(device_ref, str):
        bound = device_ref == device["artifact_id"]
    elif isinstance(device_ref, dict):
        bound = device_ref.get("artifact_id") == device["artifact_id"]
        if device_ref.get("sha256") != _hash(device):
            audit.fail("contract", "DEVICE_HASH", "device_ref.sha256 does not bind the current device")
    else:
        bound = False
    if not bound:
        audit.fail("contract", "DEVICE_REFERENCE", "Plan does not reference this device artifact")
    # Hash binding is checked if the producer exposes it; no private cache state.
    hashes = plan.get("input_hashes", {})
    for key in ("device", "device_spec"):
        if key in hashes and hashes[key] != _hash(device):
            audit.fail("contract", "DEVICE_HASH", "Device differs from the compiler input", resource=key)
    initial = plan["initial_state"]
    atoms = {a["atom_id"]: deepcopy(a) for a in initial["atoms"]}
    traps = {t["trap_id"]: deepcopy(t) for t in initial["slm_traps"]}
    if len(atoms) != len(initial["atoms"]) or len({a["qubit_id"] for a in atoms.values()}) != len(atoms):
        audit.fail("geometry", "IDENTITY_DUPLICATE", "Atom and qubit identities must be one-to-one")
    if len(traps) != len(initial["slm_traps"]):
        audit.fail("geometry", "TRAP_DUPLICATE", "SLM trap identity is duplicated")
    for a in atoms.values():
        a.setdefault("reset_epoch", 0)
        a.setdefault("measurement_count", 0)
        if not _point(a["position_um"]):
            raise ValueError("atom position_um must be a finite coordinate pair")
        if a["aod_group"] not in device["aod_groups"]:
            audit.fail("geometry", "AOD_GROUP", "Unknown AOD group", resource=a["atom_id"])
        if a["carrier"] == "SLM":
            trap = traps.get(a["trap_id"])
            if not trap or trap["occupant"] != a["atom_id"] or math.dist(trap["position_um"], a["position_um"]) > EPS:
                audit.fail("geometry", "INITIAL_OCCUPANCY", "SLM atom and trap occupancy/position disagree", resource=a["atom_id"])
        elif a["carrier"] != "AOD":
            audit.fail("geometry", "CARRIER", "Unknown carrier", resource=a["atom_id"])
    for tid, trap in traps.items():
        if not _point(trap["position_um"]):
            raise ValueError("SLM trap position must be finite")
        resident = trap.get("occupant")
        if resident is not None and (resident not in atoms or atoms[resident]["trap_id"] != tid):
            audit.fail("geometry", "INITIAL_OCCUPANCY", "Trap references an absent or differently bound atom", resource=tid)
    if initial.get("aod_rows") or initial.get("aod_columns"):
        audit.need("geometry", "INITIAL_EMPTY_AXES", "Nonempty explicit initial axis inventories, including empty lines, need a finalized inventory schema")
    site_homes = initial.get("site_home_traps", {a.get("site_id", a["qubit_id"]): a["trap_id"] for a in atoms.values()})
    counts = {aid: 0 for aid in atoms}
    starts, ends = defaultdict(list), defaultdict(list)
    inferred = defaultdict(list)
    for action in plan["actions"]:
        starts[action["t_start_us"]].append(action)
        ends[action["t_end_us"]].append(action)
        for aid in action["atoms"]:
            if aid not in atoms:
                audit.fail("geometry", "ATOM_UNKNOWN", "Action references unknown atom", action_id=action["id"], resource=aid)
        if action["kind"] in ("pickup", "drop"):
            records=transfer_records(action)
            if len(records)!=len(action['atoms']) or {r['atom_id'] for r in records}!=set(action['atoms']):
                audit.fail('geometry','TRANSFER_MEMBER_COVERAGE','Transfer records must bind all action atoms exactly once',action_id=action['id'])
            for record in records:
                for key in ("from_trap_id", "to_trap_id"):
                    inferred[f"trap:{record[key]}"].append(action)
    for resource, actions in inferred.items():
        ordered = sorted(actions, key=lambda a: a["t_start_us"])
        for previous, current in zip(ordered, ordered[1:]):
            if previous["t_end_us"] > current["t_start_us"] + EPS:
                audit.fail("resources", "TRAP_OVERLAP", "Transfer intervals share a trap", action_id=current["id"], resource=resource)
    active = {}
    times = sorted(set(starts) | set(ends))
    bzone = device["zones"][device["broadcast"]["zone_id"]]
    snapshots = {}
    for index, now in enumerate(times):
        for action in ends[now]:
            active.pop(action["id"], None)
            kind, payload = action["kind"], action["payload"]
            if kind in ("pickup", "drop"):
                for record in transfer_records(action):
                    atom_id=record['atom_id']; atom=atoms[atom_id]
                    if kind == "pickup":
                        if record["from_trap_id"] in traps:
                            traps[record["from_trap_id"]]["occupant"] = None
                        atom.update(carrier="AOD", trap_id=record["to_trap_id"], row_id=record["row_id"], column_id=record["column_id"])
                    else:
                        if record["to_trap_id"] in traps:
                            traps[record["to_trap_id"]]["occupant"] = atom_id
                        atom.update(carrier="SLM", trap_id=record["to_trap_id"], row_id=None, column_id=None)
            elif kind == "rebind":
                for b in payload["site_bindings"]:
                    atoms[b["atom_id"]]["site_id"] = b["to_site_id"]
            elif kind in ("reset", "measure"):
                field = "reset_epoch" if kind == "reset" else "measurement_count"
                for key in action["atoms"]:
                    atoms[key][field] += 1
            snapshots[(action["id"], "after")] = {aid: deepcopy(atoms[aid]) for aid in action["atoms"] if aid in atoms}
        for action in starts[now]:
            aid, kind, payload = action["id"], action["kind"], action["payload"]
            snapshots[(aid, "before")] = {key: deepcopy(atoms[key]) for key in action["atoms"] if key in atoms}
            duration = action["t_end_us"] - now
            timing_key = "cz" if kind == "gate" and payload.get("name") == "CZ" else "gate_1q" if kind == "gate" else "classical" if kind == "rebind" else kind
            if timing_key in device["timings_us"] and duration < device["timings_us"][timing_key] - EPS:
                audit.fail("timing", "DURATION_LOWER_BOUND", "Action shorter than the declared device primitive", action_id=aid)
            if kind in ("pickup", "drop"):
                for record in transfer_records(action):
                    atom=atoms[record['atom_id']]
                    expected="SLM" if kind=='pickup' else 'AOD'
                    if atom['carrier']!=expected or atom['trap_id']!=record['from_trap_id'] or atom['aod_group']!=record['aod_group']:
                        audit.fail('geometry','TRANSFER_BINDING','Transfer source carrier/trap/group does not match live state',action_id=aid,resource=record['atom_id'])
                    if math.dist(atom['position_um'],record['position_um'])>EPS:
                        audit.fail('geometry','TRANSFER_TELEPORT','Transfer position differs from current atom',action_id=aid,resource=record['atom_id'])
                    if kind=='drop':
                        target=traps.get(record['to_trap_id'])
                        if not target or target['occupant'] not in (None,atom['atom_id']) or math.dist(target['position_um'],atom['position_um'])>EPS:
                            audit.fail('geometry','DROP_TARGET','Drop target absent, occupied, or not aligned',action_id=aid,resource=record['atom_id'])
                        if any(atom[k]!=record[k] for k in ('row_id','column_id')):
                            audit.fail('geometry','TRANSFER_AXIS','Drop axes differ from live state',action_id=aid,resource=record['atom_id'])
                    elif record['row_id'] is None or record['column_id'] is None:
                        audit.fail('geometry','TRANSFER_AXIS','Pickup requires explicit axes',action_id=aid)
                    if kind=='pickup' and any(other['carrier']=='AOD' and other['trap_id']==record['to_trap_id'] for other in atoms.values()):
                        audit.fail('geometry','PICKUP_OCCUPIED','Pickup target AOD trap is occupied',action_id=aid,resource=record['atom_id'])
            elif kind == "rebind":
                bindings = payload.get('site_bindings', [])
                old = {atoms[a].get('site_id', atoms[a]['qubit_id']) for a in action['atoms']}
                if ('rebind' not in device['operations']['action_kinds'] or action['condition'] is not None or
                        payload.get('quantum_effect') != 'none' or payload.get('reads') or payload.get('writes') or
                        len(bindings) != len(action['atoms']) or {b['atom_id'] for b in bindings} != set(action['atoms']) or
                        {b['from_site_id'] for b in bindings} != old or {b['to_site_id'] for b in bindings} != old):
                    audit.fail('geometry', 'SITE_PERMUTATION_BIJECTION', 'Invalid code-site binding commit', action_id=aid)
                for b in bindings:
                    resident = atoms[b['atom_id']]
                    if (resident.get('site_id', resident['qubit_id']) != b['from_site_id'] or resident['carrier'] != 'SLM' or
                            resident['trap_id'] != b['destination_trap_id'] or site_homes.get(b['to_site_id']) != resident['trap_id'] or
                            math.dist(resident['position_um'], b['position_um']) > EPS):
                        audit.fail('geometry', 'SITE_PERMUTATION_NOT_TRANSPORTED', 'Atom did not physically reach the destination site', action_id=aid)
            elif kind == "move":
                if payload["interpolation"] != "linear":
                    audit.need("geometry", "TRAJECTORY_MODEL", "Only explicit linear trajectories are checked")
                    continue
                listed = [tr["atom_id"] for tr in payload["trajectories"]]
                if len(listed) != len(set(listed)) or set(listed) != set(action["atoms"]):
                    audit.fail("geometry", "TRAJECTORY_COVERAGE", "Action atoms and explicit trajectories differ", action_id=aid)
                for tr in payload["trajectories"]:
                    atom = atoms[tr["atom_id"]]
                    if not _point(tr["from_um"]) or not _point(tr["to_um"]):
                        raise ValueError("trajectory endpoints must be finite coordinate pairs")
                    if atom["carrier"] != "AOD" or atom["aod_group"] != payload["aod_group"] or any(atom[k] != tr[k] for k in ("row_id", "column_id")):
                        audit.fail("geometry", "MOVE_BINDING", "Motion violates AOD carrier or axis binding", action_id=aid, resource=tr["atom_id"])
                    if math.dist(atom["position_um"], tr["from_um"]) > EPS:
                        audit.fail("geometry", "MOVE_TELEPORT", "Motion start is not current position", action_id=aid, resource=tr["atom_id"])
                    if max(abs(a-b) for a,b in zip(tr["from_um"], tr["to_um"])) > duration * device["movement"]["speed_um_per_us"] + EPS:
                        audit.fail("geometry", "MOVE_SPEED", "Axis motion exceeds device speed", action_id=aid, resource=tr["atom_id"])
            elif kind == "measure":
                if payload.get("basis") != "Z":
                    audit.need("geometry", "MEASUREMENT_BASIS", "Only Z readout is checked")
                for key in action["atoms"]:
                    if not inside(atoms[key]["position_um"], device["zones"][device["measurement"]["zone_id"]]):
                        audit.fail("geometry", "MEASUREMENT_ZONE", "Readout atom is outside measurement zone", action_id=aid, resource=key)
                if payload["result_ready_us"] < action["t_end_us"] + device["timings_us"]["result_latency"] - EPS:
                    audit.fail("timing", "RESULT_LATENCY", "Result available before device readout latency", action_id=aid)
            elif kind == "reset":
                if payload.get("state") != 0:
                    audit.fail("geometry", "RESET_STATE", "Only reset to zero is supported", action_id=aid)
                for key in action["atoms"]:
                    if not any(inside(atoms[key]["position_um"], device["zones"][z]) for z in device["reset"]["allowed_zone_ids"]):
                        audit.fail("geometry", "RESET_ZONE", "Reset outside permitted zones", action_id=aid, resource=key)
            elif kind == "gate" and payload.get("name") == "CZ":
                visible, expected = _pairs(atoms, bzone, device)
                degree = defaultdict(int)
                for first, second in expected:
                    degree[first] += 1
                    degree[second] += 1
                if any(value > 1 for value in degree.values()):
                    audit.fail("broadcast", "MULTIBODY_BROADCAST_UNSUPPORTED", "Geometric edges share an atom; native pairwise CZ profile does not validate this many-body pulse", action_id=aid)
                raw_pairs = payload["pairs"]
                actual = {tuple(sorted(pair)) for pair in raw_pairs}
                if payload.get("broadcast") is not True or payload.get("zone_id") != device["broadcast"]["zone_id"]:
                    audit.fail("broadcast", "BROADCAST_MODEL", "CZ must use the declared common broadcast zone", action_id=aid)
                if actual != expected or len(raw_pairs) != len(actual):
                    audit.fail("broadcast", "BROADCAST_PAIRS", f"Actual geometry gives {sorted(expected)}, declared {sorted(actual)}", action_id=aid)
                for key in visible:
                    counts[key] += 1
            if action["t_end_us"] > now:
                active[aid] = action
        if index + 1 == len(times):
            boundary = {key: atom["position_um"] for key, atom in atoms.items()}
            _axes(audit, atoms, boundary, boundary, f"boundary:{now}")
            break
        nxt = times[index + 1]
        p = {aid: atom["position_um"][:] for aid, atom in atoms.items()}
        q = deepcopy(p)
        for action in active.values():
            if action["kind"] != "move" or action["payload"].get("interpolation") != "linear":
                continue
            fraction = (nxt - action["t_start_us"]) / (action["t_end_us"] - action["t_start_us"])
            for tr in action["payload"]["trajectories"]:
                q[tr["atom_id"]] = [v + fraction*(w-v) for v,w in zip(tr["from_um"],tr["to_um"])]
        label = f"interval:{now}:{nxt}"
        _axes(audit, atoms, p, q, label)
        axis_users = defaultdict(set)
        for action in active.values():
            if action["kind"] not in ("pickup", "move", "drop"):
                continue
            for key in action["atoms"]:
                atom = atoms[key]
                for field in ("row_id", "column_id"):
                    line = next(r[field] for r in transfer_records(action) if r['atom_id']==key) if action["kind"] == "pickup" else atom[field]
                    if line is not None:
                        axis_users[(atom["aod_group"], field, line)].add(action["id"])
        for resource, owners in axis_users.items():
            if len(owners) > 1:
                audit.fail("resources", "AXIS_RESOURCE_OVERLAP", f"Shared axis used by simultaneous actions {sorted(owners)}", action_id=label, resource="/".join(map(str, resource)))
        for a, b in _swept_candidates(p, q):
            if _collision(p[a], q[a], p[b], q[b]):
                audit.fail("geometry", "ATOM_COLLISION", "Point atoms coincide during an interval", action_id=label, resource=f"{a},{b}")
        broadcasts = [a for a in active.values() if a["kind"] == "gate" and a["payload"].get("name") == "CZ"]
        if len(broadcasts) > 1:
            audit.fail("resources", "BROADCAST_OVERLAP", "Common illumination pulses overlap", action_id=label)
        for pulse in broadcasts:
            for key in atoms:
                if math.dist(p[key], q[key]) > EPS and _segment_enters(p[key], q[key], bzone):
                    audit.fail("broadcast", "BROADCAST_MOVING_ATOM", "An atom moves within or through the illumination zone", action_id=pulse["id"], resource=key)
            for other in active.values():
                if other["id"] == pulse["id"] or other["kind"] in ("wait", "classical"):
                    continue
                if any(inside(p[key], bzone) for key in other["atoms"]):
                    audit.fail("resources", "ILLUMINATED_ATOM_OVERLAP", "Another physical action overlaps the broadcast on an illuminated atom", action_id=other["id"], resource=pulse["id"])
        for aid in atoms:
            atoms[aid]["position_um"] = q[aid]
    audit.metrics["atom_count"] = len(atoms)
    audit.metrics["broadcast_count"] = sum(a["kind"] == "gate" and a["payload"].get("name") == "CZ" for a in plan["actions"])
    duration = audit.metrics.get("makespan_us")
    if plan.get("time_basis") == "absolute_session" or "session_binding" in plan:
        # A bound window starts at the committed frontier. Its first action may
        # wait for feedback; action-span makespan must not erase that interval.
        binding = plan["session_binding"]
        origin = binding["time_origin_us"]
        first = min((a["t_start_us"] for a in plan["actions"]), default=origin)
        end = max((a["t_end_us"] for a in plan["actions"]), default=origin)
        if (plan.get("time_basis") != "absolute_session" or not _finite(origin) or
                origin < 0 or origin > first or
                plan["initial_state"].get("time_us") != origin or
                binding["execution_context"].get("time_us") != origin):
            audit.fail("contract", "PLAN_TIME_ORIGIN", "Window origin must match initial state/context and precede all actions")
        duration = end - origin
        audit.metrics.update(window_duration_us=duration, leading_idle_us=first-origin)
        for key, expected in (("t_start_us", origin), ("t_end_us", end)):
            if key in plan.get("stats", {}) and plan["stats"][key] != expected:
                audit.fail("contract", "PLAN_STATS", f"Plan stats.{key} disagrees with the bound window")
    for key, expected in (("atom_count", len(atoms)), ("action_count", len(plan["actions"])), ("duration_us", duration)):
        if key in plan.get("stats", {}) and plan["stats"][key] != expected:
            audit.fail("contract", "PLAN_STATS", f"Plan stats.{key} disagrees with actual actions/identities")
    if "planned_illumination_counts" in plan.get("stats", {}) and plan["stats"]["planned_illumination_counts"] != counts:
        audit.fail("broadcast", "PLANNED_ILLUMINATION_COUNT", "Plan illumination totals disagree with reconstructed geometry")
    return {"atoms": atoms, "slm_traps": traps, "illumination_counts": counts, "snapshots": snapshots}
