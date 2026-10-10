"""Author regressions for the joint planner; fixture bindings are labeled."""
from copy import deepcopy
import random
import unittest

from na_pipeline.backend import compile_physical_dag, place_patches, StrategyError
from na_pipeline.device import preinitialized_device
from na_pipeline.qec.physical_dag import build_patch_operation_spec
from na_pipeline.runtime import run, make_scenario


def fixture_instance(operation, patch, prefix):
    dag = build_patch_operation_spec(operation)["physical_dag"]
    replacements = {n["id"]: prefix+"/"+n["id"] for n in dag["nodes"]}
    replacements.update({b: prefix+"/"+b for n in dag["nodes"] for b in n["writes"]})
    replacements.update({q["id"]: patch+"/"+q["local_id"] for q in dag["qubits"]})
    replacements["block"] = patch
    def convert(x):
        if isinstance(x, str): return replacements.get(x, x)
        if isinstance(x, list): return [convert(v) for v in x]
        if isinstance(x, dict): return {replacements.get(k, k): convert(v) for k, v in x.items()}
        return x
    result = convert(dag)
    result["artifact_id"] = prefix
    result["provenance"]["fixture"] = True
    for g in result["groups"]: g["group_id"] = prefix+"/"+g["group_id"]
    return result


class PhysicalDAGTests(unittest.TestCase):
    def setUp(self):
        self.device = preinitialized_device()

    def world(self, patches):
        return place_patches({p: {"aod_group": "data", "basis": "Z", "value": 0} for p in patches}, [], self.device)["initial_state"]

    def test_real_r3_se_preserves_data_and_global_mz(self):
        dag = build_patch_operation_spec("SE")["physical_dag"]
        # Place the active block on a nonzero EZ row, preserving another spectator.
        world = place_patches({p: {"aod_group": "data", "basis": "Z", "value": 0}
                               for p in ("spectator", "block")}, [], self.device, grid_shape=[1, 2])["initial_state"]
        self.assertGreater(next(a for a in world["atoms"] if a["qubit_id"] == "block/d0")["position_um"][1], 0)
        result = compile_physical_dag(dag, self.device, world)
        atom = result["atom_program"]
        trace = run(atom, make_scenario(atom, value=1), self.device)
        self.assertEqual(trace["stats"]["result_count"], 8)
        reset_atoms = {aid for a in atom["actions"] if a["kind"] == "reset" for aid in a["atoms"]}
        self.assertFalse(any("/d" in a for a in reset_atoms))
        measurement_traps = [t for t in atom["initial_state"]["slm_traps"] if t["zone_id"] == "measurement"]
        self.assertTrue(all(t["position_um"][1] in (1020., 1030.) for t in measurement_traps))
        self.assertEqual([a["position_um"] for a in world["atoms"]], [a["position_um"] for a in result["exit_state"]["atoms"]])
        self.assertTrue(result["enola"]["schedule_decisions"])
        self.assertEqual(set(atom["source_map"]), {n["id"] for n in dag["nodes"]})

    def test_joint_fixture_has_real_parallel_actions_and_one_aod_world(self):
        dags = [fixture_instance("SE", p, "test-"+p) for p in ("P0", "P1")]
        result = compile_physical_dag(dags, self.device, self.world(["P0", "P1"]))
        atom = result["atom_program"]
        trace = run(atom, make_scenario(atom, value=1), self.device)
        self.assertEqual(trace["stats"]["result_count"], 16)
        resets = [a for a in atom["actions"] if a["kind"] == "reset" and a["t_start_us"] == 0]
        self.assertEqual(len(resets), 16)
        self.assertEqual({a["atoms"][0].split("/")[0] for a in resets}, {"atom:P0", "atom:P1"})
        pickups = [a for a in atom["actions"] if a["kind"] == "pickup"]
        self.assertEqual({a["payload"]["aod_group"] for a in pickups}, {"data"})
        self.assertEqual(len(atom["initial_state"]["atoms"]), 34)
        self.assertTrue(atom["provenance"]["fixture"])
        conflicting = fixture_instance("SE", "P0", "other-call")
        with self.assertRaises(StrategyError) as caught:
            compile_physical_dag([dags[0], conflicting], self.device, self.world(["P0", "P1"]))
        self.assertEqual(caught.exception.code, "JOINT_DAG_QUBIT_CONFLICT")

    def test_measurement_parity_is_derived_from_readouts(self):
        dag = build_patch_operation_spec("MEASURE", params={"basis": "X"})["physical_dag"]
        result = compile_physical_dag(dag, self.device, self.world(["block"]))
        atom = result["atom_program"]
        for value in (0, 1):
            trace = run(atom, make_scenario(atom, value=value), self.device)
            output = trace["results"]["physical/r0/value"]
            self.assertEqual(output["value"], value)
            self.assertEqual(output["derivation"], "xor")
        self.assertFalse(any(a["kind"] == "reset" for a in atom["actions"]))

    def test_cz_preserves_cross_pairing_and_cx_direction(self):
        self.device["operations"]["action_kinds"].append("rebind")
        dag = build_patch_operation_spec("CZ")["physical_dag"]
        result = compile_physical_dag(dag, self.device, self.world(["left", "right"]))
        atom = result["atom_program"]
        trace = run(atom, make_scenario(atom, value=1), self.device)
        self.assertEqual(trace["stats"]["executed_action_count"], len(atom["actions"]))
        self.assertEqual(result["physical_dags"], [dag])
        self.assertEqual(len(dag["nodes"]), 9)
        self.assertTrue(all(atom["source_map"][n["id"]] for n in dag["nodes"]))

    def test_budget_guard_and_missing_source_edge_rejected(self):
        dag = build_patch_operation_spec("SE")["physical_dag"]
        world = self.world(["block"])
        with self.assertRaises(StrategyError) as caught:
            compile_physical_dag(dag, self.device, world, budget={"max_operations": 1})
        self.assertEqual(caught.exception.code, "PHYSICAL_BUDGET_EXHAUSTED")
        guard = deepcopy(dag)
        guard["execution_guard"] = {"bit": "outside", "equals": 1}
        guard["external_reads"] = ["outside"]
        with self.assertRaises(StrategyError) as caught:
            compile_physical_dag(guard, self.device, world)
        self.assertEqual(caught.exception.code, "PHYSICAL_DAG_GUARD_UNRESOLVED")
        broken = deepcopy(dag)
        broken["edges"].pop()
        with self.assertRaises(ValueError):
            compile_physical_dag(broken, self.device, world)

    def test_incremental_broadcast_keeps_background_and_all_moved_edges(self):
        from na_pipeline.backend.physical_window import PhysicalWindowCompiler
        from na_pipeline.backend.geometry import broadcast_pairs
        world = self.world(["block", "spectator"])
        compiler = PhysicalWindowCompiler([], [], self.device, world)
        rng = random.Random(42)
        ids = list(compiler.atoms)
        # Deliberately add a stationary spectator pair. It must not vanish when
        # a different candidate endpoint is moved, including across an EZ boundary.
        compiler.atoms[ids[-1]]["position_um"] = [300., 500.]
        compiler.atoms[ids[-2]]["position_um"] = [302., 500.]
        for trial_id in range(60):
            trial = deepcopy(list(compiler.atoms.values()))
            for index in rng.sample(range(len(trial)), 1+trial_id%5):
                trial[index]["position_um"] = [float(rng.randrange(0, 320, 2)), float(rng.choice([-1, 0, 2, 500, 998, 1000, 1001]))]
            expected = broadcast_pairs(trial, compiler.zone, 2., self.device["geometry"]["distance_tolerance_um"])
            self.assertEqual(compiler.projected_broadcast_pairs(trial), expected)
        compiler.atoms[ids[-1]]["position_um"] = [400., 900.]
        trial = deepcopy(list(compiler.atoms.values()))
        self.assertEqual(compiler.projected_broadcast_pairs(trial), broadcast_pairs(trial, compiler.zone, 2., 1e-6))


if __name__ == "__main__":
    unittest.main()
