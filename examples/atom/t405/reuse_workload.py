"""R4-declared two-SE benchmark in the published R2 LogicalDAG schema.

This input contains exactly two consecutive SE calls; it is not a Shor subset
and does not claim to execute the unrelated coupling example's original graph.
R3 materializes both nodes through its real shared-specification interface.
"""
from copy import deepcopy

from na_pipeline.frontend import build_patch_dag_example, patch_interaction_graph, validate_logical_dag
from na_pipeline.backend.enola_kernel import digest


def repeated_se_workload(patch_count=1):
    if patch_count not in (1, 2): raise ValueError("Benchmark supports one or two complete patches")
    reference = build_patch_dag_example()
    dag = deepcopy(reference)
    pids = [f"P{i}" for i in range(patch_count)]
    dag["patches"] = [p for p in dag["patches"] if p["patch_id"] in pids]
    sources = [(i, pid, next(n for n in dag["nodes"] if n["id"] == f"maintenance/{phase}/{pid}"))
               for i, phase in enumerate(("entry", "after-coupling")) for pid in pids]
    nodes = []
    for i, pid, source in sources:
        node = deepcopy(source)
        old = node["id"]; new = f"reuse-benchmark/round{i}/{pid}"
        def rename(value):
            if isinstance(value, str): return value.replace(old, new)
            if isinstance(value, list): return [rename(v) for v in value]
            if isinstance(value, dict): return {k: rename(v) for k, v in value.items()}
            return value
        node = rename(node); node["source_ids"] = ["R4:declared-two-SE-reuse-workload/0.1", new]
        nodes.append(node)
    dag["nodes"] = nodes
    dag["edges"] = [{"source": f"reuse-benchmark/round0/{pid}", "target": f"reuse-benchmark/round1/{pid}", "kind": "quantum", "patch_id": pid} for pid in pids]
    dag["result_types"] = {r: "bit" for n in nodes for r in n["writes"]}
    dag["operation_counts"] = {"SE": 2*patch_count}
    dag["artifact_id"] = "two-SE-reuse-benchmark:"+digest(nodes)[:20]
    dag["producer_version"] = "R4-reuse-workload/0.1"
    dag["provenance"].update(owner="R4", purpose="explicit_two_consecutive_SE_input_no_algorithm_claim", fixture=False)
    dag["patch_interaction_graph"] = patch_interaction_graph(dag)
    dag["input_hashes"]["semantic_graph"] = digest({k: dag[k] for k in ("patches", "nodes", "edges", "entry")})
    errors = validate_logical_dag(dag)
    if errors: raise ValueError(errors)
    return dag
