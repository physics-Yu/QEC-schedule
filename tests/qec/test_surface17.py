"""Algebraic circuit qualification, not state simulation or noise sampling."""

from copy import deepcopy
from itertools import combinations, islice, product
import json
import tracemalloc
import unittest

from na_pipeline.qec import QECContractError, build_two_block_slice, iter_physical_ops, surface17_definition


def mask(support):
    return sum(1 << int(q[1:]) for q in support)


def rank(rows):
    pivots = {}
    for row in rows:
        while row:
            pivot = row.bit_length() - 1
            if pivot in pivots:
                row ^= pivots[pivot]
            else:
                pivots[pivot] = row
                break
    return len(pivots)


def commute(a, b):
    return ((a[0] & b[1]).bit_count() + (a[1] & b[0]).bit_count()) % 2 == 0


def propagate(pauli, gates, index):
    """Binary Pauli conjugation for H/CX; no amplitudes or state stored."""
    x, z = pauli
    for op in gates:
        name = op["params"]["name"]
        if name == "H":
            bit = 1 << index[op["qubits"][0]]
            if bool(x & bit) != bool(z & bit):
                x ^= bit
                z ^= bit
        elif name == "CX":
            c, t = (1 << index[q] for q in op["qubits"])
            if x & c:
                x ^= t
            if z & t:
                z ^= c
        else:
            raise AssertionError(name)
    return x, z


class Surface17Math(unittest.TestCase):
    def setUp(self):
        self.definition = surface17_definition()
        self.checks = [(mask(s["support"]), 0) if s["pauli"] == "X" else (0, mask(s["support"]))
                       for s in self.definition["stabilizers"]]

    def test_rank_commutation_logicals_and_distance(self):
        self.assertEqual(len(self.definition["data_qubits"]), 9)
        self.assertEqual(len(self.checks), 8)
        self.assertTrue(all(commute(a, b) for a in self.checks for b in self.checks))
        rows = [x | (z << 9) for x, z in self.checks]
        self.assertEqual(rank(rows), 8)
        lx, lz = (mask(self.definition["logical_x"]), 0), (0, mask(self.definition["logical_z"]))
        self.assertFalse(commute(lx, lz))
        for logical in (lx, lz):
            self.assertTrue(all(commute(logical, check) for check in self.checks))
            self.assertEqual(rank(rows + [logical[0] | logical[1] << 9]), 9)
            self.assertEqual((logical[0] | logical[1]).bit_count(), 3)
        # Every centralizer Pauli of weight < 3 must already be a stabilizer.
        for weight in (1, 2):
            for sites in combinations(range(9), weight):
                for labels in product(("X", "Y", "Z"), repeat=weight):
                    x = sum(1 << i for i, p in zip(sites, labels) if p in "XY")
                    z = sum(1 << i for i, p in zip(sites, labels) if p in "ZY")
                    if all(commute((x, z), check) for check in self.checks):
                        self.assertEqual(rank(rows + [x | z << 9]), 8)

    def test_four_layers_and_actual_measurement_observables(self):
        template = build_two_block_slice()["templates"]["s17.syndrome.v1"]
        ops = [n["op"] for n in template["body"]]
        gates = [op for op in ops if op["kind"] == "gate"]
        index = {q: i for i, q in enumerate(template["qubits"])}
        self.assertEqual(sum(op["params"].get("name") == "CX" for op in gates), 24)
        self.assertEqual(sum(op["params"].get("name") == "H" for op in gates), 8)
        for layer in range(4):
            used = [q for op in gates if op.get("metadata", {}).get("syndrome_layer") == layer for q in op["qubits"]]
            self.assertEqual(len(used), len(set(used)))
        # Back-propagate each measured ancilla Z through the ACTUAL full round.
        for check in self.definition["stabilizers"]:
            anc = 1 << index[check["ancilla"]]
            measured = propagate((0, anc), reversed(gates), index)
            data = mask(check["support"])
            expected = (data, anc) if check["pauli"] == "X" else (0, anc | data)
            self.assertEqual(measured, expected, check["id"])

    def test_transversal_cx_stabilizers_and_logicals(self):
        template = build_two_block_slice()["templates"]["s17.transversal_cx.v1"]
        ops = [n["op"] for n in template["body"]]
        index = {q: i for i, q in enumerate(template["qubits"])}
        self.assertEqual(len(ops), 9)
        for x, z in self.checks:
            self.assertEqual(propagate((x, z), ops, index), (x | x << 9, z))
            self.assertEqual(propagate((x << 9, z << 9), ops, index), (x << 9, z | z << 9))
        x, z = mask(self.definition["logical_x"]), mask(self.definition["logical_z"])
        for before, after in [((x, 0), (x | x << 9, 0)), ((0, z), (0, z)),
                              ((x << 9, 0), (x << 9, 0)), ((0, z << 9), (0, z | z << 9))]:
            self.assertEqual(propagate(before, ops, index), after)

    def test_preparation_sign_fixes_all_sixteen_branches(self):
        for state, basis in (("zero", "X"), ("plus", "Z")):
            template = build_two_block_slice()["templates"][f"s17.prepare_{state}.v1"]
            fixes = template["metadata"]["sign_fixes"]
            checks = [mask(c["support"]) for c in self.definition["stabilizers"] if c["pauli"] == basis]
            logical = mask(self.definition["logical_x" if basis == "X" else "logical_z"])
            for bits in product((0, 1), repeat=4):
                correction = 0
                for i, bit in enumerate(bits):
                    if bit:
                        correction ^= mask(fixes[f"m_{basis.lower()}{i}"])
                self.assertEqual([(correction & check).bit_count() % 2 for check in checks], list(bits))
                self.assertEqual((correction & logical).bit_count() % 2, 0)
            conditional = [n["op"] for n in template["body"] if n["op"]["condition"]]
            self.assertTrue(conditional)
            self.assertTrue(all(len(op["after"]) == 8 and op["reads"] == [op["condition"]["bit"]] for op in conditional))


