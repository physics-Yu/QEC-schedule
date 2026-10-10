"""Operator, code and protocol checks without simulating quantum states."""

from collections import Counter
from copy import deepcopy
from itertools import combinations, product
import hashlib
import json
import unittest

from na_pipeline.qec import (FactoryProtocolError, build_factory15to1_protocol, distillation_matrix,
                             bind_factory_stage, factory_stage_decision, factory_stage_program, iter_physical_ops)
from na_pipeline.qec.factory_primitives import Circuit, css_encoder, merged_zz_checks
from na_pipeline.qec.surface17 import CHECKS, LOGICAL_X, LOGICAL_Z
from test_surface17 import commute, propagate, rank


def bits(indices):
    return sum(1 << i for i in indices)


class FactoryAlgebra(unittest.TestCase):
    def test_matrix_phase_polynomial_and_detection(self):
        matrix = distillation_matrix()["rows"]
        self.assertEqual([sum(row) for row in matrix], [8, 8, 8, 8, 7])
        for assignment in product((0, 1), repeat=5):
            weight = sum(sum(assignment[r] * matrix[r][c] for r in range(5)) % 2 for c in range(15))
            self.assertEqual(weight % 8, (-assignment[4]) % 8)
        # Pure algebra: each raw Z-fault maps to its matrix column. No sampling.
        syndromes = [sum(matrix[r][c] << r for r in range(4)) for c in range(15)]
        self.assertEqual(set(syndromes), set(range(1, 16)))
        undetected_weight3 = 0
        for weight in (1, 2, 3):
            for errors in combinations(range(15), weight):
                syndrome = 0
                logical = 0
                for c in errors:
                    syndrome ^= syndromes[c]
                    logical ^= matrix[4][c]
                if syndrome == 0 and logical:
                    self.assertEqual(weight, 3)
                    undetected_weight3 += 1
                if weight < 3:
                    self.assertNotEqual(syndrome, 0)
        self.assertEqual(undetected_weight3, 35)

    def test_coherent_encoder_preserves_arbitrary_seed_logicals(self):
        enc = css_encoder()
        index = {f"d{i}": i for i in range(9)}
        gates = [{"qubits": [f"d{c}", f"d{t}"], "params": {"name": "CX"}} for c, t in enc["cx"]]
        for i, column in enumerate(enc["columns"]):
            self.assertEqual(propagate((1 << i, 0), gates, index), (column, 0))
        xrows = [bits(support) for _, b, support, _ in CHECKS if b == "X"]
        zrows = [bits(support) for _, b, support, _ in CHECKS if b == "Z"]
        seed = 1 << index[enc['seed']]
        self.assertEqual(rank(xrows+[propagate((seed,0),gates,index)[0]^bits(LOGICAL_X)]),4)
        logical_z = propagate((0, seed), gates, index)[1]
        self.assertEqual(rank(zrows + [logical_z ^ bits(LOGICAL_Z)]), 4)
        for i in [index[q] for q in enc['plus_inputs']]:
            self.assertEqual(rank(xrows+[propagate((1 << i, 0), gates, index)[0]]),4)
        for i in [index[q] for q in enc['zero_inputs']]:
            z = propagate((0, 1 << i), gates, index)[1]
            self.assertEqual(rank(zrows + [z]), 4)

    def test_joint_gauge_code_and_surviving_logical_algebra(self):
        checks = merged_zz_checks()
        index = {f"{block}_d{i}": offset + i for block, offset in (("A", 0), ("B", 9)) for i in range(9)}
        paulis = []
        for check in checks:
            support = bits(index[q] for q in check["support"])
            paulis.append((support, 0) if check["basis"] == "X" else (0, support))
        self.assertEqual(len(paulis), 17)
        self.assertEqual(rank([x | z << 18 for x, z in paulis]), 17)
        self.assertTrue(all(commute(p, q) for p in paulis for q in paulis))
        self.assertEqual(max(len(c["support"]) for c in checks), 8)
        z, x = bits(LOGICAL_Z), bits(LOGICAL_X)
        zz = (0, z | z << 9)
        gauges = [p for check, p in zip(checks, paulis) if check["id"].startswith("g")]
        self.assertEqual(gauges[0][1] ^ gauges[1][1] ^ gauges[2][1], zz[1])
        # The full instrument retains the algebra commuting with measured ZZ.
        retained = [(0, z), (0, z << 9), (x | x << 9, 0)]
        self.assertTrue(all(commute(p, q) for p in paulis for q in retained))
        # Static merged-code distance only; not a circuit hook-distance claim.
        rows = [px | pz << 18 for px, pz in paulis]
        for weight in (1, 2):
            for sites in combinations(range(18), weight):
                for labels in product(("X", "Y", "Z"), repeat=weight):
                    px = bits(i for i, label in zip(sites, labels) if label in "XY")
                    pz = bits(i for i, label in zip(sites, labels) if label in "YZ")
                    if all(commute((px, pz), s) for s in paulis):
                        self.assertEqual(rank(rows + [px | pz << 18]), 17)
        self.assertEqual(rank(rows + [z << 18]), 18)

    def test_every_merged_check_readout_is_exact_pauli_product(self):
        for check in merged_zz_checks():
            circuit = Circuit()
            circuit.measure_check(check, "test")
            support = check["support"]
            index = {q: i for i, q in enumerate(support + [check["probe"]])}
            probe = 1 << index[check["probe"]]
            gates = [n["op"] for n in circuit.nodes if n["op"]["kind"] == "gate"]
            back = propagate((0, probe), reversed(gates), index)
            data = (1 << len(support)) - 1
            self.assertEqual(back, (data, probe) if check["basis"] == "X" else (0, data | probe))

    def test_injection_and_clifford_correction_as_phase_exponents(self):
        # Diagonal Kraus relative phases in units pi/4. Global factors removed.
        for parity, mx in product((0, 1), repeat=2):
            raw_phase = (1 if parity == 0 else -1) + 4 * mx
            corrected_t = raw_phase + 4 * mx + 2 * parity
            corrected_tdg = raw_phase + 4 * mx - 2 * (1 - parity)
            self.assertEqual(corrected_t % 8, 1)
            self.assertEqual(corrected_tdg % 8, 7)
            for sign in (-1, 1):
                y_phase = (2 * sign if parity == 0 else -2 * sign) + 4 * mx
                self.assertEqual((y_phase + 4 * (parity ^ mx)) % 8, (2 * sign) % 8)
        self.assertEqual((-1 + 2) % 8, 1)  # Same-carrier S converts output A- to A+.


class FactoryStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = build_factory15to1_protocol(data_block_id="algorithm", request_id="request0")

    def test_physical_graph_raw_inputs_and_no_live_data_reset(self):
        p = self.protocol
        self.assertEqual(len(p["qubits"]), 137)
        self.assertEqual(p["entry_requirements"]["available_factory_carriers"], 120)
        self.assertEqual(len(p["raw_inputs"]), 15)
        raw_by_stage = Counter(item["stage_id"] for item in p["raw_inputs"])
        total_raw_t = 0
        for stage_id, stage in p["stages"].items():
            if stage["kind"] != "physical":
                continue
            program = factory_stage_program(p, stage_id)
            ops = list(iter_physical_ops(program))
            t_count = sum(op["kind"] == "gate" and op["params"]["name"] in {"T", "TDG"} for op in ops)
            self.assertEqual(t_count, raw_by_stage[stage_id], stage_id)
            total_raw_t += t_count
            for op in ops:
                if op["kind"] in {"reset", "measure"}:
                    self.assertFalse(any(q.startswith("algorithm/d") for q in op["qubits"]), stage_id)
            if "branch" in stage:
                results = {bit for op in ops for bit in op["writes"]}
                self.assertIn(stage["branch"]["result_id"], results)
            self.assertTrue(all(node["kind"] == "op" for t in program["templates"].values() for node in t["body"]))
        self.assertEqual(total_raw_t, 15)

    def test_next_magic_preparation_is_parallel_to_uncompute_and_maintenance(self):
        p=self.protocol
        for col in range(5,15):
            producer=f'finish_{col-1:02d}';consumer=f'rotate_{col:02d}'
            self.assertEqual(p['stages'][consumer]['entry_magic_input']['producer_stage_id'],producer)
            ops=list(iter_physical_ops(factory_stage_program(p,producer)))
            seed=next(o for o in ops if 'raw_next_seed_phase' in o['id'])
            byid={o['id']:o for o in ops};stack=list(seed['after']);ancestors=set()
            while stack:
                sid=stack.pop()
                if sid in ancestors:continue
                ancestors.add(sid);stack.extend(byid[sid]['after'])
            self.assertTrue(all(all('/M/' in q or ':M/' in q for q in byid[s]['qubits']) for s in ancestors))
            self.assertFalse(any(o['params'].get('name') in ('T','TDG') for o in iter_physical_ops(factory_stage_program(p,consumer))))

    def test_acceptance_is_four_logical_X_checks_and_output_identity(self):
        p = self.protocol
        terminal = list(iter_physical_ops(factory_stage_program(p, "terminal_checks")))
        accept = next(op for op in terminal if op["params"].get("operation") == "all_zero")
        self.assertEqual(len(accept["reads"]), 4)
        self.assertTrue(all("terminal_W" in bit and bit.endswith("_logical") for bit in accept["reads"]))
        output = set(p["output"]["qubit_ids"])
        for stage_id in ("convert_output", "consume"):
            ops = list(iter_physical_ops(factory_stage_program(p, stage_id)))
            used = {q for op in ops for q in op["qubits"]}
            self.assertTrue(output <= used)
        conversion = list(iter_physical_ops(factory_stage_program(p, "convert_output")))
        self.assertFalse(any(op["kind"] in {"measure", "reset"} and any(q in output and "/d" in q for q in op["qubits"]) for op in conversion))
        reject = list(iter_physical_ops(factory_stage_program(p, "reject_cleanup")))
        reset = {q for op in reject if op["kind"] == "reset" for q in op["qubits"]}
        self.assertEqual(len(reset), 120)
        self.assertTrue(output <= reset)

    def test_decisions_require_committed_epoch_and_ready_result(self):
        p = self.protocol
        stage_id = "rotate_04"
        rid = p["stages"][stage_id]["branch"]["result_id"]
        receipt = {"protocol_id": p["artifact_id"], "stage_id": stage_id, "epoch": p["epoch"],
                   "complete": True, "end_us": 10, "evidence_kind": "fixture"}
        records = {rid: {"value": 1, "origin": "fake", "ready_us": 11}}
        with self.assertRaises(FactoryProtocolError):
            factory_stage_decision(p, stage_id, records, now_us=10, receipt=receipt)
        answer = factory_stage_decision(p, stage_id, records, now_us=11, receipt=receipt)
        self.assertEqual(answer["next_stage"], "correct_04")
        self.assertFalse(answer["token_transition_performed"])
        self.assertEqual(answer["evidence_kind"], "fixture")
        with self.assertRaises(FactoryProtocolError):
            factory_stage_decision(p, stage_id, {}, now_us=11, receipt=receipt)
        receipt["epoch"] = 5
        with self.assertRaises(FactoryProtocolError):
            factory_stage_decision(p, stage_id, records, now_us=11, receipt=receipt)

    def test_lifecycle_cannot_be_executed_as_a_physical_window(self):
        for stage in ("ready", "reserve_delivery", "consumed", "rejected"):
            with self.assertRaises(FactoryProtocolError):
                factory_stage_program(self.protocol, stage)

    def test_all_graph_paths_require_conversion_and_preserve_raw_count(self):
        p = self.protocol
        pending = [(p["entry"], (), 0)]
        terminals = Counter()
        while pending:
            sid, path, raw_count = pending.pop()
            self.assertNotIn(sid, path)
            stage = p["stages"][sid]
            new_path = path + (sid,)
            raw_count += sum(item["stage_id"] == sid for item in p["raw_inputs"])
            if stage["kind"] == "terminal":
                terminals[sid] += 1
                self.assertEqual(raw_count, 15)
                if sid == "consumed":
                    for required in ("terminal_checks", "convert_output", "ready", "reserve_delivery", "consume", "consume_cleanup"):
                        self.assertIn(required, path)
                    self.assertLess(path.index("convert_output"), path.index("ready"))
                else:
                    self.assertIn("reject_cleanup", path)
                    self.assertNotIn("consume", path)
                    self.assertNotIn("ready", path)
                continue
            next_ids = [stage["next"]] if "branch" not in stage else [stage["branch"]["zero"], stage["branch"]["one"]]
            for next_id in next_ids:
                self.assertIn(next_id, p["stages"])
                pending.append((next_id, new_path, raw_count))
        self.assertEqual(terminals, {"rejected": 2048, "consumed": 4096})

    def test_window_requirements_are_semantic_and_input_not_mutated(self):
        stage = factory_stage_program(self.protocol, "initialize")
        self.assertTrue(stage["window_contract"]["requires_runtime_snapshot"])
        self.assertEqual(stage["window_contract"]["live_data_block_id"], "algorithm")
        self.assertNotIn("requires_runtime_snapshot", stage["metadata"])
        stage["qubits"].clear()
        stage["templates"].clear()
        self.assertEqual(len(self.protocol["qubits"]), 137)
        self.assertTrue(self.protocol["templates"])

    def test_mapping_fixture_cannot_claim_execution_and_rejects_wrong_stage(self):
        p = self.protocol
        physical = factory_stage_program(p, "reject_cleanup")
        ops = list(iter_physical_ops(physical))
        qmap = {q["id"]: f"fixture_atom_{i}" for i, q in enumerate(p["qubits"])}
        atom = {"artifact_id": "explicit_mapping_fixture", "provenance": {"fixture": True},
                "input_hashes": {"physical_program": hashlib.sha256(json.dumps(physical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()},
                "initial_state": {"atoms": [{"qubit_id": q, "atom_id": aid} for q, aid in qmap.items()]},
                "actions": [{"id": f"a{i}", "kind": op["kind"], "atoms": [qmap[q] for q in op["qubits"]], "source_ids": [op["id"]]}
                            for i, op in enumerate(ops)],
                "source_map": {op["id"]: [f"a{i}"] for i, op in enumerate(ops)}}
        bound = bind_factory_stage(p, "reject_cleanup", atom)
        self.assertEqual(len(bound["factory_reset_action_ids"]), 120)
        self.assertEqual(len(bound["output_atom_ids"]), 17)
        self.assertEqual(len(bound["output_data_atom_ids"]), 9)
        self.assertEqual(len(bound["live_block_atom_ids"]), 17)
        self.assertEqual(len(bound["live_data_atom_ids"]), 9)
        self.assertTrue(bound["provenance"]["fixture"])
        self.assertFalse(bound["execution_verified"])
        self.assertFalse(bound["token_transition_performed"])
        with self.assertRaises(FactoryProtocolError):
            bind_factory_stage(p, "consume_cleanup", atom)
        atom["source_map"].pop(ops[0]["id"])
        with self.assertRaises(FactoryProtocolError):
            bind_factory_stage(p, "reject_cleanup", atom)

    def test_tdag_consumption_routes_the_opposite_correction_branch(self):
        p = build_factory15to1_protocol(data_block_id="algorithm", request_id="request0", gate="TDG", epoch=1)
        branch = p["stages"]["consume"]["branch"]
        self.assertEqual(branch["zero"], "consume_correction")
        self.assertEqual(branch["one"], "consume_cleanup")
        self.assertNotEqual(branch["result_id"], self.protocol["stages"]["consume"]["branch"]["result_id"])
        correction = list(iter_physical_ops(factory_stage_program(p, "consume_correction")))
        self.assertEqual(sum(op["params"].get("name") == "SDG" for op in correction), 3)
        self.assertEqual(sum(op["params"].get("name") == "S" for op in correction), 2)
        self.assertEqual(sum(op["params"].get("name") == "CZ" for op in correction), 4)

    def test_reject_aliased_live_data_and_invalid_request(self):
        for kwargs in ({"data_block_id": "factory0:W4"}, {"data_block_id": "W0"},
                       {"epoch": True}, {"epoch": -1}, {"request_id": "bad/request"}, {"gate": "CCZ"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(FactoryProtocolError):
                build_factory15to1_protocol(**kwargs)


if __name__ == "__main__":
    unittest.main()
