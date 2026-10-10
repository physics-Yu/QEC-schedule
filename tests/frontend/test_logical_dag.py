"""T204 graph/entry/ready semantics; no physical scheduling or state simulation."""

from collections import Counter
from copy import deepcopy
import unittest

from na_pipeline.frontend import (
    FrontendError, build_logical_dag, build_patch_dag_example, iter_logical_ops,
    patch_interaction_graph, patch_placement_inputs, ready_logical_nodes,
    validate_logical_dag, logical_dag_requirements,
)


def parents_of(dag):
    result = {n["id"]: set() for n in dag["nodes"]}
    for edge in dag["edges"]:
        result[edge["target"]].add(edge["source"])
    return result


def ancestors(parents, ident):
    found, pending = set(), list(parents[ident])
    while pending:
        node = pending.pop()
        if node not in found:
            found.add(node)
            pending.extend(parents[node])
    return found


class CompleteShorDAG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dag = build_logical_dag()

    def test_entire_source_and_intermediate_costs_are_retained(self):
        dag = self.dag
        self.assertEqual(validate_logical_dag(dag), [])
        source_ops = list(iter_logical_ops(dag["source_program"]))
        self.assertEqual(len(source_ops), 2069)
        self.assertEqual(set(dag["source_coverage"]), {op["id"] for op in source_ops})
        entry = {p["source_operation"]["id"] for p in dag["entry"]["source_preconditions"]}
        self.assertEqual(entry, {f"init/reset_w{i}" for i in range(4)} | {"round7/reset"})
        counts = Counter(n["operation"] for n in dag["nodes"])
        self.assertEqual((counts["SE"], counts["MEASURE"], counts["RESET"]), (37, 8, 8))
        self.assertEqual(counts["T"] + counts["TDG"], 817)
        self.assertEqual(counts["CX"], 40)
        self.assertEqual(len(dag["rounds"]), 8)
        self.assertEqual(len(dag["branch_global_phases"]), 15)
        self.assertEqual(sum(bool(n["resource_requests"]) for n in dag["nodes"]), 817)
        self.assertFalse(dag["entry"]["startup_transport_required"])
        self.assertTrue(all(p["initial_state"]["logical_value"] == 0 for p in dag["patches"]))
        self.assertTrue(any(n["id"] == "logical/init/work_one" and n["operation"] == "X" for n in dag["nodes"]))

    def test_D01_every_old_edge_has_a_semantic_or_commutation_proof(self):
        source = {op["id"]: op for op in iter_logical_ops(self.dag["source_program"])}
        expected = {(dep, op["id"]) for op in source.values() for dep in op["after"]}
        actual = {(e["source_operation_id"], e["target_operation_id"]) for e in self.dag["source_dependency_audit"]}
        self.assertEqual(actual, expected)
        relaxed = [e for e in self.dag["source_dependency_audit"] if e["disposition"] == "relaxed_generated_serialization"]
        self.assertEqual(len(relaxed), 83)
        for record in relaxed:
            left, right = source[record["source_operation_id"]], source[record["target_operation_id"]]
            self.assertFalse(set(left["qubits"]) & set(right["qubits"]))
            self.assertFalse(set(left["writes"]) & (set(right["reads"]) | set(right["writes"])))
            self.assertFalse(set(left["reads"]) & set(right["writes"]))

    def test_D01_real_source_has_new_independent_ready_witness(self):
        dag, parents = self.dag, parents_of(self.dag)
        nodes = {node["id"]: node for node in dag["nodes"]}
        witness = None
        for record in dag["source_dependency_audit"]:
            if record["disposition"] != "relaxed_generated_serialization":
                continue
            left = dag["source_coverage"][record["source_operation_id"]]["node_id"]
            right = dag["source_coverage"][record["target_operation_id"]]["node_id"]
            prereq = ancestors(parents, left) | ancestors(parents, right)
            if left not in prereq and right not in prereq:
                witness = (left, right, prereq)
                break
        self.assertIsNotNone(witness)
        left, right, prereq = witness
        # Explicit readiness fixture, never a runtime or measurement receipt.
        results = {result: {"value": 0, "origin": "fake", "producer_node_id": node_id, "ready_us": 0}
                   for node_id in prereq for result in nodes[node_id]["writes"]}
        ready = {r["node_id"] for r in ready_logical_nodes(dag, prereq, results=results)}
        self.assertTrue({left, right}.issubset(ready))

    def test_explicit_protocol_annotation_is_never_relaxed(self):
        record = next(e for e in self.dag["source_dependency_audit"] if e["disposition"] == "relaxed_generated_serialization")
        source = deepcopy(self.dag["source_program"])
        left, right = record["source_operation_id"], record["target_operation_id"]
        source["dependency_annotations"] = {right: {left: {"kind": "protocol", "reason": "explicit_test_protocol_fence"}}}
        dag = build_logical_dag(source)
        self.assertEqual(validate_logical_dag(dag), [])
        self.assertTrue(any(e["source"] == "logical/"+left and e["target"] == "logical/"+right
                            and e["kind"] == "protocol" and e["reason"] == "explicit_test_protocol_fence" for e in dag["edges"]))

    def test_unknown_source_generator_cannot_get_serialization_relaxation(self):
        source = deepcopy(self.dag["source_program"])
        source["body"][4]["op"]["params"]["name"] = "Z"
        with self.assertRaisesRegex(FrontendError, "SOURCE_GENERATOR_NOT_QUALIFIED"):
            build_logical_dag(source)

    def test_source_phase_magic_or_quantum_order_tampering_rejects(self):
        for mutation, code in (("phase", "BRANCH_PHASE_COVERAGE"), ("magic", "MISSING_MAGIC_RESOURCE_REQUIREMENT"),
                               ("inventory", "UNAUTHORIZED_INITIAL_MAGIC_INVENTORY"), ("wire_order", "MISSING_PATCH_ORDER"),
                               ("coverage", "SOURCE_COVERAGE_MISMATCH")):
            dag = deepcopy(self.dag)
            if mutation == "phase": dag["branch_global_phases"][0]["global_phase_pi"]["numerator"] += 1
            elif mutation == "magic": next(n for n in dag["nodes"] if n["operation"] == "T")["resource_requests"] = []
            elif mutation == "inventory": dag["resource_policy"]["magic_initial_ready_inventory"] = 15
            elif mutation == "wire_order": dag["edges"].remove(next(e for e in dag["edges"] if e["kind"] == "quantum"))
            else: dag["source_coverage"].pop(next(iter(dag["source_coverage"])))
            self.assertIn(code, {e["code"] for e in validate_logical_dag(dag)}, mutation)

    def test_requirements_are_not_a_physical_success_claim(self):
        report = logical_dag_requirements(self.dag, available_operations=["SE", "CX"])
        self.assertIn("T", report["unsupported_operations"])
        self.assertNotIn("SE", report["unsupported_operations"])
        self.assertEqual(report["magic_requests_static_upper_bound"], 817)
        self.assertFalse(report["complete_physical_execution_qualified"])
        self.assertTrue(all(not r["qualified"] for r in report["requirements"]))
        post = next(n for n in self.dag["nodes"] if n["operation"] == "CLASSICAL_POSTPROCESS")
        self.assertEqual(post["reads"], [f"phase[{i}]" for i in range(8)])


