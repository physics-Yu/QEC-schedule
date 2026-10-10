"""Pinned Enola SAPlacer over finite patch cells, bound to the R1 t=0 state."""
from __future__ import annotations

import ast
from collections import deque
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
import io
import math
from pathlib import Path
import random
import sys
import time

from .enola_kernel import COMMIT, LICENSE_SHA, StrategyError, digest

PLACER_SHA = "d256c84490bd72d525515f24acb081d7b21bcd5f7bbc31302a3bbf79a16997cf"
DEFAULT_BUDGET = {"max_iterations": 1000, "moves_per_iteration": 400,
                  "initial_moves": 100, "max_wall_seconds": 60., "max_moves": 400100}


def _budget(value):
    result = dict(DEFAULT_BUDGET)
    if value is not None:
        if not isinstance(value, dict) or set(value) - set(result):
            raise StrategyError("PLACEMENT_BUDGET", "Unknown placement budget fields")
        result.update(value)
    for name, val in result.items():
        valid = type(val) in (int, float) if name == "max_wall_seconds" else type(val) is int
        if not valid or not math.isfinite(val) or val <= 0:
            raise StrategyError("PLACEMENT_BUDGET", "Budget must be positive and finite", field=name)
    return result


def _source(root, seed):
    root = Path(root) if root else Path(__file__).resolve().parents[3] / "third_party/enola"
    if (root / "upstream").is_dir():
        root = root / "upstream"
    path = root / "enola/placer/placer.py"
    if not path.is_file() or not (root / "LICENSE").is_file():
        raise StrategyError("ENOLA_NOT_INSTALLED", "Pinned SAPlacer and license are required", path=str(root))
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != PLACER_SHA or sha256((root / "LICENSE").read_bytes()).hexdigest() != LICENSE_SHA:
        raise StrategyError("ENOLA_PIN_MISMATCH", "Placer or license differs from the fixed original source")
    tree = ast.parse(raw.decode("utf-8"), filename=str(path))
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SAPlacer"]
    if len(nodes) != 1:
        raise StrategyError("ENOLA_API_MISSING", "Pinned SAPlacer class was not found")
    rng = random.Random(seed)
    scope = {"sys": sys, "math": math, "randrange": rng.randrange, "shuffle": rng.shuffle, "uniform": rng.uniform}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
    provenance = {"repository": "https://github.com/UCLA-VAST/Enola", "commit": COMMIT,
                  "source_file": "enola/placer/placer.py", "source_sha256": PLACER_SHA,
                  "license": "BSD-3-Clause", "license_sha256": LICENSE_SHA,
                  "loading": "unmodified SAPlacer class AST from hash-verified full source; private RNG globals",
                  "called": ["SAPlacer.run", "SAPlacer.init_sa_solution", "SAPlacer.init_perturb",
                             "SAPlacer.make_movement", "SAPlacer.get_cost", "SAPlacer.update_temperature"],
                  "adaptations": ["explicit budget via initialize_param override", "private seeded RNG",
                                  "stop at frozen temperature if initial perturbation has no uphill move"],
                  "not_called": ["Enola.solve", "upstream codegen", "upstream simulator"]}
    return scope["SAPlacer"], provenance


def _cost(mapping, layers):
    return sum(max(1 - .1 * level, .1) * math.dist(mapping[a], mapping[b])
               for level, edges in enumerate(layers) for a, b in edges)


