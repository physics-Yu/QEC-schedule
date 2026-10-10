"""Substitution and full-scene checks only: never calls Enola or route search."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from .enola_kernel import StrategyError, capture_closure, check_group_segment, digest
from .geometry import EPS, broadcast_pairs, in_zone, validate_cz_pairs


def require(ok, code, message, **details):
    if not ok:
        raise StrategyError(code, message, **details)


def bind(strategy, binding, device):
    from na_pipeline.qec import iter_physical_ops
    from na_pipeline.device import group_layout
    from .strategy import compiler_identity
    require(strategy.get("schema_version") == "compiled-logical-strategy/0.1" and
            digest(strategy.get("body")) == strategy.get("strategy_hash"), "STRATEGY_HASH_MISMATCH", "Body integrity failed")
    body = strategy["body"]
    require(body["device_hash"] == digest(device), "STRATEGY_DEVICE_MISMATCH", "Device changed; do not reuse this strategy")
    require(body["compiler_identity"] == compiler_identity(), "STRATEGY_COMPILER_MISMATCH", "Compiler rules changed")
    require(binding.get("schema_version") == "logical-call-binding/0.1", "BINDING_SCHEMA", "Expected logical-call-binding/0.1")
    required = {"schema_version", "call_id", "run_id", "epoch", "start_time_us", "qubit_bindings", "atom_bindings", "offset_um", "world_state", "resource_leases"}
    require(set(binding) == required, "BINDING_FIELDS", "Only documented binding fields are supported")
    call, run = binding["call_id"], binding["run_id"]
    require(isinstance(call, str) and re.fullmatch(r"[A-Za-z0-9_.:-]+", call) is not None, "CALL_ID_FORMAT", "Call ID must fit the physical template namespace")
    require(isinstance(run, str) and run and type(binding["epoch"]) is int and binding["epoch"] >= 0, "BINDING_IDENTITY", "Explicit run and epoch required")
    start, offset = binding["start_time_us"], binding["offset_um"]
    require(type(start) in (int, float) and math.isfinite(start) and start >= 0, "CALL_TIME", "Start must be finite and nonnegative")
    require(isinstance(offset, (list, tuple)) and len(offset) == 2 and all(type(v) in (int, float) and math.isfinite(v) for v in offset), "LAYOUT_TRANSFORM", "Only finite translations are supported")
    try:
        for layout_id in device["grouped_profile"]["layouts"]:
            group_layout(device, layout_id, offset_um=offset)
    except ValueError as exc:
        raise StrategyError("LAYOUT_TRANSFORM_OUT_OF_ZONE", "Translated complete-cycle profiles must fit the device", error=str(exc)) from exc
    qmap, amap = binding["qubit_bindings"], binding["atom_bindings"]
    formal = body["physical_program"]; relative = body["atom_program"]
    require(set(qmap) == {q["id"] for q in formal["qubits"]} and len(set(qmap.values())) == len(qmap), "QUBIT_BINDING", "All formal qubits require injective bindings")
    require(set(amap) == {a["atom_id"] for a in relative["initial_state"]["atoms"]} and len(set(amap.values())) == len(amap), "ATOM_BINDING", "All formal atoms require injective bindings")
    world = deepcopy(binding["world_state"])
    require(start + EPS >= world.get("time_us", 0), "CALL_TIME_REWIND", "Cannot rewrite committed history")
    atoms = {a["atom_id"]: a for a in world["atoms"]}
    require(set(amap.values()) <= atoms.keys(), "MISSING_CARRIER", "Bound carrier absent from full world")
    for expected in relative["initial_state"]["atoms"]:
        actual = atoms[amap[expected["atom_id"]]]
        goal = [v+d for v, d in zip(expected["position_um"], offset)]
        require(actual["qubit_id"] == qmap[expected["qubit_id"]] and actual["carrier"] == expected["carrier"] and
                actual["aod_group"] == expected["aod_group"] and math.dist(actual["position_um"], goal) <= EPS and
                actual["row_id"] == expected["row_id"] and actual["column_id"] == expected["column_id"],
                "STRATEGY_ENTRY_MISMATCH", "No implicit teleport, carrier switch or data reset", atom_id=actual["atom_id"])
    used_groups = {a["aod_group"] for a in relative["initial_state"]["atoms"]}
    require(not any(a["carrier"] == "AOD" and a["aod_group"] in used_groups for a in world["atoms"]),
            "ACTIVE_AOD_ENTRY_UNSUPPORTED", "This complete primitive entry requires its AOD groups unoccupied")
    require(not any(line["aod_group"] in used_groups for axis in ("aod_rows", "aod_columns") for line in world[axis]),
            "ACTIVE_AOD_ENTRY_UNSUPPORTED", "Even empty active lines must be explicitly released before this strategy entry")
    # The R3 primitive is a single formal call; using call_id as that ID makes
    # every resulting operation/result begin with call_id/ without invalid '/' in
    # local template IDs. Keep exact source topology and parameter bodies.
    require(len(formal["body"]) == 1 and formal["body"][0]["kind"] == "call" and formal["body"][0]["repeat"] == 1,
            "FORMAL_STRATEGY_STRUCTURE", "First strategy binder expects one complete primitive call")
    physical = deepcopy(formal)
    physical["artifact_id"] = f"bound-physical:{run}:{call}"
    physical["provenance"].update(binding_scope="instance", run_id=run, call_id=call, epoch=binding["epoch"], strategy_hash=strategy["strategy_hash"])
    physical["body"][0]["id"] = call
    physical["body"][0]["bindings"] = {k: qmap[v] for k, v in formal["body"][0]["bindings"].items()}
    physical["body"][0]["source_ids"] += [run, call]
    for q in physical["qubits"]:
        q["id"] = qmap[q["id"]]; q["formal"] = False
    original_ops, bound_ops = list(iter_physical_ops(formal)), list(iter_physical_ops(physical))
    opmap = {a["id"]: b["id"] for a, b in zip(original_ops, bound_ops)}
    resultmap = {x: y for a, b in zip(original_ops, bound_ops) for x, y in zip(a["writes"], b["writes"])}
    actionmap = {a["id"]: call+"/"+a["id"] for a in relative["actions"]}
    traps = {t["trap_id"]: t for t in world["slm_traps"]}
    require(len(atoms) == len(world["atoms"]) and len(traps) == len(world["slm_traps"]), "WORLD_IDENTITIES", "World identity lists contain duplicates")
    for atom in world["atoms"]:
        if atom["carrier"] == "SLM":
            trap = traps.get(atom["trap_id"])
            require(trap is not None and trap["occupant"] == atom["atom_id"] and math.dist(trap["position_um"], atom["position_um"]) <= EPS,
                    "WORLD_TRAP_BINDING", "SLM world occupancy is inconsistent", atom_id=atom["atom_id"])
    trapmap = {}
    for trap in relative["initial_state"]["slm_traps"]:
        target = [v+d for v, d in zip(trap["position_um"], offset)]
        matching = [t for t in traps.values() if math.dist(t["position_um"], target) <= EPS and t["zone_id"] == trap["zone_id"]]
        require(len(matching) <= 1, "AMBIGUOUS_STATIC_SITE", "Multiple SLM identities occupy one physical site")
        if matching:
            actual = matching[0]
        else:
            tid = call+"/"+trap["trap_id"]
            actual = {"trap_id": tid, "position_um": target, "zone_id": trap["zone_id"], "occupant": None}
            traps[tid] = actual
        trapmap[trap["trap_id"]] = actual["trap_id"]
    world["slm_traps"] = list(traps.values())
    idmap = {**qmap, **amap, **opmap, **resultmap, **actionmap, **trapmap}
    idmap[formal["artifact_id"]] = physical["artifact_id"]
    idmap[formal["body"][0]["id"]] = call
    for block in body["strategy_contract"]["operation"]["formal_operands"]:
        members = [amap[a["atom_id"]] for a in relative["initial_state"]["atoms"] if
                   next(q["block_id"] for q in formal["qubits"] if q["id"] == a["qubit_id"]) == block]
        idmap["bank:"+block] = "bank:"+digest(sorted(members))[:20]
    for action in relative["actions"]:
        gid = action["payload"].get("group_id")
        if gid is not None: idmap[gid] = call+"/"+gid
    # Dynamic trap and axis names are also instance-scoped, while the AOD group
    # and global Rydberg resource intentionally remain shared across calls.
    for action in relative["actions"]:
        payload = action["payload"]
        records = payload.get("bindings", []) + payload.get("trajectories", [])
        for record in records:
            for key in ("row_id", "column_id", "from_trap_id", "to_trap_id"):
                value = record.get(key)
                if value is not None and value not in idmap:
                    idmap[value] = call+"/"+value
    pattern = re.compile("|".join(re.escape(k) for k in sorted(idmap, key=len, reverse=True)))
    def text_replace(value):
        if value in idmap: return idmap[value]
        # Resources include IDs as suffixes; source provenance strings are not
        # rewritten unless they match an exact formal identity.
        if value.startswith(("atom:", "trap:", "aod:", "readout-site:")):
            return pattern.sub(lambda m: idmap[m.group()], value)
        return value
    abs_times = {"t_start_us", "t_end_us", "result_ready_us", "earliest_ready_us", "start_us", "end_us"}
    def replace(value, key=None):
        if isinstance(value, str): return text_replace(value)
        if key in {"position_um", "from_um", "to_um"} and isinstance(value, list):
            return [v+d for v, d in zip(value, offset)]
        if key == "earliest_readout_us" and isinstance(value, dict):
            return {text_replace(k): v+start for k, v in value.items()}
        if isinstance(value, list): return [replace(v) for v in value]
        if isinstance(value, dict): return {text_replace(k): replace(v, k) for k, v in value.items()}
        if key in abs_times and isinstance(value, (int, float)): return value+start
        return value
    physical["strategy_contract"] = replace(physical["strategy_contract"])
    physical["strategy_contract"].pop("contract_hash", None)
    physical["strategy_contract"]["physical_input_hash"] = digest({k: physical[k] for k in ("qubits", "templates", "body")})
    physical["strategy_contract"]["contract_hash"] = digest(physical["strategy_contract"])
    physical["input_hashes"] = {"physical_input": physical["strategy_contract"]["physical_input_hash"], "strategy_contract": physical["strategy_contract"]["contract_hash"]}
    atom_program = replace(relative)
    atom_program["artifact_id"] = f"bound-atom:{run}:{call}"
    atom_program["initial_state"] = deepcopy(world)
    atom_program["initial_state"]["time_us"] = start
    atom_program["input_hashes"] = {"device": digest(device), "physical_program": digest(physical)}
    atom_program["provenance"].update(call_id=call, run_id=run, epoch=binding["epoch"], strategy_hash=strategy["strategy_hash"],
                                      instance_binding=True, binding_search_calls=0)
    for action in atom_program["actions"]:
        action["source_ids"] = list(dict.fromkeys(action["source_ids"] + [run, call]))
    # Rebuild the entire background at each action boundary; physical semantics
    # of conditional 1q gates do not affect geometry. No fake values are read.
    scene = deepcopy(world)
    byatom = {a["atom_id"]: a for a in scene["atoms"]}
    bytrap = {t["trap_id"]: t for t in scene["slm_traps"]}
    zone = {"bounds_um": [device["zones"][device["broadcast"]["zone_id"]][k] for k in ("x_range_um", "y_range_um")]}
    checks = CounterLike()
    for action in sorted(atom_program["actions"], key=lambda a: (a["t_start_us"], a["id"])):
        payload, kind = action["payload"], action["kind"]
        if kind in {"pickup", "drop"}:
            bindings = payload["bindings"]
            require({b["atom_id"] for b in bindings} == set(action["atoms"]), "TRANSFER_MEMBERS", "Complete binding membership required")
            if kind == "pickup":
                closure = capture_closure(list(byatom.values()), action["atoms"], tolerance=device["geometry"]["distance_tolerance_um"])
                require(set(closure["captured_atoms"]) == set(action["atoms"]), "CAPTURE_CLOSURE_MISMATCH", "Background atom would be captured", closure=closure)
                payload["capture_closure"] = closure
                checks.add("capture_closure")
            for b in bindings:
                atom = byatom[b["atom_id"]]
                require(atom["trap_id"] == b["from_trap_id"] and math.dist(atom["position_um"], b["position_um"]) <= EPS,
                        "TRANSFER_ENTRY", "Transfer start no longer matches scene", atom_id=atom["atom_id"])
                if kind == "pickup":
                    require(atom["carrier"] == "SLM", "TRANSFER_CARRIER", "Pickup from non-SLM carrier")
                    bytrap[b["from_trap_id"]]["occupant"] = None
                    atom.update(carrier="AOD", trap_id=b["to_trap_id"], row_id=b["row_id"], column_id=b["column_id"])
                else:
                    require(atom["carrier"] == "AOD" and bytrap[b["to_trap_id"]]["occupant"] is None, "DROP_OCCUPANCY", "Target occupied or wrong carrier")
                    bytrap[b["to_trap_id"]]["occupant"] = atom["atom_id"]
                    atom.update(carrier="SLM", trap_id=b["to_trap_id"], row_id=None, column_id=None)
        elif kind == "move":
            targets = {t["atom_id"]: t["to_um"] for t in payload["trajectories"]}
            require(all(math.dist(byatom[t["atom_id"]]["position_um"], t["from_um"]) <= EPS for t in payload["trajectories"]), "MOVE_TELEPORT", "Wrong trajectory start")
            reason = check_group_segment(list(byatom.values()), list(targets), targets)
            require(reason is None, reason or "MOTION", "Bound full-world sweep failed")
            for aid, pos in targets.items(): byatom[aid]["position_um"] = list(pos)
            checks.add("full_cartesian_sweep")
        elif kind == "gate" and payload["name"] == "CZ":
            actual = broadcast_pairs(list(byatom.values()), zone, device["geometry"]["gate_pair_distance_um"], device["geometry"]["distance_tolerance_um"])
            require(not validate_cz_pairs(actual) and actual == sorted(sorted(p) for p in payload["pairs"]), "BROADCAST_WORLD_MISMATCH", "Background changes the physical pulse", all_pairs=actual)
            illuminated = sorted(a["atom_id"] for a in byatom.values() if in_zone(a["position_um"], zone))
            action["atoms"] = illuminated
            action["resources"] = sorted(set(action["resources"]) | {"atom:"+a for a in illuminated})
            checks.add("full_broadcast")
        for lease in binding["resource_leases"]:
            require(set(lease) <= {"resource_id", "t_start_us", "t_end_us", "action_id"} and {"resource_id", "t_start_us", "t_end_us"} <= lease.keys(),
                    "LEASE_SCHEMA", "Unknown resource lease fields")
            if lease["resource_id"] in action["resources"] and max(action["t_start_us"], lease["t_start_us"]) < min(action["t_end_us"], lease["t_end_us"])-EPS:
                raise StrategyError("RESOURCE_LEASE_CONFLICT", "Existing committed/reserved interval overlaps call", action_id=action["id"], lease=lease)
    scene["time_us"] = atom_program["stats"]["t_end_us"]
    atom_program["stats"]["atom_count"] = len(world["atoms"])
    return {"physical_program": physical, "atom_program": atom_program, "exit_state": scene,
            "binding_report": {"passed": True, "scope": "R4 static full-world composition preconditions, not R6 acceptance",
                "strategy_hash": strategy["strategy_hash"], "world_hash": digest(binding["world_state"]), "binding_hash": digest(binding),
                "call_id": call, "run_id": run, "epoch": binding["epoch"], "checks": dict(checks), "search_calls": 0,
                "result_bindings": resultmap, "source_bindings": opmap, "layout_transform": {"offset_um": list(offset), "orientation_changed": False}}}


class CounterLike(dict):
    def add(self, key):
        self[key] = self.get(key, 0)+1
