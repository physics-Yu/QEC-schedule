"""Full primitive-cycle planning with explicit groups and pinned Enola decisions."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
import time

from .enola_kernel import StrategyError, capture_closure, digest, group_route
from .geometry import EPS, broadcast_pairs, in_zone, validate_cz_pairs


class StrategyCompiler:
    def projected_broadcast_pairs(self, atoms):
        return broadcast_pairs(atoms, self.zone, self.device["geometry"]["gate_pair_distance_um"],
                               self.device["geometry"]["distance_tolerance_um"])

    def __init__(self, program, device, kernel, config):
        from na_pipeline.device import validate_device
        from na_pipeline.qec import iter_physical_ops
        errors = validate_device(device)
        if errors or "grouped_profile" not in device:
            raise StrategyError("GROUPED_DEVICE_REQUIRED", "T102 device profile must be valid", errors=errors)
        contract = program.get("strategy_contract", {})
        if contract.get("schema_version") != "strategy_contract/0.1":
            raise StrategyError("STRATEGY_CONTRACT_REQUIRED", "R3 full primitive contract is required")
        self.program, self.device, self.kernel, self.config = program, device, kernel, config
        self.contract, self.profile = contract, device["grouped_profile"]
        self.operations = list(iter_physical_ops(program))
        self.byop = {o["id"]: o for o in self.operations}
        self.pending = dict(self.byop); self.done = {}; self.results = {}
        self.actions = []; self.source_map = {o["id"]: [] for o in self.operations}
        self.atoms, self.traps, self.qatom = {}, {}, {}
        self.home, self.readout, self.initial = {}, {}, {}
        self.time = 0.; self.groups = []; self.route_calls = 0; self.candidate_count = 0
        self.zone = {"bounds_um": [device["zones"][device["broadcast"]["zone_id"]][k] for k in ("x_range_um", "y_range_um")]}
        self.operation_name = contract["operation"]["name"]
        self._layout()
        self.initial_state = {"atoms": deepcopy(list(self.atoms.values())), "slm_traps": deepcopy(list(self.traps.values())),
                              "aod_rows": [], "aod_columns": []}

    def _layout(self):
        blocks = list(dict.fromkeys(q["block_id"] for q in self.program["qubits"]))
        for q in self.program["qubits"]:
            qid, block = q["id"], q["block_id"]
            local = qid.rsplit("/", 1)[-1]
            dx = blocks.index(block)*self.config["patch_stride_um"]
            aid = "atom:"+qid
            positions = {}
            for profile_id, target in (("patch_home", self.home), ("patch_initialization", self.initial), ("ancilla_readout", self.readout)):
                layout = self.profile["layouts"][profile_id]
                if local not in layout["slots"]:
                    continue
                pos = list(layout["slots"][local]["position_um"]); pos[0] += dx
                trapid = f"slm:{profile_id}:{qid}"
                self.traps[trapid] = {"trap_id": trapid, "position_um": pos, "zone_id": layout["zone_id"], "occupant": None}
                target[aid] = trapid; positions[profile_id] = pos
            if aid not in self.home or aid not in self.initial:
                raise StrategyError("MISSING_PROFILE_SLOT", "Physical qubit lacks a declared layout slot", qubit=qid)
            start = self.initial[aid] if self.operation_name == "prepare" else self.home[aid]
            self.traps[start]["occupant"] = aid
            self.atoms[aid] = {"atom_id": aid, "qubit_id": qid, "position_um": list(self.traps[start]["position_um"]),
                               "carrier": "SLM", "trap_id": start, "aod_group": q["aod_group"], "row_id": None, "column_id": None}
            self.qatom[qid] = aid

    def emit(self, kind, atoms, duration, sources, payload, *, start=None, condition=None):
        if not math.isfinite(duration) or duration <= 0:
            raise StrategyError("INVALID_ACTION_DURATION", "No zero-duration physical action")
        sources = list(dict.fromkeys(sources))
        ops = [self.byop[s] for s in sources]
        t0 = self.time if start is None else start
        for op in ops:
            for read in op["reads"]:
                if read not in self.results:
                    raise StrategyError("RESULT_NOT_READY", "Source reads an unavailable result", result_id=read)
                t0 = max(t0, self.results[read] + (self.device["timings_us"]["feedback_latency"] if condition else 0))
            t0 = max(t0, *(self.done.get(d, 0.) for d in op["after"]), 0.)
        ids = list(dict.fromkeys([s for op in ops for s in [op["id"], *op["source_ids"]]]))
        resources = {f"atom:{a}" for a in atoms}
        if kind in {"pickup", "drop"}:
            for binding in payload["bindings"]:
                resources.update((f"trap:{binding['from_trap_id']}", f"trap:{binding['to_trap_id']}",
                                  f"aod:{payload['aod_group']}:row:{binding['row_id']}",
                                  f"aod:{payload['aod_group']}:column:{binding['column_id']}"))
        if kind == "move":
            for tr in payload["trajectories"]:
                resources.update((f"aod:{payload['aod_group']}:row:{tr['row_id']}", f"aod:{payload['aod_group']}:column:{tr['column_id']}"))
        if kind == "gate" and payload["name"] == "CZ":
            resources.add(self.device["broadcast"]["resource_id"])
            # Stationary AOD-held atoms keep their axes/traps through the pulse.
            for aid in atoms:
                a = self.atoms[aid]
                if a['carrier'] == 'AOD':
                    resources.update((f"aod:{a['aod_group']}:row:{a['row_id']}",
                                      f"aod:{a['aod_group']}:column:{a['column_id']}",
                                      f"trap:{a['trap_id']}"))
        if kind == "measure":
            resources.add(f"readout-site:{payload['bank_id']}:{payload['site_id']}")
        actionid = f"strategy-action:{len(self.actions):06d}"
        # Explicit total-stage dependency is conservative; same-stage 1q/readout
        # remains parallel. It is a schedule choice, not a hardware global lock.
        dependencies = [a["id"] for a in self.actions if abs(a["t_end_us"]-self.time) < EPS] if self.actions else []
        record = {"physical_op_ids": sources, "source_op_records": {o["id"]: {k: deepcopy(o[k]) for k in ("qubits", "params", "reads", "writes", "condition")} for o in ops},
                  "reads": [], "writes": [], **deepcopy(payload)}
        if len(ops) == 1:
            record.update(physical_op_id=ops[0]["id"], params=deepcopy(ops[0]["params"]),
                          source_reads=deepcopy(ops[0]["reads"]), source_writes=deepcopy(ops[0]["writes"]),
                          source_metadata=deepcopy(ops[0].get("metadata", {})))
        if kind in {"gate", "measure", "reset", "wait", "classical"}:
            record["reads"] = list(dict.fromkeys(r for o in ops for r in o["reads"]))
        action = {"id": actionid, "kind": kind, "atoms": list(atoms), "t_start_us": t0, "t_end_us": t0+duration,
                  "resources": sorted(resources), "source_ids": ids, "depends_on": dependencies,
                  "condition": deepcopy(condition), "payload": record}
        self.actions.append(action)
        for source in sources:
            self.source_map[source].append(actionid)
        return action

    def pickup_group(self, movers, sources, common):
        movers = list(movers)
        groupids = {self.atoms[a]['aod_group'] for a in movers}
        if len(groupids) != 1 or any(self.atoms[a]['carrier'] != 'SLM' for a in movers):
            raise StrategyError('GROUP_CARRIER', 'Pickup needs one SLM/AOD group')
        group = next(iter(groupids))
        closure = capture_closure(list(self.atoms.values()), movers, tolerance=self.device['geometry']['distance_tolerance_um'])
        if set(closure['captured_atoms']) != set(movers):
            raise StrategyError('CAPTURE_CLOSURE_MISMATCH', 'Enabled intersections capture a nonmember', closure=closure, requested=movers)
        bindings = []
        for aid in movers:
            atom=self.atoms[aid];x,y=atom['position_um']
            row=f"{group}:r{closure['y_um'].index(y)}";col=f"{group}:c{closure['x_um'].index(x)}"
            bindings.append({'atom_id':aid,'from_trap_id':atom['trap_id'],'to_trap_id':f'aod:{group}:{row}:{col}',
                             'row_id':row,'column_id':col,'position_um':list(atom['position_um'])})
        action=self.emit('pickup',movers,self.device['timings_us']['pickup'],sources,{**common,'aod_group':group,'bindings':bindings,'capture_closure':closure})
        self.time=action['t_end_us']
        for binding in bindings:
            atom=self.atoms[binding['atom_id']];self.traps[atom['trap_id']]['occupant']=None
            atom.update(carrier='AOD',trap_id=binding['to_trap_id'],row_id=binding['row_id'],column_id=binding['column_id'])
        return action

    def drop_group(self, movers, goals, sources, common):
        bindings=[]
        for aid in movers:
            atom=self.atoms[aid];tid=goals[aid]
            if atom['carrier']!='AOD':raise StrategyError('GROUP_CARRIER','Drop requires AOD-held atoms')
            if self.traps[tid]['occupant'] is not None:raise StrategyError('DESTINATION_OCCUPIED','Group drop requires empty sites',trap_id=tid)
            if math.dist(atom['position_um'],self.traps[tid]['position_um'])>EPS:raise StrategyError('DROP_POSITION','Drop requires actual arrival at its SLM trap',trap_id=tid)
            bindings.append({'atom_id':aid,'from_trap_id':atom['trap_id'],'to_trap_id':tid,
                             'row_id':atom['row_id'],'column_id':atom['column_id'],'position_um':list(atom['position_um'])})
        action=self.emit('drop',list(movers),self.device['timings_us']['drop'],sources,{**common,'bindings':bindings})
        self.time=action['t_end_us']
        for binding in bindings:
            self.traps[binding['to_trap_id']]['occupant']=binding['atom_id']
            self.atoms[binding['atom_id']].update(carrier='SLM',trap_id=binding['to_trap_id'],row_id=None,column_id=None)
        return action

    def transfer(self, movers, goals, sources, *, group_id, purpose, restore=False, after_pickup=None):
        movers=list(movers)
        groupids={self.atoms[a]['aod_group'] for a in movers}
        if len(groupids)!=1:raise StrategyError('GROUP_CARRIER','Transfer needs one SLM/AOD group')
        common={'aod_group':next(iter(groupids)),'group_id':group_id,'purpose':purpose}
        target={a:self.traps[goals[a]]['position_um'] for a in movers}
        self.route_calls+=1
        route,reasons=group_route(list(self.atoms.values()),target,self.device['geometry']['initial_spacing_um'])
        pickup=self.pickup_group(movers,sources,common)
        if after_pickup:
            if any(op['kind'] != 'reset' or not {self.qatom[q] for q in op['qubits']} <= set(movers) for op in after_pickup):
                raise StrategyError('AOD_SERVICE_RESET_SCOPE', 'After-pickup service only resets selected captured atoms')
            self.local_batch(after_pickup)
        self.move_route(route,sources,common)
        dropped=self.drop_group(movers,goals,sources,common)
        return {'pickup_action_id':pickup['id'],'drop_action_id':dropped['id'],'start_us':pickup['t_start_us'],
                'end_us':self.time,'members':movers,'route_rejection_counts':reasons,'restore':restore}

    def move_route(self, route, sources, common):
        for goals in route:
            tr = [{"atom_id": aid, "from_um": list(self.atoms[aid]["position_um"]), "to_um": list(pos),
                   "row_id": self.atoms[aid]["row_id"], "column_id": self.atoms[aid]["column_id"]} for aid, pos in goals.items()]
            duration = max(abs(t["to_um"][i]-t["from_um"][i]) for t in tr for i in (0, 1))/self.device["movement"]["speed_um_per_us"]
            action = self.emit("move", list(goals), duration, sources, {**common, "interpolation": "linear", "trajectories": tr})
            self.time = action["t_end_us"]
            for aid, pos in goals.items():
                self.atoms[aid]["position_um"] = list(pos)

    def finish_op(self, op):
        self.done[op["id"]] = self.time
        self.pending.pop(op["id"])

    def local_batch(self, operations):
        end = self.time
        for op in operations:
            atoms = [self.qatom[q] for q in op["qubits"]]
            kind = op["kind"]
            payload = {}
            if kind == "gate":
                name = op["params"]["name"]
                if name not in self.device["operations"]["native_1q_gates"]:
                    raise StrategyError("UNSUPPORTED_NATIVE_GATE", "Native gate unavailable", name=name)
                payload["name"] = name; duration = self.device["timings_us"]["gate_1q"]
            elif kind == "reset":
                payload["state"] = 0; duration = self.device["timings_us"]["reset"]
                payload['carrier_at_reset'] = {aid: self.atoms[aid]['carrier'] for aid in atoms}
                payload['reset_transport_required'] = False
            elif kind == "wait":
                duration = op["params"]["duration_us"]
            else:
                raise StrategyError("UNSUPPORTED_PRIMITIVE_OP", "No implicit classical semantics", kind=kind)
            action = self.emit(kind, atoms, duration, [op["id"]], payload, condition=op["condition"])
            end = max(end, action["t_end_us"])
        self.time = end
        for op in operations:
            self.finish_op(op)

    def readout_group(self, group):
        members = group["members"]
        ops = [self.byop[m["measurement_op_id"]] for m in members]
        movers = [self.qatom[m["physical_qubit_id"]] for m in members]
        if len(movers) > self.profile["readout"]["bank_capacity"]:
            raise StrategyError("READOUT_CAPACITY_EXCEEDED", "Current strategy requires one full group bank", size=len(movers))
        gid = group["group_id"]
        depart = self.time
        outbound = self.transfer(movers, self.readout, [o["id"] for o in ops], group_id=gid, purpose="maintenance_readout")
        start = self.time; measured = []
        for op, aid, member in zip(ops, movers, members):
            result = op["writes"][0]
            action = self.emit("measure", [aid], self.device["timings_us"]["measure"], [op["id"]],
                {"basis": "Z", "result_id": result, "writes": [result], "origin": "fake", "group_id": gid,
                 "purpose": "maintenance_readout", "bank_id": "bank:"+group["formal_block"], "site_id": member["mz_slot_role"],
                 "earliest_ready_us": start})
            action["payload"]["result_ready_us"] = action["t_end_us"]+self.device["timings_us"]["result_latency"]
            self.results[result] = action["payload"]["result_ready_us"]; measured.append(action)
        self.time = max(a["t_end_us"] for a in measured)
        for op in ops:
            self.finish_op(op)
        reset_ops = [self.byop[m["post_readout_reset_op_id"]] for m in members]
        if not all(all(dep in self.done for dep in op["after"]) for op in reset_ops):
            raise StrategyError("READOUT_RESET_DEPENDENCY", "Declared in-MZ reset has additional unmet dependencies")
        self.local_batch(reset_ops)
        returned = self.transfer(movers, self.home, [o["id"] for o in reset_ops], group_id=gid, purpose="maintenance_readout_return", restore=True)
        for op in reset_ops:
            self.done[op["id"]] = self.time
        self.groups.append({"group_id": gid, "purpose": "maintenance_readout", "members": movers,
            "measurement_action_ids": [a["id"] for a in measured], "result_ids": [a["payload"]["result_id"] for a in measured],
            "readout_start_span_us": max(a["t_start_us"] for a in measured)-min(a["t_start_us"] for a in measured),
            "readout_end_span_us": max(a["t_end_us"] for a in measured)-min(a["t_end_us"] for a in measured),
            "result_ready_span_us": max(a["payload"]["result_ready_us"] for a in measured)-min(a["payload"]["result_ready_us"] for a in measured),
            "per_atom_wait_us": {a: 0. for a in movers}, "earliest_readout_us": {a: start for a in movers},
            "pre_transport_wait_us": {self.qatom[m["physical_qubit_id"]]: depart-max(self.done[d] for d in m["transport_after_op_ids"]) for m in members},
            "transport_batch_count": 2, "split_reasons": [], "outbound": outbound, "return": returned,
            "group_service_duration_us": self.time-depart})

    def select_entangle(self, operations):
        candidates = []
        distance = self.device["geometry"]["gate_pair_distance_um"]
        roles = {self.qatom[q["id"]]: q["role"] for q in self.program["qubits"]}
        for op in operations:
            if op["condition"]:
                raise StrategyError("CONDITIONAL_CX_UNSUPPORTED", "Conditional cross-block semantics not supported")
            pair = [self.qatom[q] for q in op["qubits"]]
            ordered = sorted(pair, key=lambda a: roles[a] not in {"syndrome", "ancilla"})
            for mover in ordered:
                other = next(a for a in pair if a != mover)
                start, fixed = self.atoms[mover]["position_um"], self.atoms[other]["position_um"]
                for dx, dy in ((distance, 0), (-distance, 0), (0, distance), (0, -distance)):
                    goal = [fixed[0]+dx, fixed[1]+dy]
                    self.candidate_count += 1
                    trial = [dict(a, position_um=goal) if a["atom_id"] == mover else a for a in self.atoms.values()]
                    actual = self.projected_broadcast_pairs(trial)
                    if in_zone(goal, self.zone) and actual == [sorted(pair)]:
                        candidates.append({"op_id": op["id"], "pair": pair, "mover": mover, "from_um": list(start), "to_um": goal,
                            "aod_group": self.atoms[mover]["aod_group"], "vector": [start[1], goal[1], start[0], goal[0]]})
        if not candidates:
            raise StrategyError("ENOLA_NO_LAYOUT_CANDIDATE", "Full broadcast geometry has no allowed candidate")
        from .batch_search import select_batch
        return select_batch(self, operations, candidates)

    def entangle(self, operations):
        chosen, receipt, route = self.select_entangle(operations)
        goals = receipt['transport_goals']
        movers = list(goals)
        trial = [dict(a, position_um=goals[a["atom_id"]]) if a["atom_id"] in goals else a for a in self.atoms.values()]
        actual = self.projected_broadcast_pairs(trial)
        source = [c["op_id"] for c in chosen]
        start_index = len(self.actions)
        pre_end = self.time
        for c in chosen:
            op = self.byop[c["op_id"]]
            if op["params"]["name"] == "CX":
                a = self.emit("gate", [self.qatom[op["qubits"][1]]], self.device["timings_us"]["gate_1q"], [op["id"]], {"name": "H", "lowering_rule": "CX=H(target);CZ;H(target)"})
                pre_end = max(pre_end, a["t_end_us"])
        self.time = pre_end
        # A gate endpoint is a stationary AOD configuration, not a new SLM site.
        # Preserve the capture/axis binding until the original SLM return point.
        gid = f"enola-batch:{len(self.kernel.receipts)-1}"
        arrays={g:[a for a in movers if self.atoms[a]['aod_group']==g] for g in route}
        def parallel(actions):
            start=self.time;ends=[]
            for group in arrays:
                self.time=start;actions(group);ends.append(self.time)
            self.time=max(ends)
        def common(group,purpose):
            return {'aod_group':group,'group_id':gid+':'+group,'purpose':purpose}
        parallel(lambda g:self.pickup_group(arrays[g],source,common(g,'enola_cz_transport')))
        parallel(lambda g:self.move_route(route[g],source,common(g,'enola_cz_transport')))
        illuminated = [a["atom_id"] for a in self.atoms.values() if in_zone(a["position_um"], self.zone)]
        pulse = self.emit("gate", illuminated, self.device["timings_us"]["cz"], source,
                         {"name": "CZ", "pairs": actual, "broadcast": True, "zone_id": self.device["broadcast"]["zone_id"],
                          "pair_sources": [{"physical_op_id": c["op_id"], "qubits": self.byop[c["op_id"]]["qubits"], "atoms": c["pair"]} for c in chosen],
                          "enola_decision_hash": receipt["decision_hash"], "carrier_policy": "stationary-aod-held-cz/1"})
        self.time = pulse["t_end_us"]
        return_goals={aid:self.traps[self.home[aid]]['position_um'] for aid in movers}
        from .independent_arrays import route_arrays
        return_routes,proof=route_arrays(self,list(self.atoms.values()),return_goals)
        receipt['independent_array_return_sweep']=proof
        parallel(lambda g:self.move_route(return_routes[g],source,common(g,'enola_cz_return')))
        parallel(lambda g:self.drop_group(arrays[g],self.home,source,common(g,'enola_cz_return')))
        post_end = self.time
        for c in chosen:
            op = self.byop[c["op_id"]]
            if op["params"]["name"] == "CX":
                a = self.emit("gate", [self.qatom[op["qubits"][1]]], self.device["timings_us"]["gate_1q"], [op["id"]], {"name": "H", "lowering_rule": "CX=H(target);CZ;H(target)"})
                post_end = max(post_end, a["t_end_us"])
        self.time = post_end
        receipt["action_ids"] = [a["id"] for a in self.actions[start_index:]]
        receipt["pulse_action_id"] = pulse["id"]
        for c in chosen:
            self.finish_op(self.byop[c["op_id"]])

    def compile(self):
        started = time.perf_counter()
        for group in self.contract["groups"]:
            if group["purpose"] == "patch_initialization_transport":
                movers = [self.qatom[m["physical_qubit_id"]] for m in group["members"]]
                source = list(dict.fromkeys(s for m in group["members"] for s in m["prepare_before_op_ids"]))
                transfer = self.transfer(movers, self.home, source, group_id=group["group_id"], purpose=group["purpose"])
                self.groups.append({"group_id": group["group_id"], "purpose": group["purpose"], "members": movers,
                                    "transport_batch_count": 1, "split_reasons": [], "completion_span_us": 0., "transport": transfer})
        readouts = [g for g in self.contract["groups"] if g["purpose"] == "maintenance_readout"]
        while self.pending:
            ready = [o for o in self.pending.values() if all(p in self.done for p in o["after"])]
            handled = False
            for group in readouts:
                member_ids = [m["measurement_op_id"] for m in group["members"]]
                if all(mid in {o["id"] for o in ready} for mid in member_ids):
                    self.readout_group(group); handled = True; break
            if handled: continue
            local = [o for o in ready if o["kind"] in {"reset", "wait"} or (o["kind"] == "gate" and len(o["qubits"]) == 1)]
            if local:
                self.local_batch(local); continue
            two = [o for o in ready if o["kind"] == "gate" and o["params"]["name"] in {"CX", "CZ"}]
            if two:
                from .se_frontier import select_se_frontier
                two = select_se_frontier(two)
                self.entangle(two); continue
            raise StrategyError("UNSUPPORTED_OR_BLOCKED_SOURCE", "No dependency-safe implemented stage", ready=[o["id"] for o in ready])
        end = max([self.time, *self.results.values()])
        for group in self.groups:
            group["cycle_duration_us"] = end
        exit_state = {"atoms": deepcopy(list(self.atoms.values())), "slm_traps": deepcopy(list(self.traps.values())), "aod_rows": [], "aod_columns": []}
        plan = {"schema_version": "AtomProgram/0.2.0-draft", "artifact_id": "strategy-plan:"+digest(self.program)[:16],
            "producer_version": "na_pipeline.backend.strategy/0.1.0", "provenance": {"owner": "R4", "kb_revision": "kb-0005", "fixture": False,
            "backend_used": "enola_function_kernel", "enola_pin": self.kernel.provenance, "scope": "complete primitive cycle; compile plan only"},
            "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
            "complete": True, "device_ref": self.device["artifact_id"], "input_hashes": {"device": digest(self.device), "physical_program": digest(self.program)},
            "initial_state": self.initial_state, "actions": self.actions, "source_map": self.source_map, "groups": self.groups,
            "stats": {"physical_op_count": len(self.operations), "action_count": len(self.actions), "atom_count": len(self.atoms),
                      "t_start_us": 0., "t_end_us": end, "duration_us": end, "group_metrics": deepcopy(self.groups),
                      "routing_search_count": self.route_calls, "placement_candidate_count": self.candidate_count,
                      "enola_call_counts": dict(self.kernel.calls), "compile_wall_seconds": time.perf_counter()-started}}
        return plan, exit_state
