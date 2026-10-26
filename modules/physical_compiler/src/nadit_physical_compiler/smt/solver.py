"""Bounded SAT/UNSAT optimization with exact witness lowering and evidence."""

import hashlib
import json
from dataclasses import asdict
from time import perf_counter
from typing import Any

import z3

from ..atom_ir import Measure
from ..compilers.contracts import ProgramContext
from ..execution import FakeBackend, MeasurementBackend
from ..serialization import encode_dag, encode_device, encode_layout
from ..validation import validate_result
from .adapter import require_entry
from .contracts import Domain, Plan, SolveResult
from .expressions import ticks
from .lowering import lower_plan
from .scheduling import ScheduleModel
from .transport import TransportModel


def digest(value: Any) -> str:
    """Hash a canonical JSON value, independently of paths and formatting."""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _checked(context: ProgramContext, plan: Plan, case: MeasurementBackend):
    from .checker import check_lowering, check_plan

    errors = check_plan(context, plan)
    if errors:
        raise ValueError(f"SMT plan failed independent check: {errors[:5]}")
    result = lower_plan(context, plan, case)
    errors = check_lowering(context, plan, result)
    report = validate_result(
        result,
        entry_state=context.entry_state,
        device=context.device,
        dag=context.dag,
        detailed=True,
    )
    if errors or not report["ok"]:
        raise ValueError(f"SMT lowering failed validation: {errors}; {report}")
    return result


def fix_plan(transport: TransportModel, schedule: ScheduleModel, plan: Plan) -> list:
    """Constrain one known witness, solely for explicit witness-membership checks."""
    if len(plan.transitions) != transport.domain.horizon:
        raise ValueError("Witness horizon differs from the declared search horizon.")
    constraints: list[z3.BoolRef] = []
    for t, state in enumerate(plan.states):
        for q, position in enumerate(state.positions):
            constraints.extend(
                (
                    transport.x[t][q] == transport.domain.xs.index(position.x),
                    transport.y[t][q] == transport.domain.ys.index(position.y),
                    transport.carried[t][q] == state.carried[q],
                )
            )
        constraints.extend(
            v == (x in state.columns)
            for x, v in zip(transport.domain.xs, transport.columns[t], strict=True)
        )
        constraints.extend(
            v == (y in state.rows)
            for y, v in zip(transport.domain.ys, transport.rows[t], strict=True)
        )
    for t, (transition, operations) in enumerate(
        zip(plan.transitions, plan.operations, strict=True)
    ):
        constraints.append(
            transport.kind[t] == ("none", "load", "move", "store").index(transition)
        )
        constraints.extend(schedule.when[index] == t for index in operations)
        if transport.aod.motion == "rigid":
            for name, before, after in (
                ("x", plan.states[t].columns, plan.states[t + 1].columns),
                ("y", plan.states[t].rows, plan.states[t + 1].rows),
            ):
                delta = after[0] - before[0] if transition == "move" and before else 0
                constraints.append(z3.Real(f"td{name}_{t}") == delta)
    return constraints


def _critical_path(context: ProgramContext, schedule: ScheduleModel) -> int:
    finish = [0] * len(context.dag.nodes)
    predecessors: dict[int, list[int]] = {}
    for source, target in context.dag.edges:
        predecessors.setdefault(target, []).append(source)
    for node in context.dag.nodes:
        finish[node.id] = max(
            (finish[p] for p in predecessors.get(node.id, [])), default=0
        ) + ticks(schedule.durations[node.id], schedule.domain.time_quantum_us)
    return max(finish, default=0)


def _rounded_duration(result, context: ProgramContext, domain: Domain) -> int:
    elapsed = ready = 0
    for step in result.program.steps:
        for action in step.actions:
            if isinstance(action, Measure):
                assert context.device.readout is not None
                ready = max(
                    ready,
                    elapsed
                    + ticks(action.duration_us, domain.time_quantum_us)
                    + ticks(context.device.readout.latency_us, domain.time_quantum_us),
                )
        elapsed += ticks(step.duration_us, domain.time_quantum_us)
    return max(elapsed, ready)


