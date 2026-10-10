"""Execution-bound adaptive factory over one persistent, finite physical world.

Unlike the legacy fixture ledger, this controller consumes actual R3 DAGs and
R4 plans already executed by EventSession. It never manufactures measurements.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from na_pipeline.qec import build_factory_physical_dag, factory_stage_decision

from .engine import digest
from .errors import fail


def controller_sources():
    root = Path(__file__).resolve().parent
    return {name: sha256((root/name).read_bytes()).hexdigest() for name in ("factory_session.py", "resource_pool.py", "factory_ports.py")}


class FactoryExecution:
    def __init__(self, protocol, pool, session, *, owner):
        if protocol.get("schema_version") != "factory-protocol/0.1.0-draft":
            fail("FACTORY_PROTOCOL_VERSION", "R3 adaptive protocol is required")
        if protocol.get('production_mode') and not hasattr(pool,'acquire_production'):
            fail('FACTORY_FLEET_POOL_REQUIRED','Independent production requires a line-aware finite resource pool')
        expected_epoch=pool.epoch_for(protocol['factory_id']) if hasattr(pool,'epoch_for') else pool.next_epoch
        if protocol["epoch"] != expected_epoch:
            fail("FACTORY_EPOCH", "Protocol must use the next unallocated physical pool epoch")
        if not {q["id"] for q in protocol["qubits"]} <= pool.qubit_to_atom.keys():
            fail("FACTORY_CARRIER_COVERAGE", "All participants must belong to the finite complete world")
        if 'data_input_contract' in protocol:
            from .factory_ports import data_surface_port
            port=protocol['data_input_contract']
            actual=data_surface_port(session,pool,protocol['data_block_id'],encoded_state_ref=port['encoded_state_ref'],logical_frame=port['logical_frame'])
            if actual!=port:fail('DATA_PORT_STALE','Refresh the data input contract before starting a factory request')
        guard = protocol.get("execution_guard")
        if guard:
            record = session.results.get(guard["bit"])
            if not record or record["ready_us"] > session.now_us:
                fail("FACTORY_GUARD_NOT_READY", "Protocol cannot read a future or configured-only result")
            if record["value"] != guard["equals"]:
                fail("FACTORY_GUARD_FALSE", "False logical requests do not start factories")
        self.protocol, self.pool, self.session = deepcopy(protocol), pool, session
        self.owner = owner
        self.lease = (pool.acquire_production(owner,protocol['factory_id'],session) if protocol.get('production_mode')
                      else pool.acquire(owner, protocol["request_gate"], protocol["data_block_id"], session))
        self.stage_id = protocol["entry"]
        self.receipts, self.decisions, self.lifecycle = [], [], []
        self.graph = None
        self.accepted = None
        self.token = None
        self.terminal = None
        self.live_atoms = {pool.qubit_to_atom[q] for q in protocol["live_data_information_qubit_ids"]}
        self.output_atoms = [pool.qubit_to_atom[q] for q in protocol["output"]["qubit_ids"]]
        self.output_data = {pool.qubit_to_atom[q] for q in protocol["output"]["qubit_ids"] if "/d" in q}

    def _stage_protocol(self):
        if self.stage_id in ('consume','consume_correction','consume_cleanup','consumed'):
            return getattr(self,'consumer_protocol',None) or self.protocol
        return self.protocol

    def next_graph(self):
        if self.owner not in self.pool.active:
            fail("FACTORY_LEASE_LOST", "A physical protocol requires its continuous exclusive pool lease")
        stage = self.protocol["stages"][self.stage_id]
        if stage["kind"] != "physical":
            fail("FACTORY_NOT_PHYSICAL_STAGE", "Apply the declared lifecycle transition before physical compilation")
        prepared = stage.get('entry_magic_input')
        if prepared:
            previous = self.receipts[-1] if self.receipts else {}
            port = previous.get('prepared_magic_output', {})
            expected = [self.pool.qubit_to_atom[self.protocol['bindings'][f'M_{q}']]
                        for q in [f'd{i}' for i in range(9)]+[f'{p}{i}' for p in ('x','z') for i in range(4)]]
            if (previous.get('stage_id') != prepared['producer_stage_id'] or previous.get('epoch') != self.protocol['epoch']
                    or port.get('raw_input_index') != prepared['raw_input_index'] or port.get('atom_ids') != expected
                    or port.get('consumer_stage_id') != self.stage_id):
                fail('FACTORY_PREPARED_INPUT_MISSING', 'Next injection requires the committed preparation on the same epoch and carriers')
        if self.stage_id == "consume":
            if not self.token or self.token["status"] != "reserved":
                fail("FACTORY_TOKEN_NOT_RESERVED", "Consumption requires this epoch's reserved ready resource")
        if self.graph is None:
            self.graph = build_factory_physical_dag(self._stage_protocol(), self.stage_id)
            from na_pipeline.qec.geometry_variants import resolve_geometry_variants
            self.graph = resolve_geometry_variants(self.graph, self.session.snapshot()['world_state'])
        return deepcopy(self.graph)

    def validate_submission(self, plan, atom_program, *, joint=False):
        graph = self.next_graph()
        if (not joint and plan.get("physical_dags") != [graph]) or (joint and graph not in plan.get('physical_dags',[])):
            fail("FACTORY_STAGE_DAG", "A stage plan must retain its exact original physical DAG")
        binding = atom_program.get("session_binding", {})
        if binding.get("physical_plan_sha256") != digest(plan):
            fail("FACTORY_STAGE_PLAN", "Absolute atom actions are not bound to this exact plan")
        actual = {a["qubit_id"]: a["atom_id"] for a in atom_program["initial_state"]["atoms"]}
        if actual != self.pool.qubit_to_atom:
            fail("FACTORY_WORLD_CHANGED", "Every inactive algorithm patch must remain in the same world")
        source_map = atom_program["source_map"]
        if set(source_map) != {n["id"] for d in (plan['physical_dags'] if joint else [graph]) for n in d["nodes"]}:
            fail("FACTORY_SOURCE_COVERAGE", "All physical source operations must remain mapped")
        actions = {a["id"]: a for a in atom_program["actions"]}
        used = set()
        for sid, ids in source_map.items():
            if not ids or len(ids) != len(set(ids)):
                fail("FACTORY_SOURCE_COVERAGE", "Empty or repeated source mapping")
            for aid in ids:
                if aid not in actions or sid not in actions[aid]["source_ids"]:
                    fail("FACTORY_SOURCE_BINDING", "Source map does not identify a concrete action")
                used.add(aid)
        if used != actions.keys(): fail("FACTORY_SOURCE_COVERAGE", "Extra unmapped physical action")
        for action in actions.values():
            if action["kind"] in ("reset", "measure") and set(action["atoms"]) & self.live_atoms:
                fail("FACTORY_LIVE_DATA_DESTROYED", "Factory must preserve existing live information carriers without destructive readout/reset")
        return True

    def commit_stage(self, plan, atom_program, *, joint=False):
        self.validate_submission(plan, atom_program,joint=joint)
        if not any(p["plan_hash"] == digest(atom_program) for p in self.session.plans):
            fail("FACTORY_STAGE_NOT_SUBMITTED", "Matching physical actions were not submitted to this session")
        owned={a for n in self.graph['nodes'] for a in atom_program['source_map'][n['id']]}
        action_ids = [a["id"] for a in atom_program["actions"] if a['id'] in owned]
        for action in atom_program["actions"]:
            if action['id'] not in owned:continue
            aid = action["id"]
            event = self.session.events.get(aid)
            if self.session.actions.get(aid) != action or event is None or event["status"] not in ("completed", "skipped"):
                fail("FACTORY_STAGE_NOT_COMMITTED", "Every source action needs a matching completed or causally skipped event")
        graph = self.graph
        if any(r not in self.session.results or self.session.results[r]["ready_us"] > self.session.now_us for r in graph["result_producers"]):
            fail("FACTORY_STAGE_RESULTS_NOT_READY", "Stage outputs have not all been published")
        physical_end = max(self.session.completed[a] for a in action_ids)
        required_ready = max((self.session.results[r]["ready_us"] for r in graph["result_producers"]), default=physical_end)
        effective_protocol=self._stage_protocol()
        receipt = {"protocol_id": effective_protocol["artifact_id"], "stage_id": self.stage_id, "epoch": self.protocol["epoch"],
            "complete": True, "evidence_kind": "fake_event_run", "end_us": max(physical_end, required_ready),
            "physical_end_us": physical_end, "required_results_ready_us": required_ready,
            "atom_program_hash": digest(atom_program), "physical_dag_hash": digest(graph), "action_ids": action_ids,
            "result_ids": sorted(graph["result_producers"]), "event_trace_ref": self.session.run_id+"/trace/"+str(self.session.revision)}
        prepared = self.protocol['stages'][self.stage_id].get('prepared_magic_output')
        if prepared:
            receipt['prepared_magic_output'] = {**deepcopy(prepared),
                'atom_ids':[self.pool.qubit_to_atom[self.protocol['bindings'][f'M_{q}']]
                            for q in [f'd{i}' for i in range(9)]+[f'{p}{i}' for p in ('x','z') for i in range(4)]],
                'ready_us':receipt['end_us'], 'evidence_kind':'committed_fake_events_quantum_untracked'}
        decision = factory_stage_decision(effective_protocol, self.stage_id, self.session.results, now_us=self.session.now_us, receipt=receipt)
        if self.stage_id == "terminal_checks":
            parities = []
            for check in self.protocol["acceptance_checks"]:
                values = [self.session.results[r]["value"] for r in check["result_ids"]]
                parities.append(sum(values) % 2 == check["expected_parity"])
            self.accepted = all(parities)
            if self.accepted != (decision["next_stage"] == "convert_output"):
                fail("FACTORY_ACCEPTANCE_DERIVATION", "Terminal branch differs from actual four parity checks")
            self.lifecycle.append({"event": "accept" if self.accepted else "reject", "time_us": self.session.now_us,
                                   "receipt": deepcopy(receipt), "check_passes": parities})
        if self.stage_id == "convert_output":
            if self.accepted is not True: fail("FACTORY_READY_BEFORE_ACCEPT", "Conversion alone cannot supply a ready token")
            if any(a["kind"] in ("reset", "measure") and set(a["atoms"]) & self.output_data for a in atom_program["actions"]):
                fail("FACTORY_OUTPUT_CARRIER_DESTROYED", "Output conversion must preserve the same W4 information carriers")
        if self.stage_id == "consume":
            if not self.token or self.token["status"] != "reserved": fail("FACTORY_TOKEN_REUSE", "Token already consumed or unavailable")
            self.token["status"] = "consumption_executed"
            self.lifecycle.append({"event": "consume_physical", "token_id": self.token["token_id"], "time_us": self.session.now_us,
                                   "target_patch": effective_protocol["data_block_id"], "receipt": deepcopy(receipt)})
        if self.stage_id in self.protocol["cleanup_stage_ids"]:
            factory_qubits = set(self.protocol["factory_qubit_ids"])
            factory_atoms = {self.pool.qubit_to_atom[q] for q in factory_qubits}
            cleanup = [a["id"] for a in atom_program["actions"] if a["kind"] == "reset" and set(a["atoms"]) <= factory_atoms]
            # Earlier resets may precede operations; select the final reset for each carrier.
            chosen = set()
            for aid in factory_atoms:
                matches = [a for a in cleanup if aid in self.session.events[a]["atoms"]]
                if not matches: fail("FACTORY_CLEANUP_INCOMPLETE", "No actual reset covers a reusable factory carrier")
                chosen.add(max(matches, key=lambda a: self.session.events[a]["t_end_us"]))
            kwargs={}
            if self.protocol.get('production_mode'):
                kwargs['protocol_action_ids']={a for r in self.receipts for a in r['action_ids']}|set(action_ids)
            release = self.pool.release(self.owner, self.session, cleanup_action_ids=sorted(chosen), reset_qubit_ids=factory_qubits,**kwargs)
            self.lifecycle.append(release)
            if self.stage_id == "consume_cleanup":
                if not self.token or self.token["status"] != "consumption_executed": fail("FACTORY_CONSUMPTION_MISSING", "Cleanup does not substitute for real consumption")
                self.token["status"] = "consumed"
            elif self.token is not None: fail("FACTORY_REJECTED_TOKEN", "Rejected attempt cannot mint a ready token")
        self.receipts.append(receipt); self.decisions.append(decision)
        self.stage_id, self.graph = decision["next_stage"], None
        if self.protocol["stages"][self.stage_id]["kind"] == "terminal":
            self.terminal = self.protocol["stages"][self.stage_id]["outcome"]
        return deepcopy(receipt)

    def advance_lifecycle(self):
        if self.stage_id == "ready":
            if self.accepted is not True or not self.receipts or self.receipts[-1]["stage_id"] != "convert_output" or self.token is not None:
                fail("FACTORY_NOT_READY", "Ready requires actual accepted checks and committed output conversion")
            self.token = {"token_id": self.protocol["artifact_id"]+"/token", "status": "ready", "epoch": self.protocol["epoch"],
                          "output_atom_ids": self.output_atoms.copy(), "ready_us": self.session.now_us,
                          "state": "A_plus_declared_protocol_quantum_untracked", "sampled": False}
            self.lifecycle.append({"event": "ready", **deepcopy(self.token)})
            self.stage_id = "reserve_delivery"
        elif self.stage_id == "reserve_delivery":
            if not self.token or self.token["status"] != "ready": fail("FACTORY_TOKEN_REUSE", "Only one owner may reserve a ready token")
            self.token.update(status="reserved", request_id=self.protocol["request_id"], target_patch=self.protocol["data_block_id"])
            self.lifecycle.append({"event": "reserve_and_handoff", "time_us": self.session.now_us, "token": deepcopy(self.token),
                                   "delivery_kind": "same_carrier_scheduling_handoff", "physical_motion_claimed": False})
            self.stage_id = "consume"
        else: fail("FACTORY_NOT_LIFECYCLE", "Current protocol stage is not a lifecycle transition")
        return self.snapshot()

    def snapshot(self):
        result = {"schema_version": "factory-execution/0.1", "protocol_ref": self.protocol["artifact_id"], "protocol_hash": digest(self.protocol),
                "logical_node_id": self.protocol.get("logical_binding", {}).get("logical_node_id"),
                "request_id": self.protocol["request_id"], "target_patch": self.protocol["data_block_id"], "requested_gate": self.protocol["request_gate"],
                "run_id": self.session.run_id, "owner": self.owner, "epoch": self.protocol["epoch"], "stage_id": self.stage_id,
                "accepted": self.accepted, "token": deepcopy(self.token), "terminal": self.terminal,
                "stage_receipts": deepcopy(self.receipts), "stage_decisions": deepcopy(self.decisions), "lifecycle": deepcopy(self.lifecycle),
                "pool": self.pool.snapshot(), "quantum_state_simulated": False, "hardware_executed": False, "sampled": False,
                "independent_validation": "pending_R6"}
        if getattr(self,'consumer_protocol',None) is not None:
            result.update(consumer_protocol=deepcopy(self.consumer_protocol),consumer_binding=deepcopy(self.consumer_binding),
                          target_patch=self.consumer_protocol['data_block_id'],request_id=self.consumer_protocol['request_id'],
                          requested_gate=self.consumer_protocol['request_gate'])
        return result

    def checkpoint(self):
        body = {"schema_version": "factory-session-checkpoint/0.1", "protocol": deepcopy(self.protocol),
                "requirements": deepcopy(self.pool.requirements), "initial_state": deepcopy(self.session.initial_state),
                "controller": self.snapshot(), "session": self.session.checkpoint(), "graph": deepcopy(self.graph), "lease": deepcopy(self.lease),
                "controller_source_hashes": controller_sources()}
        return {"body": body, "sha256": digest(body)}

    @classmethod
    def restore(cls, device, checkpoint, *, archive_root=None):
        from .session import EventSession
        from .resource_pool import FiniteResourcePool
        body = checkpoint["body"]
        if body.get('requirements',{}).get('factories'):
            fail('FACTORY_FLEET_CHECKPOINT_REQUIRED','Restore FactoryFleet once so all lines share the same session and pool')
        if body.get("schema_version") != "factory-session-checkpoint/0.1" or digest(body) != checkpoint["sha256"]:
            fail("FACTORY_CHECKPOINT_HASH", "Factory/session checkpoint integrity failed")
        if body["controller_source_hashes"] != controller_sources():
            fail("FACTORY_CHECKPOINT_SOURCE", "Controller or finite pool implementation changed; requalification is required")
        obj = cls.__new__(cls)
        obj.protocol = deepcopy(body["protocol"])
        state = body["controller"]
        if state["protocol_hash"] != digest(obj.protocol): fail("FACTORY_PROTOCOL_CHANGED", "Protocol recipe changed")
        obj.session = EventSession.restore(device, body["session"], archive_root=archive_root)
        obj.pool = FiniteResourcePool.restore(body["requirements"], body["initial_state"], state["pool"])
        for field in ("owner", "stage_id", "accepted", "token", "terminal", "lifecycle"):
            setattr(obj, field, deepcopy(state[field]))
        obj.receipts, obj.decisions = deepcopy(state["stage_receipts"]), deepcopy(state["stage_decisions"])
        obj.lease, obj.graph = deepcopy(body["lease"]), deepcopy(body["graph"])
        obj.live_atoms = {obj.pool.qubit_to_atom[q] for q in obj.protocol["live_data_information_qubit_ids"]}
        obj.output_atoms = [obj.pool.qubit_to_atom[q] for q in obj.protocol["output"]["qubit_ids"]]
        obj.output_data = {obj.pool.qubit_to_atom[q] for q in obj.protocol["output"]["qubit_ids"] if "/d" in q}
        if 'consumer_protocol' in state:
            obj.consumer_protocol=deepcopy(state['consumer_protocol']);obj.consumer_binding=deepcopy(state['consumer_binding'])
            obj.live_atoms={obj.pool.qubit_to_atom[q] for q in obj.consumer_protocol['live_data_information_qubit_ids']}
        return obj
