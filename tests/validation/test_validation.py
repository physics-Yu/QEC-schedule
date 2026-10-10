"""Mutation tests of real plans plus explicitly marked geometric fixtures."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from na_pipeline.device import default_device
from na_pipeline.qec import build_two_block_slice
from na_pipeline.backend import compile_physical
from na_pipeline.validation import validate, make_scenario
from na_pipeline.validation.checker import _hash


def fixture(points):
    device = default_device()
    atoms = [{"atom_id": f"a{i}", "qubit_id": f"q{i}", "position_um": p[:], "carrier": "SLM", "trap_id": f"s{i}", "aod_group": "data", "row_id": None, "column_id": None} for i,p in enumerate(points)]
    traps = [{"trap_id": f"s{i}", "position_um": p[:], "zone_id": "storage_entanglement", "occupant": f"a{i}"} for i,p in enumerate(points)]
    plan = {"schema_version": "AtomProgram/0.2.0-draft", "artifact_id": "R6-geometry-fixture", "provenance": {"fixture": True}, "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False, "complete": True, "device_ref": {"artifact_id": device["artifact_id"], "sha256": _hash(device)}, "input_hashes": {"device": _hash(device)}, "initial_state": {"atoms": atoms, "slm_traps": traps, "aod_rows": [], "aod_columns": []}, "actions": [], "source_map": {}, "stats": {}}
    return plan, device


def action(plan, kind, atoms, start, end, payload, resources=()):
    a = {"id": f"f{len(plan['actions'])}", "kind": kind, "atoms": atoms, "t_start_us": start, "t_end_us": end, "resources": list(resources), "source_ids": ["fixture/source"], "depends_on": [], "condition": None, "payload": payload}
    plan["actions"].append(a)
    return a


def pickup(plan, i, start, row, column):
    return action(plan, "pickup", [f"a{i}"], start, start+200, {"from_trap_id": f"s{i}", "to_trap_id": f"ad{i}", "aod_group": "data", "row_id": row, "column_id": column, "position_um": plan["initial_state"]["atoms"][i]["position_um"][:]})


class RealPlanMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = default_device()
        cls.physical = build_two_block_slice()
        cls.plan = compile_physical(cls.physical, cls.device)

    def check_mutation(self, mutate, code):
        plan = deepcopy(self.plan)
        mutate(plan)
        report = validate(plan, self.device, physical_program=self.physical)
        self.assertFalse(report["passed"])
        self.assertIn(code, {f["code"] for f in report["failures"]}, report["failures"][:8])

    def test_real_plan_scoped_checks_and_missing_trace(self):
        before = json.dumps(self.plan, sort_keys=True)
        report = validate(self.plan, self.device, physical_program=self.physical)
        self.assertTrue(report["scoped_pass"], report["failures"][:5])
        self.assertFalse(report["passed"])
        self.assertEqual([x["code"] for x in report["unverified"]], ["TRACE_MISSING"])
        self.assertEqual(before, json.dumps(self.plan, sort_keys=True))

    def test_missing_gate_even_when_source_map_kept(self):
        def mutate(p):
            a = next(a for a in p["actions"] if a["kind"] == "gate")
            p["actions"].remove(a)
        self.check_mutation(mutate, "SOURCE_MAP")

    def test_removed_source_map_and_actions(self):
        def mutate(p):
            sid = next(iter(p["source_map"]))
            ids = p["source_map"].pop(sid)
            p["actions"] = [a for a in p["actions"] if a["id"] not in ids]
        self.check_mutation(mutate, "SOURCE_OMITTED")

    def test_wrong_native_gate(self):
        self.check_mutation(lambda p: next(a for a in p["actions"] if a["kind"] == "gate" and a["payload"]["name"] == "H")["payload"].update(name="X"), "LOWERING_SEMANTICS")

    def test_wrong_pair(self):
        self.check_mutation(lambda p: next(a for a in p["actions"] if a["payload"].get("name") == "CZ")["payload"].update(pairs=[]), "BROADCAST_PAIRS")

    def test_resource_conflict_with_declarations_removed(self):
        def mutate(p):
            first = p["actions"][0]
            copy = deepcopy(first); copy["id"] = "rogue"; copy["resources"] = []
            p["actions"].append(copy)
        self.check_mutation(mutate, "RESOURCE_OVERLAP")

    def test_early_result(self):
        def mutate(p):
            a = next(a for a in p["actions"] if a["condition"])
            a["t_start_us"] = 0.; a["t_end_us"] = 1.
        self.check_mutation(mutate, "EARLY_RESULT_READ")

    def test_wrong_drop(self):
        self.check_mutation(lambda p: next(a for a in p["actions"] if a["kind"] == "drop")["payload"].update(to_trap_id="missing"), "DROP_TARGET")

    def test_instance_result_reused(self):
        def mutate(p):
            measurements = [a for a in p["actions"] if a["kind"] == "measure"]
            measurements[1]["payload"]["result_id"] = measurements[0]["payload"]["result_id"]
        self.check_mutation(mutate, "RESULT_REUSED")

    def test_condition_dropped(self):
        self.check_mutation(lambda p: next(a for a in p["actions"] if a["condition"]).update(condition=None), "CONDITION_CHANGED")

    def test_measurement_writes_cannot_be_erased(self):
        self.check_mutation(lambda p:next(a for a in p['actions'] if a['kind']=='measure')['payload'].update(writes=[]),'WRITES_CHANGED')

    def test_transport_cannot_write_measurement_result(self):
        self.check_mutation(lambda p:next(a for a in p['actions'] if a['kind']=='move')['payload'].update(writes=['forged-result']),'WRITES_CHANGED')

    def test_teleport(self):
        self.check_mutation(lambda p: next(a for a in p["actions"] if a["kind"] == "move")["payload"]["trajectories"][0].update(from_um=[999.,999.]), "MOVE_TELEPORT")

    def test_forged_device_ref(self):
        self.check_mutation(lambda p: p["input_hashes"].update(device="0"*64), "DEVICE_HASH")

    def test_incomplete_is_not_pass(self):
        self.check_mutation(lambda p: p.update(complete=False), "INCOMPLETE_PLAN")

    def test_unknown_version(self):
        self.check_mutation(lambda p: p.update(schema_version="AtomProgram/99"), "SCHEMA_VERSION")

    def test_invalid_input_reported(self):
        report = validate({}, {})
        self.assertFalse(report["passed"])
        self.assertTrue(report["failures"])

    def test_explicit_scenario(self):
        scenario = make_scenario(self.plan, value=1)
        expected = {a["payload"]["result_id"] for a in self.plan["actions"] if a["kind"] == "measure"}
        self.assertEqual(set(scenario["results"]), expected)
        self.assertTrue(all(r == {"value": 1, "origin": "fake"} for r in scenario["results"].values()))
        with self.assertRaises(ValueError):
            make_scenario(self.plan, value=True)


class GeometryFixtureTests(unittest.TestCase):
    def assertCode(self, plan, device, code):
        report = validate(plan, device)
        self.assertIn(code, {f["code"] for f in report["failures"]}, report)

    def test_affine_shared_axis_order_swaps_without_atom_collision(self):
        p,d = fixture([[0.,0.],[10.,10.]])
        pickup(p,0,0,"r0","c0"); pickup(p,1,200,"r1","c1")
        action(p,"move",["a0","a1"],400,410,{"aod_group":"data","interpolation":"linear","trajectories":[{"atom_id":"a0","from_um":[0.,0.],"to_um":[10.,0.],"row_id":"r0","column_id":"c0"},{"atom_id":"a1","from_um":[10.,10.],"to_um":[0.,10.],"row_id":"r1","column_id":"c1"}]})
        self.assertCode(p,d,"AXIS_CROSSING")

    def test_omitted_shared_row_passenger(self):
        p,d = fixture([[0.,0.],[10.,0.]])
        pickup(p,0,0,"r0","c0"); pickup(p,1,200,"r0","c1")
        action(p,"move",["a0"],400,410,{"aod_group":"data","interpolation":"linear","trajectories":[{"atom_id":"a0","from_um":[0.,0.],"to_um":[0.,10.],"row_id":"r0","column_id":"c0"}]})
        self.assertCode(p,d,"SHARED_AXIS")

    def test_hidden_geometric_pair(self):
        p,d = fixture([[0.,0.],[2.,0.],[10.,0.],[12.,0.]])
        action(p,"gate",["a0","a1"],0,1,{"name":"CZ","broadcast":True,"zone_id":"storage_entanglement","pairs":[["a0","a1"]]})
        self.assertCode(p,d,"BROADCAST_PAIRS")

    def test_all_edges_listed_still_rejects_multibody_pulse(self):
        p,d = fixture([[0.,0.],[2.,0.],[4.,0.]])
        action(p,"gate",["a0","a1","a2"],0,1,{"name":"CZ","broadcast":True,"zone_id":"storage_entanglement","pairs":[["a0","a1"],["a1","a2"]]})
        self.assertCode(p,d,"MULTIBODY_BROADCAST_UNSUPPORTED")

    def test_two_disjoint_pairs_and_spectator_are_supported(self):
        p,d = fixture([[0.,0.],[2.,0.],[10.,0.],[12.,0.],[30.,0.]])
        action(p,"gate",["a0","a1","a2","a3"],0,1,{"name":"CZ","broadcast":True,"zone_id":"storage_entanglement","pairs":[["a0","a1"],["a2","a3"]]})
        r=validate(p,d)
        self.assertTrue(r['scoped_pass'],r['failures'])
        self.assertEqual(next(c['status'] for c in r['checks'] if c['id']=='broadcast'),'passed')

    def test_bystander_parallel_gate_is_conflict(self):
        p,d = fixture([[0.,0.],[2.,0.],[10.,0.]])
        action(p,"gate",["a0","a1"],0,1,{"name":"CZ","broadcast":True,"zone_id":"storage_entanglement","pairs":[["a0","a1"]]})
        action(p,"gate",["a2"],0,1,{"name":"H"})
        self.assertCode(p,d,"ILLUMINATED_ATOM_OVERLAP")

    def test_atom_collision_between_endpoints(self):
        p,d = fixture([[0.,0.],[10.,0.]])
        pickup(p,0,0,"r0","c0")
        action(p,"move",["a0"],200,220,{"aod_group":"data","interpolation":"linear","trajectories":[{"atom_id":"a0","from_um":[0.,0.],"to_um":[20.,0.],"row_id":"r0","column_id":"c0"}]})
        self.assertCode(p,d,"ATOM_COLLISION")

    def test_unknown_trajectory_not_accepted(self):
        p,d = fixture([[0.,0.]])
        pickup(p,0,0,"r0","c0")
        action(p,"move",["a0"],200,220,{"aod_group":"data","interpolation":"cubic","trajectories":[]})
        report=validate(p,d)
        self.assertFalse(report["passed"])
        self.assertIn("TRAJECTORY_MODEL",{u["code"] for u in report["unverified"]})


class TraceMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from na_pipeline.runtime import run
        cls.device = default_device()
        cls.physical = build_two_block_slice()
        cls.plan = compile_physical(cls.physical, cls.device)
        cls.trace = run(cls.plan, make_scenario(cls.plan, value=1), cls.device)

    def reject(self, mutate, code):
        trace = deepcopy(self.trace)
        mutate(trace)
        report = validate(self.plan, self.device, trace, self.physical)
        self.assertFalse(report["passed"])
        self.assertIn(code, {f["code"] for f in report["failures"]}, report["failures"][:8])

    def test_real_chain_both_fake_paths(self):
        from na_pipeline.runtime import run
        for value in (0,1):
            trace=run(self.plan,make_scenario(self.plan,value=value),self.device)
            report=validate(self.plan,self.device,trace,self.physical)
            self.assertTrue(report['passed'],report['failures'][:5])
            self.assertEqual(report['unverified'],[])
        self.assertTrue(validate(self.plan,self.device,self.trace,self.physical)['passed'])

    def test_event_omitted(self):
        self.reject(lambda t:t['events'].pop(), 'EVENT_COVERAGE')

    def test_event_payload_changed(self):
        self.reject(lambda t:t['events'][0]['payload'].update(state=1),'EVENT_CHANGED')

    def test_result_from_another_instance(self):
        self.reject(lambda t:next(iter(t['results'].values())).update(action_id='previous-run'),'RESULT_INSTANCE')

    def test_future_result_used(self):
        def mutate(t):
            event=next(e for e in t['events'] if e['condition'])
            t['results'][event['condition']['bit']]['ready_us']=1e12
        self.reject(mutate,'EARLY_RESULT_READ')

    def test_condition_read_forged(self):
        self.reject(lambda t:next(e for e in t['events'] if e['condition'])['condition_reads'][0].update(value=0),'CONDITION_READ_RECORD')

    def test_wrong_branch(self):
        self.reject(lambda t:next(e for e in t['events'] if e['condition']).update(status='skipped'),'BRANCH_STATUS')

    def test_wrong_cumulative_illumination(self):
        self.reject(lambda t:t['illumination_counts'].update({'atom:0':0}),'ILLUMINATION_COUNT')

    def test_reset_is_not_new_atom(self):
        self.reject(lambda t:t['final_state']['atoms'].append({**t['final_state']['atoms'][0],'atom_id':'new-reset-atom'}),'FINAL_IDENTITY')

    def test_reset_epoch_reuse(self):
        self.reject(lambda t:t['final_state']['atoms'][0].update(reset_epoch=0),'FINAL_BINDING')

    def test_event_state_forged(self):
        self.reject(lambda t:next(iter(t['events'][0]['state_after'].values())).update(trap_id='invented'),'EVENT_STATE')

    def test_final_trap_occupancy_forged(self):
        self.reject(lambda t:t['final_state']['slm_traps'][0].update(occupant='wrong'),'FINAL_TRAPS')

    def test_final_axis_inventory_forged(self):
        self.reject(lambda t:t['final_state']['aod_rows'].append({'aod_group':'data','row_id':'phantom','y_um':10}),'FINAL_AXES')

    def test_time_is_not_sum_of_durations(self):
        self.reject(lambda t:t['stats'].update(duration_us=sum(a['t_end_us']-a['t_start_us'] for a in self.plan['actions'])),'TRACE_STATS')

    def test_old_execution_label(self):
        self.reject(lambda t:t.update(execution_kind='scenario_event_simulation'),'EVIDENCE_LABEL')

    def test_sampled_label_rejected(self):
        self.reject(lambda t:t.update(sampled=True),'FAKE_LABEL')

    def test_fixture_does_not_gain_production_label(self):
        p=deepcopy(self.plan); p['provenance']['fixture']=True
        from na_pipeline.runtime import run
        t=run(p,make_scenario(p),self.device)
        r=validate(p,self.device,t,self.physical)
        self.assertTrue(r['provenance']['input_fixture'])

    def test_source_rotation_angle_retained(self):
        physical=deepcopy(self.physical)
        physical['body'].append({'kind':'op','op':{'id':'rotation-test','kind':'gate','qubits':['control/d0'],'params':{'name':'RZ','angle':0.25,'angle_unit':'rad'},'reads':[],'writes':[],'after':[],'source_ids':['test/explicit-angle'],'condition':None}})
        plan=compile_physical(physical,self.device)
        a=next(a for a in plan['actions'] if a['payload'].get('name')=='RZ')
        a['payload']['params']['angle']=0.5
        r=validate(plan,self.device,physical_program=physical)
        self.assertIn('GATE_PARAMETER',{f['code'] for f in r['failures']})

    def test_validator_does_not_delegate_its_decision(self):
        with patch('na_pipeline.device.validate_device',side_effect=AssertionError('producer verifier called')), patch('na_pipeline.backend.geometry.validate_motion',side_effect=AssertionError('compiler geometry called')), patch('na_pipeline.runtime.run',side_effect=AssertionError('runtime replay called')):
            r=validate(self.plan,self.device,self.trace,self.physical)
            self.assertTrue(r['passed'],r['failures'])


if __name__ == "__main__":
    unittest.main()