def _run_placer(shape, count, layers, seed, budget, root):
    base, provenance = _source(root, seed)
    start = time.perf_counter()

    class BoundedPlacer(base):
        def initialize_param(self):
            super().initialize_param()
            # Original loop breaks when sa_n > sa_iter_limit, after its iteration.
            self.sa_iter_limit = budget["max_iterations"] - 1
            self.sa_l = budget["moves_per_iteration"]
            self.sa_init_perturb_num = budget["initial_moves"]
            self.move_count = 0
            self.initial_mapping = None
            self.zero_uphill = False

        def make_movement(self, given_movement=False):
            if self.move_count >= budget["max_moves"] or time.perf_counter() - start >= budget["max_wall_seconds"]:
                raise StrategyError("PLACEMENT_BUDGET_EXHAUSTED", "Search interrupted; candidate is not a completed placement",
                                    complete=False, moves=self.move_count, iterations=self.sa_n,
                                    best_mapping=deepcopy(self.best_mapping), best_cost=self.best_cost,
                                    elapsed_seconds=time.perf_counter() - start, budget=budget)
            self.move_count += 1
            return super().make_movement(given_movement)

        def init_perturb(self):
            self.initial_mapping = deepcopy(self.current_mapping)
            try:
                super().init_perturb()
            except ZeroDivisionError:
                # The only division here is uphill_sum/uphill_cnt in this pinned method.
                # Its search movements and best solution have already been retained.
                self.zero_uphill = True
                self.sa_t = self.sa_t_frozen
                self.sa_t1 = self.sa_t_frozen

    placer = BoundedPlacer(l2=False)
    log = io.StringIO()
    with redirect_stdout(log):
        placer.run(tuple(shape), count, layers)
    best = [list(p) for p in placer.best_mapping]
    computed = _cost(best, layers)
    if not math.isclose(computed, placer.best_cost, rel_tol=1e-8, abs_tol=1e-8):
        raise StrategyError("ENOLA_COST_MISMATCH", "Independently recomputed cost disagrees with raw Enola output")
    return best, {**provenance, "raw_output": {"best_mapping": best, "best_cost": placer.best_cost,
                    "initial_mapping": [list(p) for p in placer.initial_mapping],
                    "effective_grid_shape": list(placer.chip_dim)}, "stdout": log.getvalue()}, {
                    "seed": seed, "budget": budget, "moves": placer.move_count, "iterations": placer.sa_n,
                    "wall_seconds": time.perf_counter() - start, "parallelism": 1,
                    "stop_reason": "no_initial_uphill" if placer.zero_uphill else (
                        "frozen_temperature" if placer.sa_t <= placer.sa_t_frozen else "iteration_budget"),
                    "complete": True, "optimality_proven": False}


