"""Finite carrier inventory and exclusive protocol leases, never free tokens."""
from copy import deepcopy

from .engine import digest
from .errors import fail


def resource_inventory(requirements, nonpatch_positions, *, placement_ref):
    """Bind R3 slots to R4-chosen probe coordinates for R1's t=0 builder."""
    if requirements.get("schema_version") != "PhysicalResourceRequirements/0.1.0":
        fail("RESOURCE_REQUIREMENTS_SCHEMA", "R3 PhysicalResourceRequirements/0.1.0 required")
    expected = {r["physical_qubit_id"] for r in requirements["nonpatch_atoms"]}
    if set(nonpatch_positions) != expected:
        fail("RESOURCE_POSITION_COVERAGE", "R4 must assign every finite nonpatch carrier position")
    inventory = {"schema_version": "initial-resource-inventory/0.1", "artifact_id": "R5-pool:"+digest(requirements),
        "provenance": {"producer": "R5-resource-pool/0.1", "fixture": bool(placement_ref["fixture"]),
                       "source_refs": ["R3:PhysicalResourceRequirements/0.1.0:"+digest(requirements), placement_ref["artifact_id"]]},
        "patch_roles": {}, "nonpatch_atoms": {}}
    for pid, p in requirements["patches"].items():
        pool = "algorithm" if p["role"] == "algorithm" else p.get('factory_id',requirements["factory_id"])
        inventory["patch_roles"][pid] = {"role": p["role"], "pool_id": pool, "slot_id": "patch:"+pid}
    for r in requirements["nonpatch_atoms"]:
        qid = r["physical_qubit_id"]
        inventory["nonpatch_atoms"]["atom:"+qid] = {"qubit_id": qid, "trap_id": "slm:"+qid,
            "position_um": deepcopy(nonpatch_positions[qid]), "aod_group": r["aod_group"], "role": "probe",
            "pool_id": r.get('factory_id',requirements["factory_id"]), "slot_id": "probe:"+r["slot_id"], "basis": r["basis"], "value": r["value"]}
    return inventory


