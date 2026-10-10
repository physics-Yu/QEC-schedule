"""Causal logical ready-set selection; physical feasibility stays with R4/R6."""
from copy import deepcopy
from collections import deque

from .calendar import ResourceCalendar, finite, require
from .engine import digest
from .errors import RuntimeContractError
from .history import write_chunk, verify_chunks


class LogicalListScheduler:
    def __init__(self, logical_dag, summaries, *, capacities=None):
        require(logical_dag.get("entry_mode") == "preinitialized", "ENTRY_MODE", "T505 requires an explicit preinitialized entry")
        self.dag = deepcopy(logical_dag)
        self.summaries = deepcopy(summaries)
        self.nodes = {}
        self.parents, self.children, self.producers = {}, {}, {}
        for node in self.dag["nodes"]:
            nid = node.get("id")
            require(isinstance(nid, str) and nid and nid not in self.nodes, "DAG_NODE_ID", "Node IDs must be unique")
            require(node.get("source_ids"), "DAG_SOURCE", "Logical source mapping must not be empty")
            require(isinstance(node.get("patch_operands"), dict), "DAG_OPERANDS", "Named patch operands are required")
            self.nodes[nid] = node
            self.parents[nid], self.children[nid] = set(), set()
            for rid in node.get("writes", []):
                require(rid not in self.producers, "DAG_RESULT_REUSE", "Logical result IDs must have exactly one producer")
                self.producers[rid] = nid
        for edge in self.dag["edges"]:
            a, b = edge["source"], edge["target"]
            require(a in self.nodes and b in self.nodes, "DAG_EDGE_NODE", "Edge references absent node")
            require(edge.get("kind") in ("quantum", "classical", "classical_ready", "protocol", "lifecycle"), "DAG_EDGE_KIND", "Dependency semantics must be explicit")
            self.parents[b].add(a); self.children[a].add(b)
        indegree = {nid: len(parents) for nid, parents in self.parents.items()}
        queue = deque(sorted(nid for nid, count in indegree.items() if not count))
        order = []
        while queue:
            nid = queue.popleft(); order.append(nid)
            for child in sorted(self.children[nid]):
                indegree[child] -= 1
                if indegree[child] == 0: queue.append(child)
        require(len(order) == len(self.nodes), "DAG_CYCLE", "Logical DAG contains a cycle")
        self.ancestors = {}
        for nid in order:
            self.ancestors[nid] = set(self.parents[nid])
            for parent in self.parents[nid]: self.ancestors[nid].update(self.ancestors[parent])
            reads = set(self.nodes[nid].get("reads", []))
            condition = self.nodes[nid].get("condition")
            if condition:
                require(set(condition) == {"bit", "equals"} and type(condition["equals"]) is int and condition["equals"] in (0, 1), "DAG_CONDITION", "Only explicit bit equality is supported")
                reads.add(condition["bit"])
            for rid in reads:
                require(rid in self.producers, "DAG_MISSING_PRODUCER", "Every classical read needs a declared producer")
                require(self.producers[rid] in self.ancestors[nid], "DAG_MISSING_CLASSICAL_EDGE", "A read must depend causally on its result producer")
        self.rank = {}
        for nid in reversed(order): self.rank[nid] = 1+max((self.rank[c] for c in self.children[nid]), default=0)
        self.calendar = ResourceCalendar(capacities)
        self.clock_us = 0.0
        self.states = {nid: {"status": "pending"} for nid in self.nodes}
        self.results, self.decisions = {}, []
        self.decision_chunks = []
        self.revision = 0

    def advance(self, to_us):
        at = finite(to_us, "to_us")
        require(at >= self.clock_us, "LOGICAL_CLOCK_REWIND", "Logical clock cannot rewind")
        self.clock_us = at
        self.calendar.advance_floor(at)

    def ready_set(self):
        ready = []
        for nid, node in self.nodes.items():
            if self.states[nid]["status"] != "pending": continue
            if any(self.states[p]["status"] not in ("completed", "skipped") for p in self.parents[nid]): continue
            reads = set(node.get("reads", []))
            if node.get("condition"): reads.add(node["condition"]["bit"])
            if any(rid not in self.results or self.results[rid]["ready_us"] > self.clock_us for rid in reads): continue
            ready.append(nid)
        return sorted(ready, key=lambda nid: (-self.rank[nid], nid))

    def _profile(self, nid):
        summary = self.summaries.get(nid)
        require(isinstance(summary, dict) and summary.get("supported", True), "UNSUPPORTED_LOGICAL_NODE", f"No supported physical resource summary for {nid}")
        duration = finite(summary.get("duration_us"), "duration_us")
        require(duration > 0, "NODE_DURATION", "Unknown duration cannot be silently set to zero")
        intervals = deepcopy(summary.get("intervals", []))
        require(all(i["end_us"] <= duration for i in intervals), "SUMMARY_INTERVAL", "Resource interval exceeds the declared node duration")
        for patch in self.nodes[nid]["patch_operands"].values():
            intervals.append({"resource_id": "patch:"+patch, "start_us": 0, "end_us": duration, "units": 1})
        return summary, intervals

    def propose(self, *, max_nodes=None):
        temp = ResourceCalendar.restore(self.calendar.snapshot())
        ready = self.ready_set()
        selected, rejected, skipped = [], [], []
        for nid in ready:
            node = self.nodes[nid]
            condition = node.get("condition")
            if condition and self.results[condition["bit"]]["value"] != condition["equals"]:
                skipped.append({"node_id": nid, "condition_result": deepcopy(self.results[condition["bit"]])})
                continue
            occupied = {patch for other, state in self.states.items() if state["status"] == "running" for patch in self.nodes[other]["patch_operands"].values()}
            if set(node["patch_operands"].values()) & occupied:
                rejected.append({"node_id": nid, "reason": "patch_in_flight"}); continue
            if max_nodes is not None and len(selected) >= max_nodes:
                rejected.append({"node_id": nid, "reason": "batch_size_limit"}); continue
            summary, intervals = self._profile(nid)
            start = temp.earliest_start(intervals, self.clock_us, feasible_start_intervals=summary.get("feasible_start_intervals"))
            if start > self.clock_us:
                rejected.append({"node_id": nid, "reason": "resource_window", "earliest_start_us": start,
                                 "conflicts_now": temp.conflicts(intervals, self.clock_us)})
                continue
            temp.reserve(nid, intervals, start)
            selected.append({"node_id": nid, "start_us": start, "end_us": start+summary["duration_us"],
                             "intervals": intervals, "source_ids": deepcopy(node["source_ids"])})
        return {"schema_version": "LogicalScheduleBatch/0.1", "logical_dag_hash": digest(self.dag), "base_revision": self.revision,
                "time_us": self.clock_us, "ready_set": ready, "selected": selected, "skipped": skipped, "rejected": rejected,
                "calendar_cost": deepcopy(temp.stats), "physical_feasibility": "requires_R4_joint_plan_and_R6_validation"}

    def reserve(self, batch):
        require(batch.get("base_revision") == self.revision and batch.get("time_us") == self.clock_us and batch.get("logical_dag_hash") == digest(self.dag),
                "STALE_LOGICAL_FRONTIER", "Batch was computed for another DAG/frontier")
        # Recompute from current inputs; caller cannot replace selected intervals
        # or insert a node that was not actually ready.
        expected = self.propose()
        allowed = {item["node_id"]: item for item in expected["selected"]}
        temp = ResourceCalendar.restore(self.calendar.snapshot())
        for selection in batch["selected"]:
            require(selection["node_id"] in allowed and selection == allowed[selection["node_id"]], "LOGICAL_BATCH_CHANGED", "Selected node differs from its current feasible proposal")
            temp.reserve(selection["node_id"], selection["intervals"], selection["start_us"])
        require(batch["skipped"] == expected["skipped"], "LOGICAL_SKIP_CHANGED", "Skipped branches need actual ready condition evidence")
        for selection in batch["selected"]:
            self.states[selection["node_id"]] = {"status": "running", "start_us": selection["start_us"], "reserved_end_us": selection["end_us"]}
        for skip in batch["skipped"]:
            self.states[skip["node_id"]] = {"status": "skipped", "completed_us": self.clock_us, "condition_result": deepcopy(skip["condition_result"])}
        self.calendar = temp
        self.decisions.append(deepcopy(batch)); self.revision += 1

    def joint_candidates(self, *, required_leases=None, max_nodes=None, eligible_nodes=None):
        """Semantic ready batch for R4 joint planning; no guessed physical costs."""
        ready = self.ready_set()
        occupied = {p for n, s in self.states.items() if s["status"] == "running"
                    for p in self.nodes[n]["patch_operands"].values()}
        selected, skipped, rejected = [], [], []
        for nid in ready:
            node, condition = self.nodes[nid], self.nodes[nid].get("condition")
            if condition and self.results[condition["bit"]]["value"] != condition["equals"]:
                skipped.append({"node_id": nid, "condition_result": deepcopy(self.results[condition["bit"]])}); continue
            if eligible_nodes is not None and nid not in eligible_nodes:
                rejected.append({"node_id": nid, "reason": "execution_kind_requires_separate_window"}); continue
            leases = set(node["patch_operands"].values()) | set((required_leases or {}).get(nid, []))
            if leases & occupied:
                rejected.append({"node_id": nid, "reason": "logical_or_pool_lease", "conflicts": sorted(leases & occupied)}); continue
            if max_nodes is not None and len(selected) >= max_nodes:
                rejected.append({"node_id": nid, "reason": "batch_size_limit"}); continue
            occupied.update(leases); selected.append(nid)
        return {"ready_set": ready, "selected_node_ids": selected, "skipped": skipped, "rejected": rejected,
                "physical_feasibility": "pending_joint_compilation"}

    def propose_joint(self, plan):
        """Reconcile actual joint intervals, including a shared broadcast once."""
        require(plan.get("schema_version") == "physical-plan/0.1", "JOINT_PLAN_SCHEMA", "R4 physical-plan/0.1 required")
        temp = ResourceCalendar.restore(self.calendar.snapshot())
        ready = self.ready_set()
        selected, skipped = [], []
        for nid in ready:
            condition = self.nodes[nid].get("condition")
            if condition and self.results[condition["bit"]]["value"] != condition["equals"]:
                skipped.append({"node_id": nid, "condition_result": deepcopy(self.results[condition["bit"]])})
        skip_ids = {s["node_id"] for s in skipped}
        seen = set()
        for dag in plan["physical_dags"]:
            nid = dag.get("logical_node_id", dag.get("logical_binding", {}).get("logical_node_id"))
            require(nid in ready and nid not in skip_ids and nid not in seen, "JOINT_PLAN_NOT_READY", "Every compiled node must be an actual unique ready execute candidate")
            seen.add(nid)
            summary = plan["node_summaries"][dag["artifact_id"]]
            start = self.clock_us+summary["start_us"]
            intervals = deepcopy(summary["intervals"])
            actions = {a["id"]: a for a in plan["atom_program"]["actions"]}
            for lease in intervals:
                aid = lease["action_id"]
                require(aid in actions and aid in summary["action_ids"], "JOINT_INTERVAL_ACTION", "Real intervals require a concrete shared action")
                action = actions[aid]
                require(lease["resource_id"] in action["resources"] and
                        abs(lease["start_us"]+summary["start_us"]-action["t_start_us"]) < 1e-8 and
                        abs(lease["end_us"]+summary["start_us"]-action["t_end_us"]) < 1e-8,
                        "JOINT_INTERVAL_TIME", "Resource offsets must match the actual action")
                lease["share_key"] = "joint-action:"+aid
            for resource in set(self.nodes[nid]["patch_operands"].values()) | set(dag.get("required_leases", [])):
                intervals.append({"resource_id": "logical-lease:"+resource, "start_us": 0,
                                  "end_us": summary["duration_us"], "units": 1})
            temp.reserve(nid, intervals, start)
            selected.append({"node_id": nid, "start_us": start, "end_us": self.clock_us+summary["end_us"],
                             "intervals": intervals, "action_ids": deepcopy(summary["action_ids"]), "source_ids": deepcopy(self.nodes[nid]["source_ids"])})
        rejected = [{"node_id": n, "reason": "not_in_joint_plan"} for n in ready if n not in seen | skip_ids]
        return {"schema_version": "LogicalScheduleBatch/0.1", "logical_dag_hash": digest(self.dag), "base_revision": self.revision,
                "time_us": self.clock_us, "ready_set": ready, "selected": selected, "skipped": skipped, "rejected": rejected,
                "calendar_cost": deepcopy(temp.stats), "physical_plan_hash": digest(plan), "physical_feasibility": "R4_joint_plan_R6_pending"}

    def reserve_joint(self, plan, proposal):
        require(proposal == self.propose_joint(plan), "STALE_OR_CHANGED_JOINT_PROPOSAL", "Joint feedback changed since proposal")
        temp = ResourceCalendar.restore(self.calendar.snapshot())
        for selection in proposal["selected"]: temp.reserve(selection["node_id"], selection["intervals"], selection["start_us"])
        for selection in proposal["selected"]:
            self.states[selection["node_id"]] = {"status": "running", "start_us": selection["start_us"], "reserved_end_us": selection["end_us"]}
        for skip in proposal["skipped"]:
            self.states[skip["node_id"]] = {"status": "skipped", "completed_us": self.clock_us, "condition_result": deepcopy(skip["condition_result"])}
        self.calendar = temp
        self.decisions.append(deepcopy(proposal)); self.revision += 1

    def _check_results(self, node_id, results):
        require(set(results) <= set(self.nodes[node_id].get("writes", [])) and not set(results) & self.results.keys(),
                "LOGICAL_RESULT_COVERAGE", "Logical outputs must be declared and published once")
        for rid, result in results.items():
            kind = self.dag.get("result_types", {}).get(rid, "bit")
            value = result.get("value")
            valid = (type(value) is int and value in (0, 1)) if kind == "bit" else (
                kind == "postprocess_record" and isinstance(value, dict) and value.get("schema_version") == "PhasePostprocess/0.1.0"
                and value.get("origin") == "fake" and value.get("status") in ("success", "failed"))
            require(result.get("origin") == "fake" and valid, "LOGICAL_RESULT_ORIGIN", "Result must match its declared bit or classical report type")
            require(result.get("producer_node_id", node_id) == node_id, "LOGICAL_RESULT_INSTANCE", "Result belongs to another node")
            ready = finite(result.get("ready_us"), "ready_us")
            require(ready <= self.clock_us and ready >= self.states[node_id]["start_us"], "LOGICAL_RESULT_NOT_READY", "Future or previous-instance values cannot be published")

    def publish_results(self, node_id, results, *, event_trace_ref):
        require(node_id in self.states and self.states[node_id]["status"] in ("running", "completed") and bool(event_trace_ref),
                "LOGICAL_NODE_STATE", "Only actual in-flight/completed producers may publish results")
        self._check_results(node_id, results)
        for rid, result in results.items():
            self.results[rid] = dict(deepcopy(result), producer_node_id=node_id, event_trace_ref=event_trace_ref)
        self.revision += 1

    def commit_ready_skips(self):
        ready = self.ready_set()
        skipped = []
        for nid in ready:
            condition = self.nodes[nid].get("condition")
            if condition and self.results[condition["bit"]]["value"] != condition["equals"]:
                record = {"node_id": nid, "condition_result": deepcopy(self.results[condition["bit"]])}
                skipped.append(record)
                self.states[nid] = {"status": "skipped", "completed_us": self.clock_us, "condition_result": record["condition_result"]}
        if skipped:
            self.decisions.append({"time_us": self.clock_us, "ready_set": ready, "selected": [], "skipped": skipped,
                                   "rejected": [{"node_id": n, "reason": "not_selected_in_skip_only_step"} for n in ready if n not in {s["node_id"] for s in skipped}]})
            self.revision += 1
        return skipped

    def begin_protocol(self, node_id, protocol, lease):
        require(node_id in self.ready_set() and self.nodes[node_id]["operation"] in ("T", "TDG"), "PROTOCOL_NODE_NOT_READY", "Adaptive node must be genuinely ready")
        condition = self.nodes[node_id].get("condition")
        require(not condition or self.results[condition["bit"]]["value"] == condition["equals"], "PROTOCOL_GUARD_FALSE", "False request cannot start production")
        require(protocol["logical_binding"]["logical_node_id"] == node_id and lease["epoch"] == protocol["epoch"] and
                lease["target_patch"] == self.nodes[node_id]["patch_operands"]["block"], "PROTOCOL_BINDING", "Factory must lease this node's actual target")
        self.states[node_id] = {"status": "running", "start_us": self.clock_us, "adaptive_protocol": protocol["artifact_id"],
                               "epoch": protocol["epoch"], "reserved_end_us": None, "duration_status": "determined_by_executed_adaptive_path"}
        self.decisions.append({"time_us": self.clock_us, "ready_set": self.ready_set()+[node_id],
            "selected": [{"node_id": node_id, "protocol_ref": protocol["artifact_id"], "resources": deepcopy(lease["resources"])}],
            "skipped": [], "rejected": [{"node_id": n, "reason": "single_adaptive_protocol_window"} for n in self.ready_set()]})
        self.revision += 1

    def record_protocol_stage(self, node_id, plan, receipt, *, origin_us):
        require(self.states[node_id].get("adaptive_protocol") == receipt["protocol_id"], "PROTOCOL_STAGE_OWNER", "Stage belongs to another logical request")
        owner = node_id+"/"+str(receipt["epoch"])+"/"+receipt["stage_id"]
        self.calendar.reserve(owner, plan["resource_intervals"], origin_us)
        self.decisions.append({"time_us": origin_us, "ready_set": [], "selected": [{"node_id": node_id,
            "stage_id": receipt["stage_id"], "action_ids": deepcopy(receipt["action_ids"]), "resource_intervals": deepcopy(plan["resource_intervals"])}],
            "skipped": [], "rejected": [], "kind": "in_flight_adaptive_stage", "receipt": deepcopy(receipt)})
        self.revision += 1

    def begin_magic_consumption(self,node_id,producer,consumer,lease,token,reservation):
        """Attach ready stock to an actual ready T node; production ran independently."""
        require(node_id in self.ready_set(),'PROTOCOL_NODE_NOT_READY','Consumer logical node must be ready')
        node=self.nodes[node_id];source=consumer.get('fleet_logical_source')
        require(source==node and node['operation'] in ('T','TDG') and consumer['request_gate']==node['operation'] and
                consumer['data_block_id']==node['patch_operands']['block'],'PROTOCOL_BINDING','Consumer must preserve the original logical source')
        condition=node.get('condition')
        require(not condition or self.results[condition['bit']]['value']==condition['equals'],'PROTOCOL_GUARD_FALSE','False logical request cannot consume stock')
        port=reservation['output_port'];link=consumer.get('consumer_link',{})
        require(link.get('producer_protocol_hash')==digest(producer) and reservation['consumer_protocol_hash']==digest(consumer)
                and token['status']=='reserved' and token['token_id']==port['token_id'] and
                token['epoch']==lease['epoch']==producer['epoch'] and token['target_patch']==node['patch_operands']['block']
                and token['request_id']==consumer['request_id'] and port['ready_us']<=self.clock_us,
                'PROTOCOL_STOCK_BINDING','Ready stock, producer, lease and consumer must share one proven reservation')
        self.states[node_id]={'status':'running','start_us':self.clock_us,'adaptive_protocol':consumer['artifact_id'],
            'producer_protocol':producer['artifact_id'],'consumer_request_id':consumer['request_id'],'token_id':token['token_id'],
            'consumer_protocol_hash':digest(consumer),'producer_protocol_hash':digest(producer),'output_atom_ids':list(token['output_atom_ids']),
            'factory_owner':lease['owner'],'epoch':lease['epoch'],'reserved_end_us':None,'duration_status':'actual_consumer_path'}
        self.decisions.append({'kind':'ready_magic_consumption_begin','time_us':self.clock_us,'selected':[{
            'node_id':node_id,'producer_protocol':producer['artifact_id'],'consumer_protocol':consumer['artifact_id'],
            'token_id':token['token_id'],'resources':deepcopy(lease['resources'])}],'ready_set':self.ready_set(), 'skipped':[], 'rejected':[]})
        self.revision+=1

    def complete_magic_consumption(self,node_id,ledger):
        state=self.states[node_id];consumer=ledger.get('consumer_protocol',{});token=ledger.get('token') or {}
        require(state.get('adaptive_protocol')==consumer.get('artifact_id') and state.get('producer_protocol')==ledger['protocol_ref']
                and token.get('token_id')==state['token_id'] and token.get('status')=='consumed' and ledger['terminal']=='consumed'
                and digest(consumer)==state['consumer_protocol_hash'] and ledger['protocol_hash']==state['producer_protocol_hash']
                and token.get('output_atom_ids')==state['output_atom_ids']
                and ledger['epoch']==state['epoch'] and ledger['owner']==state['factory_owner']
                and ledger['owner'] not in ledger['pool']['active_leases'] and
                token['target_patch']==self.nodes[node_id]['patch_operands']['block'] and token['request_id']==state['consumer_request_id'],
                'PROTOCOL_NOT_CONSUMED','This consumer needs actual same-token consumption and its own factory cleanup')
        required={'consume','consume_cleanup'}
        require(required<={r['stage_id'] for r in ledger['stage_receipts']},'PROTOCOL_CONSUMPTION_EVIDENCE','Actual consume and cleanup receipts are required')
        self.states[node_id]=dict(state,status='completed',completed_us=self.clock_us,factory_execution=deepcopy(ledger))
        self.revision+=1

    def retry_protocol(self, node_id, protocol, lease, rejected, *, ledger_ref):
        current = self.states[node_id]
        require(current.get("adaptive_protocol") == rejected["protocol_ref"] and rejected["terminal"] == "rejected"
                and rejected["token"] is None and not rejected["pool"]["active_leases"],
                "PROTOCOL_RETRY_BEFORE_CLEANUP", "Retry requires the prior rejected attempt and actual released pool")
        require(protocol["logical_binding"]["logical_node_id"] == node_id and protocol["epoch"] == rejected["pool"]["next_epoch"]
                and lease["epoch"] == protocol["epoch"] and lease["target_patch"] == self.nodes[node_id]["patch_operands"]["block"],
                "PROTOCOL_RETRY_BINDING", "Retry must use a fresh pool epoch for the same original T request")
        history = deepcopy(current.get("attempt_history", [])) + [deepcopy(ledger_ref)]
        self.states[node_id] = dict(current, adaptive_protocol=protocol["artifact_id"], epoch=protocol["epoch"], attempt_history=history)
        self.decisions.append({"kind": "adaptive_retry_after_reject_cleanup", "time_us": self.clock_us, "ready_set": [],
            "selected": [{"node_id": node_id, "protocol_ref": protocol["artifact_id"], "epoch": protocol["epoch"]}],
            "skipped": [], "rejected": [], "prior_attempt": deepcopy(ledger_ref)})
        self.revision += 1

    def complete_protocol(self, node_id, state, *, ledger_ref=None):
        current = self.states[node_id]
        require(current.get("adaptive_protocol") == state["protocol_ref"] and state["epoch"] == current["epoch"], "PROTOCOL_COMPLETION_IDENTITY", "Completion belongs to another epoch")
        require(state["terminal"] == "consumed" and isinstance(state.get("token"), dict) and state["token"]["status"] == "consumed" and not state["pool"]["active_leases"],
                "PROTOCOL_NOT_CONSUMED", "T completes only after actual single-use consumption and cleanup")
        evidence = {"factory_execution_ref": deepcopy(ledger_ref), "factory_execution_hash": digest(state),
                    "token_id": state["token"]["token_id"]} if ledger_ref else {"factory_execution": deepcopy(state)}
        self.states[node_id] = dict(current, status="completed", completed_us=self.clock_us, reserved_end_us=self.clock_us, **evidence)
        self.revision += 1

    def complete(self, node_id, receipt, results=None):
        require(node_id in self.states and self.states[node_id]["status"] == "running", "LOGICAL_NODE_STATE", "Only running nodes may complete")
        state = self.states[node_id]
        require(not state.get("adaptive_protocol"), "ADAPTIVE_COMPLETION_REQUIRED", "Adaptive T completion requires its execution-bound factory ledger")
        end = finite(receipt.get("completed_us"), "completed_us")
        require(state["start_us"] <= end <= self.clock_us and end <= state["reserved_end_us"], "LOGICAL_COMPLETION_TIME", "Receipt exceeds current time or reserved resource window")
        require(receipt.get("node_id") == node_id and receipt.get("event_trace_ref") and receipt.get("physical_plan_ref"),
                "LOGICAL_RECEIPT", "Completion must reference the same physical plan and actual event trace")
        results = results or {}
        self._check_results(node_id, results)
        for rid, result in results.items():
            self.results[rid] = dict(deepcopy(result), producer_node_id=node_id, event_trace_ref=receipt["event_trace_ref"])
        self.states[node_id] = dict(state, status="completed", completed_us=end, receipt=deepcopy(receipt))
        self.revision += 1

    def snapshot(self):
        return {"schema_version": "LogicalSchedule/0.2" if self.decision_chunks else "LogicalSchedule/0.1", "entry_mode": "preinitialized", "logical_dag_hash": digest(self.dag),
                "clock_us": self.clock_us, "revision": self.revision, "nodes": deepcopy(self.states), "results": deepcopy(self.results),
                "calendar": self.calendar.snapshot(), "decisions": deepcopy(self.decisions), "decision_chunks": deepcopy(self.decision_chunks),
                "complete": all(s["status"] in ("completed", "skipped") for s in self.states.values()) and all(
                    rid in self.results for rid, producer in self.producers.items() if self.states[producer]["status"] != "skipped"),
                "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False}

    def retire_decisions(self, path):
        require(bool(self.decisions), "NO_LOGICAL_DECISIONS", "No new scheduler decisions to archive")
        body = {"schema_version": "logical-decision-chunk/0.1", "logical_dag_hash": digest(self.dag),
                "decisions": self.decisions, "start_us": self.decisions[0]["time_us"], "end_us": self.clock_us,
                "actions": [], "results": {}, "submitted_plans": []}
        record = write_chunk(path, body, self.decision_chunks[-1]["chain_sha256"] if self.decision_chunks else None)
        self.decision_chunks.append(record); self.decisions = []
        return deepcopy(record)

    def checkpoint(self):
        from hashlib import sha256
        from pathlib import Path
        root = Path(__file__).resolve().parent
        sources = {n: sha256((root/n).read_bytes()).hexdigest() for n in ("logical_scheduler.py", "calendar.py")}
        body = {"schema_version": "logical-scheduler-checkpoint/0.1", "state": self.snapshot(),
                "summaries": deepcopy(self.summaries), "source_hashes": sources}
        return {"body": body, "sha256": digest(body)}

    @classmethod
    def restore(cls, logical_dag, checkpoint, *, decision_root=None):
        body = checkpoint["body"]
        require(digest(body) == checkpoint["sha256"] and body.get("schema_version") == "logical-scheduler-checkpoint/0.1", "LOGICAL_CHECKPOINT_HASH", "Checkpoint integrity/schema failed")
        obj = cls(logical_dag, body["summaries"])
        state = body["state"]
        require(body["source_hashes"] == obj.checkpoint()["body"]["source_hashes"] and state["logical_dag_hash"] == digest(logical_dag),
                "LOGICAL_CHECKPOINT_IDENTITY", "DAG or scheduler implementation changed")
        obj.states, obj.results, obj.decisions = deepcopy(state["nodes"]), deepcopy(state["results"]), deepcopy(state["decisions"])
        obj.clock_us, obj.revision = state["clock_us"], state["revision"]
        obj.calendar = ResourceCalendar.restore(state["calendar"])
        obj.decision_chunks = verify_chunks(state["decision_chunks"], archive_root=decision_root)
        return obj
