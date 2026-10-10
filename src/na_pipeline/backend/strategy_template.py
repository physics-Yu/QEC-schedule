"""Canonical physical identities and explicit complete-world reuse support domain."""
from copy import deepcopy
from hashlib import sha256
import math
from pathlib import Path

from .enola_kernel import StrategyError, digest
from .geometry import in_zone

ATOM_GEOMETRY = ("atom_id", "qubit_id", "site_id", "position_um", "carrier", "trap_id", "aod_group", "row_id", "column_id", "patch_id", "local_id")


def remap(value, mapping):
    if isinstance(value, str): return mapping.get(value, value)
    if isinstance(value, list): return [remap(v, mapping) for v in value]
    if isinstance(value, tuple): return [remap(v, mapping) for v in value]
    if isinstance(value, dict): return {mapping.get(k, k): remap(v, mapping) for k, v in value.items()}
    return value


def source_identity():
    root = Path(__file__).resolve().parents[1]
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for part in ("backend", "qec", "device") for p in sorted((root/part).glob("*.py"))}


def geometry_world(world, device):
    """Check every atom/site/occupied binding, excluding only runtime counters and time."""
    if world.get("aod_rows") or world.get("aod_columns") or any(a["carrier"] != "SLM" for a in world["atoms"]):
        raise StrategyError("STRATEGY_ACTIVE_AOD_UNSUPPORTED", "Compiled strategy supports an empty-AOD commit boundary only")
    atoms = [{k: deepcopy(a[k]) for k in ATOM_GEOMETRY if k in a} for a in world["atoms"]]
    by_id = {a["atom_id"]: a for a in atoms}
    if len(by_id) != len(atoms) or len({a["qubit_id"] for a in atoms}) != len(atoms):
        raise StrategyError("STRATEGY_WORLD_ALIAS", "Complete atom/qubit identities must be unique")
    traps = [{k: deepcopy(t[k]) for k in ("trap_id", "position_um", "zone_id", "occupant")} for t in world["slm_traps"]]
    by_trap = {t["trap_id"]: t for t in traps}
    if len(by_trap) != len(traps): raise StrategyError("STRATEGY_SITE_ALIAS", "Static site IDs must be unique")
    for t in traps:
        pos = t["position_um"]
        zone = device["zones"].get(t["zone_id"])
        if (not isinstance(pos, list) or len(pos) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in pos) or
            zone is None or not in_zone(pos, {"bounds_um": [zone["x_range_um"], zone["y_range_um"]]})):
            raise StrategyError("STRATEGY_SITE_GEOMETRY", "Every static site must retain legal declared geometry", trap_id=t["trap_id"])
        aid = t["occupant"]
        if aid is not None and (aid not in by_id or by_id[aid]["trap_id"] != t["trap_id"] or by_id[aid]["position_um"] != pos):
            raise StrategyError("STRATEGY_SITE_OCCUPANCY", "Full scene contains a mismatched occupied trap", trap_id=t["trap_id"])
    for a in atoms:
        if a["trap_id"] not in by_trap or by_trap[a["trap_id"]]["occupant"] != a["atom_id"] or by_trap[a["trap_id"]]["position_um"] != a["position_um"]:
            raise StrategyError("STRATEGY_ATOM_BINDING", "Every atom must match its actual SLM site", atom_id=a["atom_id"])
        if a["row_id"] is not None or a["column_id"] is not None or a["aod_group"] not in device["aod_groups"]:
            raise StrategyError("STRATEGY_ATOM_BINDING", "Unknown AOD group or stale active axes", atom_id=a["atom_id"])
    if len({tuple(a["position_um"]) for a in atoms}) != len(atoms):
        raise StrategyError("STRATEGY_ATOM_COLLISION", "Two atoms occupy the same point")
    clean = {"atoms": atoms, "slm_traps": traps, "aod_rows": [], "aod_columns": []}
    # Empty static sites are separately checked on every bind; unlike atoms or
    # active AOD intersections, new unoccupied SLM declarations do not obstruct
    # trajectories in the published point-atom model.
    support = {**clean, "slm_traps": [t for t in traps if t["occupant"] is not None]}
    return clean, support


