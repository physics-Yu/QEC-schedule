"""Structured Shor-15 source with exact arithmetic and explicit synthesis gaps.

Work bits w0..w3 are little endian. Phase bits phase[0]..phase[7] are
most significant first; measurement order is phase[7] down to phase[0].
P(theta) means diag(1, exp(i theta)), distinct from RZ's global phase.
No fake results, runtime epochs, physical carriers, or timings are cached here.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from typing import Iterator

VERSION = "0.2.0"
SCHEMA = "LogicalProgram/0.2.0-draft"
GATE_ARITY = {"H": 1, "X": 1, "Z": 1, "S": 1, "SDG": 1,
              "T": 1, "TDG": 1, "CX": 2, "CZ": 2, "P": 1}
EVIDENCE = {"execution_kind": "compile_plan", "quantum_state_simulated": False,
            "hardware_executed": False, "loss_enabled": False}


class FrontendError(ValueError):
    """An unsupported or invalid logical input, never a success placeholder."""


class SynthesisRequiredError(FrontendError):
    def __init__(self, operations: list[dict]):
        self.operations = operations
        super().__init__(
            "SYNTHESIS_REQUIRED: " + ", ".join(op["id"] for op in operations)
        )


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False)
                          .encode("utf-8")).hexdigest()


def _op(op_id: str, kind: str, qubits: list[str], params: dict, *,
        after: list[str] | None = None, writes: list[str] | None = None,
        condition: dict | None = None, source_ids: list[str] | None = None) -> dict:
    return {"id": op_id, "kind": kind, "qubits": qubits, "params": params,
            "reads": [] if condition is None else [condition["bit"]],
            "writes": writes or [], "after": after or [],
            "source_ids": source_ids or [f"shor15:{op_id}"],
            "condition": condition}


def _ccx(a: str, b: str, c: str) -> list[tuple[str, list[str]]]:
    # Exact, not relative-phase CCX. Qiskit qelib1.inc ccx definition.
    return [("H", [c]), ("CX", [b, c]), ("TDG", [c]),
            ("CX", [a, c]), ("T", [c]), ("CX", [b, c]),
            ("TDG", [c]), ("CX", [a, c]), ("T", [b]),
            ("T", [c]), ("H", [c]), ("CX", [a, b]),
            ("T", [a]), ("TDG", [b]), ("CX", [a, b])]


def _multiplier_template(multiplier: int) -> dict:
    swaps = {1: [], 2: [(0, 1), (0, 2), (0, 3)],
             4: [(0, 2), (1, 3)]}[multiplier]
    body = []
    previous = []
    for swap_index, (i, j) in enumerate(swaps):
        a, b = f"w{i}", f"w{j}"
        sequence = [("CX", [b, a]), *_ccx("ctrl", a, b), ("CX", [b, a])]
        for gate_index, (name, targets) in enumerate(sequence):
            op_id = f"swap{swap_index}/g{gate_index:02d}"
            source = [f"template:mul{multiplier}",
                      f"template:mul{multiplier}/fredkin{swap_index}",
                      "decomposition:fredkin-exact-7t/1"]
            body.append({"kind": "op", "op": _op(
                op_id, "gate", targets, {"name": name}, after=previous,
                source_ids=source)})
            previous = [op_id]
    return {"template_id": f"controlled_mul{multiplier}/1",
            "formal_qubits": ["ctrl", "w0", "w1", "w2", "w3"],
            "body": body,
            "metadata": {"protocol": "controlled-full-permutation-mod15",
                         "version": "1", "multiplier": multiplier,
                         "modulus": 15, "extension_x15": "fixed",
                         "bit_order": "w0_lsb", "exact": True,
                         "identity": multiplier == 1,
                         "fredkin_count": len(swaps),
                         "t_like_count": len(swaps) * 7,
                         "source": "R8-FACT-015@0.1.0",
                         "decomposition_source": "Qiskit qelib1.inc ccx/cswap"}}


def build_shor15(*, synthesis_error_budget: float = 1e-3, synthesize: bool = True) -> dict:
    """Build complete Clifford+T logic with certified conditional phase metadata.

    synthesize=False retains the exact symbolic P source for inspection.
    Call require_clifford_t before downstream handoff to recheck certificates.
    The budget is a path bound on synthesis operator-norm error, not fidelity.
    """
    if type(synthesize) is not bool:
        raise FrontendError("INVALID_SYNTHESIS_MODE")
    if (isinstance(synthesis_error_budget, bool)
            or not isinstance(synthesis_error_budget, (int, float))
            or not math.isfinite(synthesis_error_budget)
            or not 0 < synthesis_error_budget < 1):
        raise FrontendError("INVALID_SYNTHESIS_BUDGET: expected finite 0 < epsilon < 1")
    inputs = {"N": 15, "a": 2, "work_bits": 4, "phase_bits": 8,
              "extension_x15": "fixed", "synthesis_error_budget": synthesis_error_budget}
    templates = {f"controlled_mul{b}/1": _multiplier_template(b) for b in (1, 2, 4)}
    body: list[dict] = []
    last: list[str] = []

    def append(op: dict) -> None:
        nonlocal last
        op["after"] = list(dict.fromkeys(last + op["after"]))
        body.append({"kind": "op", "op": op})
        last = [op["id"]]

    for i in range(4):
        append(_op(f"init/reset_w{i}", "reset", [f"w{i}"], {"basis": "Z", "value": 0}))
    append(_op("init/work_one", "gate", ["w0"], {"name": "X"}))
    rounds = []
    pending = []
    for j in range(7, -1, -1):
        prefix = f"round{j}"
        source = [f"shor15:round/{j}"]
        append(_op(f"{prefix}/reset", "reset", ["ctrl"], {"basis": "Z", "value": 0},
                   source_ids=source + [f"shor15:{prefix}/reset"]))
        append(_op(f"{prefix}/prepare", "gate", ["ctrl"], {"name": "H"}))
        b = pow(2, 1 << j, 15)  # Computed from a,N; no input order or factors.
        call_id = f"{prefix}/multiply"
        body.append({"kind": "call", "id": call_id,
                     "template_id": f"controlled_mul{b}/1", "repeat": 1,
                     "bindings": {q: q for q in ["ctrl", "w0", "w1", "w2", "w3"]},
                     "after": last.copy(), "source_ids": source + [f"shor15:U^(2^{j})"],
                     "metadata": {"power_index": j, "multiplier": b}})
        last = [call_id]
        corrections = []
        for k in range(j + 1, 8):
            # Correct phase tail x_(j+2)..x_8 from already measured bits.
            denominator = 1 << (k - j)
            correction_id = f"{prefix}/feedback_from_{k}"
            params = {"name": {2: "SDG", 4: "TDG"}.get(denominator, "P"),
                      "angle_pi": {"numerator": -1, "denominator": denominator},
                      "angle_rad": -math.pi / denominator, "angle_unit": "rad",
                      "phase_convention": "diag(1,exp(i*theta))",
                      "synthesis_status": "exact" if denominator <= 4 else "required",
                      "error_bound": 0.0 if denominator <= 4 else None,
                      "error_budget": 0.0 if denominator <= 4 else synthesis_error_budget / 15}
            append(_op(correction_id, "gate", ["ctrl"], params,
                       after=[f"round{k}/measure"], condition={"bit": f"phase[{k}]", "equals": 1}))
            corrections.append(correction_id)
            if denominator > 4:
                pending.append(correction_id)
        append(_op(f"{prefix}/readout_h", "gate", ["ctrl"], {"name": "H"}))
        append(_op(f"{prefix}/measure", "measure", ["ctrl"], {"basis": "Z"},
                   writes=[f"phase[{j}]"]))
        rounds.append({"id": prefix, "power_index": j, "controlled_multiplier": b,
                       "measurement_bit": f"phase[{j}]", "feedback_ops": corrections})
    append(_op("release/control_reset", "reset", ["ctrl"], {"basis": "Z", "value": 0}))
    program = {
        "schema_version": SCHEMA, "artifact_id": "shor15-logical-" + _hash(inputs)[:16],
        "producer_version": f"na_pipeline.frontend/{VERSION}",
        "input_hashes": {"algorithm_config_sha256": _hash(inputs)},
        "device_ref": None, "device_ref_reason": "device-independent logical source",
        "capability_profile": "shor15-semiclassical-qpe8/full-permutation-v1",
        "provenance": {"owner": "R2", "task_id": "T201", "knowledge_revision": "kb-0004",
                       "interface_ref": "IF-MVP-001/0.2.1-draft", "fixture": False,
                       "source_kind": "generated_algorithm", "generator": "build_shor15",
                       "source_refs": ["R8-ADR-001@0.4.0", "R8-FACT-015@0.1.0"]},
        **EVIDENCE, "algorithm": inputs,
        "qubits": [{"id": "ctrl", "role": "reused_phase_control"}]
                  + [{"id": f"w{i}", "role": "work", "significance": i} for i in range(4)],
        "classical_bits": [{"id": f"phase[{j}]", "role": "phase_output",
                            "binary_fraction_weight": f"1/{1 << (j + 1)}"} for j in range(8)],
        "bit_order": {"work": "little_endian_w0_lsb", "postprocess": "phase[0..7]_msb_first",
                      "measurement_order": [f"phase[{j}]" for j in range(7, -1, -1)]},
        "templates": templates, "body": body, "rounds": rounds,
        "synthesis": {"status": "incomplete", "metric": "operator_norm_per_path",
                      "path_error_budget": synthesis_error_budget,
                      "allocation": "equal_over_15_nonexact_conditional_rotations",
                      "unresolved_operation_ids": pending, "clifford_t_ready": False},
        "resource_summary": {"modular_multiply_fredkin": 5, "modular_multiply_t_like": 35,
                             "exact_feedback_t_like": 6, "conditional_feedback_count": 28,
                             "nonexact_feedback_count": 15, "total_t_like": None,
                             "total_t_like_status": "unknown_until_synthesis_and_path_selection"},
        "lifecycle": {"work_initial_value": 1, "work_persists_across_rounds": True,
                      "work_final_state": "live_unmeasured", "control_final_state": "reset_zero",
                      "measurement_results": "runtime_only_no_values_in_compile_plan"},
    }
    program["template_hashes"] = {key: _hash(value) for key, value in templates.items()}
    if synthesize:
        from .synthesis import synthesize_feedback
        return synthesize_feedback(program)
    return program


def iter_logical_ops(program: dict) -> Iterator[dict]:
    """Lazily bind logical templates; after references always name actual ops.

    Only nonrecursive call(repeat=1) and op nodes are supported in this version.
    Conditional calls require explicit classical scope and cannot nest conditions.
    Empty exact-identity calls retain provenance in source_ids of the next op.
    Consumers retain the structured source as the authority for such identities.
    """
    if program.get("schema_version") != SCHEMA:
        raise FrontendError("UNSUPPORTED_SCHEMA")
    aliases: dict[str, list[str]] = {}
    emitted: set[str] = set()
    pending_sources: list[str] = []

    def resolve(ids: list[str]) -> list[str]:
        result = []
        for op_id in ids:
            for actual in aliases.get(op_id, [op_id]):
                if actual not in emitted:
                    raise FrontendError(f"NONCAUSAL_DEPENDENCY: {op_id}")
                if actual not in result:
                    result.append(actual)
        return result

    for node in program["body"]:
        if node.get("kind") == "op":
            op = deepcopy(node["op"])
            if op["id"] in emitted or op["id"] in aliases:
                raise FrontendError(f"DUPLICATE_ID: {op['id']}")
            op["after"] = resolve(op["after"])
            op["source_ids"] = list(dict.fromkeys(op["source_ids"] + pending_sources))
            pending_sources.clear()
            emitted.add(op["id"])
            yield op
        elif node.get("kind") == "call":
            call_condition = node.get("condition")
            if (node.get("repeat") != 1 or (call_condition is not None
                    and node.get("condition_scope") != "classical")):
                raise FrontendError(f"UNSUPPORTED_CALL_CONTROL: {node['id']}")
            call_id = node["id"]
            if call_id in emitted or call_id in aliases:
                raise FrontendError(f"DUPLICATE_ID: {call_id}")
            template = program["templates"][node["template_id"]]
            bindings = node["bindings"]
            if set(bindings) != set(template["formal_qubits"]) or len(set(bindings.values())) != len(bindings):
                raise FrontendError(f"INVALID_BINDINGS: {call_id}")
            inputs = resolve(node.get("after", []))
            local_ids: set[str] = set()
            tails = inputs
            call_sources = [call_id, *node["source_ids"], *pending_sources]
            pending_sources.clear()
            for inner in template["body"]:
                if inner.get("kind") != "op":
                    raise FrontendError(f"UNSUPPORTED_NESTED_TEMPLATE: {call_id}")
                local = inner["op"]
                if any(dep not in local_ids for dep in local["after"]):
                    raise FrontendError(f"NONCAUSAL_TEMPLATE: {call_id}/{local['id']}")
                op = deepcopy(local)
                op["id"] = f"{call_id}/{local['id']}"
                if op["id"] in emitted:
                    raise FrontendError(f"DUPLICATE_ID: {op['id']}")
                op["qubits"] = [bindings[q] for q in local["qubits"]]
                op["reads"] = [f"{call_id}/{b}" for b in local["reads"]]
                op["writes"] = [f"{call_id}/{b}" for b in local["writes"]]
                if local["condition"] is not None:
                    op["condition"]["bit"] = f"{call_id}/{local['condition']['bit']}"
                if call_condition is not None:
                    if local["condition"] is not None:
                        raise FrontendError(f"UNSUPPORTED_NESTED_CONDITION: {call_id}")
                    op["condition"] = deepcopy(call_condition)
                    op["reads"] = list(dict.fromkeys(op["reads"] + [call_condition["bit"]]))
                if "synthesis_certificate_ref" in node:
                    op["synthesis_instance_id"] = call_id
                    if not local_ids:
                        op["branch_global_phase_pi"] = deepcopy(template["metadata"]["global_phase_pi"])
                op["after"] = list(dict.fromkeys(inputs + [f"{call_id}/{d}" for d in local["after"]]))
                op["source_ids"] = list(dict.fromkeys(call_sources + local["source_ids"]))
                # Completion of an arbitrary local DAG depends on every leaf.
                tails = [t for t in tails if t not in op["after"]] + [op["id"]]
                local_ids.add(local["id"])
                emitted.add(op["id"])
                yield op
            if not template["body"]:
                if template.get("metadata", {}).get("identity") is not True:
                    raise FrontendError(f"EMPTY_NONIDENTITY_TEMPLATE: {call_id}")
                pending_sources.extend(call_sources)
            aliases[call_id] = tails
        else:
            raise FrontendError(f"UNSUPPORTED_NODE: {node.get('kind')}")


def validate_logical(program: dict) -> list[dict]:
    """Validate this frontend subset, without claiming arithmetic/QEC validation."""
    errors: list[dict] = []

    def error(code: str, op_id: str, message: str) -> None:
        errors.append({"code": code, "operation_id": op_id, "message": message})

    try:
        for field in ("artifact_id", "producer_version", "provenance", "input_hashes"):
            if not program.get(field):
                error("MISSING_ENVELOPE_FIELD", "program", field)
        for field, value in EVIDENCE.items():
            if program.get(field) != value or type(program.get(field)) is not type(value):
                error("INVALID_EVIDENCE_LABEL", "program", field)
        qubits = {q["id"] for q in program["qubits"]}
        bits = {b["id"] for b in program["classical_bits"]}
        if len(qubits) != len(program["qubits"]) or len(bits) != len(program["classical_bits"]):
            error("DUPLICATE_DECLARATION", "program", "qubit or bit declarations repeat")
        producers: dict[str, str] = {}
        parents: dict[str, set[str]] = {}
        last_qubit_op: dict[str, str] = {}

        def precedes(earlier, later):
            pending = list(parents[later])
            seen = set()
            while pending:
                node = pending.pop()
                if node == earlier:
                    return True
                if node not in seen:
                    seen.add(node)
                    pending.extend(parents[node])
            return False

        for op in iter_logical_ops(program):
            op_id = op["id"]
            parents[op_id] = set(op["after"])
            if (not isinstance(op["source_ids"], list) or not op["source_ids"]
                    or any(not isinstance(s, str) or not s for s in op["source_ids"])):
                error("MISSING_SOURCE", op_id, "source_ids must be nonempty")
            if not set(op["qubits"]).issubset(qubits) or len(set(op["qubits"])) != len(op["qubits"]):
                error("INVALID_QUBIT", op_id, "unknown or repeated qubit")
            for qubit in op["qubits"]:
                if qubit in last_qubit_op and not precedes(last_qubit_op[qubit], op_id):
                    error("QUBIT_ORDER_DEPENDENCY", op_id, qubit)
                last_qubit_op[qubit] = op_id
            condition = op["condition"]
            reads = op["reads"]
            if condition is not None:
                if type(condition.get("equals")) is not int or condition["equals"] not in (0, 1):
                    error("INVALID_CONDITION", op_id, "equals must be bit 0 or 1")
                if condition["bit"] not in reads:
                    error("MISSING_CONDITION_READ", op_id, condition["bit"])
            for bit in reads:
                if bit not in producers or not precedes(producers[bit], op_id):
                    error("READ_BEFORE_READY_DEPENDENCY", op_id, bit)
            for bit in op["writes"]:
                if bit not in bits or bit in producers:
                    error("INVALID_WRITE", op_id, bit)
                producers[bit] = op_id
            if op["kind"] == "gate":
                if op["writes"]:
                    error("INVALID_GATE_WRITE", op_id, "gate cannot produce classical results")
                name = op["params"]["name"]
                if name not in GATE_ARITY or len(op["qubits"]) != GATE_ARITY.get(name):
                    error("UNSUPPORTED_GATE", op_id, name)
                if name == "P" or "angle_pi" in op["params"]:
                    angle = op["params"]["angle_pi"]
                    if (type(angle["numerator"]) is not int or type(angle["denominator"]) is not int
                            or angle["denominator"] <= 0):
                        error("INVALID_ANGLE", op_id, "angle_pi needs integer numerator and positive denominator")
                    exact = Fraction(angle["numerator"], angle["denominator"])
                    if (op["params"].get("angle_unit") != "rad"
                            or not math.isclose(float(exact) * math.pi, op["params"]["angle_rad"], abs_tol=1e-14)):
                        error("INVALID_ANGLE", op_id, "rational angle and rad value disagree")
                    if op["params"].get("phase_convention") != "diag(1,exp(i*theta))":
                        error("INVALID_PHASE_CONVENTION", op_id, "phase gate convention required")
                    exact_gate_angles = {"SDG": Fraction(-1, 2), "TDG": Fraction(-1, 4)}
                    if name != "P" and exact_gate_angles.get(name) != exact:
                        error("GATE_ANGLE_MISMATCH", op_id, "gate and target angle disagree")
                    if name == "P" and op["params"].get("synthesis_status") != "required":
                        error("UNVERIFIED_SYNTHESIS", op_id, "P remains unsynthesized")
                    if name == "P":
                        budget = op["params"].get("error_budget")
                        if (type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0
                                or op["params"].get("error_bound") is not None):
                            error("INVALID_SYNTHESIS_BUDGET", op_id, "positive budget and unknown achieved bound required")
            elif op["kind"] in ("measure", "reset"):
                if op["condition"] is not None or op["reads"]:
                    error("UNSUPPORTED_CONDITIONAL_IO", op_id, "only unconditional measure/reset in this subset")
                if len(op["qubits"]) != 1 or op["params"].get("basis") != "Z":
                    error("UNSUPPORTED_IO", op_id, "only single-qubit Z measure/reset")
                if op["kind"] == "measure" and len(op["writes"]) != 1:
                    error("INVALID_MEASUREMENT", op_id, "one output required")
                if op["kind"] == "reset" and op["params"].get("value") != 0:
                    error("UNSUPPORTED_RESET", op_id, "reset must prepare zero")
                if op["kind"] == "reset" and op["writes"]:
                    error("INVALID_RESET_WRITE", op_id, "reset does not produce classical results")
            else:
                error("UNSUPPORTED_OPERATION", op_id, op["kind"])
        if bits != set(producers):
            error("UNWRITTEN_RESULTS", "program", str(sorted(bits - set(producers))))
        if (program.get("synthesis", {}).get("status") == "complete"
                or "synthesis_certificates" in program or "branch_global_phases" in program
                or any("synthesis_certificate_ref" in node for node in program["body"])):
            from .synthesis import audit_synthesis
            errors.extend(audit_synthesis(program))
    except (KeyError, TypeError, ValueError, ZeroDivisionError, AttributeError, IndexError) as exc:
        error("INVALID_PROGRAM", "program", str(exc))
    return errors


def require_clifford_t(program: dict) -> None:
    """Fail before downstream execution if any unsupported rotation remains."""
    errors = validate_logical(program)
    if errors:
        raise FrontendError("INVALID_PROGRAM: " + json.dumps(errors, ensure_ascii=False))
    pending = [op for op in iter_logical_ops(program) if op["kind"] == "gate"
               and op["params"]["name"] == "P"]
    if pending:
        raise SynthesisRequiredError(pending)
