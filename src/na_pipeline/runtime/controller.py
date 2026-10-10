"""Logical block ownership and transactional batches of compiled strategies.

Strategy compilation/binding is delegated exclusively to the public R3/R4
boundaries. Pending geometry is a projection, never an execution receipt.
"""

from copy import deepcopy

from .engine import digest, number, run
from .errors import fail
from .errors import RuntimeContractError
from .state import RuntimeState
from .group_metrics import summarize_groups


def require(test, code, message):
    if not test:
        fail(code, message)


class LogicalBlockController:
    def __init__(self, device, initial_state, *, run_id, strategy_library, binder=None, primitive_builder=None, fixture=False, binding_retry_budget=256):
        require(isinstance(run_id, str) and bool(run_id), "INVALID_RUN_ID", "A stable run_id is required")
        RuntimeState(initial_state, device)
        self._device = deepcopy(device)
        self._world = deepcopy(initial_state)
        self._world.setdefault("time_us", 0)
        self._run_id = run_id
        self._library = strategy_library
        self._binder = binder
        self._builder = primitive_builder
        self._fixture = fixture
        require(type(binding_retry_budget) is int and binding_retry_budget >= 1, "BINDING_BUDGET", "Binding attempts need a positive explicit budget")
        self._binding_retry_budget = binding_retry_budget
        self._blocks, self._planned_blocks = {}, {}
        self._pending, self._history, self._results = [], [], {}
        self._used_calls = set()
        self._strategies, self._result_aliases = {}, {}
        self._encoded_program, self._encoded_call_map = None, {}
        self._counts = {a["atom_id"]: 0 for a in initial_state["atoms"]}
        self._revision = 0

    def register_block(self, logical_id, *, qubits, data_slots, code_profile, layout_profile, lifecycle="unprepared", offset_um=(0, 0)):
        """Register explicit local-slot -> existing physical-qubit bindings."""
        require(not self._pending, "PENDING_REGISTRATION", "Register blocks at a committed boundary")
        require(isinstance(logical_id, str) and logical_id and logical_id not in self._blocks,
                "BLOCK_ID_REUSE", "Logical block ID must be new")
        require(isinstance(qubits, dict) and qubits and len(set(qubits.values())) == len(qubits), "BLOCK_BINDING", "Block slots need unique physical qubits")
        require(isinstance(data_slots, list) and set(data_slots) <= qubits.keys() and data_slots,
                "BLOCK_BINDING", "Protected data slots must be explicitly declared")
        if code_profile.get("code") == "rotated_surface" and code_profile.get("distance") == 3:
            data = {f"d{i}" for i in range(9)}
            slots = data | {f"{basis}{i}" for basis in ("x", "z") for i in range(4)}
            require(set(qubits) == slots and set(data_slots) == data, "SURFACE17_BINDING",
                    "A Surface-17 handle must retain all 17 slots and protect exactly its 9 data carriers")
        require(lifecycle in ("unprepared", "live", "measured"), "BLOCK_LIFECYCLE", "Unknown registration lifecycle")
        by_qubit = {a["qubit_id"]: a["atom_id"] for a in self._world["atoms"]}
        require(set(qubits.values()) <= by_qubit.keys(), "BLOCK_BINDING", "Physical qubits must exist in the world")
        claimed = {q for b in self._blocks.values() for q in b["qubits"].values()}
        require(not claimed & set(qubits.values()), "BLOCK_ALIAS", "A physical qubit cannot belong to two logical blocks")
        block = {"logical_id": logical_id, "qubits": deepcopy(qubits), "atoms": {slot: by_qubit[q] for slot, q in qubits.items()},
                 "data_slots": list(data_slots), "code_profile": deepcopy(code_profile), "layout_profile": layout_profile,
                 "offset_um": list(offset_um),
                 "lifecycle": lifecycle, "ready_at_us": self._world["time_us"], "epoch": 0,
                 "frame": {"status": "physical_corrections_only_no_decoder", "result_ids": []}, "last_call_id": None}
        self._blocks[logical_id] = block
        self._planned_blocks[logical_id] = deepcopy(block)
        return deepcopy(block)

    def _project_world(self, at):
        """Geometry preview only. It neither consumes fake values nor publishes results."""
        world = deepcopy(self._world)
        traps = {t["trap_id"]: t for t in world["slm_traps"]}
        for pending in self._pending:
            for trap in pending["atom_program"]["initial_state"]["slm_traps"]:
                if trap["trap_id"] not in traps:
                    empty = deepcopy(trap); empty["occupant"] = None
                    traps[trap["trap_id"]] = empty
        world["slm_traps"] = list(traps.values())
        state = RuntimeState(world, self._device)
        actions = [a for p in self._pending for a in p["atom_program"]["actions"]]
        for action in sorted(actions, key=lambda a: (a["t_end_us"], a["id"])):
            if action["t_end_us"] <= at:
                require(action.get("condition") is None or action["kind"] in ("gate", "classical", "wait"),
                        "CONDITIONAL_GEOMETRY_UNSUPPORTED", "Cannot project conditional carrier or lifecycle changes")
                state.finish(action)
        for action in actions:
            if action["kind"] == "move" and action["t_start_us"] <= at < action["t_end_us"]:
                state.active[action["id"]] = action
        positions = state.positions(at)
        for aid, xy in positions.items():
            state.atoms[aid]["position_um"] = xy
            atom = state.atoms[aid]
            if atom["carrier"] == "AOD":
                state.lines[atom["aod_group"]]["rows"][atom["row_id"]] = xy[1]
                state.lines[atom["aod_group"]]["columns"][atom["column_id"]] = xy[0]
        return state.export(at)

    def _library_stats(self):
        value = getattr(self._library, "stats", {})
        return deepcopy(value() if callable(value) else value)

    def _geometry_composition(self, candidate, start):
        """Check joint carrier/lease intervals without reading any fake value."""
        plans = [p["atom_program"] for p in self._pending] + [candidate]
        initial = deepcopy(self._world)
        traps = {t["trap_id"]: t for t in initial["slm_traps"]}
        for plan in plans:
            for trap in plan["initial_state"]["slm_traps"]:
                if trap["trap_id"] not in traps:
                    new = deepcopy(trap); new["occupant"] = None; traps[trap["trap_id"]] = new
        initial["slm_traps"] = list(traps.values())
        state = RuntimeState(initial, self._device)
        actions = [a for p in plans for a in p["actions"]]
        new_ids = {a["id"] for a in candidate["actions"]}
        timeline = sorted([(a[t], phase, i, a) for i, a in enumerate(actions) for t, phase in (("t_end_us", 0), ("t_start_us", 1))])
        active, leases = {}, {}
        for at, phase, _, action in timeline:
            aid = action["id"]
            if phase == 0:
                state.finish(action)
                for key in [k for k, holder in leases.items() if holder == aid]: leases.pop(key)
                active.pop(aid, None)
                continue
            try:
                state.check(action)
                keys = state.resource_keys(action)
                conflict = next((k for k in keys if k in leases), None)
                if conflict:
                    fail("RESOURCE_CONFLICT", f"Joint preview lease conflict: {conflict}", action, resource_id=conflict)
            except RuntimeContractError as exc:
                if not self._pending:
                    raise
                old_active = [a for a in active.values() if a["id"] not in new_ids]
                new_active = [a for a in active.values() if a["id"] in new_ids]
                if aid in new_ids and old_active:
                    proposed = max(a["t_end_us"] for a in old_active) - (action["t_start_us"]-start)
                elif aid not in new_ids and new_active:
                    proposed = action["t_end_us"] - min(a["t_start_us"]-start for a in new_active)
                else:
                    raise
                if proposed <= start:
                    raise
                return {"code": "JOINT_"+exc.code, "from_us": start, "to_us": proposed,
                        "details": {"action_id": aid, "active_action_ids": sorted(active), "reason": str(exc)}}
            for key in keys: leases[key] = aid
            state.start(action)
            active[aid] = action
        return None

    def queue_call(self, operation, operands, *, call_id, params=None, qubit_bindings=None, offset_um=None,
                   start_time_us=None, after=(), source_ids=None):
        """Select/reuse one strategy and reserve a distinct instance, without execution."""
        require(operation in ("prepare", "syndrome_round", "logical_cx", "measure", "reset", "release"),
                "LOGICAL_OPERATION_UNSUPPORTED", "Operation has no implemented control semantics")
        require(isinstance(call_id, str) and call_id and call_id not in self._used_calls,
                "CALL_ID_REUSE", "Call IDs remain unique for the entire run")
        expected = {"control", "target"} if operation == "logical_cx" else {"block"}
        require(isinstance(operands, dict) and set(operands) == expected and len(set(operands.values())) == len(operands),
                "LOGICAL_OPERANDS", "Named logical operands and direction must match the operation")
        require(set(operands.values()) <= self._planned_blocks.keys(), "UNKNOWN_LOGICAL_BLOCK", "Operand block is not registered")
        blocks = [self._planned_blocks[lid] for lid in operands.values()]
        if offset_um is None:
            origin_role = "control" if operation == "logical_cx" else "block"
            offset_um = self._planned_blocks[operands[origin_role]]["offset_um"]
        for block in blocks:
            permitted = {"unprepared", "measured"} if operation == "prepare" else {"unprepared", "measured"} if operation == "release" else {"live", "measured"} if operation == "reset" else {"live"}
            require(block["lifecycle"] in permitted, "BLOCK_LIFECYCLE", f"{operation} is not allowed on {block['lifecycle']} block {block['logical_id']}")
        known_calls = {p["call_id"]: p for p in [*self._history, *self._pending]}
        require(all(dep in known_calls for dep in after), "UNKNOWN_CALL_DEPENDENCY", "Every after call must have been committed or queued")
        earliest = max([self._world["time_us"], *(b["ready_at_us"] for b in blocks), *(known_calls[d]["end_us"] for d in after)])
        start = earliest if start_time_us is None else number(start_time_us, "start_time_us")
        require(start >= earliest, "CALL_NOT_READY", "Call starts before its own blocks or dependencies are ready")
        builder = self._builder
        if builder is None:
            try:
                from na_pipeline.qec import build_logical_primitive
                builder = build_logical_primitive
            except ImportError:
                fail("LOGICAL_PRIMITIVE_UNAVAILABLE", "R3 build_logical_primitive is not available")
        stats_before = self._library_stats()
        physical = builder(operation, params=deepcopy(params or {}))
        strategy = self._library.get_or_compile(physical)
        body = strategy.get("body", {})
        require(strategy.get("schema_version") == "compiled-logical-strategy/0.1" and digest(body) == strategy.get("strategy_hash"),
                "STRATEGY_HASH_MISMATCH", "Immutable compiled strategy body does not match its identity")
        backend = body.get("backend_used")
        require(backend in ("enola", "enola_function_kernel") or self._fixture and backend == "fixture",
                "STRATEGY_BACKEND", "No silent fallback to another backend")
        require(body.get("device_hash") == digest(self._device), "STRATEGY_DEVICE_MISMATCH", "Compiled strategy is for another device")
        contract = body.get("strategy_contract", physical.get("strategy_contract", {}))
        require(contract.get("operation", {}).get("name") == operation, "STRATEGY_OPERATION_MISMATCH", "Strategy must implement the requested operation")
        require(contract["operation"].get("params", {}) == (params or {}), "STRATEGY_PARAMETER_MISMATCH", "Compiled parameters differ from requested semantics")
        profile = contract["operation"].get("code_profile")
        if profile is not None:
            require(all(b["code_profile"] == profile for b in blocks), "BLOCK_CODE_PROFILE", "Encoding, orientation or logical convention differs from strategy")
        formal_program = body.get("physical_program")
        formal_atoms = body.get("atom_program", {}).get("initial_state", {}).get("atoms", [])
        require(isinstance(formal_program, dict) and formal_atoms, "STRATEGY_FIELDS", "Strategy needs complete formal physical and atom programs")
        formal_qubits = {q["id"] for q in formal_program["qubits"]}
        if qubit_bindings is None:
            # R3 publishes explicit block/local-slot identity in its contract.
            qubit_bindings = {}
            formals = contract.get("formal_bindings", {}).get("physical_qubits", [])
            require(len(formals) == len(formal_qubits), "EXPLICIT_QUBIT_BINDING_REQUIRED", "R3 formal role mapping is absent")
            for q in formals:
                role = q.get("formal_block")
                slot = q.get("local_role")
                require(role in operands and slot in self._planned_blocks[operands[role]]["qubits"],
                        "EXPLICIT_QUBIT_BINDING_REQUIRED", "Provide complete formal-to-physical qubit_bindings; no implicit identity guess")
                qubit_bindings[q["physical_qubit_id"]] = self._planned_blocks[operands[role]]["qubits"][slot]
        require(set(qubit_bindings) == formal_qubits and len(set(qubit_bindings.values())) == len(qubit_bindings),
                "STRATEGY_QUBIT_BINDING", "Every formal physical qubit requires an injective binding")
        operand_qubits = {q for b in blocks for q in b["qubits"].values()}
        require(set(qubit_bindings.values()) == operand_qubits, "STRATEGY_QUBIT_BINDING", "Bindings must cover the complete operand blocks")
        current = self._project_world(start)
        by_qubit = {a["qubit_id"]: a["atom_id"] for a in current["atoms"]}
        atom_bindings = {a["atom_id"]: by_qubit[qubit_bindings[a["qubit_id"]]] for a in formal_atoms}
        leases = [{"resource_id": r, "t_start_us": a["t_start_us"], "t_end_us": a["t_end_us"], "action_id": a["id"]}
                  for p in self._pending for a in p["atom_program"]["actions"] for r in set(a["resources"]) | {"atom:"+x for x in a["atoms"]}]
        binding = {"schema_version": "logical-call-binding/0.1", "call_id": call_id, "run_id": self._run_id,
                   "epoch": len(self._used_calls), "start_time_us": start, "qubit_bindings": deepcopy(qubit_bindings),
                   "atom_bindings": atom_bindings, "offset_um": list(offset_um), "world_state": current, "resource_leases": leases}
        compiled_stats = self._library_stats()
        retry_records = []
        for attempt in range(self._binding_retry_budget):
            try:
                if self._binder is not None:
                    bound = self._binder(strategy, deepcopy(binding), deepcopy(self._device))
                else:
                    bound = self._library.bind(strategy, deepcopy(binding))
                joint = self._geometry_composition(bound["atom_program"], start)
                if joint is not None:
                    if start_time_us is not None:
                        fail("JOINT_COMPOSITION_CONFLICT", str(joint))
                    retry_records.append(joint)
                    start = joint["to_us"]
                    current = self._project_world(start)
                    binding.update(start_time_us=start, world_state=current)
                    continue
                break
            except Exception as exc:
                code = getattr(exc, "code", None)
                if start_time_us is not None or code not in ("RESOURCE_LEASE_CONFLICT", "ACTIVE_AOD_ENTRY_UNSUPPORTED", "BROADCAST_WORLD_MISMATCH"):
                    raise
                details = getattr(exc, "details", {})
                if code == "RESOURCE_LEASE_CONFLICT":
                    relative = next((a for a in body["atom_program"]["actions"] if call_id+"/"+a["id"] == details.get("action_id")), None)
                    require(relative is not None and "lease" in details, "BINDING_CONFLICT_FIELDS", "Retry requires the exact conflicting action and lease")
                    next_start = details["lease"]["t_end_us"]-relative["t_start_us"]
                else:
                    boundaries = sorted({a["t_end_us"] for p in self._pending for a in p["atom_program"]["actions"]
                                         if a["kind"] == "drop" and a["t_end_us"] > start})
                    require(bool(boundaries), "BINDING_ADAPTATION_REQUIRED", "Composition mismatch has no queued geometry/release boundary; explicit adaptation is required")
                    next_start = boundaries[0]
                require(next_start > start, "BINDING_RETRY_NO_PROGRESS", "Composition retry did not advance past a constraint")
                retry_records.append({"code": code, "from_us": start, "to_us": next_start, "details": deepcopy(details)})
                start = next_start
                current = self._project_world(start)
                binding.update(start_time_us=start, world_state=current)
        else:
            error = RuntimeContractError("BINDING_BUDGET_EXHAUSTED", "No completed binding within the composition-attempt budget; this is not an infeasibility proof")
            error.details = {"attempts": self._binding_retry_budget, "last_start_us": start, "last_retries": retry_records[-8:]}
            raise error
        stats_after = self._library_stats()
        for key in ("strategy_compile_count", "placement_search_count", "routing_search_count"):
            require(stats_after.get(key) == compiled_stats.get(key), "BIND_TRIGGERED_SEARCH", "Binding must not run another layout/routing search")
        require(strategy["strategy_hash"] == digest(strategy["body"]), "STRATEGY_MUTATED", "Binder changed the reusable strategy")
        ap, pp = bound.get("atom_program"), bound.get("physical_program")
        require(isinstance(ap, dict) and isinstance(pp, dict), "BOUND_PROGRAM_MISSING", "Binding must return both complete instance programs")
        require(ap.get("complete") is True and ap.get("device_ref") == self._device["artifact_id"], "BOUND_PROGRAM_INCOMPLETE", "Bound atom program is not complete for this call/device")
        existing_actions = {a["id"] for p in [*self._history, *self._pending] for a in p["atom_program"]["actions"]}
        existing_results = set(self._results) | {a["payload"]["result_id"] for p in self._pending for a in p["atom_program"]["actions"] if a["kind"] == "measure"}
        data_atoms = {b["atoms"][slot] for b in blocks for slot in b["data_slots"]}
        for a in ap["actions"]:
            require(a["id"].startswith(call_id+"/") and a["id"] not in existing_actions, "ACTION_NAMESPACE_REUSE", "Bound action IDs must use this call's namespace")
            require(a["t_start_us"] >= start, "CALL_TIME_REWIND", "Bound actions cannot precede this call")
            if operation in ("syndrome_round", "logical_cx"):
                require(not (a["kind"] in ("measure", "reset") and set(a["atoms"]) & data_atoms), "LIVE_DATA_DESTROYED", "Maintenance/CX cannot reset or measure live data")
            if a["kind"] == "measure":
                rid = a["payload"]["result_id"]
                require(rid.startswith(call_id+"/") and rid not in existing_results, "RESULT_NAMESPACE_REUSE", "Measurement results are instance-local")
        actual_ids = {a["atom_id"] for a in current["atoms"]}
        require({a["atom_id"] for a in ap["initial_state"]["atoms"]} == actual_ids, "WORLD_ATOMS_CHANGED", "Binding must preserve the entire world, including spectators")
        for atom in ap["initial_state"]["atoms"]:
            before = next(a for a in current["atoms"] if a["atom_id"] == atom["atom_id"])
            require(all(atom.get(k) == before.get(k) for k in ("qubit_id", "position_um", "carrier", "trap_id", "aod_group", "row_id", "column_id")),
                    "ENTRY_TELEPORT", "Binding changed the world entry instead of emitting actions")
        end = max([start, *(a["t_end_us"] for a in ap["actions"]), *(a["payload"]["result_ready_us"] for a in ap["actions"] if a["kind"] == "measure")])
        pending = {"call_id": call_id, "operation": operation, "params": deepcopy(params or {}), "operands": deepcopy(operands),
                   "strategy_id": strategy["strategy_id"], "strategy_hash": strategy["strategy_hash"], "backend_used": backend,
                   "binding": binding, "physical_program": deepcopy(pp), "atom_program": deepcopy(ap),
                   "binding_report": deepcopy(bound.get("binding_report", {})), "start_us": start, "end_us": end,
                   "composition_retries": retry_records,
                   "source_ids": list(source_ids or [call_id]), "after": list(after),
                   "formal_result_slots": deepcopy(contract.get("formal_bindings", {}).get("result_slots", [])),
                   "strategy_groups": deepcopy(contract.get("groups", [])),
                   "library_stats_before": stats_before, "library_stats_after": stats_after}
        # No controller mutation occurs until every binding/lifecycle check passes.
        self._pending.append(pending)
        self._used_calls.add(call_id)
        self._strategies[strategy["strategy_id"]] = deepcopy(strategy)
        for block in blocks:
            block["epoch"] += 1
            block["ready_at_us"] = end
            block["last_call_id"] = call_id
            block["lifecycle"] = {"prepare": "live", "measure": "measured", "reset": "unprepared", "release": "released"}.get(operation, "live")
            block["layout_profile"] = contract.get("exit", {}).get("layout_profile_id", block["layout_profile"])
        return deepcopy(pending)

    def pending_program(self):
        require(bool(self._pending), "NO_PENDING_CALLS", "There are no queued calls")
        initial = deepcopy(self._world)
        traps = {t["trap_id"]: t for t in initial["slm_traps"]}
        actions, sources = [], {}
        for p in self._pending:
            for trap in p["atom_program"]["initial_state"]["slm_traps"]:
                if trap["trap_id"] not in traps:
                    empty = deepcopy(trap); empty["occupant"] = None; traps[trap["trap_id"]] = empty
                else:
                    require(traps[trap["trap_id"]]["position_um"] == trap["position_um"], "TRAP_REDEFINED", "Static trap location changed between calls")
            actions.extend(deepcopy(p["atom_program"]["actions"]))
            for source, ids in p["atom_program"]["source_map"].items():
                require(source not in sources, "SOURCE_NAMESPACE_REUSE", "Bound source operation is not unique")
                sources[source] = deepcopy(ids)
        initial["slm_traps"] = list(traps.values())
        return {"schema_version": "AtomProgram/0.2.0-draft", "artifact_id": f"{self._run_id}/batch-{self._revision}",
                "provenance": {"producer": "LogicalBlockController", "fixture": self._fixture, "scope": "queued_strategy_batch"},
                "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
                "complete": True, "complete_scope": "queued_strategy_batch", "device_ref": self._device["artifact_id"],
                "input_hashes": {"device": digest(self._device)}, "initial_state": initial, "actions": actions, "source_map": sources, "stats": {}}

    def execute_pending(self, scenario):
        """Execute all queued calls in one shared timeline, atomically publish success."""
        before_snapshot = self.snapshot()
        program = self.pending_program()
        trace = run(program, scenario, self._device)
        require(not set(trace["results"]) & set(self._results), "RESULT_NAMESPACE_REUSE", "Cannot overwrite a committed result")
        actual_ready = {}
        ready_by_call = {p["call_id"]: p["end_us"] for p in self._history}
        for pending in self._pending:
            for lid in pending["operands"].values():
                require(pending["start_us"] >= actual_ready.get(lid, self._world["time_us"]),
                        "CALL_RESULT_NOT_READY", "Scenario-delayed result leaves a block unavailable for the next call")
            require(all(pending["start_us"] >= ready_by_call[d] for d in pending["after"]),
                    "CALL_RESULT_NOT_READY", "An explicit predecessor has not published all its results")
            own = {a["id"] for a in pending["atom_program"]["actions"]}
            ready = max([pending["end_us"], *(r["ready_us"] for r in trace["results"].values() if r["action_id"] in own)])
            for lid in pending["operands"].values():
                actual_ready[lid] = ready
            ready_by_call[pending["call_id"]] = ready
        for aid, count in trace["illumination_counts"].items():
            self._counts[aid] += count
        self._world = deepcopy(trace["final_state"])
        self._results.update(deepcopy(trace["results"]))
        committed = []
        for pending in self._pending:
            own = {a["id"] for a in pending["atom_program"]["actions"]}
            records = {rid: r for rid, r in trace["results"].items() if r["action_id"] in own}
            pending["end_us"] = max([pending["end_us"], *(r["ready_us"] for r in records.values())])
            pending["result_ids"] = sorted(records)
            pending["status"] = "completed"
            pending["event_trace_ref"] = trace["artifact_id"]
            pending["trace_action_ids"] = sorted(own)
            for slot in pending["formal_result_slots"]:
                physical_id = pending["binding_report"].get("result_bindings", {}).get(slot["result_id"])
                if physical_id in records and "encoded_result_slot" in slot:
                    self._result_aliases[pending.get("encoded_call_id", pending["call_id"])+"/"+slot["encoded_result_slot"]] = physical_id
            for lid in pending["operands"].values():
                self._planned_blocks[lid]["ready_at_us"] = max(self._planned_blocks[lid]["ready_at_us"], pending["end_us"])
                self._planned_blocks[lid]["frame"]["result_ids"].extend(sorted(records))
            committed.append(deepcopy(pending))
        self._blocks = deepcopy(self._planned_blocks)
        self._history.extend(committed)
        self._pending.clear()
        self._revision += 1
        outcome = {"schema_version": "logical-controller-run/0.1", "artifact_id": f"{self._run_id}/execution-{self._revision}",
                "provenance": {"producer": "LogicalBlockController", "fixture": self._fixture},
                "execution_kind": "fake_event_run", "quantum_state_simulated": False, "hardware_executed": False,
                "loss_enabled": False, "sampled": False, "instances": committed, "atom_program": program, "event_trace": trace,
                "strategies": deepcopy(self._strategies), "initial_snapshot": before_snapshot,
                "group_metrics": summarize_groups(program, trace, committed),
                "snapshot": self.snapshot(), "unverified": ["R6 independent strategy and composition qualification", "user_visual_acceptance"]}
        if self._encoded_program is not None:
            outcome.update(encoded_program=deepcopy(self._encoded_program), encoded_call_map=deepcopy(self._encoded_call_map),
                           encoded_result_map=deepcopy(self._result_aliases))
        return outcome

    def queue_encoded_program(self, program):
        """Consume R2's public iterator; queue all calls or restore previous reservations."""
        from na_pipeline.frontend import iter_encoded_calls, validate_encoded_program
        errors = validate_encoded_program(program, require_executable=False)
        require(not errors, "ENCODED_PROGRAM_INVALID", str(errors[:3]))
        for block in program["blocks"]:
            require(block["logical_id"] in self._blocks and self._blocks[block["logical_id"]]["code_profile"] == block["code_profile"],
                    "ENCODED_BLOCK_PROFILE", "Encoded logical blocks must match the registered code/orientation/convention")
        saved = deepcopy((self._pending, self._planned_blocks, self._used_calls, self._strategies, self._encoded_program, self._encoded_call_map))
        calls = list(iter_encoded_calls(program))
        names = {call["id"]: "ec-"+call["id"].encode("utf-8").hex() for call in calls}
        dependencies, last_use = {}, {}
        for call in calls:
            deps = set(call["after"])
            deps.update(last_use[lid] for lid in call["operands"].values() if lid in last_use)
            dependencies[call["id"]] = deps
            for lid in call["operands"].values(): last_use[lid] = call["id"]
        completed, remaining = set(), list(enumerate(calls))
        try:
            while remaining:
                ready = [(index, call) for index, call in remaining if dependencies[call["id"]] <= completed]
                require(bool(ready), "ENCODED_DEPENDENCY_CYCLE", "No logical call is causally ready")
                index, call = min(ready, key=lambda item: (item[1]["operation"] != "prepare", item[0]))
                remaining.remove((index, call))
                require(not call.get("condition") and not call.get("reads"), "ENCODED_FEEDBACK_UNSUPPORTED",
                        "Cross-call logical feedback needs a separate ready boundary; it cannot be preselected")
                backend_id = names[call["id"]]
                self.queue_call(call["operation"], call["operands"], call_id=backend_id, params=call["params"],
                                after=[names[d] for d in call["after"]], source_ids=call["source_ids"])
                self._pending[-1]["encoded_call_id"] = call["id"]
                completed.add(call["id"])
        except Exception:
            self._pending, self._planned_blocks, self._used_calls, self._strategies, self._encoded_program, self._encoded_call_map = saved
            raise
        self._encoded_program, self._encoded_call_map = deepcopy(program), names
        return self.snapshot()

    def result(self, result_id, *, at_us=None):
        at = self._world["time_us"] if at_us is None else number(at_us, "at_us")
        require(at <= self._world["time_us"], "FUTURE_CLOCK", "Cannot query beyond the committed clock")
        result_id = self._result_aliases.get(result_id, result_id)
        require(result_id in self._results and self._results[result_id]["ready_us"] <= at,
                "RESULT_NOT_READY", "Result is not yet published at the requested time")
        return deepcopy(self._results[result_id])

    def snapshot(self):
        return {"schema_version": "logical-controller-state/0.1", "run_id": self._run_id, "revision": self._revision,
                "time_us": self._world["time_us"], "world_state": deepcopy(self._world), "blocks": deepcopy(self._blocks),
                "planned_blocks": deepcopy(self._planned_blocks), "pending_call_ids": [p["call_id"] for p in self._pending],
                "results": deepcopy(self._results), "illumination_counts": deepcopy(self._counts),
                "logical_result_aliases": deepcopy(self._result_aliases),
                "history_hash": digest([{k: p[k] for k in ("call_id", "strategy_hash", "start_us", "end_us")} for p in self._history]),
                "library_stats": self._library_stats(), "fixture": self._fixture}