class Instantiation(unittest.TestCase):
    def test_optional_annotations_do_not_hide_dependencies(self):
        program = build_two_block_slice(2)
        annotated = list(iter_physical_ops(program))
        for template in program["templates"].values():
            for node in template["body"]:
                annotation = node["op"].pop("metadata", None)
                if annotation is not None:
                    self.assertEqual(set(annotation), {"syndrome_layer", "corner", "check_id"})
                    self.assertIn(annotation["syndrome_layer"], range(4))
                    self.assertIn(annotation["corner"], {"NW", "NE", "SW", "SE"})
        # This mutation exists only in the test: production annotations stay.
        semantic = list(iter_physical_ops(program))
        for op in annotated:
            op.pop("metadata", None)
        self.assertEqual(annotated, semantic)
        # Every shared-qubit order is encoded as an explicit predecessor.
        last = {}
        for op in semantic:
            for q in op["qubits"]:
                if q in last:
                    self.assertIn(last[q], op["after"])
                last[q] = op["id"]

    def test_parameters_conditions_and_waits_survive_instantiation(self):
        program = build_two_block_slice()
        op = {"id": "read", "kind": "measure", "qubits": ["q"], "params": {"basis": "Z"},
              "reads": [], "writes": ["bit"], "after": [], "source_ids": ["original:read"], "condition": None}
        rotate = {"id": "rotate", "kind": "gate", "qubits": ["q"],
                  "params": {"name": "RZ", "angle": -0.125, "angle_unit": "rad"},
                  "reads": ["bit"], "writes": [], "after": ["read"],
                  "source_ids": ["original:rotation"], "condition": {"bit": "bit", "equals": 1}}
        wait = {"id": "wait", "kind": "wait", "qubits": ["q"], "params": {"duration_us": 17.5},
                "reads": [], "writes": [], "after": ["rotate"], "source_ids": ["original:wait"], "condition": None}
        program["templates"] = {"parameter_fixture": {"template_id": "parameter_fixture", "qubits": ["q"],
                                  "metadata": {"fixture": True},
                                  "body": [{"kind": "op", "op": item} for item in (op, rotate, wait)]}}
        program["body"] = [{"kind": "call", "id": "call", "template_id": "parameter_fixture",
                             "bindings": {"q": "control/d0"}, "repeat": 2, "source_ids": ["fixture_call"]}]
        program["provenance"]["fixture"] = True
        ops = list(iter_physical_ops(program))
        for i in (0, 1):
            self.assertEqual(ops[3*i+1]["params"], rotate["params"])
            self.assertEqual(ops[3*i+1]["condition"], {"bit": f"call/r{i}/bit", "equals": 1})
            self.assertEqual(ops[3*i+1]["reads"], [f"call/r{i}/bit"])
            self.assertIn(f"call/r{i}/read", ops[3*i+1]["after"])
            self.assertIn("original:rotation", ops[3*i+1]["source_ids"])
            self.assertEqual(ops[3*i+2]["params"], {"duration_us": 17.5})
        self.assertIn("call/r0/wait", ops[3]["after"])
        # Versioned unsupported operations must fail before any emitted prefix.
        program["templates"]["parameter_fixture"]["body"][1]["op"]["params"]["angle_unit"] = "deg"
        with self.assertRaises(QECContractError):
            next(iter_physical_ops(program))

    def test_instance_namespaces_dependencies_and_round_growth(self):
        program = build_two_block_slice(rounds=3)
        ops = list(iter_physical_ops(program))
        self.assertEqual(len(program["qubits"]), 34)
        self.assertEqual(sum(q["role"] == "data" for q in program["qubits"]), 18)
        seen, writers, last = set(), {}, {}
        for op in ops:
            self.assertNotIn(op["id"], seen)
            self.assertTrue(set(op["after"]) <= seen)
            for q in op["qubits"]:
                if q in last:
                    self.assertIn(last[q], op["after"])
                last[q] = op["id"]
            for bit in op["reads"]:
                self.assertIn(writers[bit], op["after"])
                self.assertEqual(bit.rsplit("/", 1)[0], op["id"].rsplit("/", 1)[0])
            for bit in op["writes"]:
                self.assertNotIn(bit, writers)
                writers[bit] = op["id"]
            seen.add(op["id"])
        self.assertEqual(len(writers), 16 + 32 * 3 + 18)
        self.assertEqual(len(ops) - len(list(iter_physical_ops(build_two_block_slice(1)))), 4 * 48 * 2)
        # Independent patches have no implicit whole-program serialization edge.
        first_target = next(op for op in ops if op["id"].startswith("prepare_target/"))
        self.assertEqual(first_target["after"], [])
        for obs in program["metadata"]["logical_observables"]:
            self.assertTrue(set(obs["results"]) <= writers.keys())

    def test_direct_syndrome_reference_matches_every_expanded_round(self):
        # Table 2 support plus independently written four-layer pairing table.
        layers = [
            [("x0", 0), ("x2", 4), ("x3", 6), ("z1", 1), ("z2", 3), ("z3", 5)],
            [("x0", 1), ("x2", 5), ("x3", 7), ("z1", 4), ("z2", 6), ("z3", 8)],
            [("x0", 3), ("x1", 1), ("x2", 7), ("z0", 0), ("z1", 2), ("z2", 4)],
            [("x0", 4), ("x1", 2), ("x2", 8), ("z0", 3), ("z1", 5), ("z2", 7)],
        ]
        ancillas = [f"{p}{i}" for p in "xz" for i in range(4)]
        reference = [("reset", "Z", [q]) for q in ancillas]
        reference += [("gate", "H", [q]) for q in ancillas[:4]]
        reference += [("gate", "CX", [a, f"d{i}"] if a[0] == "x" else [f"d{i}", a]) for layer in layers for a, i in layer]
        reference += [("gate", "H", [q]) for q in ancillas[:4]]
        reference += [("measure", "Z", [q]) for q in ancillas]
        ops = list(iter_physical_ops(build_two_block_slice(2)))
        for stage, block, iteration in product(("pre", "post"), ("control", "target"), range(2)):
            prefix = f"{stage}_{block}/r{iteration}/"
            actual = [(op["kind"], op["params"].get("name", op["params"].get("basis")),
                       [q.split("/")[1] for q in op["qubits"]]) for op in ops if op["id"].startswith(prefix)]
            self.assertEqual(actual, reference)

    def test_reuse_has_no_mutable_state_and_prefix_is_lazy(self):
        program = build_two_block_slice(100_000_000)
        original = json.dumps(program, sort_keys=True)
        tracemalloc.start()
        stream = iter_physical_ops(program)
        prefix = list(islice(stream, 200))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(len(prefix), 200)
        self.assertLess(peak, 8_000_000)
        self.assertEqual(original, json.dumps(program, sort_keys=True))
        prefix[0]["params"]["mutated"] = True
        self.assertNotIn("mutated", next(iter_physical_ops(program))["params"])
        other = build_two_block_slice(1)
        other["templates"].clear()
        self.assertEqual(len(build_two_block_slice(1)["templates"]), 5)

    def test_chunk_consumption_matches_complete_iteration(self):
        program = build_two_block_slice(2)
        stream = iter_physical_ops(program)
        chunked = []
        while chunk := list(islice(stream, 37)):
            chunked.extend(chunk)
        self.assertEqual(chunked, list(iter_physical_ops(program)))

    def test_reject_incomplete_or_ambiguous_contracts(self):
        mutations = [
            lambda p: p["body"][0]["bindings"].pop("d0"),
            lambda p: p["body"][0]["bindings"].update(d0="control/d1"),
            lambda p: p["body"][1].update(id=p["body"][0]["id"]),
            lambda p: p["body"][0].update(repeat=True),
            lambda p: p["body"][0].update(condition={"bit": "future", "equals": 1}),
            lambda p: p["body"][0].update(template_id="missing"),
            lambda p: p["templates"]["s17.syndrome.v1"]["body"][0]["op"].update(after=["future"]),
            lambda p: p["templates"]["s17.syndrome.v1"]["body"][0]["op"].update(reads=["previous_instance/m_x0"]),
            lambda p: p["templates"]["s17.syndrome.v1"]["body"].append({"kind": "call"}),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                program = build_two_block_slice()
                mutation(program)
                with self.assertRaises(QECContractError):
                    list(iter_physical_ops(program))
        for bad in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                build_two_block_slice(bad)


if __name__ == "__main__":
    unittest.main()
