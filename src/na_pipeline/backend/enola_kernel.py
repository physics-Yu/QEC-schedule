"""Pinned original Enola compatibility/MIS functions used in actual decisions.

Project constraints include full capture closure, broadcast graph and continuous
point/empty-intersection sweeps. This is explicitly not the Enola.solve wrapper.
"""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from itertools import combinations, product
import json
import math
from pathlib import Path

from .geometry import EPS, _collision, broadcast_pairs, in_zone, validate_cz_pairs

COMMIT = "2944dbf4e163e8d2eeeec607add0d9139edce689"
ROUTER_SHA = "a75e92353a74b6f3597a33b214d358b0782de2fa60400362c5e1967646cecb82"
LICENSE_SHA = "a8663338fce27cf0e5da614f04d0b72e7559b31bcd41b6b115572d1d8df985f0"


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class StrategyError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(f"{code}: {message}")
        self.code, self.details = code, details

    def to_dict(self):
        return {"code": self.code, "message": str(self), "details": self.details}


class EnolaKernel:
    def __init__(self, root=None):
        root = Path(root) if root else Path(__file__).resolve().parents[3] / "third_party/enola"
        if (root / "upstream").is_dir():
            root = root / "upstream"
        path = root / "enola/router/router_mis.py"
        if not path.is_file() or not (root / "LICENSE").is_file():
            raise StrategyError("ENOLA_NOT_INSTALLED", "R7 pinned source is required; no fallback", path=str(root))
        raw, license_raw = path.read_bytes(), (root / "LICENSE").read_bytes()
        if sha256(raw).hexdigest() != ROUTER_SHA or sha256(license_raw).hexdigest() != LICENSE_SHA:
            raise StrategyError("ENOLA_PIN_MISMATCH", "Consumed router or license differs from audited pin")
        tree = ast.parse(raw.decode("utf-8"), filename=str(path))
        names = {"compatible_2D", "maximalis_solve_sort"}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        if {n.name for n in nodes} != names:
            raise StrategyError("ENOLA_API_MISSING", "Pinned functions not found")
        scope = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
        self.compatible = scope["compatible_2D"]
        self.solve = scope["maximalis_solve_sort"]
        self.provenance = {"backend_used": "enola_function_kernel", "repository": "https://github.com/UCLA-VAST/Enola",
                           "commit": COMMIT, "source_file": "enola/router/router_mis.py", "source_sha256": ROUTER_SHA,
                           "license": "BSD-3-Clause", "license_sha256": LICENSE_SHA,
                           "functions": {n.name: [n.lineno, n.end_lineno] for n in nodes},
                           "loading": "exact unmodified function AST from hash-verified complete upstream file",
                           "not_called": ["Enola.solve", "upstream codegen", "upstream simulator"]}
        self.calls = Counter()
        self.receipts = []

    def select(self, candidates, extra_conflicts=()):
        edges = set(tuple(sorted(e)) for e in extra_conflicts)
        for i, a in enumerate(candidates):
            for j in range(i + 1, len(candidates)):
                b = candidates[j]
                self.calls["compatible_2D"] += 1
                compatible = self.compatible(a["vector"], b["vector"])
                if (not compatible or a["op_id"] == b["op_id"] or
                        set(a["pair"]) & set(b["pair"]) or a["aod_group"] != b["aod_group"]):
                    edges.add((i, j))
        edges = sorted(edges)
        selected = self.solve(len(candidates), edges)
        self.calls["maximalis_solve_sort"] += 1
        receipt = {"input_hash": digest(candidates), "candidates": deepcopy(candidates),
                   "conflicts": [list(e) for e in edges], "selected_indices": selected,
                   "selected_op_ids": [candidates[i]["op_id"] for i in selected], "action_ids": []}
        receipt["decision_hash"] = digest(receipt)
        self.receipts.append(receipt)
        return [candidates[i] for i in selected], receipt


def capture_closure(atoms, selected, *, tolerance=EPS):
    byid = {a["atom_id"]: a for a in atoms}
    xs = sorted({byid[a]["position_um"][0] for a in selected})
    ys = sorted({byid[a]["position_um"][1] for a in selected})
    captured = sorted(a["atom_id"] for a in atoms if a["carrier"] == "SLM" and
                      any(abs(a["position_um"][0]-x) <= tolerance for x in xs) and
                      any(abs(a["position_um"][1]-y) <= tolerance for y in ys))
    return {"x_um": xs, "y_um": ys, "captured_atoms": captured,
            "intersections_um": [list(p) for p in product(xs, ys)]}


def check_group_segment(atoms, movers, goals):
    """Analytic full Cartesian sweep, including empty dynamic intersections."""
    byid = {a["atom_id"]: a for a in atoms}
    maps = [{}, {}]
    for aid in movers:
        for axis in (0, 1):
            start, end = byid[aid]["position_um"][axis], goals[aid][axis]
            if start in maps[axis] and abs(maps[axis][start]-end) > EPS:
                return "SHARED_AXIS"
            maps[axis][start] = end
    for mapping in maps:
        ordered = sorted(mapping)
        if any(mapping[b]-mapping[a] <= EPS for a, b in zip(ordered, ordered[1:])):
            return "AXIS_CROSSING"
    stationary = [a["position_um"] for a in atoms if a["atom_id"] not in movers]
    for x, y in product(maps[0], maps[1]):
        end = [maps[0][x], maps[1][y]]
        if any(_collision([x, y], end, p, p) for p in stationary):
            return "CARTESIAN_SWEEP_CAPTURE"
    return None


def group_route(atoms, goals, pitch):
    """Bounded route search whose segments preserve the selected Enola axes."""
    movers = list(goals)
    starts = {a["atom_id"]: a["position_um"] for a in atoms if a["atom_id"] in goals}
    candidates = [[goals]]
    for axis in (0, 1):
        mid = {a: [goals[a][i] if i == axis else starts[a][i] for i in (0, 1)] for a in movers}
        candidates.append([mid, goals])
    for dx, dy in ((.5, .25), (-.5, .25), (.5, -.25), (-.5, -.25), (1.5, .75), (-1.5, -.75)):
        mid = {a: [starts[a][0]+dx*pitch, starts[a][1]+dy*pitch] for a in movers}
        candidates.append([mid, goals])
    reasons = Counter()
    for points in candidates:
        scene = deepcopy(atoms); path = []
        for target in points:
            if all(math.dist(a["position_um"], target[a["atom_id"]]) <= EPS for a in scene if a["atom_id"] in target):
                continue
            reason = check_group_segment(scene, movers, target)
            if reason:
                reasons[reason] += 1
                break
            path.append(deepcopy(target))
            for a in scene:
                if a["atom_id"] in target:
                    a["position_um"] = list(target[a["atom_id"]])
        else:
            return path, dict(reasons)
    raise StrategyError("GROUP_ROUTE_SEARCH_EXHAUSTED", "Finite candidates exhausted; not an infeasibility proof", reasons=dict(reasons), candidates=len(candidates))
