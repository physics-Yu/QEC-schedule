"""Immutable compiled PhysicalDAG strategies with fresh exact-world instance binding."""
from copy import deepcopy
from pathlib import Path
import time

from .enola_kernel import EnolaKernel, StrategyError, digest
from .enola_scheduler import EnolaReadyScheduler
from .execution_context import validate_execution_context
from .physical_dag import compile_physical_dag, finalize_physical_plan
from .strategy_template import canonical_dags, geometry_world, qualify_sites, remap, source_identity


class PhysicalStrategyLibrary:
    """In-memory, content-bound compilation cache; never stores execution/context/results."""
    def __init__(self, device, *, enola_root=None, budget=None, evidence_dir=None):
        self.device = deepcopy(device)
        self.enola_root, self.budget = enola_root, deepcopy(budget)
        self.evidence_dir = Path(evidence_dir) if evidence_dir is not None else None
        self._cache = {}
        self._stats = {"strategy_compile_count": 0, "compile_attempt_count": 0, "failed_compile_count": 0,
                       "cache_hit_count": 0, "cache_miss_count": 0, "static_site_variant_miss_count": 0,
                       "bind_count": 0, "composition_check_count": 0, "placement_search_count": 0,
                       "routing_search_count": 0, "enola_scheduler_calls": 0, "enola_compatible_calls": 0,
                       "enola_mis_calls": 0, "compile_wall_seconds": 0., "bind_wall_seconds": 0., "strategy_import_count": 0}

    @property
    def stats(self): return deepcopy(self._stats)

    def _inputs(self, dags, world):
        from na_pipeline.device import validate_device
        errors = validate_device(self.device)
        if errors: raise StrategyError("INVALID_DEVICE", "Strategy device failed producer validation", errors=errors)
        actual, canonical, mapping = canonical_dags(dags)
        clean, support = geometry_world(world, self.device)
        # These constructors qualify actual fixed source bytes/dependencies only;
        # they do not run the original scheduler/MIS or any routing search.
        router, scheduler = EnolaKernel(self.enola_root), EnolaReadyScheduler(self.enola_root)
        identity = {"compiler_sources": source_identity(), "device_hash": digest(self.device),
                    "router": router.provenance, "scheduler": scheduler.provenance,
                    "schema": "CompiledPhysicalStrategy/0.1", "budget": self.budget}
        key = digest({"canonical_dags": canonical, "entry_geometry": support, "identity": identity})
        return actual, canonical, mapping, clean, support, identity, key

    def _count_compile(self, stats):
        self._stats["placement_search_count"] += stats.get("placement_candidate_count", 0)
        self._stats["routing_search_count"] += stats.get("routing_search_count", 0)
        self._stats["enola_scheduler_calls"] += stats.get("enola_scheduler_calls", 0)
        calls = stats.get("enola_call_counts", {})
        self._stats["enola_compatible_calls"] += calls.get("compatible_2D", 0)
        self._stats["enola_mis_calls"] += calls.get("maximalis_solve_sort", 0)

    def get_or_compile(self, physical_dags, world_state):
        if self.evidence_dir is None:
            return self._get_or_compile(physical_dags, world_state)
        from .observation import RawCompilerObserver, map_raw_calls_to_strategy, save_observation
        before = self.stats
        with RawCompilerObserver(Path(__file__).resolve().parents[3]) as observer:
            strategy = self._get_or_compile(physical_dags, world_state)
        observation = observer.evidence()
        cold = self._stats["strategy_compile_count"] > before["strategy_compile_count"]
        proof = {"schema_version": "PhysicalStrategyAccessEvidence/0.1", "strategy_id": strategy["strategy_id"],
                 "source_dags_sha256": digest(physical_dags), "world_state_sha256": digest(world_state),
                 "cache_hit": not cold, "stats_before": before, "stats_after": self.stats, "raw_observation": observation,
                 "raw_plan_mapping": map_raw_calls_to_strategy(strategy, observation) if cold else None}
        ref = save_observation(self.evidence_dir, "compile" if cold else "hit", proof)
        if cold:
            strategy["compilation_evidence_ref"] = ref
            self._cache[strategy["body"]["cache_key"]]["compilation_evidence_ref"] = deepcopy(ref)
        strategy["cache_access_evidence_ref"] = ref
        return strategy

    def _get_or_compile(self, physical_dags, world_state):
        _, canonical, _, clean, support, identity, key = self._inputs(physical_dags, world_state)
        if key in self._cache:
            strategy = self._cache[key]
            if digest(strategy["body"]) != strategy["strategy_hash"]:
                raise StrategyError("STRATEGY_BODY_CORRUPTED", "Stored immutable strategy changed")
            try:
                qualify_sites(strategy["body"]["template_plan"]["atom_program"]["initial_state"], clean)
            except StrategyError:
                self._stats["static_site_variant_miss_count"] += 1
            else:
                self._stats["cache_hit_count"] += 1
                return deepcopy(strategy)
        self._stats["cache_miss_count"] += 1
        self._stats["compile_attempt_count"] += 1
        started = time.perf_counter()
        try:
            template = compile_physical_dag(canonical, self.device, clean, enola_root=self.enola_root,
                                            budget=self.budget, defer_runtime_inputs=True)
        except StrategyError as exc:
            self._stats["failed_compile_count"] += 1
            self._count_compile(exc.details.get("compile_counters", {}))
            raise
        finally:
            elapsed = time.perf_counter()-started
            self._stats["compile_wall_seconds"] += elapsed
        compile_stats = deepcopy(template["atom_program"]["stats"])
        self._count_compile(compile_stats)
        compile_stats.pop("compile_wall_seconds", None)
        template["atom_program"]["stats"].pop("compile_wall_seconds", None)
        template["atom_program"]["complete"] = False
        template["atom_program"]["provenance"]["requires_strategy_binding"] = True
        template["atom_program"]["provenance"]["requires_runtime_binding"] = True
        body = {"cache_key": key, "identity": identity, "entry_geometry": support,
                "canonical_dags": canonical, "template_plan": template,
                "compilation_counters": compile_stats,
                "support_domain": {"exact_all_atom_geometry": True, "exact_carrier_qubit_identity": True,
                    "empty_AOD_only": True, "translation_or_rotation": False,
                    "new_empty_SLM_sites": "checked individually; no occupied carrier may be added",
                    "runtime_context_results_epochs_tokens_cached": False}}
        body_hash = digest(body)
        strategy = {"schema_version": "CompiledPhysicalStrategy/0.1", "strategy_id": "physical-strategy:"+body_hash,
                    "strategy_hash": body_hash, "body": body,
                    "build_metrics": {"compile_wall_seconds": elapsed}, "qualification": "pending_independent_R6"}
        self._cache[key] = deepcopy(strategy)
        self._stats["strategy_compile_count"] += 1
        return deepcopy(strategy)

    def bind(self, strategy, physical_dags, world_state, *, execution_context):
        if self.evidence_dir is None:
            return self._bind(strategy, physical_dags, world_state, execution_context=execution_context)
        from .observation import RawCompilerObserver, save_observation
        before = self.stats
        with RawCompilerObserver(Path(__file__).resolve().parents[3]) as observer:
            result = self._bind(strategy, physical_dags, world_state, execution_context=execution_context)
        proof = {"schema_version": "PhysicalStrategyInstanceEvidence/0.1", "strategy_id": strategy["strategy_id"],
                 "source_dags_sha256": digest(physical_dags), "world_state_sha256": digest(world_state),
                 "execution_context_sha256": digest(execution_context), "binding": deepcopy(result["strategy_binding"]),
                 "stats_before": before, "stats_after": self.stats, "raw_observation": observer.evidence()}
        result["strategy_binding"]["instance_evidence_ref"] = save_observation(self.evidence_dir, "bind", proof)
        result["strategy_binding"]["compilation_evidence_ref"] = deepcopy(strategy.get("compilation_evidence_ref"))
        return result

    def _bind(self, strategy, physical_dags, world_state, *, execution_context):
        self._stats["composition_check_count"] += 1
        started = time.perf_counter()
        if strategy.get("schema_version") != "CompiledPhysicalStrategy/0.1" or digest(strategy["body"]) != strategy.get("strategy_hash"):
            raise StrategyError("STRATEGY_BODY_CORRUPTED", "The complete immutable compiled body and hash are required")
        actual, canonical, actual_to_formal, clean, support, identity, key = self._inputs(physical_dags, world_state)
        body = strategy["body"]
        if key != body["cache_key"] or canonical != body["canonical_dags"] or support != body["entry_geometry"] or identity != body["identity"]:
            raise StrategyError("PHYSICAL_STRATEGY_MISS", "Operation, parameters, all-world geometry/occupancy or compiler identity changed; get_or_compile is required")
        validate_execution_context(execution_context, actual, self.device, world_state)
        original = body["template_plan"]
        qualify_sites(original["atom_program"]["initial_state"], clean)
        formal_to_actual = {v: k for k, v in actual_to_formal.items()}
        instance_id = digest({"dags": actual, "world": world_state, "run_id": execution_context["run_id"],
                              "revision": execution_context["revision"], "strategy": strategy["strategy_id"]})[:24]
        action_map = {a["id"]: f"strategy-instance:{instance_id}/action:{i:06d}" for i, a in enumerate(original["atom_program"]["actions"])}
        mapping = {**formal_to_actual, **action_map}
        result = remap(deepcopy(original), mapping)
        atom = result["atom_program"]
        atom["artifact_id"] = "physical-strategy-instance:"+instance_id
        atom["provenance"].update(requires_strategy_binding=False, backend_used="enola_compiled_physical_strategy_binding",
                                  strategy_id=strategy["strategy_id"], original_search_repeated=False)
        entry_traps = {t["trap_id"]: deepcopy(t) for t in world_state["slm_traps"]}
        for t in atom["initial_state"]["slm_traps"]: entry_traps.setdefault(t["trap_id"], deepcopy(t))
        atom["initial_state"] = {"atoms": deepcopy(world_state["atoms"]), "slm_traps": list(entry_traps.values()),
                                 "aod_rows": [], "aod_columns": []}
        # Exit geometry is static. Per-atom runtime fields are copied from the new
        # entry and remain predictions, never substituted for R5's actual receipts.
        fresh = {a["atom_id"]: deepcopy(a) for a in world_state["atoms"]}
        for a in result["exit_state"]["atoms"]:
            fresh[a["atom_id"]].update({k: deepcopy(a[k]) for k in ("position_um", "carrier", "trap_id", "row_id", "column_id", "site_id") if k in a})
        exit_traps = {t["trap_id"]: deepcopy(t) for t in entry_traps.values()}
        for t in result["exit_state"]["slm_traps"]: exit_traps[t["trap_id"]] = deepcopy(t)
        result["exit_state"] = {"atoms": list(fresh.values()), "slm_traps": list(exit_traps.values()), "aod_rows": [], "aod_columns": []}
        byop = {o["id"]: o for d in actual for o in d["nodes"]}
        for action in atom["actions"]:
            payload = action["payload"]
            sources = payload["physical_op_ids"]
            ops = [byop[s] for s in sources]
            action["source_ids"] = list(dict.fromkeys(s for op in ops for s in [op["id"], *op["source_ids"]]))
            payload["source_op_records"] = {o["id"]: {k: deepcopy(o[k]) for k in ("qubits", "params", "reads", "writes", "condition")} for o in ops}
            if len(ops) == 1:
                op = ops[0]
                payload.update(physical_op_id=op["id"], params=deepcopy(op["params"]),
                               source_reads=deepcopy(op["reads"]), source_writes=deepcopy(op["writes"]),
                               source_metadata=deepcopy(op.get("metadata", {})))
        operations = [deepcopy(o) for d in actual for o in d["nodes"]]
        group_inputs = []
        for d in actual:
            for group in d["groups"]:
                g = deepcopy(group)
                for member in g["members"]: member.setdefault("mz_slot_role", member["local_id"])
                group_inputs.append(g)
        result["source"] = {"operations": operations, "groups": group_inputs}
        atom["input_hashes"] = {"device": digest(self.device), "physical_window": digest(result["source"])}
        atom["stats"].update(compile_wall_seconds=0., routing_search_count=0, placement_candidate_count=0,
                             enola_call_counts={}, enola_scheduler_calls=0)
        result["enola"] = deepcopy(original["enola"])
        result["enola"]["strategy_binding"] = {"strategy_id": strategy["strategy_id"], "search_performed_for_instance": False,
                                                "formal_to_instance": mapping}
        result["strategy_binding"] = {"schema_version": "PhysicalStrategyBinding/0.1", "strategy_id": strategy["strategy_id"],
            "strategy_hash": strategy["strategy_hash"], "cache_key": key, "formal_to_instance": mapping,
            "world_state_hash": digest(world_state), "device_hash": digest(self.device),
            "checked_atom_count": len(world_state["atoms"]), "checked_static_site_count": len(world_state["slm_traps"]),
            "scene_equivalence": "all atoms/positions/occupancies/axes exact; every referenced static site checked",
            "placement_search_count": 0, "routing_search_count": 0, "enola_calls": 0,
            "absolute_time_binding_owner": "R5", "cached_runtime_values": False}
        result = finalize_physical_plan(result, actual, self.device, world_state, execution_context)
        elapsed = time.perf_counter()-started
        result["strategy_binding"]["bind_wall_seconds"] = elapsed
        self._stats["bind_count"] += 1; self._stats["bind_wall_seconds"] += elapsed
        return result

    def import_strategy(self, strategy, world_state):
        """Qualify a static saved body against current code/device/full world; no search.

        R5 checks strategy_refs byte hashes before calling this. Historical
        counters, results, tokens, context and acceptance are not imported.
        """
        if strategy.get("schema_version") != "CompiledPhysicalStrategy/0.1":
            raise StrategyError("STRATEGY_IMPORT_VERSION", "Only CompiledPhysicalStrategy/0.1 is supported")
        body = strategy["body"]; body_hash = digest(body)
        if strategy.get("strategy_hash") != body_hash or strategy.get("strategy_id") != "physical-strategy:"+body_hash:
            raise StrategyError("STRATEGY_BODY_CORRUPTED", "Imported strategy identity/body digest mismatch")
        forbidden = {"execution_context", "published_results", "scenario", "event_trace", "validation_report",
                     "results", "frame", "frames", "token", "tokens", "epoch", "run_id"}
        if set(strategy) & forbidden:
            raise StrategyError("STRATEGY_DYNAMIC_STATE_IMPORT", "Only static compiled strategy data may be imported", fields=sorted(set(strategy) & forbidden))
        def static(value):
            if isinstance(value, dict):
                illegal = set(value) & forbidden
                if illegal: raise StrategyError("STRATEGY_DYNAMIC_STATE_IMPORT", "Runtime state or acceptance may not enter a compiled strategy", fields=sorted(illegal))
                for child in value.values(): static(child)
            elif isinstance(value, list):
                for child in value: static(child)
        static(body)
        _, canonical, _, clean, support, identity, key = self._inputs(body["canonical_dags"], world_state)
        if identity != body["identity"] or key != body["cache_key"] or canonical != body["canonical_dags"] or support != body["entry_geometry"]:
            raise StrategyError("STRATEGY_IMPORT_INCOMPATIBLE", "Current source/device/full-world support domain differs")
        qualify_sites(body["template_plan"]["atom_program"]["initial_state"], clean)
        if body["template_plan"]["atom_program"].get("complete") is not False or any(d.get("execution_guard") is not None for d in body["canonical_dags"]):
            raise StrategyError("STRATEGY_IMPORT_NOT_STATIC", "An executable bound instance is not a reusable template")
        imported = {k: deepcopy(strategy[k]) for k in ("schema_version", "strategy_id", "strategy_hash", "body", "build_metrics")}
        imported["qualification"] = "pending_independent_R6"
        if strategy.get("compilation_evidence_ref"): imported["compilation_evidence_ref"] = deepcopy(strategy["compilation_evidence_ref"])
        already = key in self._cache and self._cache[key]["strategy_id"] == strategy["strategy_id"]
        self._cache[key] = imported
        self._stats["strategy_import_count"] += 1
        return {"schema_version": "PhysicalStrategyImportReceipt/0.1", "strategy_id": strategy["strategy_id"],
                "status": "already_present" if already else "imported", "source_device_world_checked": True,
                "runtime_state_imported": False, "qualification_imported": False, "search_calls": 0}

    def restore_strategies(self, strategies, world_state, *, skip_incompatible=False):
        receipts, skipped = [], []
        for strategy in strategies:
            try: receipts.append(self.import_strategy(strategy, world_state))
            except StrategyError as exc:
                if not skip_incompatible: raise
                skipped.append({"strategy_id": strategy.get("strategy_id"), **exc.to_dict()})
        return {"schema_version": "PhysicalStrategyRestoreReceipt/0.1", "imported": receipts, "skipped": skipped,
                "runtime_state_imported": False, "search_calls": 0}
