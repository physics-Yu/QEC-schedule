"""Pinned Enola routing with immutable per-window conflict projection reuse."""
from copy import deepcopy
import time

from .enola_kernel import EnolaKernel, StrategyError, capture_closure, digest


class JointEnolaKernel(EnolaKernel):
    def __init__(self, root, atoms, tolerance, max_wall_seconds, *, independent_arrays=False):
        super().__init__(root)
        self.atoms = atoms
        self.tolerance = tolerance
        self.independent_arrays = independent_arrays
        self.deadline = time.perf_counter()+max_wall_seconds
        self.projections = {}
        self.provenance["constraint_adaptation"] = "pairwise operation/axis conflicts; capture closure and broadcast checked on the selected complete set"
        self.provenance["projection_reuse"] = {"scope": "same candidate set and exact compile-world geometry only", "builds": 0, "hits": 0, "max_retained_projections": 1}

    def select(self, candidates, extra_conflicts=()):
        if time.perf_counter() >= self.deadline:
            raise StrategyError("PHYSICAL_BUDGET_EXHAUSTED", "Joint route refinement exhausted wall budget", complete=False,
                                decisions=len(self.receipts), original_call_counts=dict(self.calls))
        # Try complete sets first. If their full-world qualification rejects a
        # set, refine with a conservative pairwise closure projection rather
        # than enumerating thousands of nearly identical unsafe supersets.
        conservative = bool(extra_conflicts)
        key = digest({"candidates": candidates, "world": list(self.atoms.values()), "capture_refinement": conservative})
        if key not in self.projections:
            self.projections.clear()
            self.provenance["projection_reuse"]["builds"] += 1
            edges = set()
            scene = list(self.atoms.values())
            pairwise_capture_rejections = 0
            for i, a in enumerate(candidates):
                for j in range(i+1, len(candidates)):
                    b = candidates[j]
                    if (a["op_id"] == b["op_id"] or set(a["pair"]) & set(b["pair"])):
                        edges.add((i, j)); continue
                    if a['aod_group'] != b['aod_group']:
                        # Independent deflectors do not share axes. Complete
                        # capture and continuous cross-group sweeps are checked
                        # by the joint batch planner before any action is emitted.
                        if not self.independent_arrays:edges.add((i,j))
                        continue
                    self.calls["compatible_2D"] += 1
                    if not self.compatible(a["vector"], b["vector"]):
                        edges.add((i, j)); continue
                    # Capture is a set constraint. Two diagonal atoms may pick
                    # up the other corners, while the complete rectangle is
                    # legal. The caller checks closure on the selected set.
                    if conservative:
                        movers = [a['mover'], b['mover']]
                        closure = capture_closure(scene, movers, tolerance=self.tolerance)
                        if set(closure['captured_atoms']) != set(movers):
                            edges.add((i, j)); pairwise_capture_rejections += 1
            self.projections[key] = (edges, pairwise_capture_rejections)
        else:
            self.provenance["projection_reuse"]["hits"] += 1
        base_edges, rejected = self.projections[key]
        edges = sorted(base_edges | {tuple(sorted(e)) for e in extra_conflicts})
        selected = self.solve(len(candidates), edges)
        self.calls["maximalis_solve_sort"] += 1
        receipt = {"input_hash": digest(candidates), "candidates": deepcopy(candidates), "projection_key": key,
                   "capture_selection_mode": "pairwise_refinement_after_full_set_rejection" if conservative else "complete_set_candidate",
                   "pairwise_capture_rejections": rejected, "conflicts": [list(e) for e in edges],
                   "selected_indices": selected, "selected_op_ids": [candidates[i]["op_id"] for i in selected], "action_ids": []}
        receipt["decision_hash"] = digest(receipt)
        self.receipts.append(receipt)
        return [candidates[i] for i in selected], receipt
