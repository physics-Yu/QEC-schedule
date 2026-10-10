"""T304 signed operator algebra and source contracts; no state simulation."""

from collections import Counter
from copy import deepcopy
import unittest

from na_pipeline.frontend import build_logical_dag, build_patch_dag_example
from na_pipeline.qec import (PhysicalDAGError, build_patch_operation_spec, build_physical_dag_bundle,
                             materialize_physical_node, materialize_factory_protocol,
                             build_factory_physical_dag, validate_physical_dag)
from na_pipeline.qec.surface17 import CHECKS, LOGICAL_X, LOGICAL_Z


def pauli(support, basis, offset=0):
    mask = sum(1 << (i + offset) for i in support)
    return (mask, 0, 0) if basis == "X" else (0, mask, 0)


def multiply(a, b):
    # i^p X^x Z^z, including the sign when Z_left crosses X_right.
    return a[0] ^ b[0], a[1] ^ b[1], (a[2] + b[2] + 2 * (a[1] & b[0]).bit_count()) % 4


def signed_propagate(p, ops, index):
    x, z, phase = p
    for op in ops:
        qs = [index[q] for q in op["qubits"]]
        if op['kind'] == 'permute':
            targets = [qs[i] for i in op['params']['destination_indices']]
            mask = sum(1 << i for i in qs)
            x = x & ~mask | sum(((x >> a) & 1) << b for a,b in zip(qs,targets))
            z = z & ~mask | sum(((z >> a) & 1) << b for a,b in zip(qs,targets))
            continue
        name = op["params"]["name"]
        if name == "H":
            b = 1 << qs[0]
            phase = (phase + 2 * bool(x & b) * bool(z & b)) % 4
            if bool(x & b) != bool(z & b):
                x ^= b
                z ^= b
        elif name == "CX":
            c, t = qs
            x ^= ((x >> c) & 1) << t
            z ^= ((z >> t) & 1) << c
        elif name == "CZ":
            # Independent derivation through H-CX-H, rather than copying the
            # producer's direct symplectic CZ implementation.
            c, t = op['qubits']
            expanded = [{'kind':'gate','qubits':q,'params':{'name':n}} for n,q in (('H',[t]),('CX',[c,t]),('H',[t]))]
            x,z,phase = signed_propagate((x,z,phase),expanded,index)
        else:
            raise AssertionError(name)
    return x, z, phase


def stabilizer_group():
    result = {(0, 0, 0)}
    for _, basis, support, _ in CHECKS:
        generator = pauli(support, basis)
        result |= {multiply(p, generator) for p in list(result)}
    return result


class SignedCliffordAlgebra(unittest.TestCase):
    def assert_equivalent(self, actual, expected, blocks=1):
        difference = multiply(actual, expected)
        group = stabilizer_group()
        phase = 0
        for block in range(blocks):
            x, z = (difference[0] >> (9 * block)) & 511, (difference[1] >> (9 * block)) & 511
            matches = [p for p in group if p[:2] == (x, z)]
            self.assertEqual(len(matches), 1, (actual, expected, block))
            phase = (phase + matches[0][2]) % 4
        self.assertEqual(difference[2], phase, "incorrect signed logical action")

    def test_encoded_H_preserves_signed_code_and_exchanges_logicals(self):
        dag = build_patch_operation_spec("H")["physical_dag"]
        index = {f"block/d{i}": i for i in range(9)}
        self.assertEqual(Counter(op["params"].get("name", op["kind"]) for op in dag["nodes"]), {"H": 9, "permute": 1})
        for _, basis, support, _ in CHECKS:
            self.assert_equivalent(signed_propagate(pauli(support, basis), dag["nodes"], index), (0, 0, 0))
        self.assert_equivalent(signed_propagate(pauli(LOGICAL_X, "X"), dag["nodes"], index), pauli(LOGICAL_Z, "Z"))
        self.assert_equivalent(signed_propagate(pauli(LOGICAL_Z, "Z"), dag["nodes"], index), pauli(LOGICAL_X, "X"))

    def test_encoded_CX_and_CZ_full_signed_generator_action(self):
        x0, z0, x1, z1 = pauli(LOGICAL_X, "X"), pauli(LOGICAL_Z, "Z"), pauli(LOGICAL_X, "X", 9), pauli(LOGICAL_Z, "Z", 9)
        for gate, roles, expected in (("CX", ["control", "target"], [multiply(x0, x1), z0, x1, multiply(z0, z1)]),
                                       ("CZ", ["left", "right"], [multiply(x0, z1), z0, multiply(z0, x1), z1])):
            dag = build_patch_operation_spec(gate)["physical_dag"]
            index = {f"{role}/d{i}": 9 * b + i for b, role in enumerate(roles) for i in range(9)}
            for block in range(2):
                for _, basis, support, _ in CHECKS:
                    self.assert_equivalent(signed_propagate(pauli(support, basis, 9 * block), dag["nodes"], index), (0, 0, 0), 2)
            for before, after in zip((x0, z0, x1, z1), expected):
                self.assert_equivalent(signed_propagate(before, dag["nodes"], index), after, 2)


class PhysicalDAGContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logical = build_logical_dag()
        cls.bundle = build_physical_dag_bundle(cls.logical)

    def test_complete_source_binding_no_flatten_or_truncation(self):
        b = self.bundle
        self.assertEqual(b["logical_dag"], self.logical)
        self.assertEqual(b["edges"], self.logical["edges"])
        self.assertEqual(set(b["instances"]), {n["id"] for n in self.logical["nodes"]})
        self.assertEqual(b["coverage"]["logical_nodes"], 2102)
        self.assertEqual(b["coverage"]["static_source_coverage"], self.logical["source_coverage"])
        self.assertEqual(b["coverage"]["unbound_nodes"], [])
        for node in self.logical["nodes"]:
            self.assertEqual(b["instances"][node["id"]]["logical_node"], node)
        self.assertEqual(sum(n["operation"] in {"T", "TDG"} for n in self.logical["nodes"]), 817)
        self.assertLess(len(b["specifications"]), 20)

    def test_pool_is_complete_finite_and_shared_scratch_exclusive(self):
        r = self.bundle["resource_requirements"]
        self.assertEqual(r["physical_qubit_count"], 205)
        self.assertEqual(len(set(r["physical_qubit_ids"])), 205)
        self.assertEqual(len(r["patches"]), 12)
        self.assertEqual(r["counts"]["data_aod_atoms"], 85)
        self.assertEqual(r["counts"]["magic_aod_atoms"], 120)
        self.assertEqual(r["initial_ready_magic_tokens"], [])
        self.assertFalse(r["dynamic_carrier_creation_allowed"])
        self.assertEqual(r["shared_phase_scratch"]["phase_aux"], "factory0:Y")
        mutex = r["shared_phase_scratch"]["exclusive_mutex"]
        self.assertIn(mutex, r["lease_rules"]["S_SDG"]["exclusive"])
        self.assertIn(mutex, r["lease_rules"]["T_TDG"]["exclusive"])

    def test_no_startup_transport_and_mid_reset_real(self):
        for operation, count in (("SE", 56), ("H", 10), ("CX", 9), ("CZ", 9), ("RESET", 71), ("MEASURE", 10)):
            spec = build_patch_operation_spec(operation)
            dag = spec["physical_dag"]
            self.assertEqual(len(dag["nodes"]), count)
            self.assertEqual(spec["entry_requirements"]["startup_actions"], [])
            self.assertFalse(spec["exit_effects"]["fixed_home_required"])
            self.assertTrue(validate_physical_dag(dag)["passed"])
        reset = build_patch_operation_spec("RESET")["physical_dag"]
        self.assertEqual(sum(o["kind"] == "reset" and o["qubits"][0].startswith("block/d") for o in reset["nodes"]), 9)
        self.assertEqual(sum(o["kind"] == "measure" for o in reset["nodes"]), 8)
        self.assertTrue(any(o["condition"] for o in reset["nodes"]))

    def test_group_all_eight_sources_and_real_service_resets(self):
        for operation in ("SE", "RESET", "S", "SDG"):
            dag = build_patch_operation_spec(operation)["physical_dag"]
            self.assertTrue(validate_physical_dag(dag)["passed"])
            by_id = {op["id"]: op for op in dag["nodes"]}
            for group in dag["groups"]:
                self.assertEqual(len(group["members"]), 8)
                for m in group["members"]:
                    reset = by_id[m["post_readout_reset_op_id"]]
                    self.assertEqual(reset["kind"], "reset")
                    self.assertEqual(reset["qubits"], [m["physical_qubit_id"]])
                    self.assertIn(m["measurement_op_id"], reset["after"])

    def test_phase_gate_has_preparation_and_preserves_live_data(self):
        for operation, physical_seed in (("S", "S"), ("SDG", "SDG")):
            dag = build_patch_operation_spec(operation)["physical_dag"]
            self.assertEqual(len(dag["nodes"]), 65)
            self.assertEqual(len(dag["qubits"]), 17)
            seeds = [o for o in dag["nodes"] if o["params"].get("name") == physical_seed]
            self.assertEqual(len(seeds), 3)
            self.assertEqual({q for op in seeds for q in op['qubits']}, {'block/d2','block/d4','block/d6'})
            for op in dag["nodes"]:
                if op["kind"] in {"reset", "measure"}:
                    self.assertFalse(any(q.startswith("block/d") for q in op["qubits"]))
            self.assertEqual(sum(o['params'].get('name')=='CZ' for o in dag['nodes']),4)

    def test_actual_result_slots_guards_and_local_namespaces(self):
        b = self.bundle
        nodes = [n for n in self.logical["nodes"] if n["operation"] == "SE"][:2]
        dags = [materialize_physical_node(b, n["id"]) for n in nodes]
        self.assertFalse({o["id"] for o in dags[0]["nodes"]} & {o["id"] for o in dags[1]["nodes"]})
        for node, dag in zip(nodes, dags):
            self.assertTrue(set(node["writes"]) <= set(dag["result_producers"]))
        conditional = next(n for n in self.logical["nodes"] if n["condition"] and n["operation"] not in {"T", "TDG"})
        dag = materialize_physical_node(b, conditional["id"], epoch=4)
        self.assertEqual(dag["execution_guard"], conditional["condition"])
        self.assertIn(conditional["condition"]["bit"], dag["external_reads"])
        self.assertEqual(dag["logical_binding"]["logical_source"], conditional)
        self.assertTrue(all(conditional["id"] in o["source_ids"] for o in dag["nodes"]))
        dag["nodes"][0]["params"]["name"] = "CORRUPT"
        self.assertNotEqual(dag, materialize_physical_node(b, conditional["id"], epoch=4))

    def test_measurement_and_classical_postprocessing_preserve_writes(self):
        for node in self.logical["nodes"]:
            if node["operation"] in {"MEASURE", "CLASSICAL_POSTPROCESS"}:
                dag = materialize_physical_node(self.bundle, node["id"])
                self.assertTrue(set(node["writes"]) <= set(dag["result_producers"]))
                self.assertEqual(dag["external_reads"], node["reads"])
                if node["operation"] == "CLASSICAL_POSTPROCESS":
                    self.assertEqual(dag["nodes"][0]["params"]["bits_msb_first"], node["reads"])
                    self.assertEqual(dag["nodes"][0]["writes"], ["postprocess/result"])

    def test_real_factory_protocol_subset_same_carrier_and_guard(self):
        node = next(n for n in self.logical["nodes"] if n["operation"] == "TDG" and n["condition"])
        with self.assertRaisesRegex(PhysicalDAGError, "ADAPTIVE_FACTORY_REQUIRED"):
            materialize_physical_node(self.bundle, node["id"])
        protocol = materialize_factory_protocol(self.bundle, node["id"], epoch=7)
        self.assertEqual(len(protocol["raw_inputs"]), 15)
        self.assertEqual(len(protocol["stages"]), 44)
        self.assertEqual(protocol["output"]["block_id"], "factory0:W4")
        self.assertEqual(protocol["data_block_id"], node["patch_operands"]["block"])
        self.assertEqual(protocol["world_resource_ref"]["physical_qubit_count"], 205)
        self.assertEqual(protocol["world_resource_ref"]["protocol_participant_count"], 137)
        for stage in ("initialize", "rotate_04", "consume", "reject_cleanup"):
            dag = build_factory_physical_dag(protocol, stage)
            self.assertTrue(validate_physical_dag(dag)["passed"])
            self.assertEqual(dag["execution_guard"], node["condition"])
            for op in dag["nodes"]:
                if op["kind"] in {"reset", "measure"}:
                    self.assertFalse(set(op["qubits"]) & set(protocol["live_data_information_qubit_ids"]))

    def test_real_example_all_nodes_materializable(self):
        b = build_physical_dag_bundle(build_patch_dag_example())
        self.assertEqual(len(b["instances"]), 12)
        for node in b["instances"]:
            validate_physical_dag(materialize_physical_node(b, node))

    def test_mutated_spec_unknown_parameters_and_resource_alias_rejected(self):
        b = deepcopy(self.bundle)
        first = next(iter(b["instances"]))
        spec = b["specifications"][b["instances"][first]["spec_ref"]]
        spec["physical_dag"]["nodes"][0]["params"]["bad"] = True
        with self.assertRaisesRegex(PhysicalDAGError, "PHYSICAL_SPEC_MUTATED"):
            materialize_physical_node(b, first)
        with self.assertRaisesRegex(PhysicalDAGError, "PATCH_PARAMETERS_UNSUPPORTED"):
            build_patch_operation_spec("CZ", params={"pretend_transversal": True})
        with self.assertRaisesRegex(PhysicalDAGError, "POSTPROCESS_PROFILE"):
            build_patch_operation_spec("CLASSICAL_POSTPROCESS", params={"N": 21})
        b = deepcopy(self.bundle)
        b["resource_requirements"]["physical_qubit_ids"] = []
        with self.assertRaisesRegex(PhysicalDAGError, "PHYSICAL_RESOURCE_BINDING"):
            materialize_physical_node(b, first)

    def test_cycle_and_missing_classical_ready_edge_rejected(self):
        dag = build_patch_operation_spec("MEASURE")["physical_dag"]
        edge = next(e for e in dag["edges"] if e["kind"] == "classical_ready")
        edge["kind"] = "protocol"
        with self.assertRaisesRegex(PhysicalDAGError, "PHYSICAL_CLASSICAL_READY_MISSING"):
            validate_physical_dag(dag)
        dag = build_patch_operation_spec("X")["physical_dag"]
        a, b = [o["id"] for o in dag["nodes"][:2]]
        dag["nodes"][0]["after"] = [b]
        dag["nodes"][1]["after"] = [a]
        dag["edges"] = [{"source": a, "target": b, "kind": "protocol"}, {"source": b, "target": a, "kind": "protocol"}]
        with self.assertRaisesRegex(PhysicalDAGError, "PHYSICAL_DAG_CYCLE"):
            validate_physical_dag(dag)


if __name__ == "__main__":
    unittest.main()
