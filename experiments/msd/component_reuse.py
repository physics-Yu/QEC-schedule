"""Persistent component operations, separated from shared-device scheduling.

Only device-independent native operations and dependencies are reusable here.
No atom trajectory, readout destination, elapsed time or noise probability is
cached by this layer. Existing complete-world scheduling still resolves those.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from importlib.metadata import version
from math import tau
from pathlib import Path
from time import perf_counter

import qiskit.qasm3
from nadit_physical_compiler import frontend
from nadit_physical_compiler.experiments.journal import directory_lock, write_json
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation, Register
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import decode_dag, encode_dag

from modules.codes.rotated_surface.joint_factory_source import factory_component_source


@contextmanager
def _component_lock(folder: Path, key: str) -> Iterator[None]:
    try:
        with directory_lock(folder):
            yield
    except ValueError as error:
        if str(error).startswith("Experiment already has a writer:"):
            from .joint_cache import JointCacheDeferred

            raise JointCacheDeferred("component_operations", key) from error
        raise


@dataclass(frozen=True)
class ComponentOperations:
    """Native operation template with local wires and source identities."""

    dag: PhysicalDAG
    source_operations: int
    key: str
    requirements: tuple[tuple[str, int], ...]


class ComponentOperationCache:
    """Compile each source/native-ABI key once across workers and production seeds."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.memory: dict[str, ComponentOperations] = {}
        self.statistics: Counter[str] = Counter(
            {
                k: 0
                for k in ("requests", "internal_compiles", "memory_hits", "disk_hits")
            }
        )
        self.seconds = 0.0
        assert frontend.__file__ is not None
        root = Path(frontend.__file__).parent
        self.abi = {
            "schema": "nadit.component_operations/1",
            "template_implementation": sha256(Path(__file__).read_bytes()).hexdigest(),
            "frontend": {
                p.name: sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.glob("*.py"))
            },
            "qiskit": version("qiskit"),
            "qasm_import": version("qiskit-qasm3-import"),
        }

    def get(self, component: str, distance: int) -> ComponentOperations:
        """Load or explicitly lower native gates; corruption raises, never recompiles."""
        started = perf_counter()
        source = factory_component_source(component, distance)
        identity = {
            **self.abi,
            "component": component,
            "distance": distance,
            "source_sha256": sha256(source.source_qasm.encode()).hexdigest(),
            "wire_indices": list(source.wire_indices),
            "result_count": source.result_count,
        }
        key = canonical_hash(identity)
        self.statistics["requests"] += 1
        if key in self.memory:
            self.statistics["memory_hits"] += 1
            self.seconds += perf_counter() - started
            return self.memory[key]
        folder = self.directory / key
        path = folder / "operations.json"
        with _component_lock(folder, key):
            if path.exists():
                document = json.loads(path.read_text(encoding="utf-8"))
                if (
                    document["identity"] != identity
                    or canonical_hash(document["payload"]) != document["payload_sha256"]
                ):
                    raise ValueError("COMPONENT_OPERATION_CACHE_CORRUPT")
                payload = document["payload"]
                self.statistics["disk_hits"] += 1
            else:
                dag = loads_qasm(source.source_qasm)
                if any(n.condition is not None for n in dag.nodes):
                    raise ValueError("COMPONENT_REUSE_REQUIRES_UNCONDITIONAL_SOURCE")
                counts = Counter(n.name for n in dag.nodes)
                payload = {
                    "dag": encode_dag(dag),
                    "source_operations": len(
                        qiskit.qasm3.loads(source.source_qasm).data
                    ),
                    "requirements": {
                        "native_operations": len(dag.nodes),
                        "two_qubit_gates": counts["cz"],
                        "measurements": counts["measure"],
                        "resets": counts["reset"],
                        "wires": dag.num_qubits,
                        "requires_shared_aod": int(
                            counts["cz"] + counts["measure"] > 0
                        ),
                        "requires_readout": int(counts["measure"] > 0),
                        "requires_rydberg": int(counts["cz"] > 0),
                    },
                }
                write_json(
                    path,
                    {
                        "identity": identity,
                        "payload": payload,
                        "payload_sha256": canonical_hash(payload),
                        "compile_reason": "component_source_or_native_abi_key_not_present",
                    },
                )
                self.statistics["internal_compiles"] += 1
        result = ComponentOperations(
            decode_dag(payload["dag"]),
            payload["source_operations"],
            key,
            tuple(sorted(payload["requirements"].items())),
        )
        self.memory[key] = result
        self.seconds += perf_counter() - started
        return result


def compose_operations(templates: list[ComponentOperations]) -> PhysicalDAG:
    """Rebind disjoint local DAGs; shared resource conflicts remain unscheduled."""
    nodes: list[PhysicalOperation] = []
    edges: list[tuple[int, int]] = []
    quantum: list[Register] = []
    classical: list[Register] = []
    qbase = cbase = nbase = sbase = 0
    phase = 0.0
    for i, template in enumerate(templates):
        dag = template.dag
        if any(n.condition is not None for n in dag.nodes):
            raise ValueError("COMPONENT_REUSE_REQUIRES_UNCONDITIONAL_SOURCE")
        nodes.extend(
            replace(
                n,
                id=n.id + nbase,
                qubits=tuple(q + qbase for q in n.qubits),
                clbits=tuple(c + cbase for c in n.clbits),
                source_id=(n.source_id if n.source_id is not None else n.id) + sbase,
            )
            for n in dag.nodes
        )
        edges.extend((a + nbase, b + nbase) for a, b in dag.edges)
        quantum.append(Register(f"q_m{i}", tuple(range(qbase, qbase + dag.num_qubits))))
        if dag.num_clbits:
            classical.append(
                Register(f"c_m{i}", tuple(range(cbase, cbase + dag.num_clbits)))
            )
        qbase += dag.num_qubits
        cbase += dag.num_clbits
        nbase += len(dag.nodes)
        sbase += template.source_operations
        phase = (phase + dag.global_phase) % tau
    return PhysicalDAG(
        qbase,
        cbase,
        tuple(nodes),
        tuple(sorted(edges)),
        tuple(quantum),
        tuple(classical),
        phase,
    )