def place_patches(patches, interactions, device, *, seed=0, grid_shape=None, budget=None, enola_root=None, resource_inventory=None):
    """Optimize patch anchors with real Enola; return placement plus actual R1 initial state.

    Each interaction is {node_id, patch_operands:[control,target], layer:int}.
    Repeated edges retain multiplicity. Only the symmetric distance objective projects
    operand order; the original directed interaction records remain in the result.
    """
    from na_pipeline.device import patch_geometry, build_preinitialized_state, validate_preinitialized_state

    if not isinstance(patches, dict) or not patches or any(not isinstance(p, str) or not p for p in patches):
        raise StrategyError("PATCH_INPUT", "Expected a nonempty stable patch-ID mapping")
    if type(seed) is not int:
        raise StrategyError("PLACEMENT_SEED", "Seed must be an explicit integer")
    if not isinstance(interactions, list):
        raise StrategyError("PATCH_INTERACTIONS", "Expected a list of complete interaction records")
    ids = list(patches)
    indices = {p: i for i, p in enumerate(ids)}
    layers = []
    seen = set()
    for edge in interactions:
        if not isinstance(edge, dict) or set(edge) != {"node_id", "patch_operands", "layer"}:
            raise StrategyError("PATCH_INTERACTIONS", "Unknown or missing interaction fields")
        pair, level = edge["patch_operands"], edge["layer"]
        if (not isinstance(edge["node_id"], str) or not edge["node_id"] or edge["node_id"] in seen or
            not isinstance(pair, list) or len(pair) != 2 or any(p not in indices for p in pair) or pair[0] == pair[1] or
            type(level) is not int or level < 0):
            raise StrategyError("PATCH_INTERACTIONS", "Interaction ID, operands or depth is invalid", interaction=edge)
        seen.add(edge["node_id"])
        while len(layers) <= level:
            layers.append([])
        layers[level].append([indices[p] for p in pair])
    geometry = patch_geometry(device)
    step = max(geometry["cell_extent_um"])
    if grid_shape is None:
        nx = math.ceil(math.sqrt(len(ids)))
        grid_shape = [nx, math.ceil(len(ids) / nx)]
    if (not isinstance(grid_shape, (list, tuple)) or len(grid_shape) != 2 or
        any(type(x) is not int or x <= 0 for x in grid_shape) or math.prod(grid_shape) < len(ids)):
        raise StrategyError("PLACEMENT_DOMAIN", "Finite grid must fit every patch")
    shape = list(grid_shape)
    # Match the upstream finite-domain clipping, then prove the entire embedded domain legal.
    upstream_length = int(math.sqrt(len(ids))) + 4
    effective = [min(v, upstream_length) for v in shape]
    if math.prod(effective) < len(ids):
        effective = shape
    orientation = "x_vertical_z_horizontal"
    zone = device["zones"]["storage_entanglement"]
    origin = [zone[f"{axis}_range_um"][0] or 0. for axis in ("x", "y")]
    bounds = geometry["occupied_bounds_um"]
    for axis in (0, 1):
        lo, hi = zone[f"{'xy'[axis]}_range_um"]
        maximum = origin[axis] + step * (effective[axis] - 1) + bounds[axis + 2]
        if (lo is not None and origin[axis] + bounds[axis] < lo) or (hi is not None and maximum > hi):
            raise StrategyError("PLACEMENT_DOMAIN", "Entire search domain must fit EZ", axis=axis, maximum=maximum, zone=zone)
    config = _budget(budget)
    baseline = [[i // effective[1], i % effective[1]] for i in range(len(ids))]
    if interactions:
        mapping, enola, search = _run_placer(shape, len(ids), layers, seed, config, enola_root)
    else:
        mapping = baseline
        _, enola = _source(enola_root, seed)
        enola.update(called=[], raw_output=None, stdout="")
        search = {"seed": seed, "budget": config, "moves": 0, "iterations": 0, "wall_seconds": 0.,
                  "parallelism": 1, "stop_reason": "trivial_no_interactions", "complete": True, "optimality_proven": True}
    placements = {p: {"anchor_um": [origin[a] + step * mapping[i][a] for a in (0, 1)],
                      "orientation": orientation} for i, p in enumerate(ids)}
    cost = {"model": "sum(max(1-0.1*layer,0.1)*Euclidean_cell_distance)",
            "baseline_mapping": baseline, "baseline": _cost(baseline, layers), "candidate": _cost(mapping, layers),
            "units": "weighted_cells", "uniform_cell_step_um": step,
            "candidate_weighted_distance_um": step * _cost(mapping, layers), "makespan_objective": False}
    body = {"device_hash": digest(device), "patches": deepcopy(patches), "interactions": deepcopy(interactions),
            "placements": placements, "cost": cost, "input": {"patch_index": ids, "layers": layers,
            "requested_grid_shape": shape, "effective_grid_shape": effective, "origin_um": origin},
            "seed": seed, "budget": config, "enola_source_sha256": PLACER_SHA,
            "adapter_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}
    if resource_inventory is not None:
        body["resource_inventory"] = deepcopy(resource_inventory)
    artifact_id = "patch-placement:" + digest(body)
    extra = {"resource_inventory": resource_inventory} if resource_inventory is not None else {}
    state = build_preinitialized_state(device, patches, placements,
             placement_ref={"artifact_id": artifact_id, "producer": "R4-Enola-SAPlacer", "fixture": False}, **extra)
    errors = validate_preinitialized_state(state, device)
    if errors:
        raise StrategyError("PLACEMENT_STATE_INVALID", "Actual R1 t=0 state did not validate", errors=errors)
    return {"schema_version": "patch-placement/0.1", "artifact_id": artifact_id, **body,
            "initial_state": state, "enola": enola, "search": search,
            "evidence_scope": {"backend_used": "enola_sa_patch_placement" if interactions else "trivial_placement",
               "entry_mode": "preinitialized", "fixture": state["provenance"].get("fixture", False), "quantum_state_simulation": False,
               "hardware_execution": False, "independent_validation": "pending_R6", "user_visual_acceptance": "pending"}}


def _logical_projection(logical_dag):
    from na_pipeline.frontend import validate_logical_dag, patch_interaction_graph
    errors = validate_logical_dag(logical_dag)
    if errors:
        raise StrategyError("INVALID_LOGICAL_DAG", "R2 public validation rejected input", errors=errors)
    if logical_dag.get("schema_version") != "LogicalDAG/0.1.0":
        raise StrategyError("LOGICAL_DAG_VERSION", "Unsupported R2 schema")
    nodes = {n["id"]: n for n in logical_dag["nodes"]}
    parents = {n: set() for n in nodes}
    children = {n: set() for n in nodes}
    for edge in logical_dag["edges"]:
        parents[edge["target"]].add(edge["source"])
        children[edge["source"]].add(edge["target"])
    degree = {n: len(p) for n, p in parents.items()}
    queue = deque(n for n in nodes if not degree[n])
    depths = {}
    while queue:
        n = queue.popleft()
        depths[n] = max((depths[p]+1 for p in parents[n]), default=0)
        for c in sorted(children[n]):
            degree[c] -= 1
            if not degree[c]:
                queue.append(c)
    if len(depths) != len(nodes):
        raise StrategyError("LOGICAL_DAG_CYCLE", "No topological depth exists")
    graph = patch_interaction_graph(logical_dag)
    interactions = []
    for edge in graph["edges"]:
        for item in edge["interactions"]:
            node = nodes[item["node_id"]]
            roles = ["control", "target"] if node["operation"] == "CX" else ["left", "right"]
            interactions.append({"node_id": node["id"], "patch_operands": [node["patch_operands"][r] for r in roles],
                                 "layer": depths[node["id"]]})
    return interactions, graph, depths


def place_logical_dag(logical_dag, device, **options):
    """Consume the complete public R2 LogicalDAG/0.1.0 without reading fake branches."""
    interactions, graph, depths = _logical_projection(logical_dag)
    patches = {p["patch_id"]: {"aod_group": "data", "basis": p["initial_state"]["logical_basis"],
                               "value": p["initial_state"]["logical_value"]} for p in logical_dag["patches"]}
    result = place_patches(patches, interactions, device, **options)
    result["logical_dag_ref"] = {"artifact_id": logical_dag["artifact_id"], "sha256": digest(logical_dag)}
    result["interaction_graph"] = graph
    result["projection"] = {"depths": depths, "layer_policy": "longest dependency path from all typed R2 edges",
                            "aod_assignment": "algorithm patches use declared device data AOD", "branch_filtering": False}
    return result


def place_resource_requirements(logical_dag, requirements, device, **options):
    """Include every declared R3/R5 carrier in one actual t=0 world.

    The current distance objective covers the complete R2 logical interaction
    graph; internal factory protocol distance is explicitly not optimized yet.
    Every factory patch still participates in the same finite placement domain.
    """
    from na_pipeline.runtime.resource_pool import resource_inventory, FiniteResourcePool
    if requirements.get("schema_version") != "PhysicalResourceRequirements/0.1.0":
        raise StrategyError("RESOURCE_REQUIREMENTS_VERSION", "R3 complete resource requirements required")
    interactions, graph, depths = _logical_projection(logical_dag)
    patches = {p: {k: r[k] for k in ("aod_group", "basis", "value")} for p, r in requirements["patches"].items()}
    if {p["patch_id"] for p in logical_dag["patches"]} != {p for p, r in requirements["patches"].items() if r["role"] == "algorithm"}:
        raise StrategyError("RESOURCE_ALGORITHM_COVERAGE", "Finite pool must preserve all and only the source algorithm patches")
    shape = options.get("grid_shape")
    if shape is None:
        nx = math.ceil(math.sqrt(len(patches)))
        shape = [nx, math.ceil(len(patches)/nx)]
        options["grid_shape"] = shape
    step = max(device["patch_geometry"]["cell_extent_um"])
    origin_x = device["zones"]["storage_entanglement"]["x_range_um"][0] or 0.
    origin_y = device["zones"]["storage_entanglement"]["y_range_um"][0] or 0.
    # A declared probe service lane lies beyond the entire searched patch domain,
    # so it cannot silently occupy a cell later selected by SA.
    nonpatch_positions = {r["physical_qubit_id"]: [origin_x + step*(shape[0]+1+i), origin_y]
                         for i, r in enumerate(requirements["nonpatch_atoms"])}
    position_ref = {"artifact_id": "R4-nonpatch-layout:"+digest({"requirements": requirements, "positions": nonpatch_positions}), "fixture": False}
    inventory = resource_inventory(requirements, nonpatch_positions, placement_ref=position_ref)
    result = place_patches(patches, interactions, device, resource_inventory=inventory, **options)
    pool = FiniteResourcePool(requirements, result["initial_state"])
    result["logical_dag_ref"] = {"artifact_id": logical_dag["artifact_id"], "sha256": digest(logical_dag)}
    result["interaction_graph"] = graph
    result["resource_requirements"] = deepcopy(requirements)
    result["resource_pool"] = pool.snapshot()
    result["nonpatch_placement"] = {"positions": nonpatch_positions, "method": "declared service lane outside all patch cells",
                                    "original_resource_roles": deepcopy(requirements["nonpatch_atoms"]),
                                    "role_mapping": {"syndrome": "probe"}, "quantum_state_prepared_by_placement": False}
    result["projection"] = {"depths": depths, "layer_policy": "longest dependency path from all typed R2 edges", "branch_filtering": False,
                            "complete_carrier_inventory": True, "objective_scope": "R2 logical interactions; internal factory distances not yet optimized"}
    return result
