"""Physical feedback, bounded failure and replay for sparse QEC scheduling.

Only one of the 34 platform atoms is a circuit operand. The positive case
explicitly resets the measured atom before addressed control can reuse it.
"""
from collections import Counter
import json

import pytest

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.models import GateStatus, HolderRef, HolderType
from neutral_atom_env.domain.operations import OperationType
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_experiments.qec_pbc import GateTask, PBCProgram, patch_roles
from neutral_atom_experiments.qec_pbc.neutral_atom import build_native_qec_inputs
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.qec_sparse import run_qec_sparse


class _RecordingEnvironment(NeutralAtomEnv):
    def __init__(self, state):
        super().__init__(state)
        self.plans = []

    def submit(self, plan):
        super().submit(plan)
        self.plans.append(plan)


def _feedback(*, reset):
    specs = [("prepare", "X", ()), ("m1", "MEASURE", ())]
    if reset:
        # RESET clears physical measured status and prepares |0>; the next X
        # restores |1> so the real m1=1 correction must bring it back to |0>.
        specs += [("reset", "RESET", ()), ("restore", "X", ())]
    specs += [("correct", "X", (("m1", 1),)),
              ("inactive", "Z", (("m1", 0),)), ("m2", "MEASURE", ())]
    operations = []
    for name, kind, condition in specs:
        dependencies = (operations[-1].id,) if operations else ()
        operations.append(GateTask(name, kind, ("A.d0",), dependencies, condition))
    program = PBCProgram(patch_roles("A"), tuple(operations), name="sparse-feedback")
    inputs = build_native_qec_inputs(program, seed=3)
    env = _RecordingEnvironment(inputs.create_environment().state)
    site = next(t.id for t in env.state.world.traps.values()
                if (t.position.x_um, t.position.y_um) == (0, -100))
    return inputs, env, {"Q000": site}


def _records(env):
    return [json.loads(raw) for raw in env.state.trace.records]


def _effect_ids(record):
    return record.get("effect_gate_ids") or (
        [record["effect_gate_id"]] if record.get("effect_gate_id") else [])


def _run(env, destinations, **kwargs):
    return run_qec_sparse(env, working_destinations=destinations,
                          max_decisions=32, candidate_budget=8,
                          route_expansions=100000, **kwargs)


def test_sparse_feedback_executes_skip_and_restores_all_physical_supports():
    inputs, env, destinations = _feedback(reset=True)
    initial = env.snapshot()
    terminal = initial_terminal(env.state)
    initial_atoms = dict(env.state.atoms)
    initial_holders = dict(env.state.placement.atom_to_holder)
    result = _run(env, destinations, terminal=terminal)

    assert result.status == "completed", result.diagnostics
    assert not result.diagnostics and not env.pending
    assert len(inputs.compiled.bindings) == 17
    assert len(env.state.atoms) == 34
    assert len(inputs.circuit.gates) == 7
    assert env.state.dag.completed
    assert inputs.compiled.semantic_results(env.state.measurement_results) == {"m1": 1, "m2": 0}
    validate_target(terminal, env.state)
    assert dict(env.state.placement.atom_to_holder) == initial_holders
    assert not env.state.placement.mobile_occupancy
    assert env.state.atoms["Q000"].measured
    assert all(atom.alive for atom in env.state.atoms.values())
    assert {q: atom for q, atom in env.state.atoms.items() if q != "Q000"} == {
        q: atom for q, atom in initial_atoms.items() if q != "Q000"}
    assert all(env.state.quantum_state.expectation({q: "Z"}) == 1 for q in env.state.atoms)

    effects = [r for r in _records(env) if r.get("effect_completed")]
    native = {op: gate for gate, op, _ in inputs.compiled.provenance}
    assert Counter(g for r in effects for g in _effect_ids(r)) == Counter(
        {g.id: 1 for g in inputs.circuit.gates})
    assert Counter(g for r in effects for g in r.get("applied_gate_ids", ())) == Counter(
        {g.id: 1 for g in inputs.circuit.gates if g.id != native["inactive"]})

    skipped = next(r for r in effects if native["inactive"] in _effect_ids(r))
    assert skipped["applied"] is False and skipped["applied_gate_ids"] == []
    pulse = next((plan, op) for plan in env.plans for op in plan.operations
                 if native["inactive"] in op.effect_gate_ids)
    plan, op = pulse
    assert op.operation_type == OperationType.RAMAN_ROTATION and op.duration_us == 1
    interval = next(i for i in plan.operation_intervals if i.operation_id == op.id)
    assert "CONTROL:Q000" in interval.resources
    assert not any(resource.startswith("RAMAN:") for resource in interval.resources)
    assert interval.end_us - interval.start_us == 1
    assert env.state.physical_metrics.raman_busy_time_us == 3
    assert result.decisions == len(env.plans)
    assert all(plan.execution_mode == "scheduled" for plan in env.plans)

    # Replay the accepted physical operations, with no scheduling or compiler
    # calls. Codec roundtrip also verifies that the real plans are portable.
    replay = NeutralAtomEnv.restore(initial)
    for accepted in env.plans:
        plan = plan_from_dict(primitive(accepted))
        replay.validate(plan)
        replay.submit(plan)
        replay.run()
    assert replay.snapshot() == env.snapshot()

    finished = env.snapshot()
    plan_count = len(env.plans)
    again = _run(env, destinations, terminal=terminal)
    assert again.status == "completed" and again.decisions == 0
    assert not again.decision_log and len(env.plans) == plan_count
    assert env.snapshot() == finished


