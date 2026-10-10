"""Persistent fake event execution with immutable completed history.

Submissions are future work. Advancing publishes results only at their actual
ready event; state is never rebuilt from an earlier placement between plans.
"""
from copy import deepcopy
from hashlib import sha256
import heapq
from pathlib import Path

from .engine import digest, evidence, number
from .errors import RuntimeContractError, fail
from .scenario import output_ids
from .state import RuntimeState
from .history import write_chunk, verify_chunks


def source_identity():
    root = Path(__file__).resolve().parent
    return {name: sha256((root/name).read_bytes()).hexdigest() for name in ("session.py", "state.py", "engine.py", "errors.py", "scenario.py", "history.py")}


class EventSession:
    def __init__(self, device, initial_state, *, run_id):
        if not isinstance(run_id, str) or not run_id:
            fail("SESSION_ID", "A nonempty run identity is required")
        if initial_state.get("entry_mode") != "preinitialized" or device.get("entry_mode") != "preinitialized":
            fail("SESSION_ENTRY_MODE", "New sessions require explicit preinitialized device and entry")
        if initial_state.get("startup_actions") or initial_state.get("ready_magic_tokens") or initial_state.get("results"):
            fail("SESSION_INITIAL_INVENTORY", "Entry cannot contain startup actions, algorithm returns or ready magic inventory")
        self.device = deepcopy(device)
        self.initial_state = deepcopy(initial_state)
        self.state = RuntimeState(initial_state, device)
        self.run_id = run_id
        self.now_us = number(initial_state.get("time_us", initial_state.get("t_start_us", 0)), "initial clock")
        if self.now_us != 0: fail("SESSION_INITIAL_CLOCK", "Restoring nonzero history requires a checkpoint, not a new preinitialized session")
        self.revision = 0
        self.actions, self.producers, self.completed, self.results = {}, {}, {}, {}
        self.configured, self.pending_results, self.events = {}, {}, {}
        self.leases, self.queue, self.plans = {}, [], []
        self._serial = 0
        self.failure = None
        self._issued_contexts = set()
        self.history_chunks = []
        self._retired_action_prefixes, self._retired_action_ids = set(), set()
        self._retired_result_prefixes, self._retired_result_ids = set(), set()
        self._action_total = self._completed_total = self._result_total = self._plan_total = 0
        self.source_hashes = source_identity()

    def _enqueue(self, at, phase, kind, reference):
        self._serial += 1
        heapq.heappush(self.queue, (at, phase, self._serial, kind, reference))

    def _sync_position(self, at):
        positions = self.state.positions(at)
        for aid, position in positions.items():
            atom = self.state.atoms[aid]
            atom["position_um"] = position
            if atom["carrier"] == "AOD":
                self.state.lines[atom["aod_group"]]["rows"][atom["row_id"]] = position[1]
                self.state.lines[atom["aod_group"]]["columns"][atom["column_id"]] = position[0]

    def snapshot(self):
        return {"schema_version": "event-session-state/0.1", "run_id": self.run_id, "revision": self.revision, "time_us": self.now_us,
                "entry_mode": "preinitialized", "device_hash": digest(self.device), "world_state": self.state.export(self.now_us),
                "published_results": deepcopy(self.results), "pending_result_ids": sorted(self.pending_results),
                "completed_actions": deepcopy(self.completed), "in_flight": sorted(self.state.active),
                "history_chunks": deepcopy(self.history_chunks), "history_storage": "immutable_chunks_plus_live_frontier" if self.history_chunks else "in_memory",
                "leases": {k: sorted(v) for k, v in self.leases.items()}, "illumination_counts": deepcopy(self.state.illumination_counts),
                "history_hash": digest({"completed": self.completed, "results": self.results, "world": self.state.export(self.now_us),
                                        "archived_chain": self.history_chunks[-1]["chain_sha256"] if self.history_chunks else None}),
                "failure": deepcopy(self.failure), "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False}

    def compilation_context(self, physical_dags):
        dags = physical_dags if isinstance(physical_dags, list) else [physical_dags]
        snapshot = self.snapshot()
        published, decisions = {}, {}
        for dag in dags:
            guard = dag.get("execution_guard")
            reads = list(dict.fromkeys(dag.get("external_reads", []) + ([guard["bit"]] if guard else [])))
            for rid in reads:
                if rid not in self.results or self.results[rid]["ready_us"] > self.now_us:
                    fail("RESULT_NOT_READY", "External graph dependency has not been published", result_id=rid)
                record = deepcopy(self.results[rid])
                record["producer_ref"] = {"run_id": self.run_id, "action_id": record["action_id"],
                                          "event_trace_ref": self.run_id+"/trace/"+str(self.revision)}
                published[rid] = record
            nid = dag.get("logical_node_id", dag.get("logical_binding", {}).get("logical_node_id", dag["artifact_id"]))
            decisions[dag["artifact_id"]] = {"physical_dag_sha256": digest(dag), "logical_node_id": nid,
                "execution_guard": deepcopy(guard), "external_reads": deepcopy(dag.get("external_reads", [])),
                "result_refs": {r: deepcopy(published[r]["producer_ref"]) for r in reads},
                "decision": "skip" if guard and published[guard["bit"]]["value"] != guard["equals"] else "execute"}
        context = {"schema_version": "execution-context/0.1", "run_id": self.run_id, "revision": self.revision,
                "time_us": self.now_us, "device_hash": digest(self.device), "world_state_hash": digest(snapshot["world_state"]),
                "history_hash": snapshot["history_hash"], "published_results": published, "graph_decisions": decisions}
        self._issued_contexts.add(digest(context))
        return context

    def validate_context(self, context):
        snapshot = self.snapshot()
        if (context.get("schema_version") != "execution-context/0.1" or context.get("run_id") != self.run_id
                or context.get("revision") != self.revision or context.get("time_us") != self.now_us
                or context.get("device_hash") != digest(self.device)
                or context.get("world_state_hash") != digest(snapshot["world_state"]) or context.get("history_hash") != snapshot["history_hash"]):
            fail("STALE_SESSION_FRONTIER", "Bound plan belongs to another live world/history")
        for rid, record in context["published_results"].items():
            expected = deepcopy(self.results.get(rid))
            if expected is None or expected["ready_us"] > self.now_us or expected["action_id"] not in self.completed:
                fail("SESSION_CONTEXT_RESULT", "Context read is not an actual published result", result_id=rid)
            expected["producer_ref"] = {"run_id": self.run_id, "action_id": expected["action_id"],
                "event_trace_ref": self.run_id+"/trace/"+str(self.revision)}
            if record != expected:
                fail("SESSION_CONTEXT_RESULT", "Context value, readiness or producer differs from actual history", result_id=rid)
        used = set()
        for decision in context["graph_decisions"].values():
            guard = decision["execution_guard"]
            reads = set(decision["external_reads"]) | ({guard["bit"]} if guard else set())
            used.update(reads)
            if not reads <= context["published_results"].keys():
                fail("SESSION_CONTEXT_READS", "Every original graph read/guard needs a published witness")
            refs = {r: context["published_results"][r]["producer_ref"] for r in reads}
            expected_decision = "skip" if guard and context["published_results"][guard["bit"]]["value"] != guard["equals"] else "execute"
            if decision["result_refs"] != refs or decision["decision"] != expected_decision:
                fail("SESSION_CONTEXT_DECISION", "Guard decision or producer references were changed")
        if used != set(context["published_results"]): fail("SESSION_CONTEXT_READS", "Result witnesses must exactly cover graph inputs")
        if digest(context) not in self._issued_contexts:
            fail("SESSION_CONTEXT_NOT_ISSUED", "Original DAG hashes/guards differ from the context issued by this session")
        return True

    def submit(self, atom_program, scenario, *, expected_revision=None):
        if self.failure: fail("SESSION_FAILED", "A failed execution prefix cannot be silently reset or replaced")
        provenance = atom_program.get("provenance", {})
        if provenance.get("requires_runtime_binding") or provenance.get("requires_strategy_binding"):
            fail("SESSION_RUNTIME_INPUTS_UNRESOLVED", "A deferred compile template cannot become executable by changing complete")
        production = (provenance.get("fixture") is not True or bool(provenance.get("backend_used"))
                      or "physical_window" in atom_program.get("input_hashes", {}) or bool(atom_program.get("runtime_requirements")))
        if production and "session_binding" not in atom_program:
            fail("SESSION_BINDING_REQUIRED", "Production windows require a genuine issued execution context and one-way time binding")
        if expected_revision is not None and expected_revision != self.revision:
            fail("STALE_SESSION_FRONTIER", "Submission was compiled against a different session revision")
        if "session_binding" in atom_program:
            context = atom_program["session_binding"]["execution_context"]
            self.validate_context(context)
            if any(d["decision"] != "execute" for d in context["graph_decisions"].values()):
                fail("SESSION_GUARD_FALSE", "A skipped logical graph cannot be submitted for physical execution")
        for obj, label, schema in ((atom_program, "AtomProgram", "AtomProgram/0.2.0-draft"), (scenario, "ScenarioInput", "ScenarioInput/0.2.0-draft")):
            evidence(obj, label)
            if obj.get("schema_version") != schema: fail("SESSION_SCHEMA", f"Unsupported {label} schema")
        if atom_program.get("complete") is not True or atom_program.get("device_ref") != self.device["artifact_id"]:
            fail("SESSION_PLAN_SCOPE", "Only complete declared physical windows for this device may be submitted")
        if atom_program.get("execution_kind") != "compile_plan" or scenario.get("execution_kind") != "scenario":
            fail("SESSION_EVIDENCE", "Submissions need compile-plan/scenario evidence labels")
        expected_device = atom_program.get("input_hashes", {}).get("device")
        if expected_device is not None and expected_device != digest(self.device): fail("DEVICE_HASH_MISMATCH", "Device changed since compilation")
        entry = atom_program["initial_state"]
        actual = self.state.export(self.now_us)
        declared = {a["atom_id"]: a for a in entry["atoms"]}
        current = {a["atom_id"]: a for a in actual["atoms"]}
        if declared.keys() != current.keys(): fail("SESSION_CARRIER_SET", "Plans must retain every current carrier, including spectators")
        for aid, a in current.items():
            if any(declared[aid].get(k) != a.get(k) for k in ("qubit_id", "site_id", "position_um", "carrier", "trap_id", "aod_group", "row_id", "column_id")):
                fail("SESSION_ENTRY_MISMATCH", "Submission would rebuild or teleport the live world", resource_id=aid)
        if entry.get("time_us", self.now_us) != self.now_us: fail("SESSION_ENTRY_CLOCK", "Entry snapshot must be the current committed clock")
        for key in ("aod_rows", "aod_columns"):
            if sorted(entry[key], key=digest) != sorted(actual[key], key=digest):
                fail("SESSION_ENTRY_LINES", "Active AOD axes cannot be rebuilt between windows")
        traps = {t["trap_id"]: deepcopy(t) for t in actual["slm_traps"]}
        for trap in entry["slm_traps"]:
            if trap["trap_id"] in traps:
                if trap != traps[trap["trap_id"]]: fail("SESSION_TRAP_REDEFINED", "Existing static trap/occupancy changed")
            elif trap.get("occupant") is not None:
                fail("SESSION_NEW_OCCUPIED_TRAP", "New static site declarations must be empty")
            else: traps[trap["trap_id"]] = deepcopy(trap)
        check_entry = dict(actual, slm_traps=list(traps.values()))
        RuntimeState(check_entry, self.device)
        proposed, new_producers = {}, {}
        for raw in atom_program["actions"]:
            action = deepcopy(raw)
            for field in ("id", "kind", "atoms", "resources", "source_ids", "depends_on", "payload", "t_start_us", "t_end_us"):
                if field not in action: fail("MISSING_FIELD", f"Action requires {field}", action)
            aid = action["id"]
            if (not isinstance(aid, str) or not aid or aid in self.actions or aid in proposed or aid in self._retired_action_ids
                    or aid.split("/", 1)[0] in self._retired_action_prefixes): fail("SESSION_ACTION_REUSE", "Action namespace was reused", action)
            if action["kind"] not in ("pickup", "move", "drop", "gate", "measure", "reset", "wait", "classical", "rebind"):
                fail("UNSUPPORTED_ACTION", "Unknown physical action", action)
            start, end = number(action["t_start_us"], "t_start_us", action), number(action["t_end_us"], "t_end_us", action)
            if start < self.now_us or end <= start: fail("SESSION_ACTION_TIME", "Future actions require positive duration and cannot rewrite history", action)
            if not action["source_ids"] or len(action["atoms"]) != len(set(action["atoms"])) or not set(action["atoms"]) <= current.keys():
                fail("SESSION_ACTION_IDENTITY", "Action has missing source or invalid physical carriers", action)
            if action["payload"].get("purpose") == "patch_initialization_transport": fail("STARTUP_INITIALIZATION_FORBIDDEN", "ADR-0008 removed startup initialization-zone transport", action)
            condition = action.get("condition")
            if condition is not None and (not isinstance(condition, dict) or set(condition) != {"bit", "equals"} or type(condition["equals"]) is not int or condition["equals"] not in (0, 1)):
                fail("UNSUPPORTED_CONDITION", "Only explicit bit equality is supported", action)
            for rid in output_ids(action):
                if (rid in self.producers or rid in new_producers or rid in self._retired_result_ids
                        or ("/r0/" in rid and rid.rsplit("/r0/", 1)[0] in self._retired_result_prefixes)):
                    fail("SESSION_RESULT_REUSE", "Results are unique across all submitted windows", action, result_id=rid)
                new_producers[rid] = aid
            proposed[aid] = action
        known = {**self.actions, **proposed}
        writers = {**self.producers, **new_producers}
        for action in proposed.values():
            for dependency in action["depends_on"]:
                if dependency not in known or known[dependency]["t_end_us"] > action["t_start_us"]:
                    fail("SESSION_DEPENDENCY", "Physical dependency is absent or ends after its consumer starts", action)
            reads = list(action["payload"].get("reads", action.get("reads", [])))
            if action.get("condition"): reads.append(action["condition"]["bit"])
            for rid in reads:
                if rid not in writers: fail("SESSION_RESULT_PRODUCER", "Read has no producer in the session", action, result_id=rid)
        configured = deepcopy(scenario.get("results"))
        if not isinstance(configured, dict): fail("INVALID_SCENARIO", "Explicit scenario.results object is required")
        for rid, record in configured.items():
            if rid not in new_producers or rid in self.configured: fail("SESSION_SCENARIO_BINDING", "Only this submission's output values may be configured", result_id=rid)
            if record.get("origin") != "fake" or type(record.get("value")) is not int or record["value"] not in (0, 1): fail("INVALID_FAKE_VALUE", "Configured results must be fake integer bits", result_id=rid)
            if "ready_us" in record: number(record["ready_us"], "scenario.ready_us")
        # Atomically install only descriptors. No value is exposed at submission.
        self.state.traps = traps
        self.actions.update(proposed); self.producers.update(new_producers); self.configured.update(configured)
        for action in proposed.values(): self._enqueue(action["t_start_us"], 2, "start", action["id"])
        self.plans.append({"artifact_id": atom_program["artifact_id"], "plan_hash": digest(atom_program), "scenario_id": scenario["artifact_id"],
                           "scenario_hash": digest(scenario), "action_ids": list(proposed), "source_map": deepcopy(atom_program.get("source_map", {})),
                           "submitted_us": self.now_us, "revision": self.revision, "sequence": self._plan_total})
        self._action_total += len(proposed); self._plan_total += 1
        self.revision += 1
        self._issued_contexts.clear()
        return {"run_id": self.run_id, "revision": self.revision, "submitted_action_count": len(proposed), "published_result_count": 0}

    def _read(self, rid, action):
        result = self.results.get(rid)
        if result is None or result["ready_us"] > self.now_us:
            fail("RESULT_NOT_READY", "Session result is not yet published", action, result_id=rid)
        if self.now_us < result["ready_us"]+self.device["timings_us"]["feedback_latency"]:
            fail("FEEDBACK_TOO_EARLY", "Read precedes device feedback latency", action, result_id=rid)
        return deepcopy(result)

    def _start(self, action):
        for dependency in action["depends_on"]:
            if dependency not in self.completed: fail("DEPENDENCY_NOT_COMPLETE", "Source action is not complete", action)
        condition = action.get("condition")
        condition_reads = [self._read(condition["bit"], action)] if condition else []
        selected = not condition or condition_reads[0]["value"] == condition["equals"]
        event = {"action_id": action["id"], "kind": action["kind"], "status": "running" if selected else "skipped",
                 **{k: deepcopy(action[k]) for k in ("atoms", "resources", "source_ids", "depends_on", "payload", "t_start_us", "t_end_us")},
                 "condition": deepcopy(condition), "condition_reads": condition_reads, "reads": [], "result_ids": [],
                 "state_before": self.state.snapshot(action["atoms"]), "state_after": {}}
        if not selected:
            event["state_after"] = deepcopy(event["state_before"])
            self.events[action["id"]] = event; self.completed[action["id"]] = self.now_us
            self._completed_total += 1
            return
        event["reads"] = [self._read(rid, action) for rid in action["payload"].get("reads", action.get("reads", []))]
        self.state.check(action)
        resources = self.state.resource_keys(action)
        for resource in resources:
            if resource in self.leases: fail("RESOURCE_CONFLICT", f"Resource held by {sorted(self.leases[resource])}", action, resource_id=resource)
        outputs = {}
        for rid in output_ids(action):
            planned = number(action["payload"].get("result_ready_us", action["t_end_us"]), "result_ready_us", action)
            if planned < self.state.result_lower_bound(action): fail("RESULT_READY_TOO_EARLY", "Output precedes device latency", action, result_id=rid)
            op = action["payload"].get("operation")
            if action["kind"] == "measure" or op == "fake":
                if rid not in self.configured: fail("MISSING_FAKE_RESULT", "Executed measurement has no explicit fake return", action, result_id=rid)
                config = self.configured[rid]
                ready = config.get("ready_us", planned)
                if ready < planned: fail("RESULT_READY_TOO_EARLY", "Scenario may delay but cannot advance readiness", action, result_id=rid)
                value, derivation = config["value"], "scenario"
            else:
                values = [record["value"] for record in event["reads"]]
                if op == "xor" and values: value = sum(values) % 2
                elif op == "all_zero" and values: value = int(not any(values))
                elif op == "copy" and len(values) == 1: value = values[0]
                elif op == "postprocess_phase":
                    from na_pipeline.frontend import postprocess_phase
                    params = action["payload"].get("params", {})
                    if len(values) != 8 or action["payload"].get("reads") != params.get("bits_msb_first"):
                        fail("POSTPROCESS_BIT_ORDER", "Eight published phase bits must follow the declared MSB-first source order", action)
                    value = postprocess_phase(values, N=params["N"], a=params["a"], origin="fake")
                else: fail("UNSUPPORTED_CLASSICAL", "Unsupported classical expression", action)
                if len(output_ids(action)) != 1: fail("UNSUPPORTED_CLASSICAL", "Classical operations have one output", action)
                ready, derivation = planned, op
            outputs[rid] = {"result_id": rid, "action_id": action["id"], "value": value, "origin": "fake", "ready_us": ready, "derivation": derivation}
        event["result_ids"] = list(outputs)
        event["result_ready_us"] = {rid: value["ready_us"] for rid, value in outputs.items()}
        event["reserved_resources"] = resources
        self.pending_results.update(outputs)
        for resource in resources: self.leases[resource] = {action["id"]}
        self.state.start(action)
        self.events[action["id"]] = event
        self._enqueue(action["t_end_us"], 0, "finish", action["id"])

    def advance(self, to_us=None):
        if self.failure: fail("SESSION_FAILED", "Execution failed; its prefix is retained for diagnosis")
        stop = None if to_us is None else number(to_us, "to_us")
        if stop is not None and stop < self.now_us: fail("SESSION_CLOCK_REWIND", "Clock cannot move backward")
        while self.queue and (stop is None or self.queue[0][0] <= stop):
            at, phase, seq, kind, reference = heapq.heappop(self.queue)
            self.now_us = at; self._sync_position(at)
            try:
                if kind == "start": self._start(self.actions[reference])
                elif kind == "finish":
                    action, event = self.actions[reference], self.events[reference]
                    self.state.finish(action)
                    event["state_after"] = self.state.snapshot(action["atoms"])
                    event["status"] = "completed"
                    self.completed[reference] = at
                    self._completed_total += 1
                    for resource in event.pop("reserved_resources"): self.leases.pop(resource)
                    for rid in event["result_ids"]: self._enqueue(self.pending_results[rid]["ready_us"], 1, "publish", rid)
                elif kind == "publish":
                    record = self.pending_results.pop(reference); record["available_us"] = at
                    self.results[reference] = record
                    self._result_total += 1
                else: fail("SESSION_QUEUE_KIND", "Checkpoint contains an unknown event kind")
                self.revision += 1
            except RuntimeContractError as exc:
                self.failure = {**exc.to_dict(), "time_us": at, "queue_event": [at, phase, seq, kind, reference], "prefix_preserved": True}
                raise
        if stop is not None:
            if stop != self.now_us: self.revision += 1
            self.now_us = stop; self._sync_position(stop)
        return self.snapshot()

    def next_event_us(self):
        return self.queue[0][0] if self.queue else None

    @property
    def submitted_plan_count(self):
        return self._plan_total

    def retire_committed(self, path, *, keep_result_ids=(), keep_action_ids=()):
        """Archive an entirely committed prefix; retain only explicitly live inputs.

        A complete R4 physical-instance namespace is closed when retired. Its
        action/result IDs cannot reappear. Later windows may depend on retained
        producer actions; other cross-window dependencies require keep_action_ids.
        """
        if self.queue or self.failure or self.pending_results or self.state.active:
            fail("HISTORY_PREFIX_NOT_QUIESCENT", "Archive only fully completed actions and published results")
        if not self.plans: fail("HISTORY_NO_NEW_PREFIX", "No newly submitted plan to archive")
        ids = {aid for p in self.plans for aid in p["action_ids"]}
        if any(a not in self.completed for a in ids): fail("HISTORY_PREFIX_INCOMPLETE", "A submitted action has no terminal event")
        results = {r: v for r, v in self.results.items() if v["action_id"] in ids}
        body = {"schema_version": "event-session-chunk/0.1", "run_id": self.run_id, "sequence": len(self.history_chunks),
                "runtime_source_hashes": self.source_hashes, "start_us": self.history_chunks[-1]["end_us"] if self.history_chunks else 0,
                "end_us": self.now_us, "actions": {a: self.actions[a] for a in ids}, "events": {a: self.events[a] for a in ids},
                "results": results, "submitted_plans": self.plans, "final_state": self.state.export(self.now_us),
                "illumination_counts": self.state.illumination_counts, "quantum_state_simulated": False, "hardware_executed": False,
                "sampled": False, "previous_chain_sha256": self.history_chunks[-1]["chain_sha256"] if self.history_chunks else None}
        keep_results = set(keep_result_ids) & self.results.keys()
        keep_actions = set(keep_action_ids) | {self.results[r]["action_id"] for r in keep_results}
        if not keep_actions <= self.actions.keys(): fail("HISTORY_KEEP_ACTION_UNKNOWN", "Retained producer action is absent")
        record = write_chunk(path, body, body["previous_chain_sha256"])
        for aid in ids:
            prefix = aid.split("/", 1)[0]
            if prefix.startswith(("window:", "strategy-instance:")): self._retired_action_prefixes.add(prefix)
            else: self._retired_action_ids.add(aid)
        for rid in results:
            if "/r0/" in rid: self._retired_result_prefixes.add(rid.rsplit("/r0/", 1)[0])
            else: self._retired_result_ids.add(rid)
        self.history_chunks.append(record)
        self.results = {r: self.results[r] for r in keep_results}
        self.producers = {r: self.producers[r] for r in keep_results}
        self.configured = {r: v for r, v in self.configured.items() if r in keep_results}
        self.actions = {a: self.actions[a] for a in keep_actions}
        self.events = {a: self.events[a] for a in keep_actions}
        self.completed = {a: self.completed[a] for a in keep_actions}
        self.plans = []; self._issued_contexts.clear(); self.revision += 1
        return deepcopy(record)

    def checkpoint(self):
        data = {"schema_version": "event-session-checkpoint/0.1", "run_id": self.run_id, "device_hash": digest(self.device),
                "source_hashes": self.source_hashes, "initial_state": deepcopy(self.initial_state), "world_state": self.state.export(self.now_us),
                "illumination_counts": deepcopy(self.state.illumination_counts), "now_us": self.now_us, "revision": self.revision,
                "actions": deepcopy(self.actions), "producers": deepcopy(self.producers), "completed": deepcopy(self.completed),
                "results": deepcopy(self.results), "configured": deepcopy(self.configured), "pending_results": deepcopy(self.pending_results),
                "events": deepcopy(self.events), "leases": {k: sorted(v) for k, v in self.leases.items()}, "queue": deepcopy(self.queue),
                "active_ids": sorted(self.state.active), "plans": deepcopy(self.plans), "serial": self._serial, "failure": deepcopy(self.failure)}
        data["issued_context_hashes"] = sorted(self._issued_contexts)
        data["history_chunks"] = deepcopy(self.history_chunks)
        data["retired_namespaces"] = {key: sorted(getattr(self, key)) for key in ("_retired_action_prefixes", "_retired_action_ids", "_retired_result_prefixes", "_retired_result_ids")}
        data["counters"] = {key: getattr(self, key) for key in ("_action_total", "_completed_total", "_result_total", "_plan_total")}
        return {"body": data, "sha256": digest(data)}

    @classmethod
    def restore(cls, device, checkpoint, *, archive_root=None):
        data = checkpoint["body"]
        if checkpoint.get("sha256") != digest(data) or data.get("schema_version") != "event-session-checkpoint/0.1": fail("SESSION_CHECKPOINT_HASH", "Checkpoint integrity/schema failed")
        if data["device_hash"] != digest(device) or data["source_hashes"] != source_identity(): fail("SESSION_CHECKPOINT_IDENTITY", "Device/runtime source changed; requalification is required")
        obj = cls(device, data["initial_state"], run_id=data["run_id"])
        obj.state = RuntimeState(data["world_state"], device)
        obj.state.illumination_counts = deepcopy(data["illumination_counts"])
        for field in ("actions", "producers", "completed", "results", "configured", "pending_results", "events", "plans", "failure"):
            setattr(obj, field, deepcopy(data[field]))
        obj.now_us, obj.revision, obj._serial = data["now_us"], data["revision"], data["serial"]
        obj.queue = [tuple(event) for event in data["queue"]]; heapq.heapify(obj.queue)
        obj.leases = {k: set(v) for k, v in data["leases"].items()}
        obj.state.active = {aid: obj.actions[aid] for aid in data["active_ids"]}
        obj._issued_contexts = set(data["issued_context_hashes"])
        obj.history_chunks = verify_chunks(data["history_chunks"], archive_root=archive_root)
        for key, values in data["retired_namespaces"].items(): setattr(obj, key, set(values))
        for key, value in data["counters"].items(): setattr(obj, key, value)
        return obj

    def export_trace(self):
        finished = [deepcopy(e) for e in self.events.values() if e["status"] in ("completed", "skipped")]
        complete = not self.queue and self.failure is None
        return {"schema_version": "event-session-trace/0.2" if self.history_chunks else "event-session-trace/0.1", "artifact_id": self.run_id+"/trace/"+str(self.revision),
                "provenance": {"producer": "EventSession", "runtime_source_hashes": self.source_hashes}, "run_id": self.run_id,
                "entry_mode": "preinitialized", "execution_kind": "fake_event_run", "quantum_state_simulated": False,
                "hardware_executed": False, "loss_enabled": False, "sampled": False, "measurement_origin": "fake",
                "complete_submitted_prefix": complete, "full_program_complete": False,
                "submitted_plans": deepcopy(self.plans), "events": finished, "results": deepcopy(self.results),
                "history_chunks": deepcopy(self.history_chunks), "retained_events_may_also_appear_in_chunks": bool(self.history_chunks),
                "final_state": self.state.export(self.now_us), "illumination_counts": deepcopy(self.state.illumination_counts),
                "stats": {"t_start_us": 0, "t_end_us": self.now_us, "duration_us": self.now_us, "action_count": self._action_total,
                          "completed_action_count": self._completed_total, "result_count": self._result_total, "atom_count": len(self.state.atoms)},
                "failure": deepcopy(self.failure)}
