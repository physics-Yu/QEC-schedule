"""T502 fixture-only lifecycle reducer over an existing, hash-bound trace.

This module does not execute or synthesize a physical factory. Production use
is closed until R3/R4/R0 publish and integrate the complete protocol contract.
It creates no atom actions and never reads ScenarioInput directly.
"""

from copy import deepcopy

from .engine import digest, number
from .errors import fail


def require(condition, code, message, event=None):
    if not condition:
        fail(code, message, event)


def identifiers(value, label, *, nonempty=True):
    require(isinstance(value, list) and all(isinstance(v, str) and v for v in value),
            "FACTORY_ID_SET", f"{label} must be a string list")
    require(len(value) == len(set(value)) and (bool(value) or not nonempty),
            "FACTORY_ID_SET", f"{label} must be unique and nonempty")
    return set(value)


class FactoryLedger:
    """Atomic lifecycle transitions; a protocol test component, not execution.

    Public input/output dictionaries are copied. A failed apply leaves state
    unchanged. Clock and witnesses are bound to the supplied EventTrace.
    """

    def __init__(self, atom_program, event_trace, specification):
        require(specification.get("fixture") is True, "FACTORY_PROTOCOL_NOT_INTEGRATED",
                "R3 production factory protocol is not integrated; only explicit fixture qualification is available")
        require(specification.get("schema_version") == "FactorySpecification/0.1.0-draft",
                "FACTORY_SCHEMA", "Unknown specification version")
        require(isinstance(specification.get("factory_id"), str) and specification["factory_id"] and
                isinstance(specification.get("protocol_ref"), str) and specification["protocol_ref"],
                "FACTORY_PROTOCOL_REF", "Explicit factory and protocol identities are required")
        require(event_trace.get("schema_version") == "EventTrace/0.2.0-draft" and
                event_trace.get("execution_kind") == "fake_event_run" and
                event_trace.get("input_hashes", {}).get("atom_program") == digest(atom_program),
                "FACTORY_TRACE_BINDING", "Lifecycle must refer to the same AtomProgram and EventTrace")
        for flag in ("quantum_state_simulated", "hardware_executed", "loss_enabled", "sampled"):
            require(event_trace.get(flag) is False, "FACTORY_EVIDENCE", f"Trace {flag} must be false")
        self.spec = deepcopy(specification)
        self.trace = deepcopy(event_trace)
        self.initial = {a["atom_id"]: deepcopy(a) for a in atom_program["initial_state"]["atoms"]}
        self.actions = {a["id"]: deepcopy(a) for a in atom_program["actions"]}
        self.events = {e["action_id"]: deepcopy(e) for e in event_trace["events"]}
        require(len(self.events) == len(event_trace["events"]) and set(self.events) == set(self.actions),
                "FACTORY_TRACE_BINDING", "Trace must contain exactly one event for each declared action")
        for aid, ev in self.events.items():
            action = self.actions[aid]
            require(ev.get("status") in ("completed", "skipped") and all(ev.get(k) == action.get(k) for k in ("kind", "atoms", "payload", "t_start_us", "t_end_us")),
                    "FACTORY_TRACE_BINDING", f"Trace event changed the action: {aid}")
        self.pool = identifiers(specification.get("factory_atom_ids"), "factory_atom_ids")
        self.cleanup = identifiers(specification.get("cleanup_atom_ids"), "cleanup_atom_ids")
        require(self.cleanup <= self.pool <= self.initial.keys(), "FACTORY_CARRIER_BINDING",
                "Cleanup must be a subset of declared, present factory atoms")
        self.auxiliary = identifiers(specification.get("consumption_auxiliary_atom_ids", []), "consumption_auxiliary_atom_ids", nonempty=False)
        require(self.auxiliary <= self.pool, "FACTORY_CARRIER_BINDING", "Consumption auxiliaries must be in the factory pool")
        self.limit = number(event_trace["final_state"]["time_us"], "committed trace boundary")
        self.state = {"factory_id": specification["factory_id"], "phase": "idle", "epoch": -1,
                      "attempt_id": None, "request_id": None, "output_id": None,
                      "requests": {}, "attempts": {}, "outputs": {}, "history": [],
                      "last_time_us": atom_program["initial_state"].get("time_us", 0),
                      "event_ids": [], "allocated_action_ids": [], "allocated_result_ids": [],
                      "allocated_candidate_ids": [], "allocated_output_ids": []}

    def _atoms_at(self, at):
        atoms = deepcopy(self.initial)
        for a in atoms.values():
            a.setdefault("reset_epoch", 0)
            a.setdefault("measurement_count", 0)
        completed = sorted((e for e in self.events.values() if e["status"] == "completed" and e["t_end_us"] <= at),
                           key=lambda e: e["t_end_us"])
        for event in completed:
            for aid, record in event["state_after"].items():
                atoms[aid] = deepcopy(record)
        return atoms

    def _witness(self, ids, at, *, skipped=False):
        keys = identifiers(ids, "action witnesses", nonempty=False)
        for aid in keys:
            require(aid in self.events, "FACTORY_MISSING_ACTION", f"Missing physical action {aid}")
            ev = self.events[aid]
            require(ev["t_end_us"] <= at, "FACTORY_UNCOMMITTED_ACTION", f"Physical action {aid} has not completed at this boundary")
            require(ev["status"] == "completed" or skipped, "FACTORY_SKIPPED_WITNESS", f"Skipped action {aid} is not completed evidence")
        return [self.events[aid] for aid in ids]

    def _result(self, rid, at, allowed):
        result = self.trace["results"].get(rid)
        require(result is not None, "FACTORY_MISSING_RESULT", f"No executed return {rid}")
        require(result.get("origin") == "fake" and type(result.get("value")) is int and result["value"] in (0, 1),
                "FACTORY_RESULT_ORIGIN", "Factory decisions use explicit fake measurement bits")
        require(result.get("action_id") in allowed, "FACTORY_RESULT_INSTANCE", "Result belongs to another production/consumption instance")
        ev = self.events[result["action_id"]]
        measurement = ev["kind"] == "measure" and ev["payload"].get("result_id") == rid
        classical = ev["kind"] == "classical" and ev["payload"].get("operation") in ("xor", "all_zero", "copy") and rid in ev["payload"].get("writes", [])
        require(ev["status"] == "completed" and (measurement or classical),
                "FACTORY_RESULT_INSTANCE", "Return has no matching executed measurement or explicit classical producer")
        require(result["ready_us"] <= at and result.get("available_us") == result["ready_us"] and ev["t_end_us"] <= at,
                "FACTORY_RESULT_NOT_READY", f"Return {rid} is not available at the committed boundary")
        return result

    @staticmethod
    def _identity(atom):
        return {key: atom.get(key, 0 if key in ("reset_epoch", "measurement_count") else None)
                for key in ("atom_id", "qubit_id", "reset_epoch", "measurement_count")}

    def _protected(self, state, atoms):
        for request in state["requests"].values():
            if request["status"] == "fulfilled":
                continue
            for aid, original in request["live_identity"].items():
                require(aid in atoms and self._identity(atoms[aid]) == original,
                        "FACTORY_LIVE_DATA_CHANGED", "Active request cannot measure, reset or replace live data carriers")
        oid = state["output_id"]
        if oid is not None:
            output = state["outputs"][oid]
            if output["status"] in ("candidate", "ready", "reserved", "delivered", "consuming"):
                for aid, original in output["identity"].items():
                    actual = self._identity(atoms[aid])
                    if aid not in output["data_atom_ids"]:
                        actual = {k: v for k, v in actual.items() if k in ("atom_id", "qubit_id")}
                        original = {k: v for k, v in original.items() if k in ("atom_id", "qubit_id")}
                    elif output["status"] == "consuming":
                        actual.pop("measurement_count"); original = {k: v for k, v in original.items() if k != "measurement_count"}
                    require(actual == original, "FACTORY_OUTPUT_CHANGED", "Accepted output was reset, replaced or measured before consumption")

    def apply(self, event):
        """Apply one proposed lifecycle boundary, returning an independent snapshot."""
        event = deepcopy(event)
        for key in ("id", "kind", "time_us", "after"):
            require(key in event, "FACTORY_EVENT_FIELD", f"Lifecycle event requires {key}")
        require(isinstance(event["id"], str) and event["id"] and event["id"] not in self.state["event_ids"],
                "FACTORY_EVENT_REUSE", "Lifecycle event IDs are unique")
        at = number(event["time_us"], "factory event time")
        require(self.state["last_time_us"] <= at <= self.limit, "FACTORY_COMMITTED_BOUNDARY",
                "Cannot rewrite history or exceed the committed trace boundary")
        self._witness(event["after"], at)
        state = deepcopy(self.state)
        atoms = self._atoms_at(at)
        self._protected(state, atoms)
        self._coupling_boundary(state, at)
        before = state["phase"]
        handler = getattr(self, "_" + event["kind"], None) if event["kind"] in ("request", "begin", "decide", "make_ready", "reserve", "deliver", "consume_begin", "consume_finish", "cleanup") else None
        require(handler is not None, "FACTORY_UNSUPPORTED_EVENT", "Unknown lifecycle event")
        handler(state, event, atoms)
        state["last_time_us"] = at
        state["event_ids"].append(event["id"])
        state["history"].append({"event": event, "phase_before": before, "phase_after": state["phase"],
                                 "epoch": state["epoch"], "committed_until_us": at})
        self.state = state
        return self.snapshot()

    def _coupling_boundary(self, state, at):
        live = {aid for request in state["requests"].values() if request["status"] != "fulfilled"
                for aid in request["live_block_atom_ids"]}
        for event in self.events.values():
            if event["status"] != "completed" or event["kind"] != "gate" or not state["last_time_us"] < event["t_end_us"] <= at:
                continue
            crossing = [(a, b) for a, b in event["payload"].get("pairs", [])
                        if (a in self.pool and b in live) or (b in self.pool and a in live)]
            if crossing:
                require(state["phase"] == "consuming", "FACTORY_EARLY_COUPLING", "Factory/live-data coupling precedes accepted, delivered token submission")
                output = state["outputs"][state["output_id"]]
                carriers = set(output["carrier_atom_ids"]) | self.auxiliary
                target = set(state["requests"][state["request_id"]]["live_block_atom_ids"])
                require(event["t_start_us"] >= output["consume_start_us"] and
                        all((a in carriers and b in target) or (b in carriers and a in target) for a, b in crossing),
                        "FACTORY_WRONG_COUPLING", "Coupling must bind this output to its designated live data")

    def _request(self, s, e, atoms):
        rid = e.get("request_id")
        require(isinstance(rid, str) and rid and rid not in s["requests"], "FACTORY_REQUEST_REUSE", "Request ID must be new")
        live = identifiers(e.get("live_data_atom_ids"), "live_data_atom_ids")
        block = identifiers(e.get("live_block_atom_ids"), "live_block_atom_ids")
        require(live <= block <= atoms.keys() and not block & self.pool, "FACTORY_LIVE_DATA_BINDING", "Live block must exist and be disjoint from factory carriers")
        require(e.get("resource_kind") in ("T", "TDG"), "FACTORY_RESOURCE_KIND", "Only T/TDG demands are in this proposal")
        s["requests"][rid] = {"status": "pending", "live_data_atom_ids": sorted(live), "live_block_atom_ids": sorted(block), "resource_kind": e["resource_kind"],
                               "live_identity": {aid: self._identity(atoms[aid]) for aid in live}, "requested_at_us": e["time_us"]}

    def _begin(self, s, e, atoms):
        require(s["phase"] == "idle", "FACTORY_BACKPRESSURE", "One in-flight or unconsumed output occupies the supply slot")
        rid = e.get("request_id")
        require(rid in s["requests"] and s["requests"][rid]["status"] == "pending", "FACTORY_REQUEST_STATE", "Begin requires a pending live-data request")
        require(type(e.get("epoch")) is int and e["epoch"] == s["epoch"]+1, "FACTORY_EPOCH", "Attempts require the next factory epoch")
        aid, cid = e.get("attempt_id"), e.get("candidate_id")
        require(isinstance(aid, str) and aid and aid not in s["attempts"] and isinstance(cid, str) and cid and cid not in s["allocated_candidate_ids"],
                "FACTORY_ATTEMPT_REUSE", "Attempt and candidate IDs cannot be reused")
        output = identifiers(e.get("output_atom_ids"), "output_atom_ids")
        data = identifiers(e.get("output_data_atom_ids"), "output_data_atom_ids")
        require(output <= self.cleanup, "FACTORY_OUTPUT_BINDING", "Output carriers must belong to the declared cleanup/factory pool")
        require(data <= output and not data & self.auxiliary, "FACTORY_OUTPUT_BINDING", "Output data is a protected subset distinct from consumption auxiliaries")
        actions = identifiers(e.get("production_action_ids"), "production_action_ids")
        require(not actions & set(s["allocated_action_ids"]), "FACTORY_ACTION_REUSE", "Physical production evidence cannot be reused across attempts")
        for action_id in actions:
            require(action_id in self.actions and self.actions[action_id]["t_start_us"] >= e["time_us"],
                    "FACTORY_PRODUCTION_BOUNDARY", "Production must start at/after this attempt's committed beginning")
            require(set(self.actions[action_id]["atoms"]) <= self.pool, "FACTORY_PRODUCTION_TOUCHES_LIVE_DATA", "Pre-acceptance production cannot touch live data")
        s["attempts"][aid] = {"epoch": e["epoch"], "candidate_id": cid, "request_id": rid,
                               "output_atom_ids": sorted(output), "output_data_atom_ids": sorted(data), "production_action_ids": sorted(actions), "begin_us": e["time_us"]}
        s.update(phase="producing", epoch=e["epoch"], attempt_id=aid, request_id=rid)
        s["requests"][rid]["status"] = "producing"
        s["allocated_candidate_ids"].append(cid)
        s["allocated_action_ids"].extend(sorted(actions))

    def _decide(self, s, e, atoms):
        require(s["phase"] == "producing", "FACTORY_DECISION_STATE", "Decision requires one live candidate")
        attempt = s["attempts"][s["attempt_id"]]
        allowed = set(attempt["production_action_ids"])
        self._witness(attempt["production_action_ids"], e["time_us"], skipped=True)
        checks = e.get("acceptance_checks")
        require(isinstance(checks, list) and checks, "FACTORY_ACCEPTANCE_MAP", "R3 must supply explicit protocol checks; no syndrome-zero default")
        returned, outcomes, check_ids = set(), [], set()
        for check in checks:
            require(isinstance(check.get("id"), str) and check["id"] not in check_ids and type(check.get("expected_parity")) is int and check["expected_parity"] in (0, 1),
                    "FACTORY_ACCEPTANCE_MAP", "Checks require unique IDs and explicit expected parity")
            check_ids.add(check["id"])
            ids = identifiers(check.get("result_ids"), "acceptance result_ids")
            require(not ids & set(s["allocated_result_ids"]), "FACTORY_RESULT_REUSE", "Previous attempt returns cannot drive this decision")
            bits = [self._result(rid, e["time_us"], allowed)["value"] for rid in ids]
            returned |= ids
            outcomes.append({"id": check["id"], "parity": sum(bits) % 2, "expected_parity": check["expected_parity"]})
        oid = e.get("output_id")
        require(isinstance(oid, str) and oid and oid not in s["allocated_output_ids"], "FACTORY_OUTPUT_REUSE", "Output token IDs cannot be recycled, including rejected attempts")
        accepted = all(c["parity"] == c["expected_parity"] for c in outcomes)
        attempt.update(accepted=accepted, checks=outcomes, decision_us=e["time_us"], acceptance_result_ids=sorted(returned))
        s["allocated_result_ids"].extend(sorted(returned))
        s["allocated_output_ids"].append(oid)
        if accepted:
            s["outputs"][oid] = {"status": "candidate", "request_id": s["request_id"], "attempt_id": s["attempt_id"],
                                   "epoch": s["epoch"], "carrier_atom_ids": attempt["output_atom_ids"], "data_atom_ids": attempt["output_data_atom_ids"], "accepted_us": e["time_us"],
                                   "identity": {aid: self._identity(atoms[aid]) for aid in attempt["output_atom_ids"]}}
            s.update(phase="candidate", output_id=oid)
        else:
            s["phase"] = "rejected"

    def _make_ready(self, s, e, atoms):
        output = self._matching(s, e, "candidate")
        ids = identifiers(e.get("phase_conversion_action_ids"), "phase_conversion_action_ids")
        witnesses = self._witness(e["phase_conversion_action_ids"], e["time_us"], skipped=True)
        require(all(ev["t_start_us"] >= output["accepted_us"] and set(ev["atoms"]) <= self.pool for ev in witnesses),
                "FACTORY_PHASE_CONVERSION_BOUNDARY", "Output phase conversion must execute after acceptance on factory carriers")
        require(any(ev["status"] == "completed" and ev["kind"] == "gate" and set(ev["atoms"]) & set(output["data_atom_ids"]) for ev in witnesses),
                "FACTORY_PHASE_CONVERSION_WITNESS", "Accepted candidate is not yet the target resource; conversion action evidence is required")
        for ev in witnesses:
            for rid in ev.get("result_ids", []):
                self._result(rid, e["time_us"], ids)
        output.update(status="ready", ready_us=e["time_us"], phase_conversion_action_ids=sorted(ids))
        s["phase"] = "ready"

    def _matching(self, s, e, phase):
        require(s["phase"] == phase, "FACTORY_OUTPUT_STATE", f"Expected {phase}, got {s['phase']}; consumed outputs cannot be supplied again")
        require(e.get("request_id") == s["request_id"] and e.get("output_id") == s["output_id"],
                "FACTORY_REQUEST_OUTPUT_MISMATCH", "Output must be delivered to its designated live-data request")
        return s["outputs"][s["output_id"]]

    def _reserve(self, s, e, atoms):
        output = self._matching(s, e, "ready")
        output.update(status="reserved", reserved_us=e["time_us"])
        s["phase"] = "reserved"
        s["requests"][s["request_id"]]["status"] = "reserved"

    def _deliver(self, s, e, atoms):
        output = self._matching(s, e, "reserved")
        carriers = identifiers(e.get("output_atom_ids"), "delivery output_atom_ids")
        require(carriers == set(output["carrier_atom_ids"]), "FACTORY_DELIVERY_CARRIER_MISMATCH", "Cannot deliver a copied or substituted output carrier")
        witnesses = self._witness(e["after"], e["time_us"])
        mode = e.get("delivery_mode")
        require(mode in ("transport", "handoff"), "FACTORY_DELIVERY_MODE", "Delivery explicitly distinguishes transport from scheduling handoff")
        require(mode == "handoff" or any(ev["kind"] == "move" and carriers & set(ev["atoms"]) for ev in witnesses),
                "FACTORY_DELIVERY_WITNESS", "Transport delivery requires actual motion evidence")
        require(all(ev["t_start_us"] >= output["reserved_us"] and set(ev["atoms"]) <= carriers for ev in witnesses),
                "FACTORY_DELIVERY_BOUNDARY", "Delivery evidence must move the reserved carriers after reservation")
        output.update(status="delivered", delivered_us=e["time_us"], delivery_mode=mode)
        s["phase"] = "delivered"

    def _consume_begin(self, s, e, atoms):
        output = self._matching(s, e, "delivered")
        output.update(status="consuming", consume_start_us=e["time_us"])
        s["phase"] = "consuming"

    def _consume_finish(self, s, e, atoms):
        output = self._matching(s, e, "consuming")
        ids = identifiers(e.get("consumption_action_ids"), "consumption_action_ids")
        witnesses = self._witness(e["consumption_action_ids"], e["time_us"], skipped=True)
        carriers = set(output["data_atom_ids"])
        live = set(s["requests"][s["request_id"]]["live_data_atom_ids"])
        require(all(ev["t_start_us"] >= output["consume_start_us"] for ev in witnesses),
                "FACTORY_CONSUMPTION_BOUNDARY", "Consumption actions cannot predate token submission")
        allowed = set(output["carrier_atom_ids"]) | set(s["requests"][s["request_id"]]["live_block_atom_ids"]) | self.auxiliary
        adjacency = {aid: set() for aid in allowed}
        for ev in witnesses:
            if ev["status"] == "completed" and ev["kind"] == "gate":
                for a, b in ev["payload"].get("pairs", []):
                    require(a in allowed and b in allowed, "FACTORY_CONSUMPTION_CARRIER", "Coupling includes undeclared protocol carriers")
                    adjacency[a].add(b); adjacency[b].add(a)
        reachable, queue = set(carriers), list(carriers)
        while queue:
            for neighbor in adjacency[queue.pop()]:
                if neighbor not in reachable:
                    reachable.add(neighbor); queue.append(neighbor)
        require(bool(reachable & live), "FACTORY_CONSUMPTION_COUPLING",
                "Need an executed coupling path from output data to designated live data, optionally through declared probes")
        measurements = [ev for ev in witnesses if ev["status"] == "completed" and ev["kind"] == "measure"]
        require(bool(measurements), "FACTORY_CONSUMPTION_READOUT", "Consumption requires its actual measurement circuit")
        for ev in measurements:
            self._result(ev["payload"]["result_id"], e["time_us"], ids)
        output.update(status="consumed", consumed_us=e["time_us"], consumption_action_ids=sorted(ids))
        s["phase"] = "consumed"
        s["requests"][s["request_id"]].update(status="fulfilled", fulfilled_us=e["time_us"], output_id=s["output_id"])

    def _cleanup(self, s, e, atoms):
        require(s["phase"] in ("rejected", "consumed") and e.get("attempt_id") == s["attempt_id"],
                "FACTORY_CLEANUP_STATE", "Only this rejected or consumed attempt may be cleaned")
        attempt = s["attempts"][s["attempt_id"]]
        boundary = attempt["decision_us"] if s["phase"] == "rejected" else s["outputs"][s["output_id"]]["consumed_us"]
        resets = self._witness(e.get("reset_action_ids", []), e["time_us"])
        cleaned = set()
        for ev in resets:
            require(ev["kind"] == "reset" and ev["payload"].get("state") == 0 and ev["t_start_us"] >= boundary,
                    "FACTORY_CLEANUP_WITNESS", "Cleanup requires completed resets after the decision or consumption")
            require(set(ev["atoms"]) <= self.pool, "FACTORY_CLEANUP_LIVE_DATA", "Cleanup cannot release or reset live data")
            cleaned.update(ev["atoms"])
        require(self.cleanup <= cleaned, "FACTORY_INCOMPLETE_CLEANUP", "Every required factory carrier needs actual cleanup")
        if s["phase"] == "rejected":
            s["requests"][s["request_id"]]["status"] = "pending"
        attempt["cleaned_us"] = e["time_us"]
        s.update(phase="idle", attempt_id=None, request_id=None, output_id=None)

    def snapshot(self):
        return {"schema_version": "FactoryLedger/0.1.0-draft", "fixture": True,
                "execution_kind": "protocol_state_fixture", "physical_factory_executed": False,
                "protocol_ref": self.spec["protocol_ref"], "atom_program_ref": self.trace["atom_program_ref"],
                "trace_ref": self.trace["artifact_id"], "quantum_state_simulated": False,
                "hardware_executed": False, "loss_enabled": False, "sampled": False,
                "state": deepcopy(self.state),
                "unverified": ["R3 complete 15-to-1 protocol and acceptance/frame map", "online commit and backpressure enforcement", "R6 independent lifecycle acceptance"]}
