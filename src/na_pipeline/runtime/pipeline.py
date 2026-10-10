"""Complete LogicalDAG driver over finite resources and persistent real windows.

All source nodes remain in the scheduler. Conditional gates use published fake
bits, and T nodes finish only after an execution-bound adaptive factory route.
"""
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path

from na_pipeline.qec import build_physical_dag_bundle, materialize_physical_node, materialize_factory_protocol

from .engine import digest
from .errors import fail
from .session import EventSession
from .logical_scheduler import LogicalListScheduler
from .resource_pool import FiniteResourcePool
from .factory_session import FactoryExecution
from .scenario import make_scenario
from .window_binding import bind_physical_plan
from .history import byte_hash


def save_artifact(path, value, *, immutable=False):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if path.suffix == ".gz": raw = gzip.compress(raw, mtime=0)
    if immutable and path.exists():
        if path.read_bytes() != raw: fail("PIPELINE_ARTIFACT_REDEFINED", "An immutable run input or completed artifact changed")
    else:
        tmp = path.with_name(path.name+".tmp"); tmp.write_bytes(raw); tmp.replace(path)
    return {"path": str(path.resolve()), "byte_sha256": sha256(raw).hexdigest()}


class HierarchicalPipeline:
    def __init__(self, world, output_dir, *, phase_bits, compiler=None, compile_budget=None, factory_scenarios=None):
        if len(phase_bits) != 8 or any(type(b) is not int or b not in (0, 1) for b in phase_bits):
            fail("PIPELINE_PHASE_SCENARIO", "Eight explicit fake phase bits in MSB-first order are required")
        self.world = deepcopy(world); self.out = Path(output_dir)
        self.logical = deepcopy(world["logical_dag"]); self.device = deepcopy(world["device"])
        self.bundle = build_physical_dag_bundle(self.logical)
        if self.bundle["resource_requirements"] != world["requirements"]:
            fail("PIPELINE_RESOURCE_VERSION", "Placed finite world does not match the actual R3 bundle requirements")
        self.phase_bits = list(phase_bits)
        self.factory_scenarios = deepcopy({"schema_version": "factory-attempt-scenarios/0.1",
            "default": [{"default_measurement_bit": 0, "terminal_x_parities": [0, 0, 0, 0]}], "requests": {}}
            if factory_scenarios is None else factory_scenarios)
        self.session = EventSession(self.device, world["initial_state"], run_id="hierarchical:"+digest({"world": world, "phase": phase_bits, "factory_scenarios": self.factory_scenarios}))
        self.pool = FiniteResourcePool(world["requirements"], world["initial_state"])
        self.scheduler = LogicalListScheduler(self.logical, {})
        self._validate_factory_scenarios()
        self.attempt_indices = {}
        self.exhausted = None
        self.factory = None
        self.window_count = 0
        self.factory_ledgers = []
        self.strategy_refs = {}
        if compiler is None:
            from na_pipeline.backend import PhysicalStrategyLibrary
            compiler = PhysicalStrategyLibrary(self.device, budget=compile_budget or {"max_operations": 100000, "max_wall_seconds": 3600})
        self.compiler = compiler
        self.input_refs = {"world": save_artifact(self.out/"world.json.gz", world, immutable=True),
                           "physical_bundle": save_artifact(self.out/"physical-bundle.json.gz", self.bundle, immutable=True),
                           "factory_scenarios": save_artifact(self.out/"factory-scenarios.json", self.factory_scenarios, immutable=True)}

    def _validate_factory_scenarios(self):
        config = self.factory_scenarios
        if not isinstance(config, dict) or set(config) != {"schema_version", "default", "requests"} or config["schema_version"] != "factory-attempt-scenarios/0.1" or not isinstance(config["requests"], dict):
            fail("FACTORY_SCENARIO_SCHEMA", "Explicit bounded attempt lists are required")
        if any(n not in self.scheduler.nodes or self.scheduler.nodes[n]["operation"] not in ("T", "TDG") for n in config["requests"]):
            fail("FACTORY_SCENARIO_REQUEST", "Attempt policy must name an original T/TDG node")
        for attempts in [config["default"], *config["requests"].values()]:
            if not isinstance(attempts, list) or not attempts: fail("FACTORY_ATTEMPT_BOUND", "Every request needs a nonempty finite attempt list")
            for entry in attempts:
                if (not isinstance(entry, dict) or set(entry) != {"default_measurement_bit", "terminal_x_parities"} or type(entry["default_measurement_bit"]) is not int
                        or entry["default_measurement_bit"] not in (0, 1) or not isinstance(entry["terminal_x_parities"], list) or len(entry["terminal_x_parities"]) != 4
                        or any(type(v) is not int or v not in (0, 1) for v in entry["terminal_x_parities"])):
                    fail("FACTORY_ATTEMPT_SCENARIO", "Each attempt specifies fake physical defaults and four terminal parity targets")

    def _attempts(self, node_id):
        return self.factory_scenarios["requests"].get(node_id, self.factory_scenarios["default"])

    def _factory_scenario(self, factory, atom):
        nid = factory.protocol["logical_binding"]["logical_node_id"]
        entry = self._attempts(nid)[self.attempt_indices[nid]]
        default, overrides = entry["default_measurement_bit"], {}
        if factory.stage_id == "terminal_checks":
            for check, desired in zip(factory.protocol["acceptance_checks"], entry["terminal_x_parities"], strict=True):
                ids = check["result_ids"]
                overrides[ids[0]] = desired ^ (default*((len(ids)-1) % 2))
        return make_scenario(atom, value=default, overrides=overrides)

    def _plan(self, graphs):
        from .component_interface import LogicalGateLibrary
        if isinstance(self.compiler,LogicalGateLibrary):
            call=self.compiler.prepare_dags(self.compiler.component_for(graphs),self.session,graphs)
            return call['context'],call['physical_plan'],call['atom_program']
        context = self.session.compilation_context(graphs)
        self.session.validate_context(context)
        snapshot = self.session.snapshot()["world_state"]
        strategy = self.compiler.get_or_compile(graphs, snapshot)
        sid = strategy["strategy_id"]
        if sid not in self.strategy_refs:
            self.strategy_refs[sid] = save_artifact(self.out/"strategies"/(strategy["strategy_hash"]+".json.gz"), strategy, immutable=True)
        plan = self.compiler.bind(strategy, graphs, snapshot, execution_context=context)
        atom = bind_physical_plan(plan, context)
        return context, plan, atom

    def _scenario(self, graphs, atom):
        overrides = {}
        for graph in graphs:
            binding = graph.get("logical_binding", {})
            node = self.scheduler.nodes.get(binding.get("logical_node_id"))
            if node and node["operation"] == "MEASURE":
                rid = node["writes"][0]
                if not rid.startswith("phase["): fail("PIPELINE_PHASE_RESULT", "Unknown algorithm measurement output")
                index = int(rid[6:-1])
                writer = next(n for n in graph["nodes"] if n["id"] == graph["result_producers"][rid])
                if writer["kind"] != "classical" or writer["params"]["operation"] != "xor" or not writer["reads"]:
                    fail("PIPELINE_LOGICAL_READOUT", "Phase result must derive from its declared physical readout parity")
                # Configure a physical bit, never the derived public phase value.
                overrides[writer["reads"][0]] = self.phase_bits[index]
        return make_scenario(atom, value=0, overrides=overrides)

    def _persist_frontier(self):
        if self.scheduler.decisions:
            self.scheduler.retire_decisions(self.out/"decisions"/f"decision-{self.scheduler.revision:08d}.json.gz")
        save_artifact(self.out/"checkpoint.json.gz", self.checkpoint())
        save_artifact(self.out/"logical-schedule.json.gz", self.scheduler.snapshot())
        save_artifact(self.out/"manifest.json", self.status())

    def _advance_window(self, atom):
        self.session.advance()
        # R4 supplies a fixed planned window, including slots whose conditional
        # correction is skipped. Retain that explicit scheduling boundary so
        # the next window does not collide with the still-reserved final slot.
        scheduled_end = max((a["t_end_us"] for a in atom["actions"]), default=self.session.now_us)
        if self.session.now_us < scheduled_end: self.session.advance(scheduled_end)

    def _archive_window(self, plan, atom, scenario, context):
        stem = f"window-{self.window_count:07d}"
        ref = save_artifact(self.out/"windows"/(stem+"-"+digest(atom)[:16]+".json.gz"),
            {"physical_plan": plan, "atom_program": atom, "scenario": scenario, "context": context}, immutable=True)
        self.session.retire_committed(self.out/"history"/(stem+".json.gz"), keep_result_ids=self.logical["result_types"])
        self.window_count += 1
        return ref

    def _factory_step(self):
        factory = self.factory
        while factory.protocol["stages"][factory.stage_id]["kind"] == "lifecycle":
            from .component_interface import LogicalGateLibrary
            if isinstance(self.compiler,LogicalGateLibrary) and factory.stage_id=='reserve_delivery':
                from .factory_ports import FactoryDataInterface,data_surface_port
                interface=FactoryDataInterface(factory)
                target=data_surface_port(self.session,self.pool,factory.protocol['data_block_id'],
                    encoded_state_ref=factory.protocol['logical_binding']['logical_node_id'],logical_frame='identity')
                interface.reserve(interface.output_port(),target,request_id=factory.protocol['request_id'])
            else:factory.advance_lifecycle()
        graph = factory.next_graph()
        context, plan, atom = self._plan([graph])
        factory.validate_submission(plan, atom)
        scenario = self._factory_scenario(factory, atom)
        save_artifact(self.out/"windows"/(f"window-{self.window_count:07d}-"+digest(atom)[:16]+".json.gz"),
            {"physical_plan": plan, "atom_program": atom, "scenario": scenario, "context": context}, immutable=True)
        self.session.submit(atom, scenario, expected_revision=context["revision"])
        self._advance_window(atom)
        receipt = factory.commit_stage(plan, atom)
        nid = factory.protocol["logical_binding"]["logical_node_id"]
        self.scheduler.record_protocol_stage(nid, plan, receipt, origin_us=context["time_us"])
        self.scheduler.advance(self.session.now_us)
        self._archive_window(plan, atom, scenario, context)
        if factory.terminal is not None:
            ledger = factory.snapshot()
            ledger["protocol"] = deepcopy(factory.protocol)
            ref = save_artifact(self.out/"factory"/("factory-"+digest(factory.protocol)[:24]+".json.gz"), ledger, immutable=True)
            self.factory_ledgers.append(ref)
            if factory.terminal == "consumed":
                self.scheduler.complete_protocol(nid, ledger, ledger_ref=ref)
                self.factory = None
            else:
                following = self.attempt_indices[nid]+1
                if following >= len(self._attempts(nid)):
                    self.exhausted = {"logical_node_id": nid, "attempt_count": following, "last_rejected_ledger": ref,
                                      "cleanup_complete": not self.pool.active, "consumed": False}
                    self.factory = None
                    self._persist_frontier()
                    fail("PIPELINE_FACTORY_ATTEMPTS_EXHAUSTED", "All configured attempts rejected after actual cleanup; the T parent remains incomplete")
                protocol = materialize_factory_protocol(self.bundle, nid, epoch=self.pool.next_epoch)
                self.factory = FactoryExecution(protocol, self.pool, self.session, owner=nid+"/pool-epoch"+str(self.pool.next_epoch))
                self.scheduler.retry_protocol(nid, protocol, self.factory.lease, ledger, ledger_ref=ref)
                self.attempt_indices[nid] = following
        self._persist_frontier()
        return {"kind": "factory_stage", "logical_node_id": nid, "stage_id": receipt["stage_id"],
                "time_us": self.session.now_us, "windows": self.window_count}

    def step(self):
        if self.exhausted: fail("PIPELINE_FACTORY_ATTEMPTS_EXHAUSTED", "Attempt budget is exhausted; no token or T completion exists")
        if self.factory is not None: return self._factory_step()
        if self.scheduler.snapshot()["complete"]: return self.status()
        skips = self.scheduler.commit_ready_skips()
        if skips:
            self._persist_frontier()
            return {"kind": "logical_skips", "count": len(skips), "time_us": self.session.now_us}
        ready = self.scheduler.ready_set()
        if not ready: fail("PIPELINE_NO_READY_NODE", "Unfinished DAG has no causal execute/skip candidate")
        static = [n for n in ready if self.scheduler.nodes[n]["operation"] not in ("T", "TDG")]
        if not static:
            nid = ready[0]
            protocol = materialize_factory_protocol(self.bundle, nid, epoch=self.pool.next_epoch)
            self.factory = FactoryExecution(protocol, self.pool, self.session, owner=nid+"/pool-epoch"+str(self.pool.next_epoch))
            self.attempt_indices[nid] = 0
            self.scheduler.begin_protocol(nid, protocol, self.factory.lease)
            self._persist_frontier()
            return {"kind": "factory_begin", "logical_node_id": nid, "epoch": protocol["epoch"], "time_us": self.session.now_us}
        graphs = {n: materialize_physical_node(self.bundle, n) for n in static}
        candidate = self.scheduler.joint_candidates(eligible_nodes=static, required_leases={n: d.get("required_leases", []) for n, d in graphs.items()})
        chosen = candidate["selected_node_ids"]
        leases = {}
        for nid in chosen:
            node = self.scheduler.nodes[nid]
            if node["operation"] in ("S", "SDG"):
                lease = self.pool.acquire(nid+"/pool-epoch"+str(self.pool.next_epoch), node["operation"], node["patch_operands"]["block"], self.session)
                leases[nid] = lease
                graphs[nid] = materialize_physical_node(self.bundle, nid, epoch=lease["epoch"])
        selected_graphs = [graphs[n] for n in chosen]
        context, plan, atom = self._plan(selected_graphs)
        proposal = self.scheduler.propose_joint(plan)
        scenario = self._scenario(selected_graphs, atom)
        save_artifact(self.out/"windows"/(f"window-{self.window_count:07d}-"+digest(atom)[:16]+".json.gz"),
            {"physical_plan": plan, "atom_program": atom, "scenario": scenario, "context": context}, immutable=True)
        self.session.submit(atom, scenario, expected_revision=context["revision"])
        self.scheduler.reserve_joint(plan, proposal)
        self._advance_window(atom); self.scheduler.advance(self.session.now_us)
        for graph in selected_graphs:
            nid = graph["logical_binding"]["logical_node_id"]
            if any(r not in self.session.results for r in graph["result_producers"]):
                fail("PIPELINE_RESULTS_NOT_COMMITTED", "Every required source result must publish before protocol completion")
            summary = plan["node_summaries"][graph["artifact_id"]]
            if nid in leases:
                lease = leases[nid]
                scratch = self.bundle["resource_requirements"]["shared_phase_scratch"]
                qids = {q for q in self.pool.qubit_to_atom if q.startswith(scratch["phase_aux"]+"/") or q == scratch["bridge"]}
                aids = {self.pool.qubit_to_atom[q] for q in qids}
                resets = [a for a in atom["actions"] if a["kind"] == "reset" and set(a["atoms"]) <= aids]
                cleanup = set()
                for aid in aids:
                    matches = [a for a in resets if aid in a["atoms"]]
                    if not matches: fail("PIPELINE_S_CLEANUP_MISSING", "S scratch has no real final reset")
                    cleanup.add(max(matches, key=lambda a: a["t_end_us"])["id"])
                self.pool.release(lease["owner"], self.session, cleanup_action_ids=sorted(cleanup), reset_qubit_ids=qids)
            physical_end = max(self.session.completed[a] for a in summary["action_ids"])
            completion = max(physical_end, *(self.session.results[r]["ready_us"] for r in graph["result_producers"])) if nid in leases else physical_end
            self.scheduler.complete(nid, {"node_id": nid, "completed_us": completion,
                "physical_plan_ref": atom["artifact_id"], "event_trace_ref": self.session.run_id+"/trace/"+str(self.session.revision)},
                {r: self.session.results[r] for r in self.scheduler.nodes[nid]["writes"]})
        self._archive_window(plan, atom, scenario, context)
        self._persist_frontier()
        return {"kind": "logical_window", "logical_nodes": chosen, "time_us": self.session.now_us, "windows": self.window_count}

    def status(self):
        schedule = self.scheduler.snapshot()
        completed = schedule["complete"]
        report = self.session.results.get("postprocess/result", {}).get("value")
        return {"schema_version": "hierarchical-pipeline-status/0.1", "complete_source_path": completed, "full_program_passed": False,
                "logical_node_count": len(self.scheduler.nodes), "terminal_node_count": sum(s["status"] in ("completed", "skipped") for s in self.scheduler.states.values()),
                "windows": self.window_count, "time_us": self.session.now_us, "factory_stage": self.factory.stage_id if self.factory else None,
                "factory_ledgers": deepcopy(self.factory_ledgers), "strategy_refs": deepcopy(self.strategy_refs), "compiler_stats": self.compiler.stats,
                "attempt_indices": deepcopy(self.attempt_indices), "attempt_budget_exhausted": deepcopy(self.exhausted),
                "phase_bits_scenario": self.phase_bits, "postprocess": report, "inputs": deepcopy(self.input_refs),
                "source_coverage": "all_original_nodes_retained", "independent_validation": "pending_R6", "user_visual": "pending",
                "quantum_state_simulated": False, "hardware_executed": False, "sampled": False}

    def checkpoint(self):
        body = {"schema_version": "hierarchical-pipeline-checkpoint/0.1", "world_hash": digest(self.world), "bundle_hash": digest(self.bundle),
                "driver_source_hash": sha256(Path(__file__).read_bytes()).hexdigest(), "phase_bits": self.phase_bits,
                "factory_scenarios": self.factory_scenarios, "attempt_indices": self.attempt_indices, "exhausted": self.exhausted,
                "scheduler": self.scheduler.checkpoint(), "window_count": self.window_count,
                "factory_ledgers": self.factory_ledgers, "strategy_refs": self.strategy_refs,
                "factory": self.factory.checkpoint() if self.factory else None,
                "session": self.session.checkpoint() if not self.factory else None, "pool": self.pool.snapshot()}
        return {"body": body, "sha256": digest(body)}

    @classmethod
    def restore(cls, world, output_dir, checkpoint, *, compiler=None, compile_budget=None):
        body = checkpoint["body"]
        if (checkpoint["sha256"] != digest(body) or body.get("schema_version") != "hierarchical-pipeline-checkpoint/0.1"
                or body["world_hash"] != digest(world) or body["driver_source_hash"] != sha256(Path(__file__).read_bytes()).hexdigest()):
            fail("PIPELINE_CHECKPOINT_IDENTITY", "Input, driver version or checkpoint integrity changed")
        obj = cls(world, output_dir, phase_bits=body["phase_bits"], compiler=compiler, compile_budget=compile_budget, factory_scenarios=body["factory_scenarios"])
        if body["bundle_hash"] != digest(obj.bundle): fail("PIPELINE_PHYSICAL_BUNDLE_CHANGED", "Shared physical source changed")
        if body["factory"]:
            obj.factory = FactoryExecution.restore(obj.device, body["factory"], archive_root=obj.out/"history")
            obj.session, obj.pool = obj.factory.session, obj.factory.pool
        else:
            obj.session = EventSession.restore(obj.device, body["session"], archive_root=obj.out/"history")
            obj.pool = FiniteResourcePool.restore(world["requirements"], world["initial_state"], body["pool"])
        obj.scheduler = LogicalListScheduler.restore(obj.logical, body["scheduler"], decision_root=obj.out/"decisions")
        obj.window_count = body["window_count"]
        obj.factory_ledgers, obj.strategy_refs = deepcopy(body["factory_ledgers"]), deepcopy(body["strategy_refs"])
        obj.attempt_indices, obj.exhausted = deepcopy(body["attempt_indices"]), deepcopy(body["exhausted"])
        return obj
