"""Built-in adapters; generic job and experiment code has no compiler branches."""

from typing import Any

from ..job_fields import integer_at, keys_at
from ..nonzoned.support import require_capabilities
from ..physical_ir import NAMED_LOCAL_GATES
from ..registry import StrategyContext, check_strategy, construct_strategy
from ..smt.adapter import admit as smt_admit
from ..smt.adapter import build as smt_build
from ..smt.adapter import schema as smt_schema
from ..strategies.nonzoned import NonZonedStrategy
from ..support import UnsupportedJob
from .contracts import CompilerContext
from .registry import Compiler, CompilerRegistration, Reasons


def _search_admit(context: CompilerContext, options: dict[str, Any]) -> Reasons:
    """All configured stage support predicates must pass before construction."""
    if any(node.name == "cp" for node in context.dag.nodes):
        reasons: Reasons = []
        if options.get("scheduler", {}).get("kind") != "ready":
            reasons.append(
                {
                    "stage": "scheduler",
                    "kind": "search_smarter",
                    "reason": "native CP requires ready scheduling",
                }
            )
        cp, cz = context.device.cphase, context.device.cz
        if cp is None or cz is None:
            reasons.append(
                {
                    "stage": "strategy",
                    "kind": "search_smarter",
                    "reason": "native CP requires explicit CPhase and CZ capabilities",
                }
            )
        elif (cp.channel, cp.radius_um, cp.holder_pairs, cp.allow_spectators) != (
            cz.channel,
            cz.radius_um,
            cz.holder_pairs,
            cz.allow_spectators,
        ):
            reasons.append(
                {
                    "stage": "strategy",
                    "kind": "search_smarter",
                    "reason": "native CP requires the same channel and geometry as CZ",
                }
            )
        if any(
            "cz" in zone.operations and "cp" not in zone.operations
            for zone in context.device.zones
        ):
            reasons.append(
                {
                    "stage": "strategy",
                    "kind": "search_smarter",
                    "reason": "CZ interaction zones must explicitly permit cp",
                }
            )
        if reasons:
            return reasons
    try:
        _, resolved = check_strategy(
            options,
            dag=context.dag,
            device=context.device,
            aod_id=context.aod_id,
            catalog=context.catalog,
        )
    except UnsupportedJob as error:
        return list(error.reasons)
    if "mode" in options:
        resolved["mode"] = options["mode"]
    options.clear()
    options.update(resolved)
    return []


def _search_build(
    context: CompilerContext, options: dict[str, Any]
) -> tuple[Compiler, dict[str, Any]]:
    stages = StrategyContext(
        context.dag,
        context.device,
        context.aod_id,
        context.catalog,
        options["placement"],
        options,
    )
    return construct_strategy(stages, options)


def _nonzoned_admit(context: CompilerContext, options: dict[str, Any]) -> Reasons:
    """Flexible AOD, SLM-SLM CZ with isolated spectators, retained AOD readout."""
    keys_at(options, {"max_cz_gates"}, "strategy")
    if (
        "max_cz_gates" in options
        and integer_at(options["max_cz_gates"], "strategy.max_cz_gates") < 1
    ):
        raise ValueError("strategy.max_cz_gates: expected a positive integer.")
    reasons: Reasons = []
    if any(node.name == "cp" for node in context.dag.nodes):
        reasons.append(
            {
                "stage": "strategy",
                "kind": "nonzoned",
                "reason": "native CP is unavailable in nonzoned",
            }
        )
    if any(node.name in NAMED_LOCAL_GATES for node in context.dag.nodes):
        reasons.append(
            {
                "stage": "strategy",
                "kind": "nonzoned",
                "reason": "native named local gates are unavailable in nonzoned",
            }
        )
    try:
        require_capabilities(
            context.device,
            context.aod_id,
            readout=any(n.name == "measure" for n in context.dag.nodes),
        )
    except UnsupportedJob as error:
        reasons.extend(error.reasons)
    if context.catalog is None:
        reasons.append(
            {
                "stage": "strategy",
                "kind": "nonzoned",
                "reason": "requires declared shared double-trap cells",
            }
        )
    return reasons


def _nonzoned_build(
    context: CompilerContext, options: dict[str, Any]
) -> tuple[Compiler, dict[str, Any]]:
    assert context.catalog is not None
    limit = options.get("max_cz_gates", context.catalog.capacity)
    return NonZonedStrategy(
        context.aod_id,
        context.catalog,
        limit,
        context.device.readout.max_atoms if context.device.readout else 1,
    ), {"max_cz_gates": limit}


def _search_schema() -> dict[str, Any]:
    from ..schemas.job import search_smarter_schema

    return search_smarter_schema()


def _nonzoned_schema() -> dict[str, Any]:
    from ..schemas.job import nonzoned_schema

    return nonzoned_schema()


def register_builtins(registry: dict[str, CompilerRegistration]) -> None:
    """Register layer and whole-program compilers with independent defaults."""
    registry.update(
        search_smarter=CompilerRegistration(
            "search_smarter",
            "1",
            _search_schema,
            ("initial_storage", "explicit"),
            _search_admit,
            _search_build,
            budgets={"search_nodes": "placement.max_nodes"},
            budget_applicable=lambda name, options: (
                options.get("placement", {}).get("kind") in ("ids", "astar")
            ),
            modes={
                "adaptive": "Existing layout and optional retention.",
                "qec": "Restore each layer; no retention or storage search.",
            },
        ),
        nonzoned=CompilerRegistration(
            "nonzoned",
            "1",
            _nonzoned_schema,
            ("enola_initial", "explicit"),
            _nonzoned_admit,
            _nonzoned_build,
        ),
        smt=CompilerRegistration(
            "smt",
            "1",
            smt_schema,
            ("explicit",),
            smt_admit,
            smt_build,
            defaults={"timeout_s": 60, "time_quantum_us": 0.001},
            supports_feedback=False,
        ),
    )