class FiniteResourcePool:
    def __init__(self, requirements, initial_state):
        if requirements.get("schema_version") != "PhysicalResourceRequirements/0.1.0":
            fail("RESOURCE_REQUIREMENTS_SCHEMA", "R3 physical resource list required")
        actual = {a["qubit_id"]: a["atom_id"] for a in initial_state["atoms"]}
        if len(actual) != len(initial_state["atoms"]) or set(actual) != set(requirements["physical_qubit_ids"]):
            fail("POOL_CARRIER_COVERAGE", "Whole declared world, including all algorithm spectators, must exist at t=0")
        if initial_state.get("ready_magic_tokens") or requirements.get("initial_ready_magic_tokens"):
            fail("POOL_FREE_MAGIC", "Preinitialization does not supply accepted magic resources")
        self.requirements, self.qubit_to_atom = deepcopy(requirements), actual
        self.requirements_hash = digest(requirements)
        self.active, self.history, self.used_owners = {}, [], set()
        self.next_epoch = 0

    def acquire(self, owner, operation, target_patch, session):
        if owner in self.used_owners or operation not in ("S", "SDG", "T", "TDG"):
            fail("POOL_LEASE_IDENTITY", "Unique owner and a supported protocol operation required")
        rules = self.requirements["lease_rules"]["S_SDG" if operation in ("S", "SDG") else "T_TDG"]
        resources = [target_patch if r == "operand:block" else r for r in rules["exclusive"]]
        actual = {a["qubit_id"]: a["atom_id"] for a in session.snapshot()["world_state"]["atoms"]}
        if actual != self.qubit_to_atom: fail("POOL_CARRIER_REPLACED", "Finite pool identities changed after t=0")
        if target_patch not in self.requirements["patches"] or self.requirements["patches"][target_patch]["role"] != "algorithm":
            fail("POOL_LIVE_TARGET", "A protocol must bind an existing algorithm patch")
        occupied = {r for lease in self.active.values() for r in lease["resources"]}
        if occupied & set(resources): fail("POOL_RESOURCE_BUSY", "Factory and S scratch share the same exclusive physical pool")
        lease = {"owner": owner, "operation": operation, "target_patch": target_patch, "resources": resources,
                 "epoch": self.next_epoch, "acquired_us": session.now_us, "session_run_id": session.run_id,
                 "entry_revision": session.revision, "entry_plan_count": session.submitted_plan_count, "requirements_hash": self.requirements_hash,
                 "ready_magic_token": None}
        self.next_epoch += 1; self.used_owners.add(owner); self.active[owner] = lease
        self.history.append({"event": "acquire", **deepcopy(lease)})
        return deepcopy(lease)

    def release(self, owner, session, *, cleanup_action_ids, reset_qubit_ids, protocol_action_ids=None):
        if owner not in self.active: fail("POOL_LEASE_ABSENT", "Only the current owner may release")
        lease = self.active[owner]
        if lease["session_run_id"] != session.run_id: fail("POOL_SESSION_CHANGED", "Lease belongs to another runtime")
        # A target's final correction is not a proxy for DAG completion. Every
        # action and actually produced result submitted under this lease must
        # reach its real terminal/ready event, including parallel Y cleanup.
        submitted = [p for p in session.plans if p["sequence"] >= lease["entry_plan_count"]]
        selected=set(protocol_action_ids) if protocol_action_ids is not None else None
        if selected is not None:submitted=[p for p in submitted if set(p['action_ids'])&selected]
        for plan in submitted:
            for aid in plan["action_ids"]:
                if selected is not None and aid not in selected:continue
                event = session.events.get(aid)
                if not event or event["status"] not in ("completed", "skipped"):
                    fail("POOL_PROTOCOL_NOT_COMPLETE", "Pool release precedes a submitted protocol terminal action")
                if any(r not in session.results or session.results[r]["ready_us"] > session.now_us for r in event["result_ids"]):
                    fail("POOL_PROTOCOL_RESULTS_PENDING", "Pool release precedes a required published result")
        reset_qubit_ids = set(reset_qubit_ids)
        expected = {q for q in self.qubit_to_atom if any(q == r or q.startswith(r+"/") for r in lease["resources"] if r != lease["target_patch"])}
        if not reset_qubit_ids or reset_qubit_ids != expected:
            fail("POOL_CLEANUP_COVERAGE", "Cleanup must reset exactly the leased reusable scratch/factory carriers")
        reset_atoms = set()
        for aid in cleanup_action_ids:
            event = session.events.get(aid)
            if not event or event["status"] != "completed" or event["kind"] != "reset" or event["t_start_us"] < lease["acquired_us"]:
                fail("POOL_CLEANUP_NOT_EXECUTED", "Release needs actual completed same-epoch reset actions")
            reset_atoms.update(event["atoms"])
        if reset_atoms != {self.qubit_to_atom[q] for q in expected}:
            fail("POOL_CLEANUP_COVERAGE", "Physical reset receipts do not cover the leased carriers")
        reset_ends = {atom: max(session.events[a]["t_end_us"] for a in cleanup_action_ids if atom in session.events[a]["atoms"]) for atom in reset_atoms}
        protection = lease.get('target_protection_intervals', [
            {'target_patch':lease['target_patch'], 'start_us':lease['acquired_us'], 'end_us':None}])
        live_intervals = [(p, {self.qubit_to_atom[p['target_patch']+'/d'+str(i)] for i in range(9)}) for p in protection]
        for event in session.events.values():
            if event["status"] == "skipped" or event["t_start_us"] < lease["acquired_us"]: continue
            if event["kind"] in ("reset", "measure"):
                for interval, atoms in live_intervals:
                    if (set(event['atoms']) & atoms and event['t_end_us'] > interval['start_us'] and
                            (interval['end_us'] is None or event['t_start_us'] < interval['end_us'])):
                        fail("POOL_LIVE_DATA_DESTROYED", "Protocol reset or destructively measured a leased live target")
            touched = set(event["atoms"])
            if event["kind"] == "gate" and event["payload"].get("name") == "CZ":
                touched = {a for pair in event["payload"].get("pairs", []) for a in pair}
            if event["kind"] in ("gate", "measure") and any(event["t_end_us"] > reset_ends[a] for a in touched & reset_atoms):
                fail("POOL_CLEANUP_NOT_FINAL", "Reusable carrier was operated on after its cleanup reset")
        record = {"event": "release", "owner": owner, "epoch": lease["epoch"], "released_us": session.now_us,
                  "cleanup_action_ids": list(cleanup_action_ids), "reset_qubit_ids": sorted(expected),
                  "released_state": {"kind": "physical_basis", "basis": "Z", "value": 0, "encoding_status": "not_asserted_encoded"},
                  "committed_plan_hashes": [p["plan_hash"] for p in submitted]}
        self.history.append(record); del self.active[owner]
        return deepcopy(record)

    def preview_target_binding(self, owner, target_patch, session):
        """Validate a late consumer lease without changing factory ownership/epoch."""
        if owner not in self.active: fail('POOL_LEASE_ABSENT', 'An active producer lease is required')
        lease=deepcopy(self.active[owner])
        if lease['operation'] not in ('T','TDG') or lease['session_run_id']!=session.run_id:
            fail('POOL_CONSUMER_LEASE', 'Only a same-session factory lease may bind a consumer')
        if self.requirements['patches'].get(target_patch,{}).get('role')!='algorithm':
            fail('POOL_LIVE_TARGET', 'Consumer must be an existing data-region algorithm patch')
        occupied={r for key,other in self.active.items() if key!=owner for r in other['resources']}
        if target_patch in occupied: fail('POOL_RESOURCE_BUSY', 'Requested consumer is already leased')
        snap=session.snapshot()
        if snap['in_flight'] or session.queue or session.pending_results:
            fail('POOL_BINDING_FRONTIER', 'Consumer binding requires a fully committed boundary')
        if {a['qubit_id']:a['atom_id'] for a in snap['world_state']['atoms']}!=self.qubit_to_atom:
            fail('POOL_CARRIER_REPLACED', 'Full-world carrier identity changed')
        old=lease['target_patch']
        intervals=lease.setdefault('target_protection_intervals',[
            {'target_patch':old,'start_us':lease['acquired_us'],'end_us':None}] if old is not None else [])
        if intervals:intervals[-1]['end_us']=session.now_us
        intervals.append({'target_patch':target_patch,'start_us':session.now_us,'end_us':None})
        lease['target_patch']=target_patch
        lease['resources']=[target_patch if r==old else r for r in lease['resources']]
        if old is None:lease['resources'].append(target_patch)
        return lease

    def bind_target(self, owner, target_patch, session):
        lease=self.preview_target_binding(owner,target_patch,session)
        previous=self.active[owner]['target_patch']
        self.active[owner]=lease
        self.history.append({'event':'bind_consumer','owner':owner,'epoch':lease['epoch'],
            'previous_target':previous,'target_patch':target_patch,'time_us':session.now_us,
            'session_run_id':session.run_id,'revision':session.revision,'factory_resources_unchanged':True})
        return deepcopy(lease)

    def snapshot(self):
        return {"schema_version": "finite-resource-pool/0.1", "requirements_hash": self.requirements_hash,
                "qubit_to_atom": deepcopy(self.qubit_to_atom), "active_leases": deepcopy(self.active),
                "next_epoch": self.next_epoch, "history": deepcopy(self.history), "initial_ready_magic_tokens": [],
                "token_lifecycle": "separate_execution_bound_factory_controller_required"}

    @classmethod
    def restore(cls, requirements, initial_state, data):
        obj = cls(requirements, initial_state)
        if data.get("schema_version") != "finite-resource-pool/0.1" or data["requirements_hash"] != obj.requirements_hash or data["qubit_to_atom"] != obj.qubit_to_atom:
            fail("POOL_CHECKPOINT_IDENTITY", "Pool checkpoint does not bind the same requirements/world")
        obj.active = deepcopy(data["active_leases"])
        obj.history = deepcopy(data["history"])
        obj.used_owners = {e["owner"] for e in obj.history if e["event"] == "acquire"}
        obj.next_epoch = data["next_epoch"]
        if obj.next_epoch != len(obj.used_owners): fail("POOL_CHECKPOINT_EPOCH", "Epoch history is inconsistent")
        return obj