class PatchGraphAndReady(unittest.TestCase):
    def setUp(self):
        self.dag = build_patch_dag_example()

    def test_four_independent_SE_roots_and_disjoint_couplings(self):
        roots = ready_logical_nodes(self.dag, [])
        self.assertEqual(len(roots), 4)
        self.assertTrue(all(not n["resources_checked"] for n in roots))
        after = ready_logical_nodes(self.dag, [r["node_id"] for r in roots])
        self.assertEqual({n["node_id"] for n in after}, {"example/couple0", "example/couple1"})
        self.assertEqual(validate_logical_dag(self.dag), [])

    def test_classical_ready_and_false_condition_not_preselected(self):
        node = next(n for n in self.dag["nodes"] if n["id"] == "example/couple1")
        producer = "maintenance/entry/P1"
        bit = producer + "/x0"
        node["reads"], node["condition"] = [bit], {"bit": bit, "equals": 1}
        self.dag["edges"].append({"source": producer, "target": node["id"], "kind": "classical_ready", "result_id": bit})
        self.dag["patch_interaction_graph"] = patch_interaction_graph(self.dag)
        self.assertFalse(validate_logical_dag(self.dag))
        completed = [f"maintenance/entry/P{i}" for i in range(4)]
        self.assertNotIn(node["id"], {r["node_id"] for r in ready_logical_nodes(self.dag, completed)})
        results = {bit: {"value": 0, "origin": "fake", "producer_node_id": producer, "ready_us": 12}}
        self.assertNotIn(node["id"], {r["node_id"] for r in ready_logical_nodes(self.dag, completed, results=results, now_us=11)})
        ready = ready_logical_nodes(self.dag, completed, results=results, now_us=12)
        self.assertEqual(next(r["decision"] for r in ready if r["node_id"] == node["id"]), "skip")

    def test_cycle_missing_producer_unknown_gate_and_startup_zone_reject(self):
        for mutation, code in (("cycle", "LOGICAL_DAG_CYCLE"), ("producer", "MISSING_RESULT_PRODUCER"),
                               ("operation", "UNKNOWN_LOGICAL_OPERATION"), ("startup", "FORBIDDEN_STARTUP_TRANSPORT")):
            dag = deepcopy(self.dag)
            if mutation == "cycle": dag["edges"].append({"source": "example/couple0", "target": "maintenance/entry/P0", "kind": "protocol"})
            elif mutation == "producer": dag["nodes"][0]["reads"] = ["no_such_result"]
            elif mutation == "operation": dag["nodes"][0]["operation"] = "PRETEND_T"
            else: dag["entry"]["initialization_zone"] = "old-zone"
            self.assertIn(code, {e["code"] for e in validate_logical_dag(dag)}, mutation)

    def test_ready_rejects_fake_future_producer_or_inconsistent_completion(self):
        with self.assertRaisesRegex(FrontendError, "NONCAUSAL_COMPLETION_SET"):
            ready_logical_nodes(self.dag, ["example/couple0"])
        with self.assertRaisesRegex(FrontendError, "RESULT_WITHOUT_COMPLETED_PRODUCER"):
            ready_logical_nodes(self.dag, [], results={"maintenance/entry/P0/x0": {"origin": "fake", "value": 0,
                                                                                    "producer_node_id": "maintenance/entry/P0", "ready_us": 0}})

    def test_interaction_direction_weight_and_R4_projection(self):
        graph = self.dag["patch_interaction_graph"]
        self.assertEqual(sum(e["weight"] for e in graph["edges"]), 4)
        self.assertEqual(next(e["weight"] for e in graph["edges"] if e["patches"] == ["P0", "P3"]), 2)
        request = patch_placement_inputs(self.dag)
        self.assertEqual(request["interactions"][0]["patch_operands"], ["P0", "P3"])
        self.assertTrue(all(type(i["layer"]) is int and i["layer"] >= 0 for i in request["interactions"]))
        self.assertEqual(set(request["patches"]), {"P0", "P1", "P2", "P3"})
        self.assertFalse(request["placement_executed"])

    def test_additive_resource_projection_fields_do_not_invalidate_older_snapshots(self):
        for key in ("resource_patch_extensions_required", "resource_demands", "patch_scope"):
            self.dag["patch_interaction_graph"].pop(key)
        self.assertEqual(validate_logical_dag(self.dag), [])


if __name__ == "__main__":
    unittest.main()
