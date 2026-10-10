"""Immutable complete strategy compilation and search-free instance binding."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from .enola_kernel import COMMIT, ROUTER_SHA, EnolaKernel, StrategyError, digest
from .strategy_compile import StrategyCompiler


def compiler_identity():
    root = Path(__file__).resolve().parent
    return {name: sha256((root/name).read_bytes()).hexdigest() for name in
            ("strategy.py", "strategy_compile.py", "strategy_bind.py", "enola_kernel.py", "geometry.py",
             "batch_search.py", "independent_arrays.py", "se_frontier.py")}


class StrategyLibrary:
    """Memory-only cache. Returned dictionaries cannot mutate stored bodies."""
    def __init__(self, device, *, enola_root=None, config=None):
        self._device = deepcopy(device)
        self._root = enola_root
        self._config = {"patch_stride_um": 100.}
        if config:
            if set(config) != {"patch_stride_um"} or config["patch_stride_um"] != 100.:
                raise StrategyError("UNSUPPORTED_STRATEGY_CONFIG", "First strategy profile uses explicit 100 um patch ports")
            self._config.update(config)
        self._cache = {}
        self._counts = {"strategy_compile_count": 0, "placement_search_count": 0, "routing_search_count": 0,
                        "cache_hit_count": 0, "bind_count": 0, "composition_check_count": 0,
                        "compile_attempt_count": 0, "failed_compile_count": 0}

    @property
    def stats(self):
        return deepcopy(self._counts)

    def get_or_compile(self, physical_program):
        from na_pipeline.qec import validate_primitive_contract
        errors = validate_primitive_contract(physical_program)
        if errors:
            raise StrategyError("INVALID_PRIMITIVE_CONTRACT", "Physical strategy input failed producer checks", errors=errors)
        identity = compiler_identity()
        kernel = EnolaKernel(self._root)  # byte qualification only; no search on hit
        key = digest({"physical_program": physical_program, "device": self._device, "config": self._config,
                      "compiler_identity": identity, "enola_commit": COMMIT, "enola_router_sha256": ROUTER_SHA})
        if key in self._cache:
            cached = self._cache[key]
            if digest(cached["body"]) != cached["strategy_hash"]:
                raise StrategyError("CACHE_BODY_CORRUPTED", "Cached immutable body does not match its hash")
            self._counts["cache_hit_count"] += 1
            return deepcopy(cached)
        compiler = StrategyCompiler(physical_program, self._device, kernel, self._config)
        self._counts["compile_attempt_count"] += 1
        try:
            plan, exit_state = compiler.compile()
        except Exception:
            self._counts["failed_compile_count"] += 1
            raise
        finally:
            self._counts["placement_search_count"] += compiler.candidate_count
            self._counts["routing_search_count"] += compiler.route_calls
        wall = plan["stats"].pop("compile_wall_seconds")
        body = {"physical_program": deepcopy(physical_program), "atom_program": plan,
                "strategy_contract": deepcopy(physical_program["strategy_contract"]),
                "entry": deepcopy(plan["initial_state"]), "exit": exit_state,
                "device_hash": digest(self._device), "compiler_identity": identity,
                "backend_used": "enola_function_kernel", "enola_provenance": {**kernel.provenance, "config": deepcopy(self._config),
                    "call_counts": dict(kernel.calls), "decisions": deepcopy(kernel.receipts)},
                "resource_intervals": [{"action_id": a["id"], "resources": a["resources"], "t_start_us": a["t_start_us"], "t_end_us": a["t_end_us"]} for a in plan["actions"]],
                "group_metrics": deepcopy(plan["groups"]), "cache_key": key}
        strategy_hash = digest(body)
        strategy = {"schema_version": "compiled-logical-strategy/0.1", "strategy_id": "strategy:"+strategy_hash,
                    "strategy_hash": strategy_hash, "body": body, "build_metrics": {"compile_wall_seconds": wall},
                    "qualification_status": "pending_independent_R6", "user_visual_acceptance": "pending"}
        self._cache[key] = deepcopy(strategy)
        self._counts["strategy_compile_count"] += 1
        return deepcopy(strategy)

    def bind(self, strategy, binding):
        self._counts["composition_check_count"] += 1
        result = bind_strategy(strategy, binding, self._device)
        self._counts["bind_count"] += 1
        return result


def bind_strategy(strategy, binding, device):
    from .strategy_bind import bind
    return bind(strategy, binding, device)