def qualify_sites(template_entry, current_world):
    current = {t["trap_id"]: t for t in current_world["slm_traps"]}
    for t in template_entry["slm_traps"]:
        if t["trap_id"] in current and any(t[k] != current[t["trap_id"]][k] for k in ("position_um", "zone_id", "occupant")):
            raise StrategyError("STRATEGY_STATIC_SITE_CHANGED", "A strategy-referenced static site changed geometry or occupancy", trap_id=t["trap_id"])
        if t["trap_id"] not in current and t["occupant"] is not None:
            raise StrategyError("STRATEGY_OCCUPIED_SITE_MISSING", "An occupied entry site disappeared")


def canonical_dags(physical_dags):
    from na_pipeline.qec import validate_physical_dag
    dags = physical_dags if isinstance(physical_dags, list) else [physical_dags]
    if not dags: raise StrategyError("EMPTY_PHYSICAL_DAG_BATCH", "A nonempty strategy source is required")
    mapping, canonical, seen_qubits = {}, [], set()
    for di, dag in enumerate(dags):
        validate_physical_dag(dag)
        if any(dag.get(k, False) is not False for k in ("quantum_state_simulated", "hardware_executed", "loss_enabled")):
            raise StrategyError("STRATEGY_EVIDENCE_SCOPE", "Only compile/schedule DAG inputs are supported")
        used = {q for o in dag["nodes"] for q in o["qubits"]}
        if used & seen_qubits: raise StrategyError("JOINT_DAG_QUBIT_CONFLICT", "Strategy ready batch shares physical qubits")
        seen_qubits.update(used)
        mapping[dag["artifact_id"]] = f"template:dag:{di}"
        for oi, op in enumerate(dag["nodes"]):
            if op["id"] in mapping: raise StrategyError("STRATEGY_SOURCE_ALIAS", "Source operation IDs collide")
            mapping[op["id"]] = f"template:dag:{di}:op:{oi}"
        for ri, rid in enumerate(r for op in dag["nodes"] for r in op["writes"]):
            if rid in mapping: raise StrategyError("STRATEGY_RESULT_ALIAS", "Physical result IDs collide")
            mapping[rid] = f"template:dag:{di}:result:{ri}"
        for gi, group in enumerate(dag["groups"]): mapping[group["group_id"]] = f"template:dag:{di}:group:{gi}"
    local_results = {r for d in dags for o in d["nodes"] for r in o["writes"]}
    actual_external = list(dict.fromkeys(r for d in dags for o in d["nodes"] for r in o["reads"] if r not in local_results))
    for i, rid in enumerate(actual_external): mapping[rid] = f"template:input:{i}"
    for dag in dags:
        fields = ("schema_version", "entry_mode", "operation", "qubits", "nodes", "edges", "roots", "terminals", "groups", "result_producers")
        c = remap({k: deepcopy(dag[k]) for k in fields}, mapping)
        c["artifact_id"] = mapping[dag["artifact_id"]]
        c["provenance"] = {"owner": "R4", "fixture": bool(dag.get("provenance", {}).get("fixture")), "scope": "immutable compilation template only"}
        c.update(execution_kind="compile_plan", quantum_state_simulated=False, hardware_executed=False, loss_enabled=False,
                 execution_guard=None, external_reads=[mapping[r] for r in actual_external if any(r in o["reads"] for o in dag["nodes"])])
        for key in ("readout_services", "result_types", "entry_requirements", "code_profile"):
            if key in dag: c[key] = remap(deepcopy(dag[key]), mapping)
        for op in c["nodes"]: op["source_ids"] = [op["id"]]
        c["source_map"] = {o["id"]: {"physical_source_op_id": o["id"], "source_ids": [o["id"]]} for o in c["nodes"]}
        canonical.append(c)
    if len(set(mapping.values())) != len(mapping): raise StrategyError("STRATEGY_CANONICAL_ALIAS", "Canonical identity mapping must be injective")
    return dags, canonical, mapping