def test_sparse_feedback_rejects_applied_control_without_explicit_reset():
    inputs, env, destinations = _feedback(reset=False)
    initial_holders = dict(env.state.placement.atom_to_holder)
    result = _run(env, destinations)

    assert result.status == "stalled"
    assert result.diagnostics[0]["code"] == "RAMAN_TARGET_UNAVAILABLE"
    assert result.diagnostics[0]["phase"] == "frontier"
    assert not env.pending and not env.state.dag.completed
    native = {op: gate for gate, op, _ in inputs.compiled.provenance}
    assert env.state.measurement_results == {native["m1"]: 1}
    assert env.state.atoms["Q000"].measured
    assert env.state.placement.atom_to_holder["Q000"] == HolderRef(
        HolderType.STATIC, destinations["Q000"])
    assert all(env.state.placement.atom_to_holder[q] == holder
               for q, holder in initial_holders.items() if q != "Q000")
    effects = [r for r in _records(env) if r.get("effect_completed")]
    assert Counter(g for r in effects for g in _effect_ids(r)) == Counter({
        native["prepare"]: 1, native["m1"]: 1})
    assert env.state.dag.nodes[native["correct"]].status == GateStatus.READY
    assert env.state.physical_metrics.raman_busy_time_us == 1


@pytest.mark.parametrize("bad_layout", ("unknown_trap", "missing_operand", "storage", "duplicate"))
def test_sparse_invalid_layout_is_atomic(bad_layout):
    _, env, destinations = _feedback(reset=True)
    if bad_layout == "unknown_trap":
        destinations["Q000"] = "missing-trap"
    elif bad_layout == "missing_operand":
        destinations = {}
    elif bad_layout == "storage":
        destinations["Q000"] = env.state.placement.atom_to_holder["Q000"].holder_id
    else:
        destinations["Q001"] = destinations["Q000"]
    initial = env.snapshot()
    result = _run(env, destinations)

    assert result.status == "stalled" and result.diagnostics[0]["code"] == "QEC_WORKING_LAYOUT"
    assert result.decisions == 0 and not result.decision_log and not env.plans
    assert env.snapshot() == initial


def test_sparse_decision_budget_keeps_a_valid_staging_prefix():
    _, env, destinations = _feedback(reset=True)
    initial = env.snapshot()
    holders = dict(env.state.placement.atom_to_holder)
    result = run_qec_sparse(env, working_destinations=destinations, max_decisions=1,
                            candidate_budget=8, route_expansions=100000)

    assert result.status == "stalled"
    assert result.diagnostics[0]["code"] == "DECISION_BUDGET_EXHAUSTED"
    assert result.decisions == len(env.plans) == 1
    assert result.decision_log[0]["kind"] == "stage_atom"
    assert not env.pending
    assert not any(r.get("effect_completed") for r in _records(env))
    assert env.state.placement.atom_to_holder["Q000"] == HolderRef(
        HolderType.STATIC, destinations["Q000"])
    assert all(env.state.placement.atom_to_holder[q] == holder
               for q, holder in holders.items() if q != "Q000")
    assert len(env.state.atoms) == 34 and not env.state.measurement_results
    replay = NeutralAtomEnv.restore(initial)
    replay.submit(plan_from_dict(primitive(env.plans[0])))
    replay.run()
    assert replay.snapshot() == env.snapshot()
