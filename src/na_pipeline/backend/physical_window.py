"""Joint complete-operation window compiler, with a single real world/AOD state.

The public input is the existing R3 expanded PhysicalProgram operation record,
plus its declared readout groups. PhysicalDAG adapters retain typed edges above it.
No old per-strategy binding or fabricated per-patch AOD resources are used.
"""
from __future__ import annotations

from copy import deepcopy
import math
import time

from .enola_kernel import StrategyError, digest
from .joint_kernel import JointEnolaKernel
from .enola_scheduler import EnolaReadyScheduler
from .strategy_compile import StrategyCompiler
from .geometry import broadcast_pairs, in_zone


class PhysicalWindowCompiler(StrategyCompiler):
    def __init__(self, operations, groups, device, initial_state, *, enola_root=None, budget=None, external_reads=()):
        from na_pipeline.device import validate_device
        errors = validate_device(device)
        if errors or device.get("entry_mode") != "preinitialized":
            raise StrategyError("PREINITIALIZED_DEVICE_REQUIRED", "R1 current profile required", errors=errors)
        self.budget = {"max_operations": 100000, "max_wall_seconds": 300.}
        if budget:
            if set(budget)-set(self.budget):
                raise StrategyError("PHYSICAL_BUDGET", "Unknown window budget fields")
            self.budget.update(budget)
        if type(self.budget["max_operations"]) is not int or self.budget["max_operations"] <= 0:
            raise StrategyError("PHYSICAL_BUDGET", "Positive max_operations required")
        if type(self.budget["max_wall_seconds"]) not in (int, float) or not math.isfinite(self.budget["max_wall_seconds"]) or self.budget["max_wall_seconds"] <= 0:
            raise StrategyError("PHYSICAL_BUDGET", "Positive max_wall_seconds required")
        if len(operations) > self.budget["max_operations"]:
            raise StrategyError("PHYSICAL_BUDGET_EXHAUSTED", "Complete window exceeds declared operation budget; no truncation", complete=False)
        self.device, self.profile = deepcopy(device), device["grouped_profile"]
        self.scheduler = EnolaReadyScheduler(enola_root)
        self.operations = deepcopy(operations)
        # A ready-only coupling leaf has already committed its source batch.
        self.closed_coupling_batch = bool(operations) and all(o['kind']=='gate' and len(o['qubits'])==2 and not o['after'] for o in operations)
        self.window_id = digest({"operations": operations, "groups": groups, "device": device, "entry": initial_state})[:24]
        self.byop = {o["id"]: o for o in self.operations}
        if len(self.byop) != len(self.operations):
            raise StrategyError("PHYSICAL_ID_COLLISION", "Window operation IDs must be unique")
        required = {"id", "kind", "qubits", "params", "reads", "writes", "condition", "source_ids", "after"}
        for op in self.operations:
            if required-set(op) or any(dep not in self.byop for dep in op["after"]):
                raise StrategyError("PHYSICAL_WINDOW_DEPENDENCY", "Full fields and internal dependency endpoints required", operation=op["id"])
            if op["condition"] and (op["kind"] != "gate" or len(op["qubits"]) != 1):
                raise StrategyError("CONDITIONAL_OPERATION_UNSUPPORTED", "Only conditional single-qubit corrections supported inside window", operation=op["id"])
        self.pending, self.done, self.results = dict(self.byop), {}, {
            r: float(external_reads[r]) if isinstance(external_reads, dict) else 0. for r in external_reads}
        self.external_reads = set(external_reads)
        self.actions, self.groups = [], []
        self.source_map = {o["id"]: [] for o in self.operations}
        self.contract = {"groups": deepcopy(groups)}
        self.atoms = {a["atom_id"]: deepcopy(a) for a in initial_state["atoms"]}
        concurrency=self.device['concurrency']
        independent=all(concurrency[k] for k in ('independent_aod_parallel','independent_transfer_parallel')) and not concurrency['global_motion_lock']
        self.kernel = JointEnolaKernel(enola_root, self.atoms, self.device["geometry"]["distance_tolerance_um"], self.budget["max_wall_seconds"],independent_arrays=independent)
        self.traps = {t["trap_id"]: deepcopy(t) for t in initial_state["slm_traps"]}
        self.qatom = {a.get("site_id", a["qubit_id"]): a["atom_id"] for a in self.atoms.values()}
        if len(self.qatom) != len(self.atoms):
            raise StrategyError("QUBIT_BINDING_COLLISION", "Every atom must have its own physical qubit identity")
        if initial_state["aod_rows"] or initial_state["aod_columns"] or any(a["carrier"] != "SLM" for a in self.atoms.values()):
            raise StrategyError("WINDOW_ACTIVE_AOD_UNSUPPORTED", "Joint window currently requires an empty AOD commit boundary; active states need another planner")
        if any(q not in self.qatom for op in self.operations for q in op["qubits"]):
            raise StrategyError("PHYSICAL_QUBIT_UNBOUND", "All window qubits must already exist in the continuous world")
        self.home = {aid: a["trap_id"] for aid, a in self.atoms.items()}
        self.readout, self.initial = {}, {}
        self.time = 0.
        self.route_calls = self.candidate_count = 0
        self.zone = {"bounds_um": [device["zones"][device["broadcast"]["zone_id"]][k] for k in ("x_range_um", "y_range_um")]}
        self.operation_name = "joint_physical_window"
        self.bank_map = {}
        self.single_readout = {}
        blocks = list(dict.fromkeys(a.get("patch_id") or a["qubit_id"].rsplit("/", 1)[0] for a in self.atoms.values()))
        slots = self.profile["layouts"]["ancilla_readout"]["slots"]
        step = max(device["patch_geometry"]["cell_extent_um"])
        for aid, a in self.atoms.items():
            block = a.get("patch_id") or a["qubit_id"].rsplit("/", 1)[0]
            local = a.get("local_id") or a["qubit_id"].rsplit("/", 1)[-1]
            bank_x = blocks.index(block) * step
            self.bank_map[block] = {"bank_id": "bank:"+block, "x_offset_um": bank_x,
                                    "anchor_mode": "global_mz_with_independent_bank_x"}
            # Non-group destructive data/probe measurements use one of the same
            # declared bank sites, sequentially; there is no fictitious ninth lane.
            receiver = local if local in slots else next(iter(slots))
            pos = list(slots[receiver]["position_um"])
            pos[0] += bank_x  # Never add patch y to global MZ coordinates.
            tid = "slm:readout:"+block+"/"+receiver
            if tid in self.traps and self.traps[tid]["position_um"] != pos:
                raise StrategyError("READOUT_BANK_BINDING_CHANGED", "An existing static bank cannot move between windows")
            self.traps.setdefault(tid, {"trap_id": tid, "position_um": pos, "zone_id": "measurement", "occupant": None})
            self.single_readout[aid] = {"trap_id": tid, "bank_id": "bank:"+block, "site_id": receiver}
            if local in slots:
                self.readout[aid] = tid
        self.program = {"qubits": [{"id": q, "role": "syndrome" if (self.atoms[a].get("local_id") or q.rsplit("/", 1)[-1])[:1] in {"x", "z"} else "data"}
                                     for q, a in self.qatom.items()]}
        self.initial_state = {"atoms": deepcopy(list(self.atoms.values())), "slm_traps": deepcopy(list(self.traps.values())),
                              "aod_rows": [], "aod_columns": []}
        self.ready_decisions = []
        self._broadcast_projection = None
        self.measurement_placements = []

    def projected_broadcast_pairs(self, atoms):
        """Exact all-world graph update: preserve unchanged edges, recalc every moved endpoint.

        This only reuses geometry inside this compile. Spectator edges and all
        moved-to-background distances remain visible; no execution result is cached.
        """
        key = tuple((a["atom_id"], *a["position_um"]) for a in self.atoms.values())
        distance = self.device["geometry"]["gate_pair_distance_um"]
        tolerance = self.device["geometry"]["distance_tolerance_um"]
        if self._broadcast_projection is None or self._broadcast_projection[0] != key:
            baseline = broadcast_pairs(list(self.atoms.values()), self.zone, distance, tolerance)
            self._broadcast_projection = (key, baseline)
        baseline = self._broadcast_projection[1]
        moved = {a["atom_id"] for a in atoms if a["position_um"] != self.atoms[a["atom_id"]]["position_um"]}
        pairs = {tuple(pair) for pair in baseline if not moved.intersection(pair)}
        visible = [a for a in atoms if in_zone(a["position_um"], self.zone)]
        changed = [a for a in visible if a["atom_id"] in moved]
        for a in changed:
            for b in visible:
                if a["atom_id"] != b["atom_id"] and abs(math.dist(a["position_um"], b["position_um"])-distance) <= tolerance:
                    pairs.add(tuple(sorted((a["atom_id"], b["atom_id"]))))
        return [list(pair) for pair in sorted(pairs)]

    def emit(self, kind, atoms, duration, sources, payload, **kwargs):
        reads = {r for s in sources for r in self.byop[s]["reads"]}
        if reads:
            if any(r not in self.results for r in reads):
                raise StrategyError("RESULT_NOT_READY", "Window has a read before its physical producer")
            kwargs["start"] = max(kwargs.get("start", self.time),
                                  max(self.results[r] + self.device["timings_us"]["feedback_latency"] for r in reads))
        action = super().emit(kind, atoms, duration, sources, payload, **kwargs)
        old_id = action["id"]
        action["id"] = "window:" + self.window_id + "/" + old_id
        for source in dict.fromkeys(sources):
            self.source_map[source][-1] = action["id"]
        return action

    def measure_single(self, op):
        if op["params"].get("basis") != "Z" or len(op["qubits"]) != 1 or len(op["writes"]) != 1:
            raise StrategyError("UNSUPPORTED_MEASUREMENT", "Physical Z readout with one atom and one explicit result required")
        aid = self.qatom[op["qubits"][0]]
        receiver = self.single_readout[aid]
        self.transfer([aid], {aid: receiver["trap_id"]}, [op["id"]], group_id="readout:"+op["id"], purpose="individual_readout")
        result = op["writes"][0]
        action = self.emit("measure", [aid], self.device["timings_us"]["measure"], [op["id"]],
                           {"basis": "Z", "result_id": result, "writes": [result], "origin": "fake",
                            "bank_id": receiver["bank_id"], "site_id": receiver["site_id"], "purpose": "individual_readout",
                            "earliest_ready_us": self.time})
        action["payload"]["result_ready_us"] = action["t_end_us"] + self.device["timings_us"]["result_latency"]
        self.results[result] = action["payload"]["result_ready_us"]
        self.time = action["t_end_us"]
        self.transfer([aid], self.home, [op["id"]], group_id="readout:"+op["id"], purpose="individual_readout_return", restore=True)
        self.finish_op(op)

    def measure_batch(self, operations):
        """Optional explicit source batch: place, legally transport, jointly read, return."""
        from .measurement_placement import place_measurement_batch
        if any(o['params'].get('basis') != 'Z' or len(o['qubits']) != 1 or len(o['writes']) != 1 or o.get('condition') for o in operations):
            raise StrategyError('UNSUPPORTED_MEASUREMENT', 'Batch readout requires distinct single-qubit unconditional Z results')
        if operations[0]['metadata']['measurement_placement'] == 'rigid_array_translation':
            return self.measure_rigid_batch(operations)
        movers = [self.qatom[o['qubits'][0]] for o in operations]
        gid = operations[0]['metadata']['measurement_batch']
        sites = []
        for block, bank in self.bank_map.items():
            for slot in self.profile['layouts']['ancilla_readout']['slots']:
                tid = 'slm:readout:'+block+'/'+slot
                trap = self.traps[tid]
                sites.append({**deepcopy(trap), 'bank_id': bank['bank_id'], 'site_id': slot})
        placement = place_measurement_batch([self.atoms[a] for a in movers], sites,
                                            speed_um_per_us=self.device['movement']['speed_um_per_us'])
        placement['batch_id'] = gid
        placement['source_operations'] = [o['id'] for o in operations]
        assignments = {a['atom_id']: a for a in placement['assignments']}
        source_traps = {a: self.atoms[a]['trap_id'] for a in movers}
        outbound_goals = {a: assignments[a]['trap_id'] for a in movers}
        split_reasons = []
        def transport(goals, purpose):
            # AOD-compatible source rows are attempted together. A rejected
            # preflight can split movement without serializing the readout pulse.
            rows = {}
            for aid in movers:
                atom = self.atoms[aid]
                rows.setdefault((atom['aod_group'], atom['position_um'][1]), []).append(aid)
            records = []
            for group in rows.values():
                count = len(self.actions)
                try:
                    records.append(self.transfer(group, goals, [o['id'] for o in operations], group_id=gid, purpose=purpose))
                except StrategyError as exc:
                    if len(group) == 1 or len(self.actions) != count:
                        raise
                    split_reasons.append({'purpose': purpose, 'atoms': list(group), 'reason': exc.code})
                    for aid in group:
                        records.append(self.transfer([aid], goals, [o['id'] for o in operations], group_id=gid, purpose=purpose))
            return records
        depart = self.time
        outbound = transport(outbound_goals, 'parallel_measurement_outbound')
        start = self.time
        measured = []
        for op, aid in zip(operations, movers):
            target = assignments[aid]
            result = op['writes'][0]
            a = self.emit('measure', [aid], self.device['timings_us']['measure'], [op['id']],
                          {'basis': 'Z', 'result_id': result, 'writes': [result], 'origin': 'fake',
                           'group_id': gid, 'purpose': 'parallel_circuit_measurement',
                           'bank_id': target['bank_id'], 'site_id': target['site_id'], 'earliest_ready_us': start}, start=start)
            a['payload']['result_ready_us'] = a['t_end_us']+self.device['timings_us']['result_latency']
            self.results[result] = a['payload']['result_ready_us']
            measured.append(a)
        self.time = max(a['t_end_us'] for a in measured)
        returned = transport(source_traps, 'parallel_measurement_return')
        for op in operations:
            self.finish_op(op)
        placement.update(routing_verified=True, outbound=outbound, returned=returned,
                         start_us=depart, measurement_start_us=start, measurement_end_us=measured[0]['t_end_us'],
                         result_ready_us=measured[0]['payload']['result_ready_us'], end_us=self.time,
                         measurement_action_ids=[a['id'] for a in measured], split_reasons=split_reasons)
        self.measurement_placements.append(placement)

    def measure_rigid_batch(self, operations, *, group_id=None, service_resets=None, allow_readout_waves=False):
        from .rigid_measurement import rigid_measurement_placement
        measured=[self.qatom[o['qubits'][0]] for o in operations]
        placement=rigid_measurement_placement(list(self.atoms.values()),measured,list(self.traps.values()),self.device, allow_readout_waves=allow_readout_waves)
        self.route_calls+=placement['placement_route_searches']
        gid=group_id or operations[0]['metadata']['measurement_batch'];sources=[o['id'] for o in operations]
        placement.update(batch_id=gid,source_operations=sources)
        assignments={a['atom_id']:a for a in placement['assignments']}
        movers=placement['captured_atoms']
        original_traps={a:self.atoms[a]['trap_id'] for a in movers}
        for site in placement['candidate_sites']:
            if site['trap_id'] not in self.traps:
                trap={k:deepcopy(site[k]) for k in ('trap_id','position_um','zone_id','occupant')}
                self.traps[trap['trap_id']]=trap
                # Receiver SLM pattern is part of the compiled initial equipment,
                # not a physical trap teleported into place during playback.
                self.initial_state['slm_traps'].append(deepcopy(trap))
        depart=self.time;start_action=len(self.actions)
        outbound=self.transfer(movers,{a:assignments[a]['trap_id'] for a in movers},sources,group_id=gid,purpose='rigid_measurement_outbound')
        read_start=self.time;readouts=[]
        capacity=placement['max_parallel_readouts']
        wave_size=capacity if capacity is not None else len(operations)
        for index,(op,aid) in enumerate(zip(operations,measured)):
            wave_start=read_start+(index//wave_size)*self.device['timings_us']['measure']
            target=assignments[aid];result=op['writes'][0]
            action=self.emit('measure',[aid],self.device['timings_us']['measure'],[op['id']],
                             {'basis':'Z','result_id':result,'writes':[result],'origin':'fake','group_id':gid,
                              'purpose':'parallel_circuit_measurement','bank_id':target['bank_id'],'site_id':target['site_id'],
                              'earliest_ready_us':read_start},start=wave_start)
            action['payload']['result_ready_us']=action['t_end_us']+self.device['timings_us']['result_latency']
            self.results[result]=action['payload']['result_ready_us'];readouts.append(action)
        self.time=max(a['t_end_us'] for a in readouts)
        if service_resets:
            for op in operations:self.finish_op(op)
            if not all(all(dep in self.done for dep in op['after']) for op in service_resets):
                raise StrategyError('READOUT_RESET_DEPENDENCY','Service reset has an unmet source dependency')
        return_sources=[o['id'] for o in service_resets] if service_resets else sources
        returned=self.transfer(movers,original_traps,return_sources,group_id=gid,purpose='rigid_measurement_return',restore=True,
                               after_pickup=service_resets)
        # Enforce shape preservation for every emitted segment, including detours.
        for action in self.actions[start_action:]:
            if action['kind']=='move':
                tr=action['payload']['trajectories'];vector=[tr[0]['to_um'][k]-tr[0]['from_um'][k] for k in (0,1)]
                if set(action['atoms'])!=set(movers) or any(abs(t['to_um'][k]-t['from_um'][k]-vector[k])>1e-8 for t in tr for k in (0,1)):
                    raise StrategyError('RIGID_SHAPE_VIOLATION','Every segment must move the complete captured array by one vector')
                action['payload']['rigid_translation_um']=vector
                action['payload']['spectator_atoms']=placement['spectator_atoms']
        if service_resets:
            for op in service_resets:self.done[op['id']]=self.time
        else:
            for op in operations:self.finish_op(op)
        placement.update(routing_verified=True,outbound=[outbound],returned=[returned],start_us=depart,
                         measurement_start_us=read_start,measurement_end_us=max(a['t_end_us'] for a in readouts),
                         result_ready_us=max(a['payload']['result_ready_us'] for a in readouts),end_us=self.time,
                         readout_wave_count=len({a['t_start_us'] for a in readouts}),
                         readout_start_span_us=max(a['t_start_us'] for a in readouts)-read_start,
                         measurement_action_ids=[a['id'] for a in readouts],split_reasons=[])
        self.measurement_placements.append(placement)
        return placement

    def readout_group(self, group):
        if 'rigid_readout' not in self.device:
            return super().readout_group(group)
        return self.readout_groups([group])

    def readout_groups(self, groups):
        from collections import defaultdict
        arrays=defaultdict(list)
        for g in groups:
            arrays[self.atoms[self.qatom[g['members'][0]['physical_qubit_id']]]['aod_group']].append(g)
        if len(arrays)>1:
            return self.readout_independent_arrays(arrays)
        return self.readout_one_array(groups)

    def readout_independent_arrays(self, arrays):
        from .independent_arrays import separate_sweep_envelopes
        start=self.time;scene=deepcopy(list(self.atoms.values()));parts=[];paths={}
        for ag,groups in arrays.items():
            a0=len(self.actions);g0=len(self.groups);p0=len(self.measurement_placements);begin=self.time
            self.readout_one_array(groups)
            actions=self.actions[a0:];ids={m[k] for g in groups for m in g['members'] for k in ('measurement_op_id','post_readout_reset_op_id')}
            parts.append((begin,actions,self.groups[g0:],self.measurement_placements[p0:],ids))
            paths[ag]=[{t['atom_id']:t['to_um'] for t in a['payload']['trajectories']} for a in actions if a['kind']=='move']
            if not paths[ag]:paths[ag]=[{aid:list(self.atoms[aid]['position_um']) for p in self.measurement_placements[p0:] for aid in p['captured_atoms']}]
        all_sources=set().union(*(p[4] for p in parts))
        cross_edges=[(s,d) for _,_,_,_,ids in parts for s in ids for d in self.byop[s]['after'] if d in all_sources-ids]
        try:
            c=self.device['concurrency']
            if not all(c[k] for k in ('independent_aod_parallel','independent_transfer_parallel','independent_measure_parallel','independent_reset_parallel')) or c['global_motion_lock'] or c['global_measure_lock']:
                raise StrategyError('DEVICE_INDEPENDENT_READOUT_DISABLED','Retain sequential service for the declared device')
            capacity=self.device['rigid_readout']['max_parallel_readouts']
            if capacity is not None and sum(len(g['members']) for gs in arrays.values() for g in gs)>capacity:
                raise StrategyError('INDEPENDENT_READOUT_CAPACITY','Joint arrays exceed the declared total parallel readout capacity')
            if cross_edges:raise StrategyError('READOUT_CROSS_ARRAY_SOURCE_DEPENDENCY','Cannot remove a source edge to align readouts',edges=cross_edges)
            proof=separate_sweep_envelopes(scene,paths,self.device['geometry']['distance_tolerance_um'])
        except StrategyError as exc:
            for _,_,_,placements,_ in parts:
                for p in placements:p['independent_array_parallelism']={'qualified':False,'reason':exc.code}
            return
        all_actions={a['id'] for _,aa,_,_,_ in parts for a in aa}
        timekeys={'start_us','end_us','t_start_us','t_end_us','result_ready_us','earliest_ready_us','measurement_start_us','measurement_end_us'}
        def shifted(v,delta):
            if isinstance(v,list):return [shifted(x,delta) for x in v]
            if not isinstance(v,dict):return v
            return {k:(x+delta if k in timekeys and type(x) in (int,float) else
                       {q:t+delta for q,t in x.items()} if k=='earliest_readout_us' else shifted(x,delta)) for k,x in v.items()}
        ends=[]
        for begin,actions,group_records,placements,ids in parts:
            delta=start-begin;own={a['id'] for a in actions}
            for a in actions:
                a.update(shifted(a,delta));a['depends_on']=[d for d in a['depends_on'] if d not in all_actions or d in own]
            for record in group_records+placements:record.update(shifted(record,delta))
            for record in group_records:
                record['pre_transport_wait_us']={a:max(0.,t+delta) for a,t in record['pre_transport_wait_us'].items()}
            for s in ids:
                self.done[s]+=delta
                for r in self.byop[s]['writes']:self.results[r]+=delta
            for p in placements:p['independent_array_parallelism']={'qualified':True,'sweep':proof,'common_start_us':start}
            ends.extend(a['t_end_us'] for a in actions)
        self.time=max(ends)

    def readout_one_array(self, groups):
        members=[m for group in groups for m in group['members']]
        ops=[self.byop[m['measurement_op_id']] for m in members]
        resets=[self.byop[m['post_readout_reset_op_id']] for m in members]
        depart=self.time
        pre_transport_wait={self.qatom[m['physical_qubit_id']]:depart-max((self.done[d] for d in m['transport_after_op_ids']), default=0.) for m in members}
        gid=groups[0]['group_id'] if len(groups)==1 else 'joint-readout:'+digest([g['group_id'] for g in groups])[:20]
        placement=self.measure_rigid_batch(ops,group_id=gid,service_resets=resets)
        placement['source_group_ids']=[g['group_id'] for g in groups]
        for group in groups:
            members=group['members'];qids={self.qatom[m['physical_qubit_id']] for m in members}
            measurements=[a['id'] for a in self.actions if a['kind']=='measure' and a['id'] in placement['measurement_action_ids'] and set(a['atoms'])<=qids]
            self.groups.append({'group_id':group['group_id'],'purpose':'maintenance_readout',
                            'members':[self.qatom[m['physical_qubit_id']] for m in members],
                            'measurement_action_ids':measurements,
                            'result_ids':[m['result_id'] for m in members],
                            'readout_start_span_us':0.,'readout_end_span_us':0.,'result_ready_span_us':0.,
                            'per_atom_wait_us':{a:0. for a in placement['measured_atoms']},
                            'earliest_readout_us':{a:placement['measurement_start_us'] for a in placement['measured_atoms']},
                            'pre_transport_wait_us':pre_transport_wait,
                            'transport_batch_count':2,'split_reasons':[],
                            'outbound':placement['outbound'][0],'return':placement['returned'][0],
                            'group_service_duration_us':placement['end_us']-placement['start_us'],
                            'joint_transport_batch_id':gid})

    def classical(self, op):
        operation = op["params"].get("operation")
        if operation not in {"xor", "copy", "all_zero", "postprocess_phase"} or len(op["writes"]) != 1 or not op["reads"] or op["qubits"]:
            raise StrategyError("UNSUPPORTED_CLASSICAL", "Explicit supported classical function with one result is required", operation=op["id"])
        if operation == "postprocess_phase" and (op["params"].get("N") != 15 or op["params"].get("a") != 2 or
                op["params"].get("bits_msb_first") != op["reads"] or len(op["reads"]) != 8 or
                op["params"].get("failure_policy") != "return_explicit_classical_failure"):
            raise StrategyError("POSTPROCESS_PROFILE_UNSUPPORTED", "Preserve the R3 full eight-bit N15/a2 ordered input and failure policy")
        action = self.emit("classical", [], self.device["timings_us"]["classical"], [op["id"]],
                           {**deepcopy(op["params"]), "result_id": op["writes"][0], "writes": op["writes"]})
        action["payload"]["result_ready_us"] = action["t_end_us"]
        self.time = action["t_end_us"]
        self.results[op["writes"][0]] = self.time
        self.finish_op(op)

    def compile(self):
        started = time.perf_counter()
        readouts = self.contract["groups"]
        grouped_measurements = {m["measurement_op_id"] for g in readouts for m in g["members"]}
        if any(g["purpose"] != "maintenance_readout" for g in readouts):
            raise StrategyError("UNSUPPORTED_WINDOW_GROUP", "No startup transport group exists in the new entry")
        while self.pending:
            if time.perf_counter()-started > self.budget["max_wall_seconds"]:
                raise StrategyError("PHYSICAL_BUDGET_EXHAUSTED", "Window compile elapsed budget at stage boundary", complete=False,
                                    completed_operations=len(self.done), total_operations=len(self.operations),
                                    route_calls=self.route_calls, candidates=self.candidate_count)
            ready = [o for o in self.pending.values() if all(p in self.done for p in o["after"])]
            record = {"time_us": self.time, "ready_ids": [o["id"] for o in ready], "completed_ids": sorted(self.done), "selected_ids": []}
            self.ready_decisions.append(record)
            # Shared-AOD geometry is planned once for all ready nodes in this world.
            local = [o for o in ready if o["kind"] in {"reset", "wait"} or (o["kind"] == "gate" and len(o["qubits"]) == 1)]
            from .se_frontier import defer_readout_basis
            local = defer_readout_basis(local, ready, readouts, self.done)
            if local:
                record.update(stage="local", selected_ids=[o["id"] for o in local])
                self.local_batch(local)
                continue
            ready_ids = {o["id"] for o in ready}
            group = next((g for g in readouts if all(m["measurement_op_id"] in ready_ids for m in g["members"])), None)
            if group:
                batch=[g for g in readouts if all(m['measurement_op_id'] in ready_ids for m in g['members'])]
                record.update(stage="group_readout", selected_ids=[m["measurement_op_id"] for g in batch for m in g["members"]])
                if 'rigid_readout' in self.device:self.readout_groups(batch)
                else:self.readout_group(group)
                continue
            measurement = next((o for o in ready if o["kind"] == "measure" and o["id"] not in grouped_measurements), None)
            if measurement:
                metadata = measurement.get('metadata', {})
                if metadata.get('measurement_placement') in {'zac_style_min_cost_matching','rigid_array_translation'}:
                    batch_id = metadata.get('measurement_batch')
                    batch = [o for o in self.pending.values() if o['kind'] == 'measure' and o.get('metadata', {}).get('measurement_batch') == batch_id]
                    if not batch_id or any(o['id'] not in ready_ids for o in batch):
                        raise StrategyError('MEASUREMENT_BATCH_NOT_READY', 'An explicit simultaneous batch must have all its prerequisites complete')
                    record.update(stage='parallel_circuit_measurement', selected_ids=[o['id'] for o in batch])
                    self.measure_batch(batch)
                    continue
                if 'rigid_readout' in self.device:
                    group=self.atoms[self.qatom[measurement['qubits'][0]]]['aod_group']
                    candidates=[o for o in ready if o['kind']=='measure' and o['id'] not in grouped_measurements
                                and self.atoms[self.qatom[o['qubits'][0]]]['aod_group']==group]
                    record.update(stage='rigid_ready_readout',selected_ids=[o['id'] for o in candidates])
                    self.measure_rigid_batch(candidates,group_id='ready-readout:'+candidates[0]['id'],allow_readout_waves=True)
                    continue
                record.update(stage="individual_readout", selected_ids=[measurement["id"]])
                self.measure_single(measurement)
                continue
            classical = next((o for o in ready if o["kind"] == "classical"), None)
            if classical:
                record.update(stage="classical", selected_ids=[classical["id"]])
                self.classical(classical)
                continue
            permutation = next((o for o in ready if o["kind"] == "permute"), None)
            if permutation:
                from .transport_permutation import compile_permutation
                record.update(stage="atom_transport_permutation", selected_ids=[permutation["id"]])
                compile_permutation(self, permutation)
                continue
            two = [o for o in ready if o["kind"] == "gate" and o["params"]["name"] in {"CX", "CZ"}]
            if two:
                from .se_frontier import se_direction_rank
                two = sorted(two, key=lambda o: -1 if se_direction_rank(o) is None else se_direction_rank(o))
                layers = self.scheduler.partition(two, self.done)
                before = set(self.done)
                self.entangle(layers[0])
                record.update(stage="enola_two_qubit", selected_ids=sorted(set(self.done)-before),
                              scheduler_receipt=self.scheduler.receipts[-1]["sha256"])
                continue
            raise StrategyError("UNSUPPORTED_OR_BLOCKED_SOURCE", "Complete source retained; no supported ready stage", ready=[o["id"] for o in ready])
        end = max([self.time, *self.results.values()])
        exit_state = {"atoms": deepcopy(list(self.atoms.values())), "slm_traps": deepcopy(list(self.traps.values())), "aod_rows": [], "aod_columns": []}
        source = {"operations": self.operations, "groups": self.contract["groups"]}
        plan = {"schema_version": "AtomProgram/0.2.0-draft", "artifact_id": "joint-physical-window:"+self.window_id,
            "producer_version": "na_pipeline.backend.physical_window/0.1.0", "provenance": {"owner": "R4", "kb_revision": "kb-0006", "fixture": False,
            "backend_used": "enola_ready_scheduler_and_constrained_router", "scope": "joint full-operation window; no quantum-state simulation"},
            "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
            "complete": True, "device_ref": self.device["artifact_id"], "input_hashes": {"device": digest(self.device), "physical_window": digest(source)},
            "initial_state": self.initial_state, "actions": self.actions, "source_map": self.source_map, "groups": self.groups,
            "stats": {"physical_op_count": len(self.operations), "action_count": len(self.actions), "atom_count": len(self.atoms),
                      "t_start_us": 0., "t_end_us": end, "duration_us": end, "routing_search_count": self.route_calls,
                      "placement_candidate_count": self.candidate_count, "compile_wall_seconds": time.perf_counter()-started}}
        plan["stats"].update(enola_call_counts=dict(self.kernel.calls), enola_scheduler_calls=len(self.scheduler.receipts))
        return {"schema_version": "physical-window-plan/0.1", "atom_program": plan, "exit_state": exit_state,
                "source": source, "mz_banks": self.bank_map, "result_ready_offsets_us": {k: v for k, v in self.results.items() if k not in self.external_reads},
                "ready_decisions": self.ready_decisions, "budget": self.budget,
                "measurement_placements": self.measurement_placements,
                "enola": {"scheduler": self.scheduler.provenance, "schedule_decisions": self.scheduler.receipts,
                          "router": self.kernel.provenance, "route_decisions": self.kernel.receipts},
                "resource_intervals": [{"resource_id": r, "start_us": a["t_start_us"], "end_us": a["t_end_us"], "units": 1, "action_id": a["id"]}
                                       for a in self.actions for r in a["resources"]],
                "qualification": "pending_independent_R6"}


def compile_operation_window(operations, groups, device, initial_state, *, enola_root=None, budget=None, external_reads=()):
    """Joint planner for fully bound R3 expanded operations; t=0-relative window."""
    compiler = PhysicalWindowCompiler(operations, groups, device, initial_state, enola_root=enola_root, budget=budget, external_reads=external_reads)
    try:
        return compiler.compile()
    except StrategyError as exc:
        exc.details["compile_counters"] = {"placement_candidate_count": compiler.candidate_count, "routing_search_count": compiler.route_calls,
                                            "enola_call_counts": dict(compiler.kernel.calls), "enola_scheduler_calls": len(compiler.scheduler.receipts)}
        raise
