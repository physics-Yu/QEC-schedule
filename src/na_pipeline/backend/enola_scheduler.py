"""Actual pinned Enola gate scheduler, limited to dependency-ready physical gates."""
from __future__ import annotations

import ast
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from .enola_kernel import COMMIT, LICENSE_SHA, StrategyError, digest

SCHEDULER_SHA = "e5a77fb3980c4425f9aea5796d1fd28339359a14516fd4c9a5df25a26023d1e4"


class EnolaReadyScheduler:
    def __init__(self, root=None):
        root = Path(root) if root else Path(__file__).resolve().parents[3] / "third_party/enola"
        if (root / "upstream").is_dir():
            root = root / "upstream"
        path = root / "enola/scheduler/gate_scheduler.py"
        if not path.is_file() or not (root / "LICENSE").is_file():
            raise StrategyError("ENOLA_NOT_INSTALLED", "Pinned gate scheduler is required")
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != SCHEDULER_SHA or sha256((root / "LICENSE").read_bytes()).hexdigest() != LICENSE_SHA:
            raise StrategyError("ENOLA_PIN_MISMATCH", "Gate scheduler or license differs from fixed source")
        import rustworkx
        if rustworkx.__version__ != "0.17.1":
            raise StrategyError("ENOLA_DEPENDENCY_PIN", "R7-qualified rustworkx 0.17.1 is required", actual=rustworkx.__version__)
        names = {"graph_coloring_rustworkx", "gate_scheduling"}
        nodes = [n for n in ast.parse(raw.decode("utf-8")).body if isinstance(n, ast.FunctionDef) and n.name in names]
        if {n.name for n in nodes} != names:
            raise StrategyError("ENOLA_API_MISSING", "Pinned scheduler functions missing")
        scope = {"rx": rustworkx}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
        self.schedule = scope["gate_scheduling"]
        self.receipts = []
        self.provenance = {"commit": COMMIT, "source_file": "enola/scheduler/gate_scheduler.py",
             "source_sha256": SCHEDULER_SHA, "license_sha256": LICENSE_SHA, "rustworkx_version": rustworkx.__version__,
             "called": ["gate_scheduling", "graph_coloring_rustworkx"],
             "scope": "edge coloring within complete dependency-ready two-qubit window only"}

    def partition(self, operations, completed):
        if not operations:
            return []
        complete = set(completed)
        for op in operations:
            if (op.get("kind") != "gate" or op.get("params", {}).get("name") not in {"CX", "CZ"} or
                len(op.get("qubits", [])) != 2 or op["qubits"][0] == op["qubits"][1] or
                any(d not in complete for d in op.get("after", []))):
                raise StrategyError("ENOLA_WINDOW_NOT_READY", "Only proven-ready CX/CZ nodes may enter the pair projection", operation=op.get("id"))
        qubits = list(dict.fromkeys(q for op in operations for q in op["qubits"]))
        pairs = [[qubits.index(q) for q in op["qubits"]] for op in operations]
        raw = self.schedule(len(qubits), pairs)
        if sorted(i for layer in raw for i in layer) != list(range(len(operations))):
            raise StrategyError("ENOLA_SCHEDULE_COVERAGE", "Upstream output loses or duplicates a projected gate")
        for layer in raw:
            operands = [q for i in layer for q in operations[i]["qubits"]]
            if len(operands) != len(set(operands)):
                raise StrategyError("ENOLA_SCHEDULE_CONFLICT", "Upstream layer shares a qubit")
        receipt = {"input_operations": deepcopy(operations), "completed_ids": sorted(complete),
                   "qubit_index": qubits, "pairs": pairs, "raw_layers": deepcopy(raw),
                   "layers": [[operations[i]["id"] for i in layer] for layer in raw]}
        receipt["sha256"] = digest(receipt)
        self.receipts.append(receipt)
        return [[operations[i] for i in layer] for layer in raw]