def solve(
    context: ProgramContext,
    options: dict[str, Any],
    case: MeasurementBackend,
    *,
    seed: Plan | None = None,
) -> SolveResult:
    """Search a fixed finite domain and preserve every solver answer.

    Args:
        context: Static native DAG, Device and explicit SLM homes.
        options: xs, ys, horizon, timeout_s and time_quantum_us.
        case: Measurement identities are sampled only while lowering a final plan.
        seed: Optional independently validated upper bound; never constrains search.

    Returns:
        Best independently validated program (if any), its plan, and evidence.
        A timeout is UNKNOWN, even if a constructive upper bound is available.
    """
    require_entry(context)
    if any(node.condition is not None for node in context.dag.nodes):
        raise ValueError("SMT static profile does not select measurement branches.")
    domain = Domain(
        tuple(options["xs"]),
        tuple(options["ys"]),
        options["horizon"],
        options.get("timeout_s", 60),
        options.get("time_quantum_us", 0.001),
    )
    if domain.timeout_s <= 0 or domain.time_quantum_us <= 0 or domain.horizon < 1:
        raise ValueError("SMT horizon, timeout and time quantum must be positive.")
    started = perf_counter()
    seed_result = _checked(context, seed, FakeBackend()) if seed is not None else None
    solver = z3.Solver()
    solver.set(random_seed=0)
    transport = TransportModel(
        solver, context.device, context.aod_id, context.entry_state, domain
    )
    schedule = ScheduleModel(solver, context, transport)
    evidence: dict[str, Any] = {
        "schema": "nadit.smt-evidence/1",
        "solver": "z3",
        "solver_version": z3.get_version_string(),
        "random_seed": 0,
        "domain": asdict(domain),
        "input_hashes": {
            "dag": digest(encode_dag(context.dag)),
            "device": digest(encode_device(context.device)),
            "entry": digest(encode_layout(context.entry_state)),
        },
        "objective": "rounded_period_including_measurement_availability",
        "scope": (
            "finite coordinates, fixed horizon, full CZ-region pulse, one shared AOD"
        ),
        "model_build_s": perf_counter() - started,
        "queries": [],
    }
    budget_spent = 0.0

    def query(bound: int | None, purpose: str, fixed: Plan | None = None):
        nonlocal budget_spent
        remaining = domain.timeout_s - budget_spent
        if remaining <= 0:
            return None, None
        solver.push()
        if bound is not None:
            solver.add(schedule.total_ticks <= bound)
        active_solver = solver
        if fixed is not None:
            certificate_started = perf_counter()
            assert seed_result is not None
            assignments = fix_plan(transport, schedule, fixed) + [
                schedule.step_ticks[t]
                == ticks(step.duration_us, domain.time_quantum_us)
                for t, step in enumerate(seed_result.program.steps)
            ]
            substitutions = [(c.arg(0), c.arg(1)) for c in assignments]
            # Evaluate this fully specified certificate without asking SMT to
            # rediscover thousands of already fixed coordinates and booleans.
            active_solver = z3.Solver()
            grounded = z3.simplify(
                z3.substitute(z3.And(solver.assertions()), *substitutions)
            )
            active_solver.add(grounded)
            evidence["certificate_evaluation_s"] = perf_counter() - certificate_started
        query_budget = min(remaining, 30) if fixed is not None else remaining
        active_solver.set(timeout=max(1, int(query_budget * 1000)))
        before = perf_counter()
        answer = active_solver.check()
        elapsed = perf_counter() - before
        budget_spent += elapsed
        record = {
            "purpose": purpose,
            "bound_ticks": bound,
            "status": str(answer),
            "wall_s": elapsed,
        }
        model = active_solver.model() if answer == z3.sat else None
        if answer == z3.unknown:
            record["reason"] = active_solver.reason_unknown()
        if fixed is not None:
            record["method"] = "full_witness_substitution"
        evidence["queries"].append(record)
        solver.pop()
        return answer, model

    best_plan, best_result = seed, seed_result
    lower = _critical_path(context, schedule)
    upper = (
        _rounded_duration(seed_result, context, domain)
        if seed_result is not None
        else None
    )
    origin = "constructive_upper_bound" if seed is not None else None
    membership = seed is None
    if seed is not None:
        answer, _ = query(None, "fixed_witness_membership", seed)
        if answer == z3.unsat:
            raise ValueError(
                "Independent legal witness is UNSAT in declared SMT model."
            )
        if answer != z3.sat:
            evidence["witness_membership"] = "unconfirmed"
        else:
            membership = True
            evidence["witness_membership"] = "sat"
        # A phase preference is not a constraint: every search remains free.
        for constraint in fix_plan(transport, schedule, seed):
            solver.set_initial_value(constraint.arg(0), constraint.arg(1))
    else:
        answer, model = query(None, "unrestricted_feasibility")
        if answer == z3.unsat:
            evidence.update(
                status="unsat_in_domain",
                lower_bound_ticks=None,
                upper_bound_ticks=None,
                wall_s=perf_counter() - started,
            )
            return SolveResult(None, None, evidence)
        if model is not None:
            best_plan = Plan(
                tuple(transport.snapshot(model, t) for t in range(domain.horizon + 1)),
                transport.transition_names(model),
                schedule.extract(model),
            )
            upper = model.eval(schedule.total_ticks).as_long()
            origin = "unrestricted_sat"
    first_improvement = seed is not None
    while upper is not None and lower < upper:
        target = upper - 1 if first_improvement else (lower + upper - 1) // 2
        first_improvement = False
        answer, model = query(target, "unrestricted_time_bound")
        if answer == z3.unsat:
            lower = target + 1
        elif model is not None:
            best_plan = Plan(
                tuple(transport.snapshot(model, t) for t in range(domain.horizon + 1)),
                transport.transition_names(model),
                schedule.extract(model),
            )
            upper = model.eval(schedule.total_ticks).as_long()
            origin = "unrestricted_sat"
            membership = True
        else:
            break
    if best_plan is not None:
        best_result = _checked(context, best_plan, case)
    status = (
        "optimal_in_domain"
        if membership and upper is not None and lower == upper
        else ("feasible_unknown" if best_result is not None else "unknown")
    )
    evidence.update(
        status=status,
        solution_origin=origin,
        lower_bound_ticks=lower,
        upper_bound_ticks=upper,
        quantization_error_bound_us=(domain.horizon + 1) * domain.time_quantum_us,
        wall_s=perf_counter() - started,
        solver_s=budget_spent,
    )
    if best_result is not None:
        assert best_plan is not None
        evidence["actual_duration_us"] = best_result.duration_us
        evidence["plan_sha256"] = digest(asdict(best_plan))
        evidence["validation"] = (
            "independent_plan_and_lowering_checks_and_validate_result"
        )
    return SolveResult(best_result, best_plan, evidence)
